"""Task lifecycle, durable queue, idempotency, QA/QC hold, approvals and control."""

import ast
import threading
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from orchestrator_testkit import NOW

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Component, Money, RiskLevel
from dyson_contracts.control import ControlMode, ControlScope, ControlState
from dyson_contracts.tasks import TaskState
from dyson_orchestrator.api import create_app
from dyson_orchestrator.orchestrator import OrchestratorError, action_payload
from dyson_orchestrator.ports import TaskPlan

S = TaskState


def plan(tool="t0.inspect", receptor="T0", spend=None, risk=RiskLevel.LOW, **args):
    return TaskPlan(
        tool_id=tool,
        arguments=args or {"target": "R3"},
        receptor_id=receptor,
        risk=risk,
        estimated_spend=Money(amount=Decimal(spend), currency="INR") if spend else None,
        standard_id="t0-inspection-v1",
        summary=f"Run {tool}",
    )


def submit(orch, p=None, key=None):
    return orch.submit(key or f"instr-{uuid4().hex}", "inspect Receptor 3", p or plan())


def run_until_quiet(orch, rounds=10):
    for _ in range(rounds):
        if orch.tick() == 0:
            return


def states(orch, task_id):
    return [t.to_state for t in orch.history(task_id)]


# Intake and lifecycle (LA-ORC-01) -------------------------------------------------------
def test_every_instruction_gets_a_task_id_once(orch):
    t = submit(orch, key="instr-same")
    assert isinstance(t.task_id, UUID) and t.state is S.ACCEPTED
    again = orch.submit("instr-same", "inspect Receptor 3", plan())
    assert again.task_id == t.task_id  # the same command sent twice is one task
    assert states(orch, t.task_id) == [S.ACCEPTED]


def test_happy_path_completes_only_after_independent_verification(orch, parts):
    t = submit(orch)
    run_until_quiet(orch)
    done = orch.get(t.task_id)
    assert done.state is S.COMPLETED_VERIFIED and len(done.evidence_ids) == 1
    assert states(orch, t.task_id) == [S.ACCEPTED, S.RUNNING, S.COMPLETED_VERIFIED]
    assert parts["qa"].seen  # F verified before completion
    assert [r.idempotency_key for r in parts["hub"].calls] == [f"{t.task_id}:a1"]
    assert all(r.requested_by is Component.ORCHESTRATOR for r in parts["hub"].calls)
    assert orch.close(t.task_id).state is S.CLOSED


def test_tool_answer_is_not_completion(orch, parts):
    parts["qa"].unreachable = True
    t = submit(orch)
    run_until_quiet(orch)
    assert orch.get(t.task_id).state is S.RUNNING  # executed, but nothing verified it yet
    parts["qa"].unreachable = False
    run_until_quiet(orch)
    assert orch.get(t.task_id).state is S.COMPLETED_VERIFIED
    assert sum(parts["hub"].executed.values()) == 1  # re-asked G, never re-ran the tool


# Retries and idempotency (LA-ORC-03, LA-REL-02) ----------------------------------------
def test_network_retry_reuses_the_key_and_never_duplicates(orch, parts):
    parts["hub"].unreachable = 2
    t = submit(orch)
    run_until_quiet(orch)
    keys = [r.idempotency_key for r in parts["hub"].calls]
    assert keys == [f"{t.task_id}:a1"] * 3
    assert parts["hub"].executed[f"{t.task_id}:a1"] == 1
    assert orch.get(t.task_id).state is S.COMPLETED_VERIFIED


# QA/QC failures (LA-ORC-04, AMD-3) ------------------------------------------------------
def test_qa_failure_retests_with_a_new_attempt(orch, parts):
    parts["qa"].verdicts = [(True, False)]
    t = submit(orch)
    run_until_quiet(orch)
    assert orch.get(t.task_id).state is S.COMPLETED_VERIFIED
    assert [r.idempotency_key for r in parts["hub"].calls] == [f"{t.task_id}:a1", f"{t.task_id}:a2"]
    assert states(orch, t.task_id) == [
        S.ACCEPTED,
        S.RUNNING,
        S.FAILED,
        S.RUNNING,
        S.COMPLETED_VERIFIED,
    ]


def test_three_consecutive_qa_failures_hold_and_notify(orch, parts):
    parts["qa"].verdicts = [(False, False)] * 3
    t = submit(orch)
    run_until_quiet(orch)
    held = orch.get(t.task_id)
    assert held.state is S.HELD and held.hold_reason == "qa" and held.consecutive_qa_failures == 3
    assert parts["esc"] == [(t.task_id, "HOLD after 3 consecutive QA/QC failures")]
    run_until_quiet(orch)
    assert len(parts["hub"].calls) == 3  # nothing more happens until a person decides


def test_only_a_person_releases_a_qa_hold(orch, parts):
    parts["qa"].verdicts = [(False, False)] * 3
    t = submit(orch)
    run_until_quiet(orch)
    with pytest.raises(OrchestratorError):
        orch.review(t.task_id, resume=True, by=Component.CONVERSATION_ENGINE)
    orch.review(t.task_id, resume=True, by=Component.HUMAN_REVIEWER)
    run_until_quiet(orch)
    assert orch.get(t.task_id).state is S.COMPLETED_VERIFIED
    other = submit(orch)
    parts["qa"].verdicts = [(False, True)] * 3
    run_until_quiet(orch)
    assert orch.review(other.task_id, resume=False, by=Component.FOUNDER).state is S.CLOSED


def test_denial_or_tool_failure_escalates_without_blind_retries(orch, parts):
    parts["hub"].deny = True
    t = submit(orch)
    run_until_quiet(orch)
    assert orch.get(t.task_id).state is S.FAILED and orch.get(t.task_id).escalated
    assert len(parts["hub"].calls) == 1 and "approval_status" in parts["esc"][0][1]
    parts["hub"].deny, parts["hub"].crash = False, True
    u = submit(orch)
    run_until_quiet(orch)
    assert orch.get(u.task_id).state is S.FAILED and "tool crashed" in parts["esc"][-1][1]


# Approvals ------------------------------------------------------------------------------
def test_money_waits_for_the_founder(orch, parts):
    p = plan("ads.topup", receptor="R11", spend="200")
    t = submit(orch, p)
    run_until_quiet(orch)
    view = orch.get(t.task_id)
    assert view.state is S.APPROVAL_NEEDED and parts["hub"].calls == []
    payload, category = parts["gov"].proposals[view.approval_id]
    assert category is ApprovalCategory.FINANCIAL and payload == action_payload(p)
    parts["gov"].status[view.approval_id] = "approved"
    run_until_quiet(orch)
    assert orch.get(t.task_id).state is S.COMPLETED_VERIFIED
    assert parts["hub"].calls[0].approval_id == view.approval_id


def test_rejected_task_never_runs(orch, parts):
    t = submit(orch, plan("infra.deploy", receptor=None, risk=RiskLevel.HIGH))
    run_until_quiet(orch)
    parts["gov"].status[orch.get(t.task_id).approval_id] = "rejected"
    run_until_quiet(orch)
    assert orch.get(t.task_id).state is S.REJECTED and parts["hub"].calls == []
    assert orch.close(t.task_id).state is S.CLOSED


# STOP / PAUSE / RESUME ------------------------------------------------------------------
def _control(scope, mode, receptor=None):
    return ControlState(scope=scope, receptor_id=receptor, mode=mode, since=NOW)


def test_stop_ends_active_work_and_resume_returns_each_task_where_it_was(orch, parts):
    parts["qa"].unreachable = True  # keep the running task unverified, so it is still active
    waiting = submit(orch, plan("ads.topup", receptor="R11", spend="50"))
    working = submit(orch)
    run_until_quiet(orch)
    assert orch.get(waiting.task_id).state is S.APPROVAL_NEEDED
    assert orch.get(working.task_id).state is S.RUNNING
    calls_before_stop = len(parts["hub"].calls)
    parts["gov"].modes[None] = ControlMode.STOPPED
    assert orch.on_control(None, _control(ControlScope.MASTER, ControlMode.STOPPED)) == 2
    assert orch.get(working.task_id).state is S.STOPPED
    run_until_quiet(orch)
    assert len(parts["hub"].calls) == calls_before_stop  # nothing reaches G while stopped
    parts["gov"].modes[None] = ControlMode.RUNNING
    orch.on_control(None, _control(ControlScope.MASTER, ControlMode.RUNNING))
    assert orch.get(waiting.task_id).state is S.APPROVAL_NEEDED  # D-007: never skips approval
    assert orch.get(working.task_id).state is S.RUNNING
    parts["qa"].unreachable = False
    run_until_quiet(orch)
    assert orch.get(working.task_id).state is S.COMPLETED_VERIFIED
    assert parts["hub"].executed[f"{working.task_id}:a1"] == 1


def test_pause_holds_one_receptor_only(orch, parts):
    t0 = submit(orch, plan(receptor="T0"))
    r11 = submit(orch, plan("ads.topup", receptor="R11"))
    parts["gov"].modes["T0"] = ControlMode.PAUSED
    orch.on_control(None, _control(ControlScope.RECEPTOR, ControlMode.PAUSED, "T0"))
    run_until_quiet(orch)
    assert orch.get(t0.task_id).state is S.HELD and orch.get(t0.task_id).hold_reason == "control"
    assert orch.get(r11.task_id).state is S.COMPLETED_VERIFIED
    parts["gov"].modes["T0"] = ControlMode.RUNNING
    orch.on_control(None, _control(ControlScope.RECEPTOR, ControlMode.RUNNING, "T0"))
    run_until_quiet(orch)
    assert orch.get(t0.task_id).state is S.COMPLETED_VERIFIED


def test_qa_hold_is_not_released_by_resume(orch, parts):
    parts["qa"].verdicts = [(False, False)] * 3
    t = submit(orch)
    run_until_quiet(orch)
    orch.on_control(None, _control(ControlScope.MASTER, ControlMode.PAUSED))
    orch.on_control(None, _control(ControlScope.MASTER, ControlMode.RUNNING))
    assert orch.get(t.task_id).state is S.HELD and orch.get(t.task_id).hold_reason == "qa"


def test_nothing_moves_while_governance_is_unreachable(orch, parts):
    parts["gov"].down = True
    t = submit(orch)
    run_until_quiet(orch)
    assert (
        orch.get(t.task_id).state is S.ACCEPTED and "unreachable" in orch.get(t.task_id).last_error
    )


# Durability (LA-ORC-02, LA-REL-01) ------------------------------------------------------
def test_work_survives_a_restart_with_no_session(make, parts):
    first = make()
    t = submit(first)
    first.close_connection()  # the process (and any voice session) is gone
    second = make()
    run_until_quiet(second)
    assert second.get(t.task_id).state is S.COMPLETED_VERIFIED


def test_two_workers_never_run_the_same_task_twice(make, parts):
    for _ in range(6):
        submit(make())
    workers = [make(), make()]

    def work(o):
        run_until_quiet(o)

    threads = [threading.Thread(target=work, args=(w,)) for w in workers]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert all(n == 1 for n in parts["hub"].executed.values())


def test_history_is_legal_append_only_and_forwarded(orch, db, parts):
    t = submit(orch)
    run_until_quiet(orch)
    assert [e.to_state for e in parts["events"] if e.task_id == t.task_id] == states(
        orch, t.task_id
    )
    for dsn in (db["app"], db["admin"]):
        with psycopg.connect(dsn, autocommit=True) as c:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("UPDATE orchestrator.transitions SET to_state = 'completed-verified'")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute("DELETE FROM orchestrator.tasks")


# No other path to tools, no model in the loop (LA-ORC-05) -------------------------------
ALLOWED = {
    "collections", "datetime", "decimal", "importlib", "typing", "uuid",
    "fastapi", "psycopg", "pydantic", "dyson_contracts", "dyson_orchestrator",
}  # fmt: skip


def test_orchestrator_has_no_tool_or_model_client():
    pkg = Path(__file__).resolve().parents[1] / "src" / "dyson_orchestrator"
    for path in pkg.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = (
                [a.name for a in node.names] if isinstance(node, ast.Import)
                else [node.module] if isinstance(node, ast.ImportFrom) and node.level == 0
                else []
            )  # fmt: skip
            for name in names:
                assert name.split(".")[0] in ALLOWED, f"{path.name} imports {name}"


# HTTP API -------------------------------------------------------------------------------
def test_api(orch):
    client = TestClient(create_app(orch))
    body = {
        "instruction_key": "api-1",
        "instruction": "inspect",
        "plan": plan().model_dump(mode="json"),
    }
    t = client.post("/tasks", json=body).json()
    assert t["state"] == "accepted"
    assert client.post("/tasks", json=body).json()["task_id"] == t["task_id"]
    run_until_quiet(orch)
    assert client.get(f"/tasks/{t['task_id']}").json()["state"] == "completed-verified"
    assert len(client.get(f"/tasks/{t['task_id']}/history").json()) == 3
    review = {"resume": True, "by": "B"}
    assert client.post(f"/tasks/{t['task_id']}/review", json=review).status_code == 422
    assert client.get(f"/tasks/{uuid4()}").status_code == 404

# Orchestrator (card D): Step 5 notes

The package is `dyson_orchestrator`, and it uses the PostgreSQL schema `orchestrator`. It depends only on `dyson_contracts`. It reaches G, A, F, the human reviewer and I through ports in `ports.py`, faked in tests until Step 9.

## How it works

- **Durable queue.** `orchestrator.tasks` holds each task's current state. Every move updates that row and appends to `orchestrator.transitions` in one database transaction. Each move is checked against the legal transitions in `dyson_contracts.tasks`.
- **Workers.** `tick()` claims tasks with `FOR UPDATE SKIP LOCKED`, so any number of workers can run and none processes the same task twice. Nothing depends on a voice session; there isn't one in this component at all.
- **Idempotency key per attempt.** The key is `<task_id>:a<attempt>`.
  - A network retry reuses the key, so G never runs the action twice.
  - A retest after a QA/QC failure is a new attempt with a new key.
  - Re-sending the same instruction (same `instruction_key`) returns the existing task.
- **Lifecycle:**
  1. `accepted` → `approval-needed` when the plan spends money (FINANCIAL) or is high-risk. A gets an approval request for exactly that action.
  2. → `running` once approved, or straight away when no approval is needed.
  3. G executes the action.
  4. F verifies the real output.
  5. → `completed-verified` only on F's passing verdict.
- **QA/QC failure.** The task goes to `failed` and is retested. After 3 consecutive failures it goes to `held` and a human reviewer or you are notified. Only a reviewer or you can resume or close it.
- **G denies the call, or the tool fails.** The task goes to `failed` and is escalated, with no blind retries.
- **STOP, PAUSE, RESUME.** `on_control(command, state)` is a listener for A's control bus:
  - STOP → `stopped`.
  - PAUSE → `held` (D-002).
  - RESUME returns each task to the state it was interrupted in (D-007). A QA/QC hold is never released by RESUME.

## Requirements owned by this step

| ID | Proven by |
|---|---|
| LA-ORC-01 | `test_every_instruction_gets_a_task_id_once`, `test_happy_path_completes_only_after_independent_verification` |
| LA-ORC-02, LA-REL-01 | `test_work_survives_a_restart_with_no_session`, `test_two_workers_never_run_the_same_task_twice` |
| LA-ORC-03, LA-REL-02 | `test_network_retry_reuses_the_key_and_never_duplicates`, `test_every_instruction_gets_a_task_id_once`, `test_tool_answer_is_not_completion` |
| LA-ORC-04 | `test_qa_failure_retests_with_a_new_attempt`, `test_three_consecutive_qa_failures_hold_and_notify`, `test_only_a_person_releases_a_qa_hold`, `test_denial_or_tool_failure_escalates_without_blind_retries` |
| LA-ORC-05 | `test_orchestrator_has_no_tool_or_model_client`. D builds `ToolCallRequest`s for G and holds no adapters or tool credentials. |
| LA-ORC-06 | `test_happy_path_completes_only_after_independent_verification`, `test_tool_answer_is_not_completion` |

Also tested:
- Approvals: `test_money_waits_for_the_founder`, `test_rejected_task_never_runs`.
- Control: `test_stop_ends_active_work_and_resume_returns_each_task_where_it_was`, `test_pause_holds_one_receptor_only`, `test_qa_hold_is_not_released_by_resume`.
- Failing closed: `test_nothing_moves_while_governance_is_unreachable`.
- Append-only history, forwarded to the event sink: `test_history_is_legal_append_only_and_forwarded`.
- The HTTP API: `test_api`.

## Known limits, recorded for later steps

- **A retest after a QA/QC failure needs a new approval if the action needed one.** Each approval can be used only once, so on the retest G denies the call and the task escalates to you. This is safe, but you'll be asked again.
- **A task on QA/QC hold that is later STOPped stays stopped after RESUME.** Only a reviewer or you can close it.
- **A worker holds a task's row lock while calling G and F.** A STOP issued during that call waits for the call to finish. G checks the STOP state on every call, so no new action starts meanwhile.
- **Step 9:**
  - Connect the ports to G, A, F, the reviewer and I.
  - Forward task state and evidence references to I (LA-ORC-07). The transitions table stays the durable record; `event_backlog` covers I being unreachable.
  - Bind HTTP callers to service identities.

## Contract additions to make before Step 9

`TaskPlan`, `ToolRun` and `action_payload` should move into `dyson_contracts`. `action_payload` must produce the same payload as the Tool Hub's.

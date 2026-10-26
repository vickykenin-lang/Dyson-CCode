"""Conversation Engine (card B)."""

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from intelligence_testkit import (
    NOW,
    FakeCatalog,
    FakeMemory,
    FakeModel,
    FakeOrchestrator,
    configure,
)

from dyson_contracts.interface import FounderMessage, Language, Modality, TaskStatusUpdate
from dyson_contracts.tasks import TaskState
from dyson_intelligence.conversation import TASK_CLASS, ConversationEngine, ReplyKind
from dyson_intelligence.router import ModelRouter

SRC = Path(__file__).resolve().parents[1] / "src" / "dyson_intelligence"


def answer(**kw):
    return json.dumps(kw, ensure_ascii=False)


def msg(text, thread=None, language=Language.UNKNOWN, voice_uncertain=False):
    return FounderMessage(
        message_id=uuid4(), thread_id=thread or uuid4(),
        modality=Modality.VOICE if voice_uncertain else Modality.TEXT, text=text,
        language=language, transcription_uncertain=voice_uncertain, sent_at=NOW,
    )  # fmt: skip


class Parts:
    def __init__(self, router, gov, providers):
        self.router, self.gov, self.providers = router, gov, providers
        self.memory, self.orch, self.catalog = FakeMemory(), FakeOrchestrator(), FakeCatalog()
        configure(router, gov, TASK_CLASS,
                  [("primary", "alpha", {}), ("backup", "beta", {"cost": "0.5"})])  # fmt: skip
        self.b = ConversationEngine(router, self.memory, gov, self.orch, self.catalog)

    def says(self, *answers, provider="alpha"):
        self.providers[provider].answers = list(answers)


@pytest.fixture
def parts(router, gov, providers):
    return Parts(router, gov, providers)


def test_hindi_english_hinglish_with_whole_thread(parts):  # LA-CONV-01
    thread = uuid4()
    parts.memory.threads[thread] = [
        {"role": "user", "content": "Pichle hafte ki report kaisi thi?"},
        {"role": "assistant", "content": "Sales 12% upar the."},
    ]
    for lang, text in (("hinglish", "Aur is hafte ka?"), ("hi", "क्या आप बता सकते हैं?"),
                       ("en", "And this week?")):  # fmt: skip
        parts.says(answer(language=lang, kind="answer", text=f"[{lang}] reply"))
        reply = parts.b.handle(msg(text, thread))
        assert reply.kind is ReplyKind.ANSWER and reply.language == Language(lang)
        _, request = parts.providers["alpha"].requests[-1]
        sent = [m.content for m in request.messages]
        assert sent == ["Pichle hafte ki report kaisi thi?", "Sales 12% upar the.", text]


def test_action_becomes_a_prepared_instruction_for_d(parts):  # LA-CONV-02
    parts.says(answer(language="en", kind="action", plan={
        "tool_id": "report.weekly", "arguments": {"week": "2026-W41"},
        "summary": "Weekly report for R11"}))  # fmt: skip
    m = msg("Send me this week's report")
    reply = parts.b.handle(m)
    assert reply.kind is ReplyKind.ACCEPTED and reply.task_state is TaskState.ACCEPTED
    ((key, (task_id, instruction, plan)),) = parts.orch.tasks.items()
    assert key == f"founder-message:{m.message_id}" and task_id == reply.task_id
    assert plan["receptor_id"] == "R11" and plan["standard_id"] == "STD-report"
    assert "approval_id" not in plan  # B can never carry an approval


def test_the_same_message_twice_starts_one_task(parts):  # LA-CONV-02
    parts.says(answer(language="en", kind="action",
                      plan={"tool_id": "report.weekly", "summary": "report"}))  # fmt: skip
    m = msg("Send the report")
    assert parts.b.handle(m).task_id == parts.b.handle(m).task_id
    assert len(parts.orch.tasks) == 1


@pytest.mark.parametrize("model_answer", [
    answer(language="en", kind="clarify", text="Which week do you mean?"),
    answer(language="en", kind="action", plan={"tool_id": "listing.publish", "summary": "x"}),
    answer(language="en", kind="action", plan={"tool_id": "bank.transfer", "summary": "x"}),
    answer(language="en", kind="action", plan={"tool_id": "listing.publish", "receptor_id": "R99",
                                               "summary": "x"}),
    "Sure, I did it!",
    answer(language="en", kind="action"),
])  # fmt: skip
def test_ambiguous_requests_are_clarified_not_guessed(parts, model_answer):  # LA-CONV-03
    parts.says(model_answer)
    reply = parts.b.handle(msg("Publish it"))
    assert reply.kind is ReplyKind.CLARIFY and reply.text.endswith("?")
    assert parts.orch.tasks == {}


def test_two_receptors_and_none_named_asks_which(parts):  # LA-CONV-03
    parts.says(answer(language="hinglish", kind="action",
                      plan={"tool_id": "listing.publish", "summary": "publish"}))  # fmt: skip
    reply = parts.b.handle(msg("Listing daal do"))
    assert reply.kind is ReplyKind.CLARIFY and "R11, R12" in reply.text
    assert reply.language is Language.HINGLISH


def test_uncertain_speech_is_confirmed_before_anything(parts):  # LA-CONV-03
    reply = parts.b.handle(msg("send fifty thousand", voice_uncertain=True))
    assert reply.kind is ReplyKind.CLARIFY and "send fifty thousand" in reply.text
    assert not parts.providers["alpha"].requests and parts.orch.tasks == {}


def test_persona_is_grounded_in_the_approved_register(parts):  # LA-CONV-04
    parts.says(answer(language="en", kind="answer", text="hi"))
    parts.b.handle(msg("hello"))
    _, request = parts.providers["alpha"].requests[-1]
    assert "- AMD-1 v1.0: Plane separation" in request.system
    assert "- AMD-4 v1.0: No preapproved model" in request.system
    assert "Answer general questions" in request.system  # not only tool work
    parts.b._clock = lambda: datetime(2026, 10, 17, 14, 30, tzinfo=UTC)
    parts.says(answer(language="en", kind="answer", text="It is 15:30 in London."))
    parts.b.handle(msg("what time is it in London?"))
    _, request = parts.providers["alpha"].requests[-1]
    assert "Today is Saturday 17 October 2026, 14:30 UTC." in request.system
    parts.memory.rules = []
    reply = parts.b.handle(msg("hello"))
    assert reply.kind is ReplyKind.UNAVAILABLE and parts.orch.tasks == {}


def test_improvements_are_proposed_never_applied(parts):  # LA-CONV-05, LA-G-02
    parts.says(answer(language="en", kind="proposal", proposal={
        "rule_id": "AMD-7", "diff": "- 3 retries\n+ 2 retries",
        "rationale": "Retries past 2 have never succeeded in the last 30 days."}))  # fmt: skip
    consumed = list(parts.gov.consumed)
    reply = parts.b.handle(msg("Any ideas to improve the workflow?"))
    assert reply.kind is ReplyKind.PROPOSAL and reply.proposal_id is not None
    assert "Nothing changes unless you approve" in reply.text
    assert parts.gov.proposals[0][0] == "AMD-7"
    assert parts.gov.consumed == consumed  # B used no approval
    assert parts.orch.tasks == {}


def test_b_has_no_power_to_approve_spend_or_deploy():  # LA-CONV-05, LA-CONV-02
    tree = ast.parse((SRC / "conversation.py").read_text())
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}  # fmt: skip
    assert not called & {"approve", "consume_approval", "check_approval", "call", "deploy",
                         "admit", "set_budget", "register_model", "rewrite"}  # fmt: skip
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not {m for m in imports if m and m.split(".")[0] in {"dyson_toolhub", "psycopg"}}


def test_200_ok_is_never_reported_as_done(parts):  # LA-CONV-07
    parts.says(answer(language="en", kind="action", text="Done! The tool returned 200 OK.",
                      plan={"tool_id": "report.weekly", "summary": "report"}))  # fmt: skip
    reply = parts.b.handle(msg("Send the report"))
    assert reply.kind is ReplyKind.ACCEPTED and "not done yet" in reply.text
    assert "200" not in reply.text
    task_id = reply.task_id
    parts.orch.updates[task_id] = TaskStatusUpdate(
        task_id=task_id, state=TaskState.RUNNING, message="tool answered 200 OK", at=NOW
    )
    status = parts.b.status(task_id)
    assert "not done until it is verified" in status.text and "done and" not in status.text
    with pytest.raises(ValueError, match="verified evidence"):
        TaskStatusUpdate(task_id=task_id, state=TaskState.COMPLETED_VERIFIED, at=NOW)
    evidence = uuid4()
    parts.orch.updates[task_id] = TaskStatusUpdate(
        task_id=task_id,
        state=TaskState.COMPLETED_VERIFIED,
        verified_evidence_ids=(evidence,),
        at=NOW,
    )
    status = parts.b.status(task_id)
    assert "done and verified" in status.text and str(evidence) in status.text


def test_losing_a_provider_keeps_task_state_and_memory(parts):  # LA-RTR-04, LA-G-06
    thread = uuid4()
    parts.memory.threads[thread] = [{"role": "user", "content": "Track R11 sales weekly"}]
    plan = {"tool_id": "report.weekly", "summary": "report"}
    parts.says(answer(language="en", kind="action", plan=plan))
    first = parts.b.handle(msg("Send the report", thread))
    history_before = list(parts.memory.threads[thread])

    parts.providers["alpha"].down = True  # the cheapest provider disappears mid-thread
    parts.says(answer(language="en", kind="action", plan=plan), provider="beta")
    second = parts.b.handle(msg("And send it again for last week", thread))
    assert second.kind is ReplyKind.ACCEPTED
    _, request = parts.providers["beta"].requests[-1]
    assert request.messages[0].content == "Track R11 sales weekly"  # the thread survived
    assert parts.memory.threads[thread] == history_before
    assert parts.b.status(first.task_id).task_state is TaskState.ACCEPTED  # D's task untouched
    assert len(parts.orch.tasks) == 2


def test_no_route_at_all_starts_nothing(parts):  # LA-RTR-04
    parts.providers["alpha"].down = parts.providers["beta"].down = True
    reply = parts.b.handle(msg("Send the report"))
    assert reply.kind is ReplyKind.UNAVAILABLE and "Nothing was started" in reply.text
    assert parts.orch.tasks == {}


# --- second brain: grounding the Founder's own notes into the reply (knowledge retrieval) --------


class _Hit:
    def __init__(self, path, text, similarity):
        self.path, self.text, self.similarity = path, text, similarity


class _Knowledge:
    def __init__(self, *hits, error=False):
        self.hits, self.error, self.queries = list(hits), error, []

    def search(self, query):
        self.queries.append(query)
        if self.error:
            raise RuntimeError("the embedder is unreachable")
        return list(self.hits)


def _grounded(conn, gov, clock, knowledge, *, provider="bedrock"):
    """A conversation engine wired to a knowledge index and one trusted provider (so a sensitive,
    grounded call has somewhere to route). Returns (engine, that provider's fake adapter)."""
    model = FakeModel('{"language": "en", "kind": "answer", "text": "ok"}')
    router = ModelRouter(conn, gov, {provider: model}, clock)
    configure(router, gov, TASK_CLASS, [("trusted-1", provider, {})])
    b = ConversationEngine(router, FakeMemory(), gov, FakeOrchestrator(), FakeCatalog(), clock,
                           knowledge=knowledge)  # fmt: skip
    return b, model


def test_relevant_notes_ground_the_reply_and_mark_it_sensitive(conn, gov, clock):  # second brain
    k = _Knowledge(_Hit("social-media/plan.md", "Reels teen baar a week.", 0.55))
    b, model = _grounded(conn, gov, clock, k)
    model.answers = [answer(language="hinglish", kind="answer",
                            text="Plan yahan hai (social-media/plan.md)")]  # fmt: skip
    reply = b.handle(msg("mera social media wala plan kahan hai"))
    assert reply.kind is ReplyKind.ANSWER
    assert k.queries == ["mera social media wala plan kahan hai"]
    _, request = model.requests[-1]
    assert request.sensitive is True  # the Founder's notes never go to an untrusted relay
    assert "social-media/plan.md" in request.system and "Reels teen baar a week." in request.system


def test_off_topic_questions_ground_nothing_and_stay_non_sensitive(conn, gov, clock):
    k = _Knowledge(_Hit("finance/invoices.md", "GST stuff", 0.12))  # far below the threshold
    b, model = _grounded(conn, gov, clock, k)
    model.answers = [answer(language="en", kind="answer", text="Berlin is the capital of Germany.")]
    reply = b.handle(msg("what is the capital of Germany?"))
    assert reply.kind is ReplyKind.ANSWER
    _, request = model.requests[-1]
    assert request.sensitive is False and "finance/invoices.md" not in request.system


def test_a_broken_knowledge_index_never_breaks_the_conversation(conn, gov, clock):
    b, model = _grounded(conn, gov, clock, _Knowledge(error=True))
    model.answers = [answer(language="en", kind="answer", text="hello")]
    reply = b.handle(msg("hello"))
    assert reply.kind is ReplyKind.ANSWER  # the index failed, B answered anyway
    _, request = model.requests[-1]
    assert request.sensitive is False

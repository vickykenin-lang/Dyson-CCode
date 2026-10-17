"""Dyson Conversation Engine (card B): understand, decide, prepare. Never execute.

B reads the Founder's message in Hindi, English or Hinglish with the whole thread as context
(LA-CONV-01), asks when the request is ambiguous (LA-CONV-03), and hands a prepared plan to D
(LA-CONV-02). It may propose rule or workflow improvements (LA-CONV-05, LA-G-02), but those go to
A as proposals the Founder decides. It has no tool client, no approval power and no way to
deploy anything.

The model's answer is only a proposal to B. Everything that matters is checked here in code:
the tool must be admitted, the Receptor must be one that tool serves, and the plan must name the
QA/QC standard F will verify against. Status the Founder reads is composed from D's task state,
never from model text, so "200 OK" can never be reported as done (LA-CONV-07).
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import JsonValue, ValidationError

from dyson_contracts.common import Component, Contract, Money, NonEmptyStr, ReceptorId, RiskLevel
from dyson_contracts.interface import FounderMessage, Language, TaskStatusUpdate
from dyson_contracts.tasks import TaskState

from .models import ChatMessage, ModelRequest
from .ports import GovernancePort, MemoryPort, OrchestratorPort, RouterPort, ToolCatalogPort

TASK_CLASS = "conversation.interpret"
THREAD_CONTEXT_LIMIT = 50
MAX_OUTPUT_TOKENS = 2000


class ReplyKind(StrEnum):
    CLARIFY = "clarify"
    ACCEPTED = "accepted"  # handed to D; not done
    ANSWER = "answer"
    PROPOSAL = "proposal"  # sent to A for the Founder to decide
    UNAVAILABLE = "unavailable"


class Reply(Contract):
    kind: ReplyKind
    text: NonEmptyStr
    language: Language
    task_id: UUID | None = None
    task_state: TaskState | None = None
    proposal_id: UUID | None = None


class PreparedPlan(Contract):
    """What B hands to D. It matches D's TaskPlan and carries no approval and no credential."""

    tool_id: NonEmptyStr
    arguments: dict[str, JsonValue] = {}
    receptor_id: ReceptorId | None = None
    risk: RiskLevel = RiskLevel.LOW
    estimated_spend: Money | None = None
    standard_id: NonEmptyStr
    summary: NonEmptyStr


class _Plan(Contract):
    tool_id: NonEmptyStr
    arguments: dict[str, JsonValue] = {}
    receptor_id: ReceptorId | None = None
    risk: RiskLevel = RiskLevel.LOW
    estimated_spend: Money | None = None
    summary: NonEmptyStr


class _Proposal(Contract):
    rule_id: NonEmptyStr
    diff: NonEmptyStr
    rationale: NonEmptyStr


class _Interpretation(Contract):
    language: Language
    kind: str  # clarify | action | answer | proposal
    text: str = ""  # the question, the answer, or a short note to the Founder
    plan: _Plan | None = None
    proposal: _Proposal | None = None


INTERPRETATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["language", "kind"],
    "properties": {
        "language": {
            "enum": ["hi", "en", "hinglish"],
            "description": "The Founder's language: hi = Hindi in Devanagari, en = English, "
            "hinglish = Hindi or mixed Hindi-English written in Latin letters",
        },
        "kind": {"enum": ["clarify", "action", "answer", "proposal"]},
        "text": {"type": "string", "description": "The question or answer, in that language"},
        "plan": {
            "type": "object",
            "description": "Only when kind is action: the one approved tool call to prepare.",
            "required": ["tool_id", "arguments", "summary"],
            "properties": {
                "tool_id": {"type": "string", "description": "One of the approved tools"},
                "arguments": {"type": "object", "description": "As the tool describes"},
                "receptor_id": {"type": "string", "description": "e.g. T0 for t0.* tools"},
                "risk": {"enum": ["low", "medium", "high"]},
                "summary": {"type": "string", "description": "One line, in English"},
            },
        },
        "proposal": {
            "type": "object",
            "description": "Only when kind is proposal: a change to an approved rule.",
            "required": ["rule_id", "diff", "rationale"],
            "properties": {
                "rule_id": {"type": "string", "description": "e.g. AMD-7"},
                "diff": {"type": "string"},
                "rationale": {"type": "string"},
            },
        },
    },
}

# Fixed sentences B uses when it speaks for itself. The model never writes these.
_TEXT = {
    "unclear": {
        Language.ENGLISH: "I am not sure what you want me to do. Could you say it another way?",
        Language.HINDI: "मुझे ठीक से समझ नहीं आया कि आप क्या करवाना चाहते हैं। "
        "क्या आप दूसरे शब्दों में बता सकते हैं?",
        Language.HINGLISH: "Mujhe clear nahi hua ki aap kya karwana chahte hain. "
        "Thoda aur bata sakte hain?",
    },
    "unknown_tool": {
        Language.ENGLISH: "I cannot find an approved tool for that. What should be used?",
        Language.HINDI: "इसके लिए कोई स्वीकृत टूल नहीं मिला। किसका उपयोग करना चाहिए?",
        Language.HINGLISH: "Iske liye koi approved tool nahi mila. Kaunsa use karna hai?",
    },
    "which_receptor": {
        Language.ENGLISH: "Which Receptor should do this: {options}?",
        Language.HINDI: "यह काम कौन सा Receptor करे: {options}?",
        Language.HINGLISH: "Yeh kaam kaunsa Receptor kare: {options}?",
    },
    "confirm_speech": {
        Language.ENGLISH: 'I heard: "{text}". Is that right?',
        Language.HINDI: 'मैंने सुना: "{text}". क्या यह सही है?',
        Language.HINGLISH: 'Maine suna: "{text}". Kya yeh sahi hai?',
    },
    "accepted": {
        Language.ENGLISH: "Accepted as task {task_id}. It is {state}, not done yet. "
        "I will tell you when it is verified.",
        Language.HINDI: "काम {task_id} स्वीकार हुआ। स्थिति: {state}, अभी पूरा नहीं हुआ। "
        "सत्यापन होने पर बताऊँगा।",
        Language.HINGLISH: "Task {task_id} accept ho gaya. Status: {state}, abhi done nahi hai. "
        "Verify hote hi bataunga.",
    },
    "proposal": {
        Language.ENGLISH: "I have proposed a change to {rule_id}. Nothing changes unless you "
        "approve it on Direct Founder Controls.",
        Language.HINDI: "मैंने {rule_id} में बदलाव का प्रस्ताव रखा है। आपकी मंज़ूरी के बिना कुछ नहीं बदलेगा।",
        Language.HINGLISH: "Maine {rule_id} mein change propose kiya hai. Aapke approve kiye bina "
        "kuch nahi badlega.",
    },
    "unavailable": {
        Language.ENGLISH: "I cannot think this through right now: {reason}. Nothing was started.",
        Language.HINDI: "अभी मैं इस पर काम नहीं कर पा रहा: {reason}. कुछ भी शुरू नहीं हुआ।",
        Language.HINGLISH: "Abhi main isko process nahi kar pa raha: {reason}. "
        "Kuch start nahi hua.",
    },
}

# Status text per task state. Only completed-verified, which D can only reach with F's verdict
# and which the contract only allows with verified evidence, may say done.
_STATUS = {
    TaskState.ACCEPTED: "accepted, waiting to run",
    TaskState.APPROVAL_NEEDED: "waiting for your approval",
    TaskState.RUNNING: "running; not done until it is verified",
    TaskState.HELD: "held for review",
    TaskState.STOPPED: "stopped",
    TaskState.FAILED: "failed",
    TaskState.COMPLETED_VERIFIED: "done and verified",
    TaskState.REJECTED: "rejected",
    TaskState.CLOSED: "closed",
}


class ConversationEngine:
    def __init__(
        self,
        router: RouterPort,
        memory: MemoryPort,
        governance: GovernancePort,
        orchestrator: OrchestratorPort,
        catalog: ToolCatalogPort,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._router = router
        self._memory = memory
        self._gov = governance
        self._orch = orchestrator
        self._catalog = catalog
        self._clock = clock

    # --- persona (LA-CONV-04) ---------------------------------------------------------------

    def persona(self) -> str:
        rules = self._memory.locked_rules()
        if not rules:
            raise _Unavailable("the approved rule register could not be read")
        lines = [
            "You are Dyson's Conversation Engine (B). You understand the Founder, decide which",
            "approved tool and Receptor a request needs, and prepare it. You never execute,",
            "approve, spend, deploy or change a rule yourself; you may propose changes, which",
            "the Founder decides. Ask when a request is ambiguous; do not guess. Challenge",
            "assumptions respectfully. Reply in the Founder's language (Hindi, English or",
            "Hinglish). Answer only with JSON matching the given schema.",
            "kind: action = prepare one approved tool call (fill plan); clarify = ask one",
            "question in text; answer = reply in text; proposal = propose a rule change.",
            "Never invent a tool: if no approved tool fits, clarify or answer.",
            "Answer general questions (facts, time zones, explanations) from your own knowledge",
            "and say when an answer may be out of date; you cannot look anything up. For recent",
            "events, say what you knew when you were trained and that it may since have changed;",
            "do not refuse only because you cannot check.",
            f"Today is {self._clock():%A %d %B %Y}, {self._clock():%H:%M} UTC.",
            "",
            "Approved constitutional rules you work under:",
        ]
        lines += [f"- {r['id']} v{r['version']}: {r['title']}" for r in rules]
        return "\n".join(lines)

    # --- one Founder message ----------------------------------------------------------------

    def handle(self, message: FounderMessage) -> Reply:
        lang = _lang(message.language)
        if message.transcription_uncertain:  # never act on speech we may have misheard
            return self._reply(ReplyKind.CLARIFY, lang, "confirm_speech", text=message.text)
        try:
            interp = self._interpret(message)
        except _Unavailable as exc:
            return self._reply(ReplyKind.UNAVAILABLE, lang, "unavailable", reason=str(exc))
        if interp is None:
            return self._reply(ReplyKind.CLARIFY, lang, "unclear")
        lang = _lang(interp.language)

        if interp.kind == "clarify" and interp.text.strip():
            return Reply(kind=ReplyKind.CLARIFY, text=interp.text, language=lang)
        if interp.kind == "answer" and interp.text.strip():
            return Reply(kind=ReplyKind.ANSWER, text=interp.text, language=lang)
        if interp.kind == "proposal" and interp.proposal is not None:
            p = interp.proposal
            proposal_id = self._gov.propose_amendment(p.rule_id, p.diff, p.rationale)
            return self._reply(ReplyKind.PROPOSAL, lang, "proposal", rule_id=p.rule_id,
                               proposal_id=proposal_id)  # fmt: skip
        if interp.kind == "action" and interp.plan is not None:
            return self._prepare(message, interp.plan, lang)
        return self._reply(ReplyKind.CLARIFY, lang, "unclear")

    def prepare(self, plan: dict[str, Any]) -> PreparedPlan | str:
        """Check a model-proposed plan in code. Returns the plan, or the clarification needed."""
        try:
            p = _Plan.model_validate(plan)
        except ValidationError:
            return "unclear"
        tool = self._catalog.tools().get(p.tool_id)
        if tool is None:
            return "unknown_tool"
        receptors = list(tool.get("receptors", []))
        receptor = p.receptor_id
        if receptors and receptor is None:
            if len(receptors) != 1:
                return "which_receptor"
            receptor = receptors[0]
        if receptor is not None and receptor not in receptors:
            return "which_receptor"
        return PreparedPlan(
            tool_id=p.tool_id,
            arguments=p.arguments,
            receptor_id=receptor,
            risk=p.risk,
            estimated_spend=p.estimated_spend,
            standard_id=tool["standard_id"],
            summary=p.summary,
        )

    def _prepare(self, message: FounderMessage, plan: _Plan, lang: Language) -> Reply:
        prepared = self.prepare(plan.model_dump(mode="json"))
        if isinstance(prepared, str):
            options = ", ".join(self._catalog.tools().get(plan.tool_id, {}).get("receptors", []))
            return self._reply(ReplyKind.CLARIFY, lang, prepared, options=options)
        # The message id is the idempotency key: a repeated message cannot start a second task.
        update = self._orch.submit(
            f"founder-message:{message.message_id}",
            message.text,
            prepared.model_dump(mode="json"),
        )
        return Reply(
            kind=ReplyKind.ACCEPTED,
            text=_TEXT["accepted"][lang].format(
                task_id=update.task_id, state=_STATUS[update.state]
            ),  # fmt: skip
            language=lang,
            task_id=update.task_id,
            task_state=update.state,
        )

    # --- status (LA-CONV-07) ----------------------------------------------------------------

    def status(self, task_id: UUID) -> Reply:
        return self.describe(self._orch.status(task_id))

    @staticmethod
    def describe(update: TaskStatusUpdate, language: Language = Language.ENGLISH) -> Reply:
        """Words for a task state. What a tool answered (200 OK or anything else) never matters."""
        text = f"Task {update.task_id}: {_STATUS[update.state]}."
        if update.state is TaskState.COMPLETED_VERIFIED:
            text += f" Evidence: {', '.join(str(e) for e in update.verified_evidence_ids)}."
        return Reply(kind=ReplyKind.ANSWER, text=text, language=_lang(language),
                     task_id=update.task_id, task_state=update.state)  # fmt: skip

    # --- internals --------------------------------------------------------------------------

    def _interpret(self, message: FounderMessage) -> _Interpretation | None:
        history = self._memory.thread_context(message.thread_id, THREAD_CONTEXT_LIMIT)
        msgs = [
            ChatMessage(role=m["role"], content=m["content"])
            for m in history
            if m.get("role") in ("user", "assistant") and m.get("content")
        ]
        msgs.append(ChatMessage(role="user", content=message.text))
        tools = {k: v.get("description", "") for k, v in self._catalog.tools().items()}
        system = self.persona() + "\n\nApproved tools:\n" + json.dumps(tools, ensure_ascii=False)
        request = ModelRequest(system=system, messages=tuple(msgs),
                               max_output_tokens=MAX_OUTPUT_TOKENS,
                               response_schema=INTERPRETATION_SCHEMA)  # fmt: skip
        try:
            routed = self._router.complete(Component.CONVERSATION_ENGINE, TASK_CLASS, request)
        except Exception as exc:
            raise _Unavailable(str(exc) or type(exc).__name__) from exc
        try:
            return _Interpretation.model_validate(json.loads(routed.response.text))
        except (ValueError, ValidationError):
            return None  # an answer we cannot read is treated as unclear, never guessed at

    def _reply(self, kind: ReplyKind, lang: Language, key: str, *, proposal_id: UUID | None = None,
               **fmt: Any) -> Reply:  # fmt: skip
        return Reply(kind=kind, text=_TEXT[key][lang].format(**fmt), language=lang,
                     proposal_id=proposal_id)  # fmt: skip


class _Unavailable(Exception):
    pass


def _lang(language: Language | str) -> Language:
    lang = Language(language)
    return Language.ENGLISH if lang is Language.UNKNOWN else lang

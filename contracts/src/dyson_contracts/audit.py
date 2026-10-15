"""Audit events (LA-MEM-07). The audit log is append-only; AI components cannot alter it."""

from enum import StrEnum
from uuid import UUID

from pydantic import JsonValue

from .common import Component, Contract, NonEmptyStr, Timestamp


class AuditKind(StrEnum):
    CONSEQUENTIAL_ACTION = "consequential_action"
    TOOL_CALL = "tool_call"
    TOOL_CALL_DENIED = "tool_call_denied"
    APPROVAL = "approval"
    CONTROL_EVENT = "control_event"
    CONFIG_CHANGE = "config_change"
    POLICY_DECISION = "policy_decision"
    TASK_TRANSITION = "task_transition"


class AuditEvent(Contract):
    event_id: UUID
    kind: AuditKind
    actor: Component
    at: Timestamp
    summary: NonEmptyStr
    task_id: UUID | None = None
    ref_id: UUID | None = None  # the approval, tool call, command or change this event records
    data: dict[str, JsonValue] = {}

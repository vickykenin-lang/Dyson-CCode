"""STOP / PAUSE / RESUME (AMD-5). The red control path carries these; no LLM is involved."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import model_validator

from .common import Component, Contract, ReceptorId, Timestamp


class ControlCommandType(StrEnum):
    STOP = "stop"
    PAUSE = "pause"
    RESUME = "resume"


class ControlScope(StrEnum):
    MASTER = "master"  # central master STOP over everything
    RECEPTOR = "receptor"  # one Receptor


class ControlCommand(Contract):
    command_id: UUID
    command: ControlCommandType
    scope: ControlScope
    receptor_id: ReceptorId | None = None
    issued_by: Literal[Component.FOUNDER, Component.GOVERNANCE_CORE]
    issued_at: Timestamp
    # Approval record that authorizes a RESUME. Required for every RESUME.
    authorization_id: UUID | None = None
    reason: str = ""

    @model_validator(mode="after")
    def _checks(self) -> "ControlCommand":
        if self.scope is ControlScope.MASTER and self.receptor_id is not None:
            raise ValueError("a master command has no receptor_id")
        if self.scope is ControlScope.RECEPTOR and self.receptor_id is None:
            raise ValueError("a receptor command needs receptor_id")
        if self.command is ControlCommandType.RESUME:
            if self.issued_by is not Component.FOUNDER:
                raise ValueError("only the Founder can RESUME; nothing resumes automatically")
            if self.authorization_id is None:
                raise ValueError("RESUME needs an authorization_id")
        return self


class ControlMode(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"


class ControlState(Contract):
    """Current control state for the master scope or one Receptor. G reads it on every call."""

    scope: ControlScope
    receptor_id: ReceptorId | None = None
    mode: ControlMode
    serious_breach: bool = False
    last_command_id: UUID | None = None
    since: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "ControlState":
        if (self.scope is ControlScope.RECEPTOR) != (self.receptor_id is not None):
            raise ValueError("receptor_id is required exactly for receptor scope")
        return self

"""Supply-chain records (AMD-13): the gate in A admits, the registry in G enforces."""

from enum import StrEnum
from uuid import UUID

from pydantic import model_validator

from .common import Contract, NonEmptyStr, RiskLevel, Timestamp


class IntegrationKind(StrEnum):
    PACKAGE = "package"
    PLUGIN = "plugin"
    API = "api"
    MCP_SERVER = "mcp_server"
    MODEL = "model"
    SKILL = "skill"
    INTEGRATION = "integration"


class IntegrationStatus(StrEnum):
    PROPOSED = "proposed"
    ADMITTED = "admitted"
    BLOCKED = "blocked"
    ISOLATED = "isolated"
    REVOKED = "revoked"


class IntegrationRecord(Contract):
    integration_id: NonEmptyStr
    kind: IntegrationKind
    name: NonEmptyStr
    version: NonEmptyStr
    risk: RiskLevel
    status: IntegrationStatus
    security_checked: bool
    change_record_ref: NonEmptyStr
    founder_approval_id: UUID | None = None
    updated_at: Timestamp

    @model_validator(mode="after")
    def _checks(self) -> "IntegrationRecord":
        if self.status is IntegrationStatus.ADMITTED:
            if not self.security_checked:
                raise ValueError("nothing is admitted before security checks")
            if self.risk is RiskLevel.HIGH and self.founder_approval_id is None:
                raise ValueError("a high-risk integration needs Founder approval")
        return self

    @property
    def callable(self) -> bool:
        return self.status is IntegrationStatus.ADMITTED

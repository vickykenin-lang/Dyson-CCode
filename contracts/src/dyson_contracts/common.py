"""Base types shared by every contract."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints


class Contract(BaseModel):
    """Every contract is immutable and rejects unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Component(StrEnum):
    """Actors and components named in the Master Architecture (PRD sections 4 and 5)."""

    FOUNDER = "founder"
    APP = "app"
    ENTRY_GATEWAY = "entry_gateway"
    DIRECT_FOUNDER_CONTROLS = "direct_founder_controls"
    GOVERNANCE_CORE = "A"
    CONVERSATION_ENGINE = "B"
    MODEL_ROUTER = "C"
    ORCHESTRATOR = "D"
    MONITORING = "E"
    QA_QC = "F"
    TOOL_HUB = "G"
    FINANCIAL_CONTROL = "H"
    MEMORY_EVIDENCE = "I"
    FINANCIAL_DASHBOARD = "J"
    HERMES = "hermes"
    CORE_RD = "core_rd"
    RECEPTOR = "receptor"
    HUMAN_REVIEWER = "human_reviewer"


class RiskLevel(StrEnum):
    """Risk classes. The rules that assign them are decided at implementation gate 4."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


Timestamp = AwareDatetime
NonEmptyStr = Annotated[str, StringConstraints(min_length=1)]
# R11..Rn are business Receptors; T0 is the synthetic no-money test Receptor (LA-IF-12).
ReceptorId = Annotated[str, StringConstraints(pattern=r"^(T0|R[1-9][0-9]*)$")]
IdempotencyKey = Annotated[
    str, StringConstraints(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
CurrencyCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class Money(Contract):
    amount: Annotated[Decimal, Field(ge=0)]
    currency: CurrencyCode

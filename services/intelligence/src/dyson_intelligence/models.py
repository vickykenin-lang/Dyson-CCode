"""Provider-neutral shapes for model calls and model governance."""

from decimal import Decimal
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, JsonValue

from dyson_contracts.common import Contract, CurrencyCode, NonEmptyStr, Timestamp

Role = Literal["user", "assistant"]


class ChatMessage(Contract):
    role: Role
    content: NonEmptyStr


class ModelRequest(Contract):
    system: str = ""
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    max_output_tokens: int = Field(ge=1)
    response_schema: dict[str, JsonValue] | None = None  # ask for JSON matching this schema


class ModelResponse(Contract):
    text: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)


class ModelSpec(Contract):
    """A model approved for use: identity, provider and price per million tokens."""

    model_id: NonEmptyStr  # also its integration_id in A's registry
    provider: NonEmptyStr
    input_price_per_mtok: Annotated[Decimal, Field(ge=0)]
    output_price_per_mtok: Annotated[Decimal, Field(ge=0)]
    currency: CurrencyCode


class AcceptanceBar(Contract):
    """The Founder-defined bar a model must reliably meet for one class of task."""

    task_class: NonEmptyStr
    min_quality: float = Field(ge=0, le=1)  # share of real benchmark tasks passed
    max_latency_ms: int = Field(ge=1)


class ModelBudget(Contract):
    task_class: NonEmptyStr
    max_cost_per_day: Annotated[Decimal, Field(ge=0)]
    currency: CurrencyCode
    max_output_tokens_per_call: int = Field(ge=1)


class Qualification(Contract):
    """One benchmark run of a model on real tasks of a class (LA-RTR-03)."""

    model_id: NonEmptyStr
    task_class: NonEmptyStr
    tasks_run: int = Field(ge=1)
    tasks_passed: int = Field(ge=0)
    p95_latency_ms: int = Field(ge=0)
    cost_per_task: Annotated[Decimal, Field(ge=0)]
    currency: CurrencyCode
    evidence_ref: NonEmptyStr
    run_at: Timestamp

    @property
    def quality(self) -> float:
        return self.tasks_passed / self.tasks_run


class Attempt(Contract):
    model_id: str
    ok: bool
    error: str = ""


class RoutedResponse(Contract):
    """What C answers: the text, the model that actually served it and every attempt before."""

    call_id: UUID
    model_id: NonEmptyStr
    response: ModelResponse
    cost: Annotated[Decimal, Field(ge=0)]
    currency: CurrencyCode
    attempts: tuple[Attempt, ...] = Field(min_length=1)

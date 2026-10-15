"""Model Router & Fallback (card C): the only approved path from Layer A to any model.

- Only models that A's supply-chain gate admitted AND that were registered here with a Founder
  approval can be called (LA-RTR-01, LA-RTR-06). No model is built in (LA-RTR-03, AMD-4).
- Per task class, the route is every qualified model that meets the Founder's acceptance bar,
  cheapest first; the rest of the route is the tested fallback (LA-RTR-02, LA-RTR-04).
- Every attempt reserves its worst-case cost against the approved daily budget before the model
  is called, and the per-call token limit is enforced (LA-RTR-05).
- C keeps no task state and no memory. Losing a provider loses nothing but that provider
  (LA-G-06): the next model on the route answers, and B's thread lives in I.
"""

from collections.abc import Callable
from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import psycopg
from psycopg.types.json import Jsonb

from dyson_contracts.approvals import ApprovalCategory
from dyson_contracts.common import Component
from dyson_contracts.digests import external_action_digest
from dyson_contracts.integrations import IntegrationKind

from .models import (
    AcceptanceBar,
    Attempt,
    ModelBudget,
    ModelRequest,
    ModelResponse,
    ModelSpec,
    Qualification,
    RoutedResponse,
)
from .ports import GovernancePort, ModelAdapter

# Who may ask C for a model. D, G, F, H and the Receptors have no reason to; A must not use one.
CALLERS = frozenset({Component.CONVERSATION_ENGINE, Component.HERMES})
MTOK = Decimal(1_000_000)


class RouterError(Exception):
    """A refusal. Nothing was sent to any model, or every model on the route failed."""


def change_digest(op: str, value: dict[str, Any]) -> str:
    """The digest the Founder approves for a change to C's configuration."""
    return external_action_digest({"component": "C", "op": op, "value": value})


class ModelRouter:
    def __init__(
        self,
        conn: psycopg.Connection,
        governance: GovernancePort,
        adapters: dict[str, ModelAdapter],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self._conn = conn
        self._gov = governance
        self._adapters = dict(adapters)  # provider -> adapter
        self._clock = clock

    # --- governed configuration (LA-RTR-06) -------------------------------------------------

    def register_model(self, spec: ModelSpec, approval_id: UUID) -> None:
        record = self._gov.registry().get(spec.model_id)
        if record is None or record.kind is not IntegrationKind.MODEL or not record.callable:
            raise RouterError(f"{spec.model_id} is not an admitted model in A's registry")
        value = spec.model_dump(mode="json")
        self._approve("register_model", value, approval_id, ApprovalCategory.INTEGRATION)
        self._conn.execute(
            "INSERT INTO intelligence.models (model_id, spec, enabled, approval_id, at)"
            " VALUES (%s, %s, true, %s, %s)",
            [spec.model_id, Jsonb(value), approval_id, self._clock()],
        )

    def retire_model(self, model_id: str, approval_id: UUID) -> None:
        spec = self._models().get(model_id)
        if spec is None:
            raise RouterError(f"{model_id} is not registered")
        self._approve("retire_model", {"model_id": model_id}, approval_id,
                      ApprovalCategory.INTEGRATION)  # fmt: skip
        self._conn.execute(
            "INSERT INTO intelligence.models (model_id, spec, enabled, approval_id, at)"
            " VALUES (%s, %s, false, %s, %s)",
            [model_id, Jsonb(spec.model_dump(mode="json")), approval_id, self._clock()],
        )

    def set_acceptance_bar(self, bar: AcceptanceBar, approval_id: UUID) -> None:
        value = bar.model_dump(mode="json")
        self._approve("set_acceptance_bar", value, approval_id, ApprovalCategory.RULE_CHANGE)
        self._conn.execute(
            "INSERT INTO intelligence.acceptance_bars (task_class, bar, approval_id, at)"
            " VALUES (%s, %s, %s, %s)",
            [bar.task_class, Jsonb(value), approval_id, self._clock()],
        )

    def set_budget(self, budget: ModelBudget, approval_id: UUID) -> None:
        value = budget.model_dump(mode="json")
        self._approve("set_budget", value, approval_id, ApprovalCategory.FINANCIAL)
        self._conn.execute(
            "INSERT INTO intelligence.budgets (task_class, budget, approval_id, at)"
            " VALUES (%s, %s, %s, %s)",
            [budget.task_class, Jsonb(value), approval_id, self._clock()],
        )

    def record_qualification(self, q: Qualification) -> None:
        """A benchmark result on real tasks. It is evidence, not a decision: it needs no approval,
        and it lets a model onto a route only if the model is also registered and meets the bar."""
        self._conn.execute(
            "INSERT INTO intelligence.qualifications (model_id, task_class, record, at)"
            " VALUES (%s, %s, %s, %s)",
            [q.model_id, q.task_class, Jsonb(q.model_dump(mode="json")), self._clock()],
        )

    def _approve(self, op: str, value: dict, approval_id: UUID, category: ApprovalCategory) -> None:
        digest = change_digest(op, value)
        if not self._gov.check_approval(approval_id, digest, category):
            raise RouterError(f"{op} needs a Founder approval for exactly this change")
        self._gov.consume_approval(approval_id, digest, category)

    # --- routing (LA-RTR-02, LA-RTR-03) -----------------------------------------------------

    def route(self, task_class: str) -> list[str]:
        """Qualified models for the task class, cheapest first. Empty: no model may serve it."""
        bar_row = self._conn.execute(
            "SELECT bar FROM intelligence.acceptance_bars WHERE task_class = %s"
            " ORDER BY seq DESC LIMIT 1",
            [task_class],
        ).fetchone()
        if bar_row is None:
            return []
        bar = AcceptanceBar.model_validate(bar_row["bar"])
        models = self._models()
        registry = self._gov.registry()
        quals = {
            r["model_id"]: Qualification.model_validate(r["record"])
            for r in self._conn.execute(
                "SELECT DISTINCT ON (model_id) model_id, record FROM intelligence.qualifications"
                " WHERE task_class = %s ORDER BY model_id, seq DESC",
                [task_class],
            )
        }
        ok = []
        for model_id, spec in models.items():
            rec, q = registry.get(model_id), quals.get(model_id)
            if rec is None or rec.kind is not IntegrationKind.MODEL or not rec.callable:
                continue  # revoked or isolated at the gate since it was registered
            if q is None or q.quality < bar.min_quality or q.p95_latency_ms > bar.max_latency_ms:
                continue
            if q.currency != spec.currency:
                continue
            ok.append((q.cost_per_task, model_id))
        return [m for _, m in sorted(ok)]

    def _models(self) -> dict[str, ModelSpec]:
        rows = self._conn.execute(
            "SELECT DISTINCT ON (model_id) model_id, spec, enabled FROM intelligence.models"
            " ORDER BY model_id, seq DESC"
        )
        return {r["model_id"]: ModelSpec.model_validate(r["spec"]) for r in rows if r["enabled"]}

    # --- calls (LA-RTR-04, LA-RTR-05) -------------------------------------------------------

    def complete(self, caller: Component, task_class: str, request: ModelRequest) -> RoutedResponse:
        if caller not in CALLERS:
            raise RouterError(f"{caller} may not call a model")
        budget = self._budget(task_class)
        if request.max_output_tokens > budget.max_output_tokens_per_call:
            raise RouterError(
                f"max_output_tokens {request.max_output_tokens} is over the approved"
                f" {budget.max_output_tokens_per_call} per call"
            )
        route = self.route(task_class)
        if not route:
            raise RouterError(f"no qualified model meets the acceptance bar for {task_class}")
        models = self._models()
        call_id, attempts = uuid4(), []
        for n, model_id in enumerate(route, start=1):
            spec = models[model_id]
            if spec.currency != budget.currency:
                attempts.append(Attempt(model_id=model_id, ok=False, error="budget currency"))
                continue
            attempt_id = uuid4()
            worst = _cost(spec, _input_bound(request), request.max_output_tokens)
            self._reserve(attempt_id, call_id, n, caller, task_class, spec, worst, budget)
            adapter = self._adapters.get(spec.provider)
            try:
                if adapter is None:
                    raise RouterError(f"no adapter for provider {spec.provider}")
                response = adapter.complete(request, model_id)
                if response.output_tokens > request.max_output_tokens:
                    raise RouterError("the model returned more tokens than allowed")
            except Exception as exc:  # any provider failure moves on to the fallback
                error = f"{type(exc).__name__}: {exc}"[:500]
                self._settle(attempt_id, call_id, n, caller, task_class, spec, "failed",
                             ModelResponse(text="", input_tokens=0, output_tokens=0),
                             Decimal(0), error)  # fmt: skip
                attempts.append(Attempt(model_id=model_id, ok=False, error=error))
                continue
            cost = _cost(spec, response.input_tokens, response.output_tokens)
            self._settle(attempt_id, call_id, n, caller, task_class, spec, "ok", response, cost, "")
            attempts.append(Attempt(model_id=model_id, ok=True))
            return RoutedResponse(call_id=call_id, model_id=model_id, response=response, cost=cost,
                                  currency=spec.currency, attempts=tuple(attempts))  # fmt: skip
        raise RouterError(f"every model on the route failed: {[a.error for a in attempts]}")

    def spent_today(self, task_class: str, currency: str) -> Decimal:
        return self._spent(self._conn, task_class, currency)

    def _budget(self, task_class: str) -> ModelBudget:
        row = self._conn.execute(
            "SELECT budget FROM intelligence.budgets WHERE task_class = %s"
            " ORDER BY seq DESC LIMIT 1",
            [task_class],
        ).fetchone()
        if row is None:
            raise RouterError(f"no approved budget for {task_class}")
        return ModelBudget.model_validate(row["budget"])

    def _spent(self, conn: psycopg.Connection, task_class: str, currency: str) -> Decimal:
        day = datetime.combine(self._clock().astimezone(UTC).date(), time(0), tzinfo=UTC)
        row = conn.execute(
            "SELECT coalesce(sum(cost), 0) AS s FROM ("
            "  SELECT DISTINCT ON (attempt_id) cost FROM intelligence.calls"
            "  WHERE task_class = %s AND currency = %s AND at >= %s"
            "  ORDER BY attempt_id, seq DESC) latest",
            [task_class, currency, day],
        ).fetchone()
        return Decimal(row["s"])

    def _reserve(self, attempt_id, call_id, n, caller, task_class, spec, worst, budget) -> None:
        with self._conn.transaction():
            self._conn.execute(
                "SELECT pg_advisory_xact_lock(hashtext('intelligence.budget:' || %s))",
                [task_class],
            )
            spent = self._spent(self._conn, task_class, budget.currency)
            if spent + worst > budget.max_cost_per_day:
                raise RouterError(
                    f"{task_class} budget: spent {spent} + up to {worst} would pass"
                    f" {budget.max_cost_per_day} {budget.currency} today"
                )
            self._insert(attempt_id, call_id, n, caller, task_class, spec.model_id, "reserved",
                         0, 0, worst, spec.currency, "")  # fmt: skip

    def _settle(self, attempt_id, call_id, n, caller, task_class, spec, status, resp, cost, error):
        self._insert(attempt_id, call_id, n, caller, task_class, spec.model_id, status,
                     resp.input_tokens, resp.output_tokens, cost, spec.currency, error)  # fmt: skip

    def _insert(self, attempt_id, call_id, n, caller, task_class, model_id, status, tin, tout,
                cost, currency, error) -> None:  # fmt: skip
        self._conn.execute(
            "INSERT INTO intelligence.calls (attempt_id, call_id, attempt, caller, task_class,"
            " model_id, status, input_tokens, output_tokens, cost, currency, error, at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            [
                attempt_id,
                call_id,
                n,
                Component(caller).value,
                task_class,
                model_id,
                status,
                tin,
                tout,
                cost,
                currency,
                error,
                self._clock(),
            ],  # fmt: skip
        )


def _cost(spec: ModelSpec, input_tokens: int, output_tokens: int) -> Decimal:
    return (
        Decimal(input_tokens) * spec.input_price_per_mtok
        + Decimal(output_tokens) * spec.output_price_per_mtok
    ) / MTOK


def _input_bound(request: ModelRequest) -> int:
    """An upper bound on input tokens: no tokenizer emits more tokens than UTF-8 bytes."""
    text = request.system + "".join(m.content for m in request.messages)
    if request.response_schema is not None:
        text += str(request.response_schema)
    return len(text.encode("utf-8")) + 16 * (len(request.messages) + 1)

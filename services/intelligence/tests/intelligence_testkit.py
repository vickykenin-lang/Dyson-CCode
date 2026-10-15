"""Fakes and constants for the intelligence tests. Step 9 replaces the fakes with A, D, G and I."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from dyson_contracts.common import RiskLevel
from dyson_contracts.integrations import IntegrationKind, IntegrationRecord, IntegrationStatus
from dyson_contracts.interface import TaskStatusUpdate
from dyson_contracts.tasks import TaskState
from dyson_intelligence.models import ModelResponse, ModelSpec, Qualification

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


def record(integration_id, kind=IntegrationKind.MODEL, status=IntegrationStatus.ADMITTED):
    return IntegrationRecord(integration_id=integration_id, kind=kind, name=integration_id,
                             version="1", risk=RiskLevel.MEDIUM, status=status,
                             security_checked=True, change_record_ref="CR-test",
                             updated_at=NOW)  # fmt: skip


def spec(model_id, provider, inp="1", out="2", currency="INR"):
    return ModelSpec(model_id=model_id, provider=provider, input_price_per_mtok=Decimal(inp),
                     output_price_per_mtok=Decimal(out), currency=currency)  # fmt: skip


def qual(model_id, task_class, passed=95, latency=500, cost="0.01", currency="INR", subject=None):
    return Qualification(model_id=subject or model_id, task_class=task_class, tasks_run=100,
                         tasks_passed=passed, p95_latency_ms=latency,
                         cost_per_task=Decimal(cost), currency=currency,
                         evidence_ref=f"bench:{model_id}", run_at=NOW)  # fmt: skip


class FakeGovernance:
    def __init__(self):
        self.records: dict[str, IntegrationRecord] = {}
        self.approvals: set[tuple[UUID, str, str]] = set()
        self.consumed: list[UUID] = []
        self.proposals: list[tuple[str, str, str]] = []

    def registry(self):
        return dict(self.records)

    def admit(self, integration_id, kind=IntegrationKind.MODEL):
        self.records[integration_id] = record(integration_id, kind)

    def revoke(self, integration_id):
        old = self.records[integration_id]
        self.records[integration_id] = record(integration_id, old.kind, IntegrationStatus.REVOKED)

    def approve(self, digest, category):
        approval_id = uuid4()
        self.approvals.add((approval_id, digest, str(category)))
        return approval_id

    def check_approval(self, approval_id, action_digest, category):
        return (approval_id, action_digest, str(category)) in self.approvals

    def consume_approval(self, approval_id, action_digest, category):
        self.approvals.discard((approval_id, action_digest, str(category)))
        self.consumed.append(approval_id)

    def propose_amendment(self, rule_id, diff, rationale):
        self.proposals.append((rule_id, diff, rationale))
        return uuid4()


class FakeModel:
    """A provider adapter that answers from a script, or fails while `down` is set."""

    def __init__(self, *answers: str, tokens=(100, 50)):
        self.answers = list(answers)
        self.tokens = tokens
        self.down = False
        self.requests = []

    def complete(self, request, model_id):
        self.requests.append((model_id, request))
        if self.down:
            raise ConnectionError("provider unreachable")
        text = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return ModelResponse(text=text, input_tokens=self.tokens[0], output_tokens=self.tokens[1])


class FakeMemory:
    def __init__(self):
        self.threads: dict[UUID, list[dict[str, str]]] = {}
        self.rules = [
            {"id": "AMD-1", "version": "1.0", "title": "Plane separation"},
            {"id": "AMD-4", "version": "1.0", "title": "No preapproved model"},
        ]

    def thread_context(self, thread_id, limit):
        return list(self.threads.get(thread_id, []))[-limit:]

    def locked_rules(self):
        return list(self.rules)


class FakeOrchestrator:
    def __init__(self):
        self.tasks: dict[str, tuple[UUID, str, dict]] = {}
        self.updates: dict[UUID, TaskStatusUpdate] = {}

    def submit(self, instruction_key, instruction, plan):
        if instruction_key not in self.tasks:
            task_id = uuid4()
            self.tasks[instruction_key] = (task_id, instruction, plan)
            self.updates[task_id] = TaskStatusUpdate(task_id=task_id, state=TaskState.ACCEPTED,
                                                     at=NOW)  # fmt: skip
        return self.updates[self.tasks[instruction_key][0]]

    def status(self, task_id):
        return self.updates[task_id]


class FakeCatalog:
    def __init__(self):
        self.entries = {
            "report.weekly": {"receptors": ["R11"], "standard_id": "STD-report",
                              "description": "Weekly business report"},
            "listing.publish": {"receptors": ["R11", "R12"], "standard_id": "STD-listing",
                                "description": "Publish a product listing"},
        }  # fmt: skip

    def tools(self):
        return dict(self.entries)


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


def configure(router, gov, task_class, models, *, max_cost="100", max_tokens=4000,
              min_quality=0.9, max_latency=2000, currency="INR"):  # fmt: skip
    """Admit, approve, register and qualify models the way the Founder and A would.

    models: (model_id, provider, qualification kwargs) tuples.
    """
    from dyson_contracts.approvals import ApprovalCategory
    from dyson_intelligence.models import AcceptanceBar, ModelBudget
    from dyson_intelligence.router import change_digest

    def approved(op, value, category):
        return gov.approve(change_digest(op, value.model_dump(mode="json")), category)

    bar = AcceptanceBar(task_class=task_class, min_quality=min_quality, max_latency_ms=max_latency)
    router.set_acceptance_bar(
        bar, approved("set_acceptance_bar", bar, ApprovalCategory.RULE_CHANGE)
    )
    budget = ModelBudget(task_class=task_class, max_cost_per_day=Decimal(max_cost),
                         currency=currency, max_output_tokens_per_call=max_tokens)  # fmt: skip
    router.set_budget(budget, approved("set_budget", budget, ApprovalCategory.FINANCIAL))
    for model_id, provider, q in models:
        gov.admit(model_id)
        s = spec(model_id, provider, currency=currency)
        router.register_model(s, approved("register_model", s, ApprovalCategory.INTEGRATION))
        router.record_qualification(qual(model_id, task_class, currency=currency, **q))


def AcceptanceBarFor(task_class, min_quality=0.9, max_latency=2000):  # noqa: N802
    from dyson_intelligence.models import AcceptanceBar

    return AcceptanceBar(task_class=task_class, min_quality=min_quality, max_latency_ms=max_latency)

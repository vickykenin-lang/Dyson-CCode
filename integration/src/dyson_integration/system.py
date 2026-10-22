"""Layer A, assembled from the real components of Steps 2 to 8 on one database.

`LayerA.build` wires everything. `LayerA.bootstrap` then does, as the Founder would on Direct
Founder Controls, what has to happen before T0 can work: admit its tools and the stand-in model
at the integration gate, set T0's limits, activate T0 on acceptance evidence, register the model
in C, and publish the QA standards. Every approval in it goes through DFC with the Founder's
device, exactly like any other.
"""

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row

from dyson_assurance.dashboard import create_app as create_dashboard
from dyson_assurance.db import connect as assurance_connect
from dyson_assurance.finance import FinancialController, LedgerLine, Receipt
from dyson_assurance.monitoring import Monitor, SubjectKind
from dyson_assurance.qa import Check, CheckKind, QAController, QualityStandard
from dyson_contracts.approvals import ApprovalCategory, ApprovalRequest
from dyson_contracts.common import Component, Money, RiskLevel
from dyson_contracts.evidence import EvidenceOutcome, EvidenceRecord, EvidenceStage
from dyson_contracts.integrations import IntegrationKind
from dyson_contracts.lanes import HealthStatus
from dyson_contracts.toolcalls import ToolCallRequest
from dyson_founder_controls.app import create_app as create_controls
from dyson_founder_controls.client import ControlsClient
from dyson_founder_controls.passkey import PasskeyStepUp, PasskeyStore
from dyson_founder_controls.ports import HmacChannelSigner
from dyson_founder_controls.stepup import DeviceKeyStepUp
from dyson_gateway.app import create_app as create_gateway
from dyson_gateway.auth import PasswordAuthenticator, SessionStore
from dyson_gateway.ratelimit import Limits
from dyson_governance.channel import HmacChannel
from dyson_governance.core import GovernanceCore, load_initial_parameters
from dyson_governance.events import ProposalKind, ReceptorLimits
from dyson_governance.policy import PolicyEngine
from dyson_governance.store import PgEventStore
from dyson_intelligence.conversation import TASK_CLASS as CONVERSATION
from dyson_intelligence.conversation import ConversationEngine
from dyson_intelligence.db import connect as intelligence_connect
from dyson_intelligence.hermes.runtime import HermesRuntime
from dyson_intelligence.models import AcceptanceBar, ModelBudget, ModelSpec, Qualification
from dyson_intelligence.router import ModelRouter, change_digest
from dyson_intelligence.router_api import create_app as create_router_api
from dyson_memory.db import connect as memory_connect
from dyson_memory.register_seed import policy_entries, seed_register
from dyson_memory.secrets import LocalSecretStore, SecretGuard
from dyson_memory.store import MemoryStore
from dyson_orchestrator.orchestrator import Orchestrator
from dyson_toolhub.api import create_app as create_toolhub_api
from dyson_toolhub.catalog import Catalog, LaneAdapter, ToolScope, ToolSpec
from dyson_toolhub.hub import ToolHub
from dyson_toolhub.ports import StaticTokens
from dyson_toolhub.store import PgToolStore

from . import t0 as t0_module
from .adapters import (
    ApprovalReminders,
    AuditToMemory,
    CatalogForConversation,
    ConversationForGateway,
    EvidenceToMemory,
    FounderInbox,
    FounderNotices,
    GovernanceForControls,
    GovernanceForIntelligence,
    GovernanceForOrchestrator,
    GovernanceForToolHub,
    HermesGatedRouter,
    MemoryForConversation,
    NomineeOutbox,
    OrchestratorForConversation,
    QAForOrchestrator,
    StatementsForGateway,
    SurvivalWatch,
    TaskEventsToMemory,
    TaskStatus,
    ThreadsForGateway,
    ToolHubForOrchestrator,
    nominee_details,
)
from .hermes_service import RemoteHermes, create_edge, hermes_job
from .live_status import LiveStatus
from .relay import RelaySessions
from .rules_model import MODEL_ID, PROVIDER, RulesModel
from .sandbox_client import SandboxClient
from .sandbox_command import SandboxOperator

Clock = Callable[[], datetime]
HERMES_TASKS = "hermes.research"
BACKUP_MODEL_ID, BACKUP_PROVIDER = "local-rules-2", "local-rules-b"

# The QA/QC standard F applies to each tool B may offer (LA-QA-01).
STANDARDS = {
    "t0.tally": "STD-T0-TALLY",
    "t0.publish": "STD-T0-PUBLISH",
}
DESCRIPTIONS = {
    "t0.tally": 'Tally a list of numbers on the T0 test Receptor. Arguments: {"numbers": [..]}',
    "t0.publish": "Publish a note on the T0 test Receptor (high risk: needs approval). "
    'Arguments: {"note": "text"}',
}


@dataclass
class Settings:
    """Local values. Real secrets come from the secret store in Step 10; none of these numbers
    is a Founder decision except those read from policy/parameters.yaml."""

    policy_dir: Path
    secret_file: Path
    founder_username: str = "founder"
    founder_password: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    gateway_limits: Limits = field(
        default_factory=lambda: Limits(
            requests_per_minute=6000,
            burst=500,
            login_failures_before_lockout=5,
            lockout=timedelta(minutes=15),
        )
    )
    session_max_age: timedelta = timedelta(hours=12)
    session_idle: timedelta = timedelta(hours=1)
    challenge_ttl: timedelta = timedelta(minutes=2)
    # Passkeys on Direct Founder Controls (gate 3, D-014): where they are kept, and the site
    # they belong to. None keeps the development device key only.
    passkey_file: Path | None = None
    passkey_rp_id: str = "localhost"
    passkey_origin: str = "http://localhost:8082"
    poll_seconds: float = 0.05
    # Where this Layer A runs, as written on its evidence, and the release it runs.
    environment: str = "local"
    release: str | None = None
    # Set on AWS: Hermes runs in its own container at this URL (LA-DEP-01). None runs it here.
    hermes_url: str | None = None
    # Set on AWS: the nominee's details (from /dyson/nominee); notices then go by email (SES).
    nominee_file: Path | None = None
    # Set on AWS: Direct Founder Controls runs in its own container here (for the dashboard).
    controls_url: str | None = None


CORE_SECRETS = (
    "channel_key",
    "device_key",
    "orchestrator_token",
    "hermes_token",
    "governance_token",
    "b_router_token",
    "hermes_router_token",
    "hermes_job_token",
)


def write_secret_file(path: Path, canary: str | None = None) -> Path:
    """Development secret store: one namespace per scope, readable only by its owner."""
    data: dict[str, dict[str, str]] = {"core": {}, "T0": {"t0_lane_token": secrets.token_hex(24)}}
    for name in CORE_SECRETS:
        data["core"][name] = secrets.token_hex(32)
    if canary:
        data["core"]["canary_model_api_key"] = canary
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    return path


def add_missing_secrets(path: Path) -> None:
    """A store written by an older release gets the credentials added since; none is changed."""
    data = json.loads(path.read_text())
    missing = [n for n in CORE_SECRETS if n not in data["core"]]
    if missing:
        for name in missing:
            data["core"][name] = secrets.token_hex(32)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.chmod(0o600)
        tmp.replace(path)


class VerifiedFinance:
    """What J shows about money: H's figures, counted as verified only where I holds H's
    stage-8 evidence for them (LA-FIN-05, LA-DASH-04). J reads; it never writes."""

    def __init__(self, finance: FinancialController, memory_dsn: str):
        self._h = finance
        self._conn = memory_connect(memory_dsn)

    def _confirmed(self, evidence_id: UUID) -> bool:
        with self._conn.transaction():
            self._conn.execute("SELECT set_config('dyson.scope', 'core', true)")
            row = self._conn.execute(
                "SELECT outcome, stage, recorded_by FROM memory.evidence WHERE evidence_id = %s",
                [evidence_id],
            ).fetchone()
        return bool(
            row
            and row["outcome"] == "passed"
            and row["recorded_by"] == "H"
            and row["stage"] == int(EvidenceStage.REAL_BUSINESS_OUTCOME_VERIFIED)
        )

    def receipts(self) -> list[Receipt]:
        return [r for r in self._h.receipts() if self._confirmed(r.evidence_id)]

    def ledger(self) -> list[LedgerLine]:
        verified: dict[tuple[str, str], Decimal] = {}
        for r in self.receipts():
            key = (r.receptor_id, r.amount.currency)
            verified[key] = verified.get(key, Decimal(0)) + r.amount.amount
        out = []
        for line in self._h.ledger():
            v = verified.get((line.receptor_id, line.currency), Decimal(0))
            out.append(
                line.model_copy(
                    update={
                        "verified_revenue": v,
                        "unverified_revenue": line.reported_revenue - v,
                        "verified_net_profit": v - line.payments,
                    }
                )
            )
        return out

    def open_items(self) -> int:
        return self._h.open_items()

    def performance(self, currency: str) -> list[tuple[str, Decimal]]:
        rows = [
            (x.receptor_id, x.verified_net_profit) for x in self.ledger() if x.currency == currency
        ]
        return sorted(rows, key=lambda r: r[1], reverse=True)


class Repairs:
    """Bounded low-risk repair inside the preapproved policy (LA-G-05, LA-SAF-05).

    T0's manifest preapproves one repair: restart the worker. Each attempt is first recorded
    with A, which allows at most recovery_attempt_limit (D-008) and then escalates to the
    Founder. The restart goes through G like any action, and F verifies the result
    independently before it counts.
    """

    def __init__(self, layer: "LayerA"):
        self._a = layer
        self.incidents: dict[UUID, list[dict[str, Any]]] = {}

    def check(self) -> None:
        a = self._a
        view = a.monitor.view(SubjectKind.RECEPTOR, t0_module.RECEPTOR_ID)
        if view.status is not HealthStatus.FAILING:
            return
        alert = next(
            (
                x
                for x in a.monitor.alerts()
                if x.subject_id == t0_module.RECEPTOR_ID and x.issue == "bad_status"
            ),
            None,
        )
        incident = alert.alert_id if alert else uuid4()
        attempts = self.incidents.setdefault(incident, [])
        if attempts and attempts[-1]["verified"]:
            return
        if not a.core.record_recovery_attempt(
            incident, t0_module.RECEPTOR_ID, False, "restart T0 worker"
        ):
            if not any(m[2].startswith("Repair limit") for m in a.inbox.messages):
                a.inbox.escalate(
                    "founder",
                    t0_module.RECEPTOR_ID,
                    f"Repair limit reached for T0 incident {incident}; "
                    "only your approval allows more attempts.",
                )
            return
        task_id = uuid4()
        request = ToolCallRequest(
            call_id=uuid4(),
            task_id=task_id,
            idempotency_key=f"repair:{incident}:{len(attempts) + 1}",
            tool_id="t0.restart",
            requested_by=Component.ORCHESTRATOR,
            receptor_id=t0_module.RECEPTOR_ID,
            arguments={},
            risk=RiskLevel.LOW,
            requested_at=a.clock(),
        )
        result = a.hub.call(request, a.tokens[Component.ORCHESTRATOR])
        verdict = None
        if result.status == "executed":
            verdict = a.qa.verify(task_id, t0_module.RECEPTOR_ID, "STD-T0-RESTART", result.result)
        attempts.append(
            {
                "task_id": task_id,
                "status": result.status,
                "verified": bool(verdict and verdict.passed),
                "evidence_ids": verdict.evidence_ids if verdict else (),
            }
        )


class LayerA:
    def __init__(self) -> None:
        raise TypeError("use LayerA.build")

    @classmethod
    def build(
        cls,
        dsns: dict[str, str],
        settings: Settings,
        t0: "t0_module.TestReceptorT0",
        clock: Clock,
        models: dict[str, RulesModel] | None = None,
    ) -> "LayerA":
        self = object.__new__(cls)
        self.dsns, self.settings, self.t0, self.clock = dsns, settings, t0, clock
        store = LocalSecretStore(settings.secret_file)
        self.secrets = store
        core_secret = lambda name: store.get("core", name)  # noqa: E731
        self.tokens = {
            Component.ORCHESTRATOR: core_secret("orchestrator_token"),
            Component.HERMES: core_secret("hermes_token"),
            Component.GOVERNANCE_CORE: core_secret("governance_token"),
        }

        # I
        self.memory_conn = memory_connect(dsns["memory"])
        self.memory = MemoryStore(self.memory_conn, "core", SecretGuard(store))
        self.inbox = FounderInbox(self.memory, clock)

        # A, with the control lane to D, T0 and (through C's gate and G's STOP check) Hermes
        self.orch_listener: list = []
        params = load_initial_parameters(settings.policy_dir)
        self.core = GovernanceCore(
            PgEventStore(dsns["governance"]),
            PolicyEngine.load(settings.policy_dir),
            HmacChannel(core_secret("channel_key").encode()),
            AuditToMemory(self.memory),
            control_listeners=[self._to_orchestrator, t0.on_control],
            clock=clock,
            initial_parameters=params,
        )

        # E, F, H, J
        # F's independent verifier recomputes from the task as D recorded it (looked up lazily).
        verifier = t0_module.T0Verifier(t0, lambda tid: dict(self.orch.get(tid).plan.arguments))
        self.qa = QAController(
            assurance_connect(dsns["assurance"]),
            verifier,
            EvidenceToMemory(self.memory),
            self.inbox,
            clock,
            settings.environment,
        )
        self.monitor = Monitor(
            assurance_connect(dsns["assurance"]),
            self.inbox,
            stale_after=timedelta(hours=int(params["stale_after_hours"])),
            repeated_failure_threshold=int(params["repeated_failure_threshold"]),
            reminder_interval=timedelta(minutes=int(params["founder_reminder_interval_minutes"])),
            clock=clock,
        )
        self.finance = FinancialController(
            assurance_connect(dsns["assurance"]), EvidenceToMemory(self.memory), clock
        )
        self.dashboard: FastAPI = create_dashboard(
            VerifiedFinance(self.finance, dsns["memory"]), self.monitor, self.qa
        )  # type: ignore[arg-type]
        # View-only screen relay for the Founder's sandbox panel (D-026). Shared: the engine opens
        # a session when it drives the sandbox; the panel app shows what is live.
        self.relay = RelaySessions(clock)

        # C, with the stand-in models, and its HTTP API for B and Hermes
        self.models = models or {PROVIDER: RulesModel(), BACKUP_PROVIDER: RulesModel()}
        self.router = ModelRouter(
            intelligence_connect(dsns["intelligence"]),
            GovernanceForIntelligence(self.core),
            self.models,
            clock,
            personal=lambda: nominee_details(settings.nominee_file),
        )
        self.router_api = create_router_api(
            HermesGatedRouter(self.router, self.core),  # type: ignore[arg-type]
            {
                Component.CONVERSATION_ENGINE: core_secret("b_router_token"),
                Component.HERMES: core_secret("hermes_router_token"),
            },
        )

        # G, with T0's five-lane adapters and the core tools
        self.catalog = Catalog()
        self._register_tools()
        self.hub = ToolHub(
            self.catalog,
            GovernanceForToolHub(self.core),
            StaticTokens(self.tokens),
            PgToolStore(dsns["toolhub"]),
            AuditToMemory(self.memory),
            clock,
        )
        self.toolhub_api = create_toolhub_api(
            self.hub, StaticTokens(self.tokens), self.catalog.specs()
        )

        # D
        self.orch = Orchestrator(
            dsns["orchestrator"],
            ToolHubForOrchestrator(self.hub, self.tokens[Component.ORCHESTRATOR]),
            GovernanceForOrchestrator(self.core),
            QAForOrchestrator(self.qa),
            self.inbox.for_orchestrator(),
            TaskEventsToMemory(self.memory, lambda tid: self.orch.get(tid).evidence_ids),
            clock,
        )

        # B, behind the Gateway
        integ = psycopg.connect(dsns["integration"], autocommit=True, row_factory=dict_row)
        self.status = TaskStatus(self.orch, integ, self.memory)
        rule_ids = [e.rule_id for e in policy_entries(settings.policy_dir)]
        self.b = ConversationEngine(
            _RouterOverHttp(TestClient(self.router_api), core_secret("b_router_token")),
            MemoryForConversation(self.memory, rule_ids),
            GovernanceForIntelligence(self.core),
            OrchestratorForConversation(self.orch, self.status),
            CatalogForConversation(self.catalog, self.core, STANDARDS, DESCRIPTIONS),
            clock,
        )
        self.gateway: FastAPI = create_gateway(
            PasswordAuthenticator.create(settings.founder_username, settings.founder_password),
            SessionStore(clock, settings.session_max_age, settings.session_idle),
            settings.gateway_limits,
            ConversationForGateway(
                self.b, self.memory, self.status, SecretGuard(store), clock,
                sandbox=SandboxOperator(
                    ToolHubForOrchestrator(self.hub, self.tokens[Component.ORCHESTRATOR]).call,
                    self.relay,
                    clock,
                ),
            ),
            self.status,
            _AuditEvents(self.memory, clock),
            clock=clock,
            poll_seconds=settings.poll_seconds,
            notices=FounderNotices(self.core, self.memory, clock),
            statements=StatementsForGateway(self.finance, clock),
            threads=ThreadsForGateway(self.memory, dsns["integration"], clock),
            dashboard=LiveStatus(
                dsns,
                self.core,
                self.router,
                self.memory,
                clock,
                {"controls": self._probe_controls, "hermes": self._probe_hermes},
            ),
        )

        # Direct Founder Controls: its own path, to A only. On AWS it is served by its own
        # process (`controls_app`); this copy is the Founder's device for bootstrap and tests.
        self.controls: FastAPI = _controls(self.core, self.memory, store, settings, clock)

        # Hermes, reaching only C's and G's HTTP APIs with its own credentials. On AWS it runs
        # in its own container and reaches them through the edge (LA-DEP-01).
        self.hermes_edge = create_edge(
            self.router_api,
            self.toolhub_api,
            self.core.registry,
            core_secret("hermes_router_token"),
        )
        self.hermes: HermesRuntime | None = None
        self.remote_hermes: RemoteHermes | None = None
        if settings.hermes_url:
            self.remote_hermes = RemoteHermes(settings.hermes_url, core_secret("hermes_job_token"))
        else:
            self.hermes = HermesRuntime(
                _HermesRouterClient(
                    TestClient(self.router_api), core_secret("hermes_router_token")
                ),
                _HermesToolHubClient(TestClient(self.toolhub_api), self.tokens[Component.HERMES]),
                self.core,
                clock,
            )
        self.approval_reminders = ApprovalReminders(
            self.core,
            self.inbox,
            timedelta(minutes=int(params["founder_reminder_interval_minutes"])),
            clock,
        )
        nominee = NomineeOutbox(self.memory, clock)
        if settings.nominee_file is not None and settings.nominee_file.exists():
            from .email_ses import SesNominee

            nominee = SesNominee(settings.nominee_file, nominee)
        self.survival = SurvivalWatch(self.core, self.memory, self.inbox, nominee, clock)
        self.repairs = Repairs(self)
        return self

    # The Founder's own device, for bootstrap and tests: it talks only to DFC.
    def founder_device(self) -> ControlsClient:
        return ControlsClient(
            TestClient(self.controls), self.secrets.get("core", "device_key").encode()
        )

    def approve(self, request: ApprovalRequest) -> str:
        return self.founder_device().decide(request.approval_id, request.action_digest, "approve")[
            "status"
        ]

    def _to_orchestrator(self, command, state) -> None:
        if getattr(self, "orch", None) is not None:
            self.orch.on_control(command, state)

    def _register_tools(self) -> None:
        t0, orch = self.t0, frozenset({Component.ORCHESTRATOR})
        lane = lambda op: LaneAdapter(t0_module.lane_delivery(t0, op))  # noqa: E731
        reg = self.catalog.register
        reg(
            ToolSpec(
                tool_id="t0.tally",
                connector_id="t0-lane",
                allowed_callers=orch,
                scope=ToolScope.RECEPTOR,
            ),
            lane("tally"),
        )
        reg(
            ToolSpec(
                tool_id="t0.publish",
                connector_id="t0-lane",
                allowed_callers=orch,
                scope=ToolScope.RECEPTOR,
                min_risk=RiskLevel.HIGH,
            ),
            lane("publish"),
        )
        reg(
            ToolSpec(
                tool_id="t0.restart",
                connector_id="t0-lane",
                allowed_callers=orch,
                scope=ToolScope.RECEPTOR,
            ),
            lane("restart"),
        )
        reg(
            ToolSpec(
                tool_id="t0.read",
                connector_id="t0-lane",
                allowed_callers=frozenset({Component.ORCHESTRATOR, Component.HERMES}),
                scope=ToolScope.RECEPTOR,
            ),
            lane("read"),
        )
        reg(
            ToolSpec(
                tool_id="hermes.research",
                connector_id="hermes",
                allowed_callers=orch,
                scope=ToolScope.CORE,
            ),
            LaneAdapter(self._hermes_job),
        )
        reg(
            ToolSpec(
                tool_id="finance.reconcile",
                connector_id="h",
                allowed_callers=orch,
                scope=ToolScope.CORE,
            ),
            lambda args: {"matched": self.finance.reconcile()},
        )
        reg(
            ToolSpec(
                tool_id="qa.audit", connector_id="f", allowed_callers=orch, scope=ToolScope.CORE
            ),
            lambda args: {"verdicts": len(self.qa.audit_task(UUID(str(args["task_id"]))))},
        )
        # The Founder's sealed sandbox (D-026): safe browsing on its own; a sensitive act is
        # min_risk HIGH, so G always demands a Founder approval before it runs. Callable only once
        # the sandbox integrations are admitted and the sandbox container is up. Both tools reach
        # the sandbox over sandbox_net; neither moves money or touches Layer A data.
        sandbox = SandboxClient()
        both = frozenset({Component.ORCHESTRATOR, Component.HERMES})
        reg(
            ToolSpec(
                tool_id="sandbox.browse",
                connector_id="dyson.receptor.sandbox",
                allowed_callers=both,
                scope=ToolScope.CORE,
                min_risk=RiskLevel.MEDIUM,
            ),
            lambda args: sandbox.browse(args),
        )
        reg(
            ToolSpec(
                tool_id="sandbox.act",
                connector_id="dyson.receptor.sandbox",
                allowed_callers=both,
                scope=ToolScope.CORE,
                min_risk=RiskLevel.HIGH,  # a sensitive action never runs without a Founder approval
            ),
            LaneAdapter(sandbox.act),
        )

    # Dashboard probes (gate 8): is each separate process answering? Read only.
    def _probe_controls(self) -> dict:
        if self.settings.controls_url:
            import httpx

            r = httpx.get(self.settings.controls_url.rstrip("/") + "/passkeys", timeout=2)
        else:
            r = TestClient(self.controls).get("/passkeys")
        if r.status_code == 404:  # answering, with the device key only (no passkeys configured)
            return {"enrolled": "device key"}
        r.raise_for_status()
        return r.json()

    def _probe_hermes(self) -> str:
        if self.remote_hermes is None:
            return "in process"
        return self.remote_hermes.health()

    def _hermes_job(self, request: ToolCallRequest) -> Any:
        if self.remote_hermes is not None:
            return self.remote_hermes.job(request)
        assert self.hermes is not None
        return hermes_job(self.hermes, request)

    # The worker: one pass of every periodic job ---------------------------------------------
    def tick(self, rounds: int = 1) -> None:
        for _ in range(rounds):
            self.core.sync()  # a STOP made on the separate controls process reaches D and T0
            self.survival.check()  # AMD-12 v1.1
            report = self.t0.health_report()  # Monitoring lane
            if report is not None:
                self.monitor.ingest(report)
            self.monitor.sweep(SubjectKind.RECEPTOR, [t0_module.RECEPTOR_ID])
            self.repairs.check()
            self.orch.tick()
            self.monitor.remind()
            self.approval_reminders.check()
            self.finance.reconcile()

    def record_deployment(self) -> None:
        """AMD-3 stage 5: this release of T0's lane runs in this environment. Once per release."""
        rel, env = self.settings.release, self.settings.environment
        if rel is None:
            return
        status = self.memory.capability_status("receptor:T0", "T0", env, self.clock())
        last = status.get(EvidenceStage.PRODUCTION_DEPLOYED)
        if last is not None and last.record.artifact_ref == f"release:{rel}":
            return
        self.memory.record_evidence(
            EvidenceRecord(
                evidence_id=uuid4(),
                capability="receptor:T0",
                provider="T0",
                stage=EvidenceStage.PRODUCTION_DEPLOYED,
                outcome=EvidenceOutcome.PASSED,
                environment=env,
                scope="T0",
                recorded_by=Component.CORE_RD,
                recorded_at=self.clock(),
                artifact_ref=f"release:{rel}",
                detail=f"Layer A {rel} started in {env}",
            ),
            "T0",
        )

    # Founder-approved setup -----------------------------------------------------------------
    def bootstrap(self) -> None:
        core, gov = self.core, Component.GOVERNANCE_CORE
        seed_register(self.memory, self.settings.policy_dir)
        for tool_id in (
            "t0.tally",
            "t0.publish",
            "t0.restart",
            "t0.read",
            "hermes.research",
            "finance.reconcile",
            "qa.audit",
        ):
            self._admit(tool_id, IntegrationKind.INTEGRATION)
        for model_id in (MODEL_ID, BACKUP_MODEL_ID):
            self._admit(model_id, IntegrationKind.MODEL)
        self._admit("hermes", IntegrationKind.INTEGRATION)

        manifest = t0_module.MANIFEST
        core.register_receptor(manifest)
        zero = Money(amount=Decimal("0"), currency="INR")  # T0 handles no money
        self.approve(
            core.propose_limits(
                ReceptorLimits(
                    receptor_id=manifest.receptor_id,
                    permissions=manifest.permissions,
                    max_spend_per_action=zero,
                    max_spend_per_month=zero,
                ),
                gov,
            )
        )
        acceptance = EvidenceRecord(
            evidence_id=uuid4(),
            capability="receptor:T0",
            provider="T0",
            stage=EvidenceStage.TEST_PASSED,
            outcome=EvidenceOutcome.PASSED,
            environment="local",
            scope="T0",
            recorded_by=Component.CORE_RD,
            recorded_at=self.clock(),
            artifact_ref="integration/tests/test_t0_acceptance",
            detail="T0 lane contract tests",
        )
        self.memory.record_evidence(acceptance, "T0")
        self.approve(core.propose_activation("T0", [acceptance.evidence_id], Component.CORE_RD))

        for standard in _standards():
            self.qa.define_standard(standard)

        for model_id, provider in ((MODEL_ID, PROVIDER), (BACKUP_MODEL_ID, BACKUP_PROVIDER)):
            spec = ModelSpec(
                model_id=model_id,
                provider=provider,
                input_price_per_mtok=Decimal(0),
                output_price_per_mtok=Decimal(0),
                currency="INR",
            )
            self.router.register_model(
                spec, self._approve_c("register_model", spec, ApprovalCategory.INTEGRATION)
            )
        for task_class in (CONVERSATION, HERMES_TASKS):
            bar = AcceptanceBar(task_class=task_class, min_quality=0.95, max_latency_ms=2000)
            self.router.set_acceptance_bar(
                bar, self._approve_c("set_acceptance_bar", bar, ApprovalCategory.RULE_CHANGE)
            )
            budget = ModelBudget(
                task_class=task_class,
                max_cost_per_day=Decimal(0),
                currency="INR",
                max_output_tokens_per_call=4000,
            )
            self.router.set_budget(
                budget, self._approve_c("set_budget", budget, ApprovalCategory.FINANCIAL)
            )
            for model_id, cost in ((MODEL_ID, "0"), (BACKUP_MODEL_ID, "0.0001")):
                self.router.record_qualification(
                    Qualification(
                        model_id=model_id,
                        task_class=task_class,
                        tasks_run=40,
                        tasks_passed=40,
                        p95_latency_ms=5,
                        cost_per_task=Decimal(cost),
                        currency="INR",
                        evidence_ref="integration/tests (deterministic stand-in)",
                        run_at=self.clock(),
                    )
                )

    def _admit(self, integration_id: str, kind: IntegrationKind) -> None:
        core = self.core
        core.propose_integration(
            integration_id,
            kind,
            integration_id,
            "local-1",
            RiskLevel.MEDIUM,
            f"CR-local-{integration_id}",
        )
        core.record_security_check(integration_id, True, "local review")
        core.admit_integration(integration_id)

    def _approve_c(self, op: str, value, category: ApprovalCategory) -> UUID:
        payload = {"component": "C", "op": op, "value": value.model_dump(mode="json")}
        request = self.core.propose(
            ProposalKind.EXTERNAL_ACTION,
            payload,
            f"Model Router: {op}",
            Component.CORE_RD,
            category,
        )
        assert request.action_digest == change_digest(op, value.model_dump(mode="json"))
        self.approve(request)
        return request.approval_id


def _standards() -> list[QualityStandard]:
    def chk(name, kind, path, value=None):
        return Check(name=name, kind=kind, path=path, value=value)

    return [
        QualityStandard(
            standard_id="STD-T0-TALLY",
            version=1,
            receptor_id="T0",
            description="The published total equals the sum of the numbers asked for.",
            technical=(
                chk("receipt", CheckKind.PRESENT, "receipt_id"),
                chk("output ref", CheckKind.PRESENT, "output_ref"),
            ),
            fitness=(
                chk("published", CheckKind.PRESENT, "published.total"),
                chk("correct total", CheckKind.EQUALS, "matches", True),
            ),
        ),
        QualityStandard(
            standard_id="STD-T0-PUBLISH",
            version=1,
            receptor_id="T0",
            description="The note is actually published on T0.",
            technical=(chk("receipt", CheckKind.PRESENT, "receipt_id"),),
            fitness=(chk("published", CheckKind.EQUALS, "published", True),),
        ),
        QualityStandard(
            standard_id="STD-T0-RESTART",
            version=1,
            receptor_id="T0",
            description="After a restart T0 reports healthy.",
            technical=(chk("receipt", CheckKind.PRESENT, "receipt_id"),),
            fitness=(chk("healthy", CheckKind.EQUALS, "health", "healthy"),),
        ),
    ]


def _controls(core, memory, store, settings: Settings, clock: Clock) -> FastAPI:
    device_key = store.get("core", "device_key").encode()
    device = DeviceKeyStepUp(device_key, settings.challenge_ttl, clock)
    passkeys = None
    if settings.passkey_file is not None:
        passkeys = PasskeyStepUp(
            PasskeyStore(settings.passkey_file),
            device,
            device_key,
            settings.passkey_rp_id,
            settings.passkey_origin,
            settings.challenge_ttl,
            clock,
        )
    return create_controls(
        GovernanceForControls(core, clock),
        passkeys or device,
        HmacChannelSigner(store.get("core", "channel_key").encode()),
        _AuditEvents(memory, clock),
        clock,
        passkeys,
        store,  # the Founder's provider API keys page writes here (write-only)
    )


def controls_app(dsns: dict[str, str], settings: Settings, clock: Clock) -> FastAPI:
    """Direct Founder Controls in its own process (LA-DEP-02, LA-DEP-03): A and I only, no B, C,
    G, D or Hermes. Its STOP is committed to A's event log, which the main process follows."""
    store = LocalSecretStore(settings.secret_file)
    memory = MemoryStore(memory_connect(dsns["memory"]), "core", SecretGuard(store))
    core = GovernanceCore(
        PgEventStore(dsns["governance"]),
        PolicyEngine.load(settings.policy_dir),
        HmacChannel(store.get("core", "channel_key").encode()),
        AuditToMemory(memory),
        clock=clock,
        initial_parameters=load_initial_parameters(settings.policy_dir),
    )
    return _controls(core, memory, store, settings, clock)


class _RouterOverHttp:
    """B's RouterPort over C's HTTP API, identified by B's own credential."""

    def __init__(self, http: TestClient, token: str):
        self._http, self._token = http, token

    def complete(self, caller, task_class, request):
        from dyson_intelligence.models import RoutedResponse
        from dyson_intelligence.router import RouterError

        r = self._http.post(
            "/v1/complete",
            json={"task_class": task_class, "request": request.model_dump(mode="json")},
            headers={"Authorization": f"Bearer {self._token}"},
        )
        if r.status_code != 200:
            raise RouterError(r.json().get("detail", f"C answered {r.status_code}"))
        return RoutedResponse.model_validate(r.json())


class _HermesRouterClient(_RouterOverHttp):
    def complete(self, task_class, request):  # type: ignore[override]
        return super().complete(Component.HERMES, task_class, request)


class _HermesToolHubClient:
    def __init__(self, http: TestClient, token: str):
        self._http, self._token = http, token

    def call(self, request: ToolCallRequest) -> dict:
        r = self._http.post(
            "/calls",
            json=request.model_dump(mode="json"),
            headers={"X-Caller-Credential": self._token},
        )
        r.raise_for_status()
        return r.json()


class _AuditEvents:
    """The Gateway's and DFC's audit port: I's audit log."""

    def __init__(self, store: MemoryStore, clock: Clock):
        self._store, self._clock = store, clock

    def record(self, event: str, detail: dict) -> None:
        from dyson_contracts.audit import AuditEvent, AuditKind

        dfc = event in ("decision", "control", "confirmation_refused", "resume_requested")
        kind = {"decision": AuditKind.APPROVAL, "control": AuditKind.CONTROL_EVENT}.get(
            event, AuditKind.POLICY_DECISION
        )
        self._store.audit(
            AuditEvent(
                event_id=uuid4(),
                kind=kind,
                actor=Component.DIRECT_FOUNDER_CONTROLS if dfc else Component.ENTRY_GATEWAY,
                at=self._clock(),
                summary=event[:200],
                data={k: str(v) for k, v in detail.items()},
            )
        )

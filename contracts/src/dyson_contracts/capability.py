"""The extension contract (D-026): how anything new enters Dyson without touching the core.

A capability is any new thing the Founder may want later — a tool, a model, a connector, a skill,
an agent, a process, a channel, or a whole cluster. It arrives as a manifest the Supply Chain /
Integration Gate (A) reads and the Governed Tool Hub (G) enforces. The core (A, C, G, I) does not
change to admit one; only the registry gains a row.

Nothing here is trusted on the manifest's word. The Gate verifies the digest and signature,
validates this schema, scans and probes the artifact, pins every operation's definition hash, and
only then admits it — low and medium risk once checked, high risk on a Founder approval. The risk
hints below are the publisher's claim; the Gate checks them (LA-GOV-06, LA-TOOL-01, AMD-13).
"""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import Field, StringConstraints, model_validator

from .common import Contract, Money, NonEmptyStr, RiskLevel, Sha256Hex

# Reverse-DNS id, e.g. "dyson.jarvis.engine" or "com.google.gmail".
_LABEL = r"[a-z0-9]([a-z0-9-]*[a-z0-9])?"
CapabilityId = Annotated[str, StringConstraints(pattern=rf"^{_LABEL}(\.{_LABEL})+$")]
SemVer = Annotated[str, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]
# A host the capability may reach, checked against the Tool Hub's internet gate allowlist.
Host = Annotated[str, StringConstraints(pattern=r"^[a-z0-9.-]+$", min_length=1, max_length=253)]


class CapabilityKind(StrEnum):
    """What the capability is. A whole cluster enters as a PROCESS."""

    TOOL = "tool"
    MODEL_PROVIDER = "model_provider"
    CONNECTOR = "connector"
    SKILL = "skill"
    AGENT = "agent"
    PROCESS = "process"
    CHANNEL = "channel"


class IsolationTier(StrEnum):
    """The lightest tier that fits. The Gate refuses a tier below the operations' risk."""

    WASM = "wasm"  # in-process, pure logic and parsers
    GVISOR = "gvisor"  # a sandboxed container: code, third-party MCP
    CONTAINER = "container"  # a hardened container: browser, desktop
    REMOTE = "remote"  # off-box, reached over A2A / MCP


class Lifecycle(StrEnum):
    """The capability's life stage. It starts SHADOW; the Gate promotes it."""

    SHADOW = "shadow"  # admitted, runs but nothing depends on it
    CANARY = "canary"  # a slice of real work
    ENABLED = "enabled"  # fully in use
    DISABLED = "disabled"  # a definition hash changed, or the Founder stopped it


class Operation(Contract):
    """One thing the capability can do, with its typed shape and its risk.

    The hints copy MCP's tool annotations, but the Gate verifies them in a sandbox and never trusts
    them. input_schema and output_schema are JSON Schemas; G validates results against the output.
    """

    name: NonEmptyStr
    summary: NonEmptyStr
    input_schema: dict = {}
    output_schema: dict = {}
    read_only: bool = False  # claims it changes nothing outside Dyson
    destructive: bool = False  # claims it may remove or overwrite
    idempotent: bool = False  # safe to retry after a network failure
    open_world: bool = False  # reaches beyond Dyson (the internet, a third party)
    risk: RiskLevel = RiskLevel.MEDIUM
    requires_approval: bool = False  # a Founder approval per call, on Direct Founder Controls

    @model_validator(mode="after")
    def _checks(self) -> "Operation":
        if self.read_only and self.destructive:
            raise ValueError("an operation cannot be both read_only and destructive")
        if self.destructive and not self.requires_approval:
            raise ValueError("a destructive operation must require a Founder approval")
        return self


class RuleOfTwo(Contract):
    """Meta's rule: within one run, at most two of these three without a Founder approval."""

    untrusted_input: bool = False  # reads outside content: email, web, a bank statement
    sensitive_access: bool = False  # touches the Founder's personal or financial data
    external_effect: bool = False  # acts outside Dyson: sends, posts, buys

    @property
    def all_three(self) -> bool:
        return self.untrusted_input and self.sensitive_access and self.external_effect


class Budget(Contract):
    """Hard ceilings the Hub enforces. Model spend still passes C's own budget (LA-RTR-05)."""

    cpus: Annotated[Decimal, Field(gt=0, le=2)]  # the server has 2 vCPU
    memory_mb: Annotated[int, Field(gt=0, le=2048)]
    timeout_s: Annotated[int, Field(gt=0, le=3600)]
    calls_per_minute: Annotated[int, Field(gt=0, le=600)]
    spend_per_day: Money | None = None  # None means the capability moves no money


class Requests(Contract):
    """What it asks for. The Hub grants scoped handles; the capability never holds the vault."""

    egress_hosts: tuple[Host, ...] = ()  # only these, through the Tool Hub's internet gate
    secrets: tuple[NonEmptyStr, ...] = ()  # by name; Hub injects, capability never reads the store
    models: tuple[NonEmptyStr, ...] = ()  # reached only through the Model Router (C)
    fs_paths: tuple[NonEmptyStr, ...] = ()  # inside its own sandbox


class Provenance(Contract):
    """Where the artifact came from, so the Gate can verify it and catch a later swap (rug pull)."""

    source_url: NonEmptyStr
    artifact_digest: Sha256Hex  # pinned; a change auto-disables the capability
    signature_ref: str = ""  # Sigstore / cosign reference, when signed
    sbom_ref: str = ""


class CapabilityManifest(Contract):
    """The whole declaration the Gate reads. The core never changes to admit one of these."""

    id: CapabilityId
    version: SemVer
    kind: CapabilityKind
    contract_version: SemVer  # the core port API this targets
    publisher: NonEmptyStr
    license: NonEmptyStr
    summary: NonEmptyStr
    provenance: Provenance
    operations: tuple[Operation, ...] = Field(min_length=1)
    rule_of_two: RuleOfTwo = RuleOfTwo()
    requests: Requests = Requests()
    budget: Budget
    isolation: IsolationTier
    risk: RiskLevel  # overall risk; sets whether admission needs a Founder approval

    @model_validator(mode="after")
    def _checks(self) -> "CapabilityManifest":
        names = [op.name for op in self.operations]
        if len(names) != len(set(names)):
            raise ValueError("operation names must be unique")
        if any(op.open_world for op in self.operations) and not self.requests.egress_hosts:
            raise ValueError("an open-world operation must name the hosts it reaches")
        # In-process WASM cannot own a browser or a desktop; those need at least a container.
        if self.isolation is IsolationTier.WASM and self.kind in (
            CapabilityKind.PROCESS,
            CapabilityKind.AGENT,
        ):
            raise ValueError("a process or agent needs at least a gvisor sandbox, not wasm")
        # The overall risk cannot sit below any single operation's risk.
        order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
        if any(order[op.risk] > order[self.risk] for op in self.operations):
            raise ValueError("overall risk cannot be lower than an operation's risk")
        return self

    @property
    def needs_founder_admission(self) -> bool:
        """High risk, anything external, or all three Rule-of-Two flags: the Founder admits it."""
        return (
            self.risk is RiskLevel.HIGH
            or self.rule_of_two.all_three
            or any(op.open_world or op.destructive for op in self.operations)
        )

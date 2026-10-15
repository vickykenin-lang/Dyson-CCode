"""Outbound interfaces of the assurance plane. Step 9 wires them to I, A and the Receptor lanes.

None of these ports can act: they record evidence, carry escalations, or observe.
"""

from typing import Protocol
from uuid import UUID

from pydantic import JsonValue

from dyson_contracts.evidence import EvidenceRecord


class EvidenceSink(Protocol):
    def record(self, evidence: EvidenceRecord, receptor_id: str | None) -> None:
        """Write to the evidence registry in I."""
        ...


class EscalationSink(Protocol):
    def escalate(self, to: str, subject: str, message: str, task_id: UUID | None = None) -> None:
        """to: 'governance' (A), 'founder_dashboard' (J) or 'human_reviewer'."""
        ...


class Probe(Protocol):
    def observe(self, task_id: UUID, receptor_id: str | None, standard_id: str) -> JsonValue:
        """F's own, independent look at the real world after a task ran: never the Receptor's
        report. Raises when the observation cannot be made; F then gives no verdict."""
        ...

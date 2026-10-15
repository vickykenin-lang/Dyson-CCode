"""Minimum Receptor obligations at the boundary (PRD section 8, derived from Register §3.4)."""

from .common import Contract, NonEmptyStr, ReceptorId


class ReceptorManifest(Contract):
    receptor_id: ReceptorId
    purpose: NonEmptyStr
    tools: tuple[NonEmptyStr, ...]
    permissions: tuple[NonEmptyStr, ...]
    boundaries: NonEmptyStr
    recovery_policy: NonEmptyStr  # must stay inside the AMD-5 bounds
    synthetic: bool = False  # True only for Test T0
    handles_money: bool = False

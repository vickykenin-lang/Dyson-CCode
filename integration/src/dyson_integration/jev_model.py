"""Jev decision model behind B's triage (TriagePort): one call to apinex's /v1/decisions reads a
Founder message before B interprets it.

Unlike a chat model, Jev returns structured decision signals — what kind of request it is
(category), how hard it is (complexity), and how safe it looks (is_safe) — not text, so it has its
own adapter and its own port, not C's ModelAdapter. It is advisory only: B uses the signal to
calibrate its reply, and every action still passes through governance and the Founder's approval.
Best-effort by design — any error, or no apinex key, yields None and B interprets without a hint.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

TIMEOUT_S = 20.0
_LEGEND = {"0": "trivial", "1": "easy", "2": "moderate", "3": "hard", "4": "expert"}


@dataclass(frozen=True)
class Triage:
    category: str  # coding | general | analysis | creative
    complexity: str  # trivial | easy | moderate | hard | expert
    is_safe: float  # 0..1; low means the request looks risky and B should confirm first
    assessment: float  # 0..1; the decision model's own overall score for the request


class JevTriage:
    def __init__(
        self,
        base_url: str,
        api_key: Callable[[], str | None] | str,
        model_id: str = "free/jev-1.13",
        *,
        client: Any = None,
        timeout: float = TIMEOUT_S,
    ):
        # base_url like "https://api.apinex.bond/v1"; the endpoint is <base_url>/decisions. api_key
        # may be a string or a callable read at call time (a key the Founder saves on DFC is picked
        # up without a restart). client is an httpx-like object for tests; a one-shot request else.
        self._url = base_url.rstrip("/") + "/decisions"
        self._key = api_key
        self._model = model_id
        self._client = client
        self._timeout = timeout

    def triage(self, text: str) -> Triage | None:
        key = self._key() if callable(self._key) else self._key
        if not key:
            return None
        try:
            import httpx  # lazy: only needed when a real call is made

            caller = self._client or httpx
            resp = caller.post(
                self._url,
                json={"model": self._model, "input": text},
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            answers = (resp.json() or {}).get("answers") or {}
        except Exception:
            return None  # advisory only; B interprets without the hint
        probs = (answers.get("complexity") or {}).get("probabilities") or {}
        level = max(probs, key=lambda k: probs[k]) if probs else None
        return Triage(
            category=str((answers.get("category") or {}).get("choice", "general")),
            complexity=_LEGEND.get(str(level), "moderate"),
            is_safe=float((answers.get("is_safe") or {}).get("noul", 1.0)),
            assessment=float((answers.get("assessment") or {}).get("noul", 0.0)),
        )

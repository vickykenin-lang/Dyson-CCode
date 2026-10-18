"""Personal and financial identifiers never leave Layer A (D-017, LA-RTR-07, LA-SEC-07).

C replaces them with placeholders such as [PHONE_1] before a request goes to any model, and puts
the real values back into the model's reply, so a prepared tool call still carries them while
the model never sees them. What is caught: email addresses, UPI IDs, PAN, IFSC codes, card
numbers (Luhn-checked), Aadhaar numbers, Indian mobile numbers and any other run of 9 or more
digits (account and reference numbers). Names and free-text addresses are not detected.
"""

import re

from .models import ChatMessage, ModelRequest

_PATTERNS = (
    ("EMAIL", re.compile(r"\b[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b")),
    ("UPI", re.compile(r"\b[\w.-]{2,}@[A-Za-z]{2,}\b")),
    ("PAN", re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")),
    ("IFSC", re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")),
    ("CARD", re.compile(r"\b\d(?:[ -]?\d){12,18}\b")),
    ("AADHAAR", re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b")),
    ("PHONE", re.compile(r"(?:\+91[ -]?|\b0)?\b[6-9]\d{4}[ -]?\d{5}\b")),
    ("NUMBER", re.compile(r"\b\d{9,}\b")),
)


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


class Redaction:
    """One request's placeholders. `restore` puts the real values back into a reply."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}  # placeholder -> real value
        self._seen: dict[str, str] = {}  # real value -> placeholder
        self._counts: dict[str, int] = {}

    def _hide(self, kind: str, value: str) -> str:
        if value not in self._seen:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            placeholder = f"[{kind}_{self._counts[kind]}]"
            self._seen[value], self.values[placeholder] = placeholder, value
        return self._seen[value]

    def text(self, text: str) -> str:
        for kind, pattern in _PATTERNS:

            def sub(m: re.Match, kind=kind) -> str:
                value = m.group()
                digits = re.sub(r"\D", "", value)
                if kind == "CARD" and (len(digits) not in (15, 16) or not _luhn(digits)):
                    return value  # left for the narrower patterns below
                return self._hide(kind, value)

            text = pattern.sub(sub, text)
        return text

    def request(self, request: ModelRequest) -> ModelRequest:
        return request.model_copy(update={
            "system": self.text(request.system),
            "messages": tuple(ChatMessage(role=m.role, content=self.text(m.content))
                              for m in request.messages),
        })  # fmt: skip

    def restore(self, text: str) -> str:
        for placeholder, value in self.values.items():
            text = text.replace(placeholder, value)
        return text

    def kinds(self) -> dict[str, int]:
        return dict(self._counts)

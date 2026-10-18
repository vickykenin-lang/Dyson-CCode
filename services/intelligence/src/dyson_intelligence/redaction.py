"""Personal and financial identifiers never leave Layer A (D-017, LA-RTR-07, LA-SEC-07).

C replaces them with placeholders such as [PHONE_1] before a request goes to any model, and puts
the real values back into the model's reply, so a prepared tool call still carries them while
the model never sees them. What is caught: email addresses, UPI IDs, PAN, IFSC codes, card
numbers (Luhn-checked), Aadhaar numbers, Indian mobile numbers and any other run of 9 or more
digits (account and reference numbers); names of people Layer A knows (the nominee) and names
with a cue (Mr, Shri, Smt, Dr, "my name is", "mera naam ... hai", "Sharma ji", श्री, नाम ...);
and addresses that are labelled ("address:", "pata", पता) or that end in a PIN code. A name
written with no cue at all is not detected.
"""

import re
from collections.abc import Iterable

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


# (kind, pattern, group): when group > 0 only that group is hidden, so a cue such as
# "address:" or "Mr" still reaches the model and keeps the sentence readable.
_NAME = r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}"
_DEV = r"[\u0900-\u097F]+(?:\s[\u0900-\u097F]+)?"
_ADDRESS_WORDS = (
    r"house|h\.?\s?no\.?|flat|plot|door|sector|block|ward|gali|lane|street|road|marg|nagar"
    r"|colony|apartments?|society|tower|enclave|vihar|village|gram|tehsil|district|dist\.?"
)
_CONTEXT = (
    (
        "ADDRESS",
        re.compile(
            r"(?i)\b(?:address|addr\.?|pata)\b\s*(?:is|hai|:|-)?\s*([^\n;]{6,140}?"
            r"(?:\b[1-9]\d{2}\s?\d{3}\b"
            r"|(?=[\n;]|$|\s+(?:phone|mobile|mob|email|e-mail|call|whatsapp)\b)))"
        ),
        1,
    ),
    ("ADDRESS", re.compile(r"पता\s*(?:है|:)?\s*([^\n;।]{6,140})"), 1),
    (
        "ADDRESS",
        re.compile(
            r"(?i)(?:\b[A-Z]?-?\d+[A-Z]?\s*[,/-]\s*)?\b(?:" + _ADDRESS_WORDS + r")\b"
            r"[^\n;]{0,120}?\b[1-9]\d{2}\s?\d{3}\b"
        ),
        0,
    ),
    ("ADDRESS", re.compile(r"(?i)\bpin\s*(?:code)?\s*[:-]?\s*([1-9]\d{2}\s?\d{3})\b"), 1),
    (
        "NAME",
        re.compile(
            r"\b(?:Mr|Mrs|Ms|Miss|Dr|Shri|Sri|Smt|Kumari|Prof|Adv)\.?\s+"
            r"((?:[A-Z]\.\s?){0,3}" + _NAME + ")"
        ),
        1,
    ),
    (
        "NAME",
        re.compile(r"\b(?i:my name is|i am|i'm|named|called)\s+(" + _NAME + ")"),
        1,
    ),
    (
        "NAME",
        re.compile(
            r"(?i)\b(?:mera|meri|uska|uski|unka|unki|iska|inka)?\s*naam\s+(?:hai\s+)?"
            r"([a-z]+(?:\s+[a-z]+){0,2}?)\s+(?:hai|he|h)\b"
        ),
        1,
    ),
    ("NAME", re.compile(r"(?i)\bname\s*[:-]\s*([a-z][a-z .]{1,40}?)(?=[,;\n]|$)"), 1),
    ("NAME", re.compile(r"\b([A-Z][a-z]{2,})\s+ji\b"), 1),
    ("NAME", re.compile(r"(?:श्रीमती|श्री|सुश्री|डॉ\.?)\s*(" + _DEV + ")"), 1),
    ("NAME", re.compile(r"नाम\s+(" + _DEV + r")\s+है"), 1),
)
# Words a cue can sit in front of that are not people: they stay as they are.
_NOT_NAMES = {
    "dyson", "hermes", "founder", "receptor", "layer", "governance", "deepseek", "aap", "haan",
    "nahi", "theek", "accha", "achha", "shukriya", "dhanyavaad", "namaste", "pranam", "guru",
    "ready", "back", "here", "sorry", "fine", "done", "busy", "sure", "not", "kya", "kuch",
    "kaun", "bhi", "yeh", "ye", "woh", "wo", "tumhara", "aapka", "apna", "batao", "bata",
}  # fmt: skip


def _luhn(digits: str) -> bool:
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


class Redaction:
    """One request's placeholders. `restore` puts the real values back into a reply."""

    def __init__(self, known: Iterable[tuple[str, str]] = ()) -> None:
        """`known` is (kind, value) for personal data Layer A holds, such as the nominee's name;
        each is hidden wherever it appears, and a name also by each part of 3 letters or more."""
        self.values: dict[str, str] = {}  # placeholder -> real value
        self._seen: dict[str, str] = {}  # real value -> placeholder
        self._counts: dict[str, int] = {}
        terms = set()
        for kind, value in known:
            value = value.strip()
            if not value:
                continue
            terms.add((kind, value))
            if kind == "NAME":
                terms.update((kind, part) for part in value.split() if len(part) >= 3)
        # longest first, so a full name wins over its parts
        self._known = [
            (kind, re.compile(r"(?<!\w)" + re.escape(v) + r"(?!\w)", re.IGNORECASE))
            for kind, v in sorted(terms, key=lambda t: -len(t[1]))
        ]

    def _hide(self, kind: str, value: str) -> str:
        if value not in self._seen:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            placeholder = f"[{kind}_{self._counts[kind]}]"
            self._seen[value], self.values[placeholder] = placeholder, value
        return self._seen[value]

    def text(self, text: str) -> str:
        for kind, pattern in self._known:
            text = pattern.sub(lambda m, kind=kind: self._hide(kind, m.group()), text)
        for kind, pattern, group in _CONTEXT:

            def cue(m: re.Match, kind=kind, group=group) -> str:
                value = m.group(group).strip(" ,.")
                if not value or "[" in value or value.split()[0].lower() in _NOT_NAMES:
                    return m.group()
                whole = m.group()
                i = whole.find(value, m.start(group) - m.start())
                return whole[:i] + self._hide(kind, value) + whole[i + len(value) :]

            text = pattern.sub(cue, text)
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

"""Secret store interface and the guard that keeps credentials out of memory.

LA-MEM-06 / LA-SEC-01: every credential lives in the secret store, never in prompts, repositories
or conversational memory. The local store is for development; Step 10 adds the AWS-backed one
behind the same interface.
"""

import json
import os
import re
import stat
from pathlib import Path
from typing import Protocol


class SecretLeak(ValueError):
    """Raised instead of writing text that contains a credential. The text is never stored."""


class SecretStore(Protocol):
    def get(self, scope: str, name: str) -> str: ...

    def values(self) -> list[str]: ...


class LocalSecretStore:
    """Secrets from a JSON file shaped {"core": {"name": "value"}, "T0": {...}}.

    Each scope reads only its own namespace (per-Receptor credential isolation, LA-MEM-04).
    The file must not be readable by group or others.
    """

    def __init__(self, path: Path):
        mode = os.stat(path).st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise PermissionError(f"{path} must be private (chmod 600)")
        self._data: dict[str, dict[str, str]] = json.loads(Path(path).read_text("utf-8"))

    def get(self, scope: str, name: str) -> str:
        try:
            return self._data[scope][name]
        except KeyError:
            raise KeyError(f"no secret {name!r} in scope {scope!r}") from None

    def values(self) -> list[str]:
        return [v for ns in self._data.values() for v in ns.values()]


# Common credential shapes, caught even when they are not in the store.
_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key ID
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),  # common API secret-key prefix
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),  # GitHub tokens
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),  # Slack tokens
]
MIN_SECRET_LENGTH = 8


class SecretGuard:
    def __init__(self, store: SecretStore | None = None):
        self._store = store

    def check(self, *texts: str) -> None:
        known = [
            v for v in (self._store.values() if self._store else []) if len(v) >= MIN_SECRET_LENGTH
        ]
        for text in texts:
            if not text:
                continue
            if any(v in text for v in known) or any(p.search(text) for p in _PATTERNS):
                raise SecretLeak("refused: text contains a credential")

"""Read a checked-out Git vault (or any directory tree) into SourceDocs and sync it to the index.

A "vault" is just a folder of the Founder's notes and docs — usually a cloned Git repository. This
walks it, keeps the text/doc files, and turns each into a SourceDoc whose logical path mirrors the
file's path in the repo (so retrieval can route by folder). The sync then ingests everything
idempotently and runs a reconcile sweep, so a file deleted from the repo is tombstoned on the next
run. Binary files (images, PDFs) are skipped here; they arrive later through a caption/extract step.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .ingest import Ingestor, IngestOutcome
from .model import SourceDoc

# Text and document files that carry knowledge. Code and binaries are left out of the default: the
# second brain is notes and docs first, and ingesting a repo's code would mostly trip the secret
# scan. Callers can widen `exts` when they want more.
DEFAULT_EXTS = frozenset({".md", ".markdown", ".mdx", ".txt", ".rst"})
MIME = {
    ".md": "text/markdown", ".markdown": "text/markdown", ".mdx": "text/markdown",
    ".txt": "text/plain", ".rst": "text/x-rst",
}  # fmt: skip
# Folders that never hold the Founder's knowledge; skipped wholesale.
SKIP_DIRS = frozenset({
    ".git", ".github", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    ".idea", ".vscode", "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", "target", "vendor",
})  # fmt: skip
MAX_BYTES = 1_000_000  # skip a file larger than this; a 1MB note is already far past normal


@dataclass(frozen=True)
class SyncReport:
    counts: dict[IngestOutcome, int]  # how many docs were indexed / unchanged / quarantined / empty
    removed: list[str]  # paths tombstoned because they are gone from the vault
    read: int  # how many files were read from the vault

    def summary(self) -> str:
        c = self.counts
        parts = ", ".join(f"{o.value}={c[o]}" for o in IngestOutcome if o in c)
        return f"read {self.read} files; {parts or 'nothing'}; removed {len(self.removed)}"


def read_vault(
    root: str | Path,
    source: str,
    *,
    exts: Iterable[str] = DEFAULT_EXTS,
    max_bytes: int = MAX_BYTES,
) -> list[SourceDoc]:
    """Every text/doc file under `root`, as SourceDocs. `path` is the POSIX path within the vault;
    the top-level folder becomes a tag so "pull up my social-media notes" can filter by it."""
    base = Path(root)
    allowed = {e.lower() for e in exts}
    docs: list[SourceDoc] = []
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in allowed:
            continue
        rel = p.relative_to(base)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        try:
            if p.stat().st_size > max_bytes:
                continue
            text = p.read_text("utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # unreadable or not real UTF-8 text; skip rather than guess at an encoding
        posix = rel.as_posix()
        top = posix.split("/", 1)[0] if "/" in posix else ""
        docs.append(SourceDoc(
            source=source, path=posix, text=text,
            mime=MIME.get(p.suffix.lower(), "text/plain"),
            tags=(top,) if top else (),
        ))  # fmt: skip
    return docs


def sync_vault(
    ingestor: Ingestor,
    root: str | Path,
    source: str,
    *,
    exts: Iterable[str] = DEFAULT_EXTS,
    max_bytes: int = MAX_BYTES,
) -> SyncReport:
    """Ingest the whole vault, then tombstone anything in the index that the vault no longer has."""
    docs = read_vault(root, source, exts=exts, max_bytes=max_bytes)
    counts = ingestor.ingest_all(docs)
    removed = ingestor.reconcile(source, [d.path for d in docs])
    return SyncReport(counts=counts, removed=removed, read=len(docs))

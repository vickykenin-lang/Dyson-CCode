"""The small, plain types the knowledge layer moves around.

A SourceDoc is one item to ingest (a note, a code file, a chat export, an image's caption). A Chunk
is a searchable slice of it. Metadata (source, folder, filename, tags) rides along so retrieval can
route "pull up my social-media folder" by filter, not only by meaning.
"""

import posixpath
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceDoc:
    """One item to ingest. `path` is the logical path within `source` (POSIX, no leading /)."""

    source: str  # a namespace: "vault", "repo:dyson", "chat", ...
    path: str  # e.g. "projects/social-media/plan.md"
    text: str  # the extracted text (an image arrives as its caption/description)
    mime: str = "text/markdown"
    tags: tuple[str, ...] = ()

    @property
    def folder(self) -> str:
        return posixpath.dirname(self.path)

    @property
    def filename(self) -> str:
        return posixpath.basename(self.path)


@dataclass(frozen=True)
class Chunk:
    """A slice of a SourceDoc, with its position and (once embedded) its vector."""

    ord: int  # 0-based position within the document
    text: str
    embedding: list[float] = field(default_factory=list)

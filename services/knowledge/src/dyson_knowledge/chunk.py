"""Split a document into retrieval-sized chunks, structure-aware.

The 2025-26 finding is that fixed-size chunking beats semantic chunking and that the size matters
as much as the embedding model, so this keeps it simple and honest: prefer Markdown heading and
paragraph boundaries, pack up to a target size, enforce a minimum so no 40-character fragments, and
hard-split any single over-long block. Sizes are in characters (~4 chars/token), so the default
~2000 is roughly 500 tokens. No inter-chunk overlap by default — its benefit is disputed; measure
before adding it.
"""

import re

_HEADING = re.compile(r"(?m)^(?=#{1,6}\s)")  # split *before* a Markdown heading, keeping it
_PARA = re.compile(r"\n\s*\n")

TARGET = 2000
MINIMUM = 200


def chunk_text(text: str, *, target: int = TARGET, minimum: int = MINIMUM) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    blocks: list[str] = []
    for section in _HEADING.split(text):
        section = section.strip()
        if not section:
            continue
        if len(section) <= target:
            blocks.append(section)
        else:
            blocks.extend(_pack_paragraphs(section, target))
    return _merge_small(blocks, minimum)


def _pack_paragraphs(section: str, target: int) -> list[str]:
    out: list[str] = []
    buf = ""
    for para in _PARA.split(section):
        para = para.strip()
        if not para:
            continue
        if buf and len(buf) + len(para) + 2 > target:
            out.append(buf)
            buf = ""
        if len(para) > target:  # a single paragraph longer than the target: hard-split it
            out.extend(para[i : i + target] for i in range(0, len(para), target))
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        out.append(buf)
    return out


def _merge_small(blocks: list[str], minimum: int) -> list[str]:
    """Fold a too-small block into the previous one, so headings don't become lone tiny chunks."""
    merged: list[str] = []
    for b in blocks:
        if merged and len(b) < minimum:
            merged[-1] = f"{merged[-1]}\n\n{b}"
        else:
            merged.append(b)
    return merged

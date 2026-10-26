"""Chunking: structure-aware, size-bounded, no tiny fragments."""

from dyson_knowledge.chunk import chunk_text


def test_empty_is_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n  ") == []


def test_short_text_is_one_chunk():
    assert chunk_text("just a short note about youtube") == ["just a short note about youtube"]


def test_headings_become_separate_chunks():
    text = "# Plan\n\nDo the thing.\n\n## Details\n\nMore detail here."
    chunks = chunk_text(text, target=40, minimum=5)
    assert len(chunks) == 2
    assert chunks[0].startswith("# Plan")
    assert chunks[1].startswith("## Details")


def test_long_paragraph_is_hard_split():
    chunks = chunk_text("x" * 5000, target=2000)
    assert len(chunks) == 3
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks) == "x" * 5000


def test_tiny_block_is_folded_into_previous():
    # a heading with almost no body should not become its own sub-minimum chunk
    text = "# A\n\n" + "y" * 300 + "\n\n# B\n\nz"
    chunks = chunk_text(text, target=400, minimum=50)
    assert all(len(c) >= 50 for c in chunks)
    assert chunks[-1].endswith("z")

"""Reading a vault directory into SourceDocs, and syncing it (ingest + reconcile)."""

from dyson_knowledge.ingest import Ingestor, IngestOutcome
from dyson_knowledge.vault import read_vault, sync_vault
from fakes import FakeEmbedder, FakeStore


def _make_vault(root):
    (root / "social-media").mkdir()
    (root / "social-media" / "plan.md").write_text("Reels teen baar a week.", "utf-8")
    (root / "finance").mkdir()
    (root / "finance" / "invoices.txt").write_text("GST invoice ledger.", "utf-8")
    (root / "README.md").write_text("Top level note.", "utf-8")
    # things that must be skipped
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n", "utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "x.md").write_text("dependency doc", "utf-8")
    (root / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x01binary")
    (root / "app.py").write_text("print('code, not a note')", "utf-8")


def test_read_vault_keeps_docs_with_paths_and_folder_tags(tmp_path):
    _make_vault(tmp_path)
    docs = {d.path: d for d in read_vault(tmp_path, "vault")}
    assert set(docs) == {"social-media/plan.md", "finance/invoices.txt", "README.md"}
    assert docs["social-media/plan.md"].tags == ("social-media",)
    assert docs["social-media/plan.md"].folder == "social-media"
    assert docs["finance/invoices.txt"].mime == "text/plain"
    assert docs["README.md"].tags == ()  # a top-level file has no folder tag
    # .git, node_modules, the binary image and the code file are all left out
    assert not any(p.startswith(".git") or p.startswith("node_modules") for p in docs)
    assert "diagram.png" not in docs and "app.py" not in docs


def test_read_vault_skips_oversized_files(tmp_path):
    (tmp_path / "huge.md").write_text("x" * 50, "utf-8")
    assert read_vault(tmp_path, "vault", max_bytes=10) == []


def test_read_vault_can_widen_extensions(tmp_path):
    (tmp_path / "app.py").write_text("print('hi')", "utf-8")
    docs = read_vault(tmp_path, "vault", exts={".py"})
    assert [d.path for d in docs] == ["app.py"]


def test_sync_ingests_then_reconciles_deletions(tmp_path):
    _make_vault(tmp_path)
    ing = Ingestor(store=FakeStore(), embedder=FakeEmbedder())

    first = sync_vault(ing, tmp_path, "vault")
    assert first.read == 3
    assert first.counts[IngestOutcome.INDEXED] == 3 and first.removed == []

    # nothing changed → a second sync re-indexes nothing
    second = sync_vault(ing, tmp_path, "vault")
    assert second.counts[IngestOutcome.UNCHANGED] == 3

    # delete a file from the vault → the next sync tombstones it
    (tmp_path / "finance" / "invoices.txt").unlink()
    third = sync_vault(ing, tmp_path, "vault")
    assert third.removed == ["finance/invoices.txt"]
    assert ing.store.known_paths("vault") == {"social-media/plan.md", "README.md"}


def test_sync_quarantines_a_file_that_carries_a_secret(tmp_path):
    (tmp_path / "ok.md").write_text("a normal note", "utf-8")
    (tmp_path / "leak.md").write_text("aws key AKIAIOSFODNN7EXAMPLE and more", "utf-8")
    ing = Ingestor(store=FakeStore(), embedder=FakeEmbedder())
    report = sync_vault(ing, tmp_path, "vault")
    assert report.counts.get(IngestOutcome.QUARANTINED) == 1
    assert "leak.md" not in ing.store.known_paths("vault")

"""Sync a checked-out Git vault into the knowledge index (the second brain).

Run on the server, where the knowledge database and the local embedder live:

    python -m dyson_integration.vault_sync <vault-dir> <source> [ext ...]

<source> is the namespace the vault's docs live under (e.g. "repo:dyson", "vault"). Extra args are
file extensions to include beyond the default notes/docs set (e.g. ".py" ".ts" to also index code).
It reads the Founder's files with B's own database role and the on-box embedder, so text and vectors
never leave the machine; a file carrying a credential is quarantined, and a file removed from the
vault since the last run is tombstoned.
"""

import os
import sys

from psycopg.conninfo import make_conninfo

from . import db


def _integration_dsn() -> str:
    """B's (integration) database role, built the way the container entrypoint provides it."""
    admin = os.environ["DYSON_PG_ADMIN"]
    name = os.environ.get("DYSON_DB_NAME", "dyson")
    password = os.environ["DYSON_DB_PASSWORD"]
    return make_conninfo(admin, dbname=name, user=db.app_role("integration"), password=password)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: python -m dyson_integration.vault_sync <vault-dir> <source> [ext ...]",
              file=sys.stderr)  # fmt: skip
        return 2
    vault_dir, source, exts = args[0], args[1], args[2:]

    from dyson_knowledge.db import connect
    from dyson_knowledge.http_embedder import HttpEmbedder
    from dyson_knowledge.ingest import Ingestor
    from dyson_knowledge.pgstore import PgStore
    from dyson_knowledge.vault import DEFAULT_EXTS, sync_vault

    url = os.environ.get("DYSON_EMBEDDER_URL")
    if not url:
        print("DYSON_EMBEDDER_URL is not set; the embedder must be running to ingest",
              file=sys.stderr)  # fmt: skip
        return 1

    conn = connect(_integration_dsn())
    ingestor = Ingestor(store=PgStore(conn), embedder=HttpEmbedder(url))
    use = {e if e.startswith(".") else f".{e}" for e in exts} or DEFAULT_EXTS
    report = sync_vault(ingestor, vault_dir, source, exts=use)
    conn.close()
    print(f"[{source}] {report.summary()}")
    if report.removed:
        print("removed:", ", ".join(report.removed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

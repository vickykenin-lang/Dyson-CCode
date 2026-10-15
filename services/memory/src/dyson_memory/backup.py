"""Backup and restore of the "memory" schema with pg_dump / pg_restore.

Backups run as a read-only BYPASSRLS role (see db.migrate backup_role) so every Receptor's rows
are included. Restore is an operator action run as a superuser: it recreates the schema with its
original owner, grants, policies and triggers, and loads rows exactly as dumped (triggers are
disabled during the load so the audit chain is not recomputed).

Local backups are written owner-readable only. Encryption at rest and storage the runtime cannot
delete come with S3 in Step 10 (LA-REL-03, LA-DEP-04).
"""

import os
import shutil
import subprocess
from pathlib import Path


def _tool(name: str) -> str:
    bin_dir = os.environ.get("DYSON_PG_BIN")
    path = str(Path(bin_dir) / name) if bin_dir else shutil.which(name)
    if not path:
        raise FileNotFoundError(f"{name} not found; set DYSON_PG_BIN")
    return path


def backup(dsn: str, path: Path) -> Path:
    path = Path(path)
    subprocess.run(
        [_tool("pg_dump"), "--format=custom", "--schema=memory", f"--file={path}", dsn],
        check=True,
        capture_output=True,
    )
    path.chmod(0o600)
    return path


def restore(dsn: str, path: Path) -> None:
    """Restore, as a superuser, into a database where the memory schema does not exist yet."""
    subprocess.run(
        [
            _tool("pg_restore"),
            "--exit-on-error",
            "--disable-triggers",
            f"--dbname={dsn}",
            str(path),
        ],
        check=True,
        capture_output=True,
    )

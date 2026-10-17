"""Run Layer A locally: `python -m dyson_integration.serve` (used by docker-compose.yml).

Ports: 8080 Entry Gateway API, 8081 Founder app, 8082 Direct Founder Controls, 8083 J (read only).
The worker runs in this process with its own database connections. Real secrets never appear in
logs or output: they are read from the secret file and the environment only.

Environment:
  DYSON_PG_ADMIN        superuser DSN, used once to create roles, the database and schemas
  DYSON_DB_NAME         database name (default dyson)
  DYSON_DB_PASSWORD     password given to the per-component roles
  DYSON_SECRET_FILE     secret store file (created, private, if missing)
  DYSON_FOUNDER_PASSWORD_FILE  file holding the Founder's login password
  DYSON_POLICY_DIR      policy/ directory
  DYSON_SECURE_COOKIES  1 when served over HTTPS (session cookies get the Secure flag)
  DYSON_PASSKEY_RP_ID   site the Founder's passkeys belong to (e.g. control.designinfra.in)
  DYSON_PASSKEY_ORIGIN  its origin (e.g. https://control.designinfra.in)
"""

import asyncio
import os
import threading
import time
from pathlib import Path

import psycopg
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from dyson_founder_app.app import create_app as create_founder_app
from dyson_founder_app.gateway_client import GatewayClient
from dyson_founder_app.voice import NoVoice

from . import db
from .system import LayerA, Settings, write_secret_file
from .t0 import TestReceptorT0


def ensure_database(admin: str, name: str, password: str) -> dict[str, str]:
    with psycopg.connect(admin, autocommit=True) as c:
        exists = c.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name]).fetchone()
    if not exists:
        return db.prepare(admin, name, password)
    dsns = {
        "admin": make_conninfo(admin, dbname=name),
        "owner": make_conninfo(admin, dbname=name, user=db.OWNER, password=password),
        "backup": make_conninfo(admin, dbname=name, user=db.BACKUP, password=password),
    }
    for c in db.COMPONENTS:
        dsns[c] = make_conninfo(admin, dbname=name, user=db.app_role(c), password=password)
    db.migrate_all(dsns)
    return dsns


class _Serialized:
    """One request at a time across all four apps: the in-process components share database
    connections. Status streams are left out so they never block other requests."""

    def __init__(self, app: FastAPI, lock: asyncio.Lock):
        self.app, self.lock = app, lock

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].endswith("/events"):
            return await self.app(scope, receive, send)
        async with self.lock:
            return await self.app(scope, receive, send)


def main() -> None:
    env = os.environ
    policy = Path(env.get("DYSON_POLICY_DIR", "/app/policy"))
    secret_file = Path(env.get("DYSON_SECRET_FILE", "/data/secrets.json"))
    if not secret_file.exists():
        write_secret_file(secret_file)
    password = Path(env["DYSON_FOUNDER_PASSWORD_FILE"]).read_text().strip()
    dsns = ensure_database(
        env["DYSON_PG_ADMIN"], env.get("DYSON_DB_NAME", "dyson"), env["DYSON_DB_PASSWORD"]
    )
    settings = Settings(
        policy_dir=policy,
        secret_file=secret_file,
        founder_password=password,
        passkey_file=secret_file.parent / "passkeys.json",
        passkey_rp_id=env.get("DYSON_PASSKEY_RP_ID", "localhost"),
        passkey_origin=env.get("DYSON_PASSKEY_ORIGIN", "http://localhost:8082"),
    )
    t0 = TestReceptorT0()
    layer = LayerA.build(dsns, settings, t0, _now)
    if layer.core.sync().receptors.get("T0") is None:
        layer.bootstrap()
    worker = LayerA.build(dsns, settings, t0, _now)  # its own connections

    def work() -> None:
        while True:
            try:
                worker.tick()
            except Exception as exc:  # keep going; the error is visible in the log
                print(f"worker: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(2)

    threading.Thread(target=work, daemon=True).start()
    app = create_founder_app(
        GatewayClient(TestClient(layer.gateway)),
        NoVoice(),
        secure_cookies=env.get("DYSON_SECURE_COOKIES") == "1",  # 0 for local http
    )
    print("Layer A is up: gateway 8080, app 8081, controls 8082, dashboard 8083", flush=True)
    asyncio.run(
        _serve(
            [(layer.gateway, 8080), (app, 8081), (layer.controls, 8082), (layer.dashboard, 8083)]
        )
    )


async def _serve(apps) -> None:
    lock = asyncio.Lock()
    servers = [
        uvicorn.Server(
            uvicorn.Config(_Serialized(a, lock), host="0.0.0.0", port=p, log_level="warning")
        )
        for a, p in apps
    ]
    await asyncio.gather(*(s.serve() for s in servers))


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


if __name__ == "__main__":
    main()

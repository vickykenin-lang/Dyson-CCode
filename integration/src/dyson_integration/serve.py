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
  DYSON_ENVIRONMENT     where this runs, written on evidence (default local)
  DYSON_RELEASE         the release name; when set, AMD-3 stage 5 is recorded for it
  DYSON_ROLE            all (default: everything in this process), or on AWS one of
                        core (Layer A without DFC and Hermes), controls (DFC alone) or hermes
  DYSON_BIND            address the core apps listen on (default 0.0.0.0)
  DYSON_EDGE_BIND       core: the Hermes-network address the Hermes edge listens on (port 8090)
  DYSON_HERMES_URL      core: where the Hermes container takes jobs
  DYSON_HERMES_SECRETS  core writes, hermes reads: Hermes's own three credentials
  DYSON_EDGE_URL        hermes: the edge Layer A serves on the Hermes network
  DYSON_NOMINEE_FILE    the nominee's details; when set, Survival Mode notices go by email
  DYSON_BEDROCK         1 to put Amazon Bedrock behind C (role credentials from
                        AWS_SHARED_CREDENTIALS_FILE, refreshed by the host)
  DYSON_VOICE_URL       core: the voice container that hears the Founder (D-024)
  DYSON_POLLY           1 to speak Dyson's replies through Amazon Polly in Sydney (D-024)
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
from dyson_founder_app.voice import NoVoice, RemoteVoice
from dyson_memory.register_seed import seed_register

from . import db
from .rules_model import PROVIDER, RulesModel
from .system import (
    BACKUP_PROVIDER,
    LayerA,
    Settings,
    add_missing_secrets,
    controls_app,
    write_secret_file,
)
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


def _dsns(admin: str, name: str, password: str) -> dict[str, str]:
    """Connections only, for a process that must not create or migrate anything."""
    dsns = {"admin": make_conninfo(admin, dbname=name)}
    for c in db.COMPONENTS:
        dsns[c] = make_conninfo(admin, dbname=name, user=db.app_role(c), password=password)
    return dsns


def _settings_and_dsns(migrate: bool = True):
    env = os.environ
    policy = Path(env.get("DYSON_POLICY_DIR", "/app/policy"))
    secret_file = Path(env.get("DYSON_SECRET_FILE", "/data/secrets.json"))
    if migrate:
        if not secret_file.exists():
            write_secret_file(secret_file)
        add_missing_secrets(secret_file)
    password = Path(env["DYSON_FOUNDER_PASSWORD_FILE"]).read_text().strip()
    connect = ensure_database if migrate else _dsns
    dsns = connect(
        env["DYSON_PG_ADMIN"], env.get("DYSON_DB_NAME", "dyson"), env["DYSON_DB_PASSWORD"]
    )
    settings = Settings(
        policy_dir=policy,
        secret_file=secret_file,
        founder_password=password,
        passkey_file=secret_file.parent / "passkeys.json",
        passkey_rp_id=env.get("DYSON_PASSKEY_RP_ID", "localhost"),
        passkey_origin=env.get("DYSON_PASSKEY_ORIGIN", "http://localhost:8082"),
        environment=env.get("DYSON_ENVIRONMENT", "local"),
        release=env.get("DYSON_RELEASE") or None,
        hermes_url=env.get("DYSON_HERMES_URL") or None,
        controls_url=env.get("DYSON_CONTROLS_URL") or None,
        nominee_file=Path(env["DYSON_NOMINEE_FILE"]) if env.get("DYSON_NOMINEE_FILE") else None,
    )
    return settings, dsns


def _models() -> dict:
    """The stand-ins always; Bedrock behind C when the server has role credentials."""
    models = {PROVIDER: RulesModel(), BACKUP_PROVIDER: RulesModel()}
    if os.environ.get("DYSON_BEDROCK") == "1":
        from .bedrock_model import PROVIDER as BEDROCK
        from .bedrock_model import BedrockModel

        models[BEDROCK] = BedrockModel()
    return models


def build_from_env(t0=None) -> LayerA:
    """A Layer A on the server's database, for the server and for one-off admin commands."""
    settings, dsns = _settings_and_dsns()
    return LayerA.build(dsns, settings, t0 or TestReceptorT0(), _now, _models())


def main() -> None:
    role = os.environ.get("DYSON_ROLE", "all")
    if role == "hermes":
        return _main_hermes()
    if role == "controls":
        settings, dsns = _settings_and_dsns(migrate=False)
        print("Direct Founder Controls is up: 8082", flush=True)
        return asyncio.run(_serve([(controls_app(dsns, settings, _now), "0.0.0.0", 8082)]))
    settings, dsns = _settings_and_dsns()
    t0 = TestReceptorT0()
    layer = LayerA.build(dsns, settings, t0, _now, _models())
    if layer.core.sync().receptors.get("T0") is None:
        layer.bootstrap()
    seed_register(layer.memory, settings.policy_dir)  # new rule versions and decisions reach I
    layer.record_deployment()
    worker = LayerA.build(dsns, settings, t0, _now, _models())  # its own connections

    def work() -> None:
        while True:
            try:
                worker.tick()
            except Exception as exc:  # keep going; the error is visible in the log
                print(f"worker: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(2)

    threading.Thread(target=work, daemon=True).start()
    speech = None
    if os.environ.get("DYSON_POLLY") == "1":
        from .adapters import nominee_details
        from .speech_polly import PollySpeech

        speech = PollySpeech(lambda: nominee_details(settings.nominee_file))
    voice_url = os.environ.get("DYSON_VOICE_URL")
    app = create_founder_app(
        GatewayClient(TestClient(layer.gateway)),
        RemoteVoice(voice_url) if voice_url else NoVoice(),
        speech=speech,
        secure_cookies=os.environ.get("DYSON_SECURE_COOKIES") == "1",  # 0 for local http
        sandbox_novnc_url=os.environ.get("DYSON_SANDBOX_NOVNC_URL", ""),
        # The STOP link opens Direct Founder Controls in the browser: its PUBLIC origin, not the
        # internal health-check URL.
        controls_url=settings.passkey_origin or "/",
    )
    bind = os.environ.get("DYSON_BIND", "0.0.0.0")
    from .relay_app import create_relay_app

    sandbox_panel = create_relay_app(
        layer.relay,
        novnc_url=os.environ.get("DYSON_SANDBOX_NOVNC_URL", ""),
        controls_url=settings.controls_url or "/",
    )
    apps = [
        (layer.gateway, bind, 8080),
        (app, bind, 8081),
        (layer.dashboard, bind, 8083),
        (sandbox_panel, bind, 8085),  # the Founder's view-only sandbox panel (D-026)
    ]
    if role == "core":  # DFC and Hermes run in their own containers
        from .hermes_service import write_hermes_secrets

        write_hermes_secrets(layer.secrets, Path(os.environ["DYSON_HERMES_SECRETS"]))
        apps.append((layer.hermes_edge, os.environ["DYSON_EDGE_BIND"], 8090))
    else:
        apps.append((layer.controls, bind, 8082))
    print(f"Layer A ({role}) is up: " + ", ".join(str(p) for _, _, p in apps), flush=True)
    asyncio.run(_serve(apps))


def _main_hermes() -> None:
    """Hermes alone: its three credentials, the edge, nothing else (LA-DEP-01)."""
    import json

    from .hermes_service import build_hermes, create_hermes_app

    creds = json.loads(Path(os.environ["DYSON_HERMES_SECRETS"]).read_text())
    hermes = build_hermes(os.environ["DYSON_EDGE_URL"], creds)
    print("Hermes is up: 8095", flush=True)
    asyncio.run(_serve([(create_hermes_app(hermes, creds["hermes_job_token"]), "0.0.0.0", 8095)]))


async def _serve(apps) -> None:
    lock = asyncio.Lock()
    servers = [
        uvicorn.Server(uvicorn.Config(_Serialized(a, lock), host=host, port=p, log_level="warning"))
        for a, host, p in apps
    ]
    await asyncio.gather(*(s.serve() for s in servers))


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)


if __name__ == "__main__":
    main()

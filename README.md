# Dyson Sphere: Layer A

Layer A is the governed core between the Founder and the business Receptors. It covers governance, security, control, intelligence routing, state, execution coordination, monitoring and evidence. "The model proposes; the gateway enforces."

**Status:** Steps 1 to 9 of 10 are done (foundation and contracts; Memory & Evidence Layer; Governance Core; Governed Tool Hub; Orchestrator; Assurance; Intelligence; Founder Interface; internal connection with Test T0). Everything runs locally; nothing is deployed. See `docs/EXECUTION_PLAN.md`.

## Layout

| Path | What it is |
|---|---|
| `contracts/` | `dyson_contracts`, the frozen shared contracts every component depends on (`docs/CONTRACTS.md`) |
| `policy/amd_register.yaml` | AMD-1 to AMD-14 in machine-checkable form, with a lock on AMD-1 to AMD-13 |
| `policy/decisions.yaml` | Founder decisions on the PRD's open items |
| `policy/planes.yaml` | AMD-1 plane mapping |
| `policy/parameters.yaml` | Initial operational parameters, each citing a Founder decision |
| `docs/traceability/requirements.yaml` | All 174 PRD requirement IDs, each with the one step that proves it |
| `docs/process/CORE_RD.md` | How Core R&D proposals work |
| `tools/policy_lock.py` | Computes the AMD-1 to AMD-13 lock hash |
| `services/memory/` | Step 2: Memory & Evidence Layer (card I), schema `memory` (`services/memory/NOTES.md`) |
| `services/governance/` | Step 3: Governance Core (card A), schema `governance` (`services/governance/NOTES.md`) |
| `services/toolhub/` | Step 4: Governed Tool Hub (card G), schema `toolhub` (`services/toolhub/NOTES.md`) |
| `services/orchestrator/` | Step 5: Orchestrator (card D), schema `orchestrator` (`services/orchestrator/NOTES.md`) |
| `services/assurance/` | Step 6: QA/QC (F), Monitoring (E), Financial Control (H), Dashboard data (J), schema `assurance` (`services/assurance/NOTES.md`) |
| `services/intelligence/` | Step 7: Conversation Engine (B), Model Router (C), Hermes runtime, schema `intelligence` (`services/intelligence/NOTES.md`) |
| `services/gateway/` | Step 8: Entry Gateway: Founder login, sessions, rate limiting (`apps/founder-app/NOTES.md`) |
| `services/founder-controls/` | Step 8: Direct Founder Controls: Approve / Reject, STOP / PAUSE, and the `dyson-control` client (`apps/founder-app/NOTES.md`) |
| `apps/founder-app/` | Step 8: the Dyson Founder app, text first, voice slot (`apps/founder-app/NOTES.md`) |
| `integration/` | Step 9: every component connected, the Test T0 Receptor, schema `integration` (`integration/NOTES.md`) |
| `docker-compose.yml` | Step 9: Layer A running locally (Postgres plus one Layer A process) |
| `tests/` | Repository checks: policy, lock, planes, traceability |

## Run the checks

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e contracts -e "services/memory[dev]" -e "services/governance[dev]" -e "services/toolhub[dev]" -e "services/orchestrator[dev]" -e "services/assurance[dev]" -e "services/intelligence[dev]" -e "services/gateway[dev]" -e "services/founder-controls[dev]" -e "apps/founder-app[dev]" -e "integration[dev]" "pyyaml>=6" pytest ruff
ruff check . && ruff format --check .
pytest -q
```

The service tests need PostgreSQL 16. Set `DYSON_TEST_PG_ADMIN` to a superuser DSN; without it, those tests are skipped. The Hermes network test needs Docker; without it, it is skipped.

## Run Layer A locally

See the comment at the top of `docker-compose.yml` for the three local secret files, then `docker compose up --build`. The Founder app is on http://localhost:8081 and Direct Founder Controls on port 8082 (`dyson-control`). Test T0 is the only Receptor; nothing reaches AWS, a real model or a bank.

GitHub is used for source control and CI only. It is never part of Dyson's runtime (LA-SEC-06).

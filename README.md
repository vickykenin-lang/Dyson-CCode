# Dyson Sphere: Layer A

Layer A is the governed core between the Founder and the business Receptors. It covers governance, security, control, intelligence routing, state, execution coordination, monitoring and evidence. "The model proposes; the gateway enforces."

**Status:** Step 1 of 10 (foundation and frozen contracts). Nothing is deployed. See `docs/EXECUTION_PLAN.md`.

## Layout

| Path | What it is |
|---|---|
| `contracts/` | `dyson_contracts`, the frozen shared contracts every component depends on (`docs/CONTRACTS.md`) |
| `policy/amd_register.yaml` | AMD-1 to AMD-14 in machine-checkable form, with a lock on AMD-1 to AMD-13 |
| `policy/decisions.yaml` | Founder decisions on the PRD's open items |
| `policy/planes.yaml` | AMD-1 plane mapping |
| `docs/traceability/requirements.yaml` | All 174 PRD requirement IDs, each with the one step that proves it |
| `docs/process/CORE_RD.md` | How Core R&D proposals work |
| `tools/policy_lock.py` | Computes the AMD-1 to AMD-13 lock hash |
| `tests/` | Repository checks: policy, lock, planes, traceability |

## Run the checks

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e contracts "pyyaml>=6" pytest ruff
ruff check . && ruff format --check .
pytest -q
```

GitHub is used for source control and CI only. It is never part of Dyson's runtime (LA-SEC-06).

# Dyson Sphere Layer A: execution plan

Source: *Dyson Sphere — Layer A PRD* v1.0 (11 Oct 2026). Founder decisions are in `policy/decisions.yaml`.

## Rules that keep the steps from clashing

1. **Folder ownership.** Each step owns its own folders and its own PostgreSQL schema. No step edits another step's files.
2. **Contracts only.** Steps 2 to 8 depend only on `contracts/` from Step 1, never on each other. Each one is tested against fakes. Contract changes follow `docs/CONTRACTS.md`.
3. **Connections come later.** All internal connections between components happen in Step 9. All external connections (AWS, real model APIs, the voice vendor) happen in Step 10.
4. **One owner per requirement.** Every requirement ID belongs to the step in which it is fully proven (`docs/traceability/requirements.yaml`). Earlier steps may build parts of it.
5. **Evidence, not claims.** A step is done only on recorded evidence at the right AMD-3 stage. Locally, Steps 2 to 9 reach at most stage 4 (test passed).

## Progress

| Step | Status |
|---|---|
| 1 | Done |
| 2 | Done (see `services/memory/NOTES.md`) |
| 3 to 10 | Not started |

## The ten steps

| Step | Builds | Owns | Requirements owned | Founder gates first |
|---|---|---|---|---|
| 1 | Foundation and frozen contracts | `contracts/`, `policy/`, `docs/`, `tools/`, `tests/`, CI | 7 | none |
| 2 | Memory and Evidence Layer (I) | `services/memory/`, schema `memory` | 14 | none |
| 3 | Governance Core (A) | `services/governance/`, schema `governance` | 19 | none |
| 4 | Governed Tool Hub (G) | `services/toolhub/`, schema `toolhub` | 8 | none |
| 5 | Orchestrator (D) | `services/orchestrator/`, schema `orchestrator` | 8 | none |
| 6 | Assurance: QA/QC (F), Monitoring (E), Financial (H), Dashboard data (J) | `services/assurance/`, schema `assurance` | 31 | none |
| 7 | Intelligence: Conversation (B), Model Router (C), Hermes sandbox | `services/intelligence/` | 20 | none (fake models only) |
| 8 | Founder Interface: App, Entry Gateway, Direct Founder Controls | `apps/founder-app/`, `services/gateway/`, `services/founder-controls/` | 20 | none (auth is pluggable; gate 3 picks the method) |
| 9 | Internal connection phase plus Test T0 | `integration/`, `receptors/test-t0/`, `docker-compose.yml` | 21 | none |
| 10 | External connection phase on AWS | `infra/` | 26 | gates 1, 2, 3, 4, 5, 6; gate 9 before production |

### Step 1: Foundation and frozen contracts

- **Builds:**
  - Repo skeleton
  - `dyson_contracts` v1.0.0
  - AMD-1 to AMD-14 as `policy/amd_register.yaml`, with each rule's version, effective date and controls, and a lock on AMD-1 to AMD-13
  - Plane mapping
  - Founder decisions
  - Traceability for all 174 requirement IDs
  - CI
- **Done when:** the contracts validate, CI is green, and every requirement ID is assigned to exactly one step.

### Step 2: Memory and Evidence Layer (I)

- **Builds:**
  - Conversation archive
  - Long-term memory with provenance
  - Decision and amendment register with immutable history
  - Evidence registry for the 8 stages, which keeps failed and negative evidence
  - Append-only audit log
  - Per-Receptor isolation
  - Secret-store interface, with a local version for now
  - Backup and local restore scripts
- **Done when:** the tests prove:
  - A transcript survives a restart.
  - A restore works.
  - The audit log cannot be altered.
  - A canary credential never appears in memory.

### Step 3: Governance Core (A)

- **Builds:**
  - Policy engine that reads `policy/amd_register.yaml`
  - Founder approval engine
  - Budget and permission limits
  - Supply-chain and integration gate
  - Legal and compliance records
  - Deterministic STOP / PAUSE / RESUME controller with no LLM
  - Receptor lifecycle (pause, archive, replace only on a Founder decision)
  - Safe Continuity mode reserved, with its trigger off
- **Done when:** the tests prove:
  - A self-approval is refused.
  - A financial action stays blocked without approval.
  - STOP works with no model running.
  - Nothing resumes automatically after a breach.

### Step 4: Governed Tool Hub (G)

- **Builds:**
  - The six per-call checks. Policy and STOP state come from fakes until Step 9.
  - Tool registry fed by the integration gate
  - Kill switch per tool and per connector
  - Deny-and-audit for any call that fails a check
- **Done when:** a call without permission or outside the registry is denied and audited. This is the PRD's first milestone, proven in isolation.

### Step 5: Orchestrator (D)

- **Builds:**
  - Task IDs
  - A durable queue
  - The `dyson_contracts.tasks` state machine
  - Idempotency keys
  - Retry and escalation
  - `held` after 3 consecutive QA failures
  - No `completed-verified` without a verification verdict
- **Done when:** the tests prove:
  - The same command sent twice runs once.
  - Tasks survive a restart.
  - Three failures put the task in `held`.

### Step 6: Assurance

- **Builds:**
  - **F:** independent verifier that accepts no self-certification.
  - **E:** health, KPI and failure tracking. It reports truthfully, including offline or unknown, and has no power to act.
  - **H:** per-Receptor ledger and bank-statement intake. Revenue becomes `final` only on a match.
  - **J:** a read-only data API. The dashboard UX is deferred (gate 8).
- **Done when:** the tests prove:
  - Unmatched revenue stays "reported, not final".
  - The dashboard API has no write path.
  - A Receptor's own claim of success is rejected.

### Step 7: Intelligence

- **Builds:**
  - **B:** interprets requests, asks for clarification, and proposes actions. It never executes anything.
  - **C:** routing and tested fallback, plus token and cost limits, against fake models.
  - **Hermes:** an isolated container whose network reaches only C and G.
- **Done when:** the tests prove:
  - Fallback keeps task state.
  - Hermes cannot reach a model or tool directly.
  - "200 OK" is never reported as done.

### Step 8: Founder Interface

- **Builds:**
  - A text-first app served from Python, with an honest acknowledgment followed by live status
  - A gateway handling authentication, sessions and rate limits
  - Approve, Reject, STOP and PAUSE as a separately authenticated endpoint
  - Voice built as a slot only
- **Done when:** an acknowledgment is never shown as completion, and the controls work with the app turned off. Tested against a fake backend.

### Step 9: Internal connection phase plus Test T0

- **Builds:**
  - Replaces every fake with the real Step 2–8 components.
  - Wires the five lanes.
  - Builds the synthetic, no-money Test T0 Receptor with a planted fault.
  - Runs every negative and security test in PRD §13 locally.
- **Done when:** the end-to-end chain passes locally: command → policy → G → T0 → F verifies → answer.

### Step 10: External connection phase on AWS

- **Builds:**
  - Infrastructure as code
  - Budgets, alarms and least-privilege IAM before any paid resource
  - Encrypted S3 backups the runtime cannot delete
  - Real secret store
  - Real model APIs behind C
  - The voice vendor behind the app, after the gate 5 benchmark
- **Done when:** evidence reaches AMD-3 stages 5 to 7. Production launch still needs gate 9.

## Founder gates (PRD §14) and where they block

| Gate | Decision | Blocks |
|---|---|---|
| 1 | AWS account verification and spend cap | Step 10 |
| 2 | Compute SKU, network / DNS / TLS, database method, backups, IAM and secrets | Step 10 |
| 3 | Step-up authentication method and signed-approval semantics | Step 10 (Step 8 builds a pluggable slot) |
| 4 | STOP handling for in-progress actions; high-risk classification | Step 10 live write tests |
| 5 | Voice vendor and Hindi / Hinglish thresholds | Step 10 voice |
| 6 | Data retention, classification, isolation and redaction | Step 10 real data |
| 7 | AMD-12 presence detection | The 48-hour trigger only (stays off) |
| 8 | Dashboard UX | Dashboard screens (outside these 10 steps) |
| 9 | Acceptance, disaster recovery, production authorization | Production |

# Jarvis engine: free benchmark (20 Oct 2026)

No model spend. Mechanical properties of the Dyson engine (scripted decisions) plus a capability
comparison with the Nous Hermes Agent from its source. The paid run (real model quality, latency,
cost against the acceptance bar, and a live head-to-head once the Founder admits Hermes's model
wiring) comes next.

## Mechanical benchmark: 9/9

The agent-loop properties that must hold whatever the model is:

- multi-step task completes
- a tool outside the allowed set never reaches G
- STOP ends the loop immediately
- a denied action ends the run
- the step budget is bounded
- a subagent runs, scoped to a subset of tools
- a tool-result injection produces no rogue action (plan-then-execute)
- engine output is always unverified (F decides)
- a malformed decision is an error, not an action

## Capability comparison (from code study)

| Dimension | Nous Hermes Agent | Dyson engine (now) | Where Dyson stands |
|---|---|---|---|
| Agent loop | mature, broad tools | bounded plan-then-execute, governed | at parity on mechanics; model quality unproven |
| Memory | 2 capped files + FTS5 + Honcho | bi-temporal facts, FTS + trigram, provenance | ahead on honesty/history; no vectors, no consolidation yet |
| Skills | self-writing, self-improving | can propose; Gate admits | behind: only proposal, no self-improvement loop |
| Session recall | FTS5 + LLM summaries | FTS on messages | behind: no per-session summaries yet |
| Subagents | isolated, tool-limited | scoped, depth-bounded | at parity; no parallel subagents |
| Scheduled work | built-in cron | via D's durable queue | at parity; briefing scheduler not wired |
| Browser / desktop | full | capability + internet gate + relay | governed design ready; live Chromium not deployed |
| Proactivity | nudges | inbox + briefing + tuning | ahead on design; not wired to live data |
| Governance / safety | host-run, warns | model via C, tools via G, STOP, approvals, rug-pull, quarantined parser | clearly ahead |
| Observability | traces | audit log + evidence registry | behind on lightweight per-run traces |

## What to improve (from this free comparison)

1. Nightly consolidation ("dreaming"): episodes to facts and skills, into a proposal queue.
2. Per-session LLM summaries for session recall.
3. The skill self-improvement loop, not just proposal.
4. Wire the briefing scheduler and proactive inbox to live data and the dashboard.
5. Optional vector similarity as a later capability (a pgvector image), if FTS+trigram proves thin.
6. Lightweight per-run traces (OpenTelemetry GenAI), sampled.
7. The paid run: measure real model quality, latency and cost against the acceptance bar.

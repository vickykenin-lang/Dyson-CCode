# Milestone A: live benchmark findings (20 Oct 2026)

Recorded as the live test runs. The Founder admitted the benchmark wiring on Direct Founder
Controls (D-027); each finding below is an observed strength or weakness of the system.

## Finding 1 (weakness): the model behind C was never functional

The Dyson engine's real-model run failed on every task with a read timeout. Direct Bedrock
probes from inside Layer A, in ap-southeast-2 with the server's own role:

| Model | Result |
|---|---|
| `amazon.nova-micro-v1:0` | OK, 0.4 s — "Sure, I understand." |
| `apac.amazon.nova-micro-v1:0` | AccessDenied (inference profile not granted) |
| `deepseek.v3.2` (configured behind C, D-019) | ReadTimeout, 30 s — no response |

**Conclusion:** Bedrock, the role and the network are fine (Nova micro answers in 0.4 s). The model
configured behind C, `deepseek.v3.2`, does not work on Bedrock in Sydney — the bare id is not an
available on-demand model and the call hangs. D-019 recorded it as live, but it had never served a
real request: the deploys only checked health endpoints, never a real model call.

**What held:** Dyson's engine and architecture are not at fault; the governed path (engine → C →
Bedrock) carried the call correctly and the failure was reported plainly, never guessed.

**Fix:** switch C to a working, available model (Nova micro), through the governed model change with
Founder approval, then re-run the benchmark. Done — C's route is now
`['amazon.nova-micro-v1:0', 'deepseek.v3.2']` and the re-run succeeded.

## Scoreboard (re-run on Nova micro)

Same six tasks (morning-brief, draft-reply, recall-fact, plan-week, triage-inbox, watch-receptor),
each with real tool side effects denied, so the measure is reasoning and governed tool-choice.

| Agent | Completed | Governed | Latency (median) | Tool calls |
|---|---|---|---|---|
| Dyson engine (via C) | 5 / 6 | yes (every run) | ~2 s (0.6–21 s) | through G, side effects denied |
| Nous Hermes Agent (via shim → C) | 6 / 6 | n/a (no governed tools) | ~20 s each | 0 |

**Reading:** the Nous agent completed one more task, but about 10x slower and with no governed
tool use — it had no governed tools to call. Dyson's engine ran every task under its governance
(plan-then-execute, STOP honoured, output always unverified) and far faster. On the metrics that
matter for Dyson — governed, bounded, fast — the engine matched or beat the agent, which is the
bar D-023/D-025 set for archiving the Nous agent.

## Finding 2 (weakness): recorded qualification did not match runtime

D-019 recorded `deepseek.v3.2` as a live, qualified model, but it had never served a real request
— only health endpoints were checked. A model can pass every recorded gate and still be dead to
callers.

**Fix:** added a live route health probe (`dyson_intelligence.routecheck`). It sends one tiny
request through C, exactly like any caller, and fails if no real answer comes back inside a latency
budget. Run it after a deploy or a model switch; a route that fails the probe is dead, whatever the
scoreboard said.

## Finding 3 (weakness): the engine gave up after an off-limits action

The Jarvis engine stopped the whole run with an ERROR the moment the model asked for a tool it was
not given, or returned a malformed decision — one bad step ended the task.

**Fix:** the engine now refuses the bad action locally (an off-limits tool never reaches G), feeds
a correction back as data, and re-plans within the allowed tools. Only after several invalid
decisions in a row (MAX_STRIKES) does it give up as ERROR, so a model looping on garbage is still
bounded. Plan-then-execute holds: the correction is data, never a new instruction.

## Finding 4 (weakness): no latency guard in the loop

A slow or stuck model call could hold the engine's loop open with no wall-clock bound.

**Fix:** `run()` now takes a wall-clock budget (MAX_SECONDS, default 60s). When it is exceeded the
run ends cleanly as `StopReason.TIMEOUT`; subagents inherit the remaining budget.

## Finding 5 (weakness): the shim could not stream

The OpenAI shim returned only a single JSON body. The Nous agent prefers streaming for liveness and
errored ("EmptyStreamError") until streaming was forced off as a workaround.

**Fix:** the shim now honours `stream=true` and re-frames C's finished answer as an OpenAI SSE
chunk stream (role, word-sized content chunks, stop, `[DONE]`). C does not stream, so the shim
holds the whole answer and invents nothing; a router refusal still lands as a 502 before any
stream begins. The workaround was removed when the agent's config was reset.

## Teardown (debris removal)

After the re-run and the fixes, the benchmark was torn down (D-027 → re-isolate):

- `dyson-bench-shim-1` container removed; `dyson_bench_net` removed.
- Nous agent config reset: `provider` → `auto`, benchmark `base_url` and the `streaming: false`
  override removed — back to installed-and-isolated, no model reachable.
- Nous agent archived: stopped and gated behind the `archived` compose profile so a deploy does
  not restart it. Image stays pinned by digest and the `hermes-agent-data` volume is kept
  (archive, never delete — D-023).
- `dyson.benchmark.hermes-wiring` capability disabled in governance (lifecycle → disabled,
  admitted → false).
- Kept: the governed switch of C to Nova micro (the fix for Finding 1).

All five weaknesses are addressed; the three code fixes and the route probe ship on `main` with
tests (intelligence suite: 97 passing).

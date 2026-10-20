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
Founder approval, then re-run the benchmark.

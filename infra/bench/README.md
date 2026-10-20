# Milestone A benchmark: Dyson engine vs Nous Hermes (D-027)

A time-boxed, governed head-to-head. Hermes is given a model, and only a model, through C; it runs
the same task set as the Dyson engine; then it is re-isolated. Nothing here runs until the Founder
admits the wiring on Direct Founder Controls.

## Pieces (already in the repo)

- `dyson_intelligence.openai_shim` — an OpenAI-compatible endpoint that forwards every call to C
  with the Hermes credential and the fixed `hermes.benchmark` task class. Hermes holds no key and
  cannot choose the model or the budget.
- `dyson_intelligence.benchmark` — the task set, scoring, and the live scoreboard sink.
- D-027 in `policy/decisions.yaml` — the Founder decision this admission approves.

## Run order (at benchmark time)

1. **Admit (Founder):** on Direct Founder Controls, approve the D-027 wiring. This is a passkey
   action; no one else can do it.
2. **Wire (bounded):** bring up the shim from the layer-a image, reading the Hermes router token
   from the `hermes-secrets` volume and C's URL; put the shim on a `bench_net` shared only with
   `hermes-agent`. Point the Nous agent's provider at the shim (`base_url` → the shim's `/v1`),
   with its tools routed through G and real side effects denied.
3. **Run:** run the task set against both the Dyson engine and the Nous agent. Each result streams
   to the live scoreboard (one row per task: agent, completed, governed, steps, latency), then the
   summary.
4. **Re-isolate:** tear down `bench_net` and the shim; `hermes-agent` returns to its own internal
   network with no model. Archive it once Dyson matches or beats it (D-025, D-023).

## Guardrails

- Model only through C; the shim never holds a model or makes a decision.
- Hermes keeps no internet, no Layer A data, no secrets beyond its own token.
- Tool side effects are denied for the run: the benchmark measures reasoning and tool-choice.
- Model spend stays inside C's budget and the hourly guard.

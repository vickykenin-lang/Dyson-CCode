# Benchmark — gemini-3-flash-preview for conversation.interpret (2026-10-26)

**Purpose:** Qualify a strong free model as the conversation engine (B) primary, replacing
`amazon.nova-micro-v1:0` (the cheapest-qualified model, too weak — it returned the "I'm not sure
what you want" fallback on simple inputs). Measured live on the server against B's real
`INTERPRETATION_SCHEMA`.

## Setup
- Provider: `gemini` (direct Google AI Studio OpenAI-compatible endpoint,
  `https://generativelanguage.googleapis.com/v1beta/openai`), Founder key saved on DFC (free tier).
- Model: `gemini-3-flash-preview`, `temperature=0`, `reasoning_effort="none"` (Gemini 3.x Flash
  "thinks" by default — ~25 s and truncated replies; `none` returns full replies in ~2 s).
- Request shape: B's exact flow — a governed system prompt + the `INTERPRETATION_SCHEMA` appended,
  asking for exactly one JSON object; parsed with `first_json_object`.
- 8 representative Founder prompts (open-a-site, chit-chat, a tool action, a spend-rule proposal,
  an ambiguous one). A reply "passes" if it is a valid JSON object with `language` and a `kind` in
  {clarify, action, answer, proposal}. Transient free-tier API errors were retried up to 3× per
  prompt (mirrors the router's runtime fallback).

## Result
- **Quality: 8/8 valid, sensible engine decisions** (youtube kholo→action/answer, T0 restart→action,
  spend limit→proposal, chit-chat→answer, "hmm"→clarify). 0 transient errors on the clean run.
- **Latency: p95 1999 ms, avg 1614 ms.** Far faster than `gemini-3.5-flash` (p95 ~25 s under load).
- Reply quality is markedly better and wittier than Nova micro (e.g. "Hukum mere aaka! 🧞 YouTube
  khul gaya hai, bas thoda popcorn taiyar rakho 🍿").

## Notes / caveats
- Free-tier reliability blips occur (occasional error-array responses / "high demand" 503s). These
  are infrastructure, not decision quality, and are handled by the router's fallback to Bedrock
  (Nova micro / DeepSeek) when a Gemini call errors or is slow.
- `gemini-3-flash-preview` is a *preview* model id and may be withdrawn; if so, re-run this
  benchmark on the then-current flash id and re-roll. Router fallback covers an outage meanwhile.
- `reasoning_effort="none"` is set per-provider in `_models()` via the adapter's `extra_body`.

## Decision
Register `gemini-3-flash-preview` (provider `gemini`, price 0) for `conversation.interpret` with
min_quality 0.90 and a generous max_latency_ms 8000 (headroom for free-tier variance on future
re-benchmarks). Priced at 0, it wins C's cheapest-first routing over Nova/DeepSeek while clearing
the quality bar; Bedrock stays the trusted fallback. Qualification recorded as tasks_run 8,
tasks_passed 8, p95_latency_ms 1999, cost_per_task 0.

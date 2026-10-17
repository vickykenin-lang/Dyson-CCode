# conversation.interpret benchmark, 17 Oct 2026

Run on `dyson-server` in Sydney with the server role, `tools/model_benchmark.py` at `efecc98`:
B's exact system prompt, tools and schema; 26 Founder commands in English, Hindi and Hinglish.
A case passes only with the right kind of reply, the right language and, for actions, the right
tool, Receptor and arguments. Costs use Sydney on-demand prices of 17 Oct 2026. Raw results:
`/opt/dyson/bench/2026-10-17/results.json` on the server.

| Model | Passed | Quality | p95 latency | Median | Cost per task (USD) |
|---|---|---|---|---|---|
| deepseek.v3.2 | 25/26 | 96% | 3423 ms | 2184 ms | 0.0007419 |
| amazon.nova-pro-v1:0 | 24/26 | 92% | 6095 ms | 614 ms | 0.0009824 |
| mistral.mistral-large-3-675b-instruct | 22/26 | 85% | 1651 ms | 681 ms | 0.0006102 |
| qwen.qwen3-32b-v1:0 | 19/26 | 73% | 753 ms | 307 ms | 0.0001839 |
| openai.gpt-oss-120b-1:0 | 19/26 | 73% | 888 ms | 751 ms | 0.0002526 |
| openai.gpt-oss-20b-1:0 | 17/26 | 65% | 937 ms | 710 ms | 0.0001268 |
| amazon.nova-lite-v1:0 | 17/26 | 65% | 11243 ms | 1564 ms | 0.0000766 |
| mistral.ministral-3-14b-instruct | 14/26 | 54% | 3865 ms | 818 ms | 0.0002114 |
| amazon.nova-micro-v1:0 | 2/26 | 8% | 8800 ms | 3315 ms | 0.0000382 |
| local-rules stand-in (scored locally) | 18/26 | 69% | — | — | 0 |

Most failures of the cheaper models are the language label (Hinglish called Hindi or English);
Nova Micro leaves the language out. Two calls hit Bedrock throttling (counted as failures).
Claude models in Australia (`au.` profiles) were not run: they route through ap-southeast-4,
which the deployer policy does not allow.

Chosen: `deepseek.v3.2` with the acceptance bar 90% quality and 5,000 ms p95 latency (D-019).

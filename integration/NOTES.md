# Internal connection phase and Test T0: Step 9 notes

Step 9 replaces every fake from Steps 2 to 8 with the real component. The package is `dyson_integration`, and it owns the schema `integration` (one append-only table linking each Founder thread to the tasks it started).

All components share one PostgreSQL database. Each has its own schema and its own least-privilege app role, and each runs its own migration (`db.py`).

## What is connected (`adapters.py`, `system.py`)

| From | Port | Connected to |
|---|---|---|
| Gateway | conversation, status | B (through `ConversationForGateway`), D's tasks, I's thread history |
| B | router | C's HTTP API, as B by B's own credential |
| B | memory | I: thread history and the locked register entries |
| B | orchestrator | D |
| B | tool catalog | G's catalog, filtered by A: only admitted tools, only for active Receptors whose Founder-set limits permit them (LA-CONV-06) |
| B | governance | A: amendment proposals |
| D | tool hub | G, with D's credential |
| D | governance | A: control state, external-action approvals |
| D | QA | F |
| D | escalation, events | Founder inbox; task transitions with evidence references into I's audit log (LA-ORC-07) |
| G | governance | A: control state, registry, Receptor permissions, spend limits, approvals |
| G | audit | I's audit log |
| F | probe | T0's independent verifier |
| F, H | evidence | I's evidence registry |
| E | escalation | Founder inbox (D-009 reminders) |
| J | finance | H's figures, counted as verified only where I holds H's stage-8 evidence (LA-FIN-05, LA-DASH-04) |
| Direct Founder Controls | governance | A only |
| A | control listeners | D, T0's control lane; G and C check A's state on every call |
| Hermes | router, tool hub | C's and G's HTTP APIs with Hermes's own credentials |
| C | governance | A: registry and approvals |

## Test T0 (`t0.py`)

- **What it is.** A synthetic, no-money Receptor with zero spend limits. It tallies numbers and publishes notes.
- **How Layer A reaches it.** Only through the five lanes:
  - tasks, only from G;
  - QA, through an independent verifier that reads T0's real published output and recomputes the expected result from the task as D recorded it;
  - financial, where T0's revenue is always 0;
  - monitoring;
  - control, from A.
- **Planted fault.** Asked to tally more than five numbers, T0 drops the last one but still claims "done" with a valid receipt. F catches it every time, and the task is held after 3 failures.
- **Permitted repair.** T0's manifest preapproves one repair: restarting its worker.
  - Each attempt is first recorded with A, which allows at most `recovery_attempt_limit` (3, D-008) and then escalates to the Founder.
  - The restart goes through G, and F checks independently that T0 is healthy afterwards.

## Changes made to earlier steps to connect them

Each is small, additive and tested in its own step's tests.

| Step | Change | Why |
|---|---|---|
| Contracts | v1.1.0 adds `digests` (shared approval digest and channel signing bytes); A, G, D, C and Direct Founder Controls now import it instead of keeping copies | So the bytes an approval binds to cannot drift between components |
| G (Step 4) | `LaneAdapter`: an adapter may receive the whole authorized request | Work sent to a Receptor must carry the task ID and idempotency key (LA-IF-02) |
| Gateway (Step 8) | Optional `client_message_id` on `POST /messages`; the app sends one per drawn form | A network retry of the same command must not start a second task (LA-REL-02) |
| A (Step 3) | `repeated_failure_threshold`, `founder_reminder_interval_minutes` and `stale_after_hours` are validated operational parameters | D-009, D-010, D-011 |

## Requirements owned by this step

| ID | Proven by |
|---|---|
| LA-G-04 | `test_command_to_verified_answer`, `test_planted_fault_is_caught_and_held` |
| LA-G-05, LA-SAF-05 | `test_inspect_repair_and_return_evidence`, `test_repairs_stop_at_the_founder_set_limit` |
| LA-CONV-06 | `test_b_offers_only_what_a_permits`, `test_command_to_verified_answer` |
| LA-ORC-07 | `test_command_to_verified_answer` (every transition and the evidence reference in I) |
| LA-TOOL-05 | `test_g_routes_to_hermes_qa_and_finance_within_scope` |
| LA-FIN-05, LA-DASH-04 | `test_finance_reaches_j_only_through_verified_records_in_i` |
| LA-MEM-10, LA-REL-06 | `test_switching_the_model_keeps_history_tasks_and_register` |
| LA-HER-05 | `test_stop_with_models_and_voice_down_reaches_everything` (C refuses Hermes while stopped; G denies; only the Founder's approved resume lifts it) |
| LA-RD-04 | `test_core_rd_proposals_enter_the_amendment_workflow` |
| LA-AMD-03 | `test_controls_stay_effective_while_an_amendment_is_in_flight` |
| LA-IF-01 | `test_layer_a_reaches_t0_only_through_the_five_lanes` |
| LA-IF-02 | `test_every_task_to_t0_goes_through_g_with_id_and_key`, `test_command_to_verified_answer` |
| LA-IF-03 | `test_stop_with_models_and_voice_down_reaches_everything`, `test_breach_never_resumes_without_authorization` |
| LA-IF-04 | `test_planted_fault_is_caught_and_held` |
| LA-IF-12 | `test_t0_is_synthetic_with_no_money`, `test_planted_fault_is_caught_and_held` |
| LA-EVD-01 | `test_command_to_verified_answer`, `test_app_never_shows_a_failed_verification_as_done` |
| LA-REL-04 | Receptor down: `test_receptor_down_fails_safely_and_is_reported`; model outage: `test_model_outage_falls_back_and_total_outage_starts_nothing`; tool compromise: `test_tool_compromise_is_contained_at_once`; duplicate or retried action: `test_same_command_twice_after_a_network_retry_runs_once`; Founder disconnected and session lost: `test_founder_disconnected_and_session_lost_lose_nothing`; central server down: `test_central_server_restart_resumes_from_the_database`; approval pending: `test_approval_pending_then_founder_approves_once` |
| LA-PERF-03 | `test_status_streams_while_the_task_runs` |

## PRD §13 negative and security tests, run on the connected system

| PRD test | Test |
|---|---|
| Tool without permission or outside the registry | `test_tool_without_permission_or_outside_registry_is_denied_and_audited` |
| A model, agent or Receptor approves its own action or a rule change | `test_nobody_but_the_founder_can_approve` |
| STOP with the LLM and voice provider down | `test_stop_with_models_and_voice_down_reaches_everything` |
| Same command twice after a network retry | `test_same_command_twice_after_a_network_retry_runs_once` |
| Canary credential | `test_canary_credential_never_leaks` (not in any prompt or any row of any schema; a credential typed into chat is refused before B) |
| Hermes direct tool or model call | `test_hermes_direct_tool_call_is_blocked_and_audited`; `test_hermes_reaches_only_c_and_g` runs the real `deploy/hermes.compose.yml` topology in Docker: Hermes reaches C and G, and nothing else (not A, not the internet by IP or name, not its own disk) |
| Bank API, credential or payment path | `test_no_bank_api_credential_or_payment_path_exists` (every source file in the repository) |
| Revenue with no matching statement | `test_revenue_without_a_bank_statement_stays_reported` |
| Three QA/QC failures | `test_planted_fault_is_caught_and_held` |
| Failed verification shown in the app | `test_app_never_shows_a_failed_verification_as_done` |
| Switch the model or voice provider | `test_switching_the_model_keeps_history_tasks_and_register` (voice has no vendor until gate 5) |
| Restart the host and restore a backup | `test_host_restart_and_backup_restore_bring_the_transcript_back` |
| Start an action from the dashboard | `test_dashboard_has_no_action_path` |
| Recover after a serious breach | `test_breach_never_resumes_without_authorization` |

The PRD §13 stream milestones that can run locally are also covered:
- **Stream B:** recall a previous session and an approved rule: `test_recalls_a_previous_session_and_an_approved_rule`.
- **Stream D:** inspect, repair, return evidence: `test_inspect_repair_and_return_evidence`.
- **Stream E:** text path only: `test_hindi_and_hinglish_commands_reach_the_same_chain`.

## Running it locally

- **The test suite.** `pytest integration/tests` builds a fresh database per test. Bootstrapping happens through Direct Founder Controls with the Founder's device key, exactly as approvals happen later: admitting tools and models, setting T0's limits, activating T0 on acceptance evidence, and registering models in C.
- **The local stack.** `docker-compose.yml` runs Postgres and one Layer A process, `python -m dyson_integration.serve`:
  - Gateway on 8080, Founder app on 8081, Direct Founder Controls on 8082, J on 8083;
  - the worker runs in the same process with its own database connections;
  - it was brought up and driven over HTTP: a command reached completed-verified, STOP held new work, and the Founder's approved resume let it finish.
- **The model.** The model behind C is a deterministic stand-in (`rules_model.py`), wired exactly like a real provider: admitted, registered with an approval, qualified and called only through C.

## Known limits of the local setup (for Step 10)

- **One process.** The local stack runs every component in one process, and the components call each other's HTTP APIs in-process. The process serves one request at a time; status streams are excluded so they never block. Separate services, TLS and network isolation between A, G, DFC and the rest come with the AWS deployment in Step 10.
- **T0 in memory.** T0 runs in memory inside Layer A's process. A real Receptor reaches the five lanes over the network.
- **Local-only values.** The acceptance bars, budgets (0 INR) and qualification figures used for the stand-in model, and the Gateway limits, are local values, not Founder decisions. Real values come with the Step 10 benchmark and gates 2, 3 and 5.
- **Founder inbox.** Escalations go to an in-process Founder inbox and to I's audit log. Push delivery to the app comes in Step 10.
- **Bank statement format.** Still open, waiting for your sample.

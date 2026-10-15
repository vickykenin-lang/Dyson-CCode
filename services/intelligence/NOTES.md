# Intelligence plane (cards B, C, Hermes): Step 7 notes

The package is `dyson_intelligence`, and it uses the PostgreSQL schema `intelligence`, where every table is append-only. It depends only on `dyson_contracts`. Its outbound ports (`GovernancePort`, `MemoryPort`, `OrchestratorPort`, `ToolCatalogPort`, and Hermes's `RouterClient`, `ToolHubClient`, `RegistryView`) are faked in tests until Step 9.

No model is built in. No vendor SDK or raw network client is imported anywhere (a test checks this). Models plug in as adapters inside C, chosen by benchmark in Step 10 (AMD-4).

## C: Model Router & Fallback (`router.py`, `router_api.py`)

- **The only road to a model.** Only B and Hermes may call C. D, A, G, F and the Receptors are refused. Over HTTP, the caller is identified by its credential, never by anything in the request, so Hermes cannot call as B.
- **Nothing is preapproved.** A model can be used only when all of these hold:
  - A's integration gate admitted it as a model, and it is still admitted;
  - it was registered in C with a Founder approval for exactly that model and price;
  - its latest benchmark on real tasks of that class meets the Founder's acceptance bar (quality and p95 latency).
- **Choice.** Per task class, the route is every model that qualifies, cheapest per task first. The first answers; the rest are the tested fallback. A model that failed the bar is never a fallback.
- **Budgets.** Each task class has a Founder-approved daily budget and a per-call output-token limit. Before each model call, C reserves the worst possible cost of that call against the day's budget, and refuses if it would go over. The actual cost replaces the reservation afterwards. Without a budget, nothing is called.
- **Governed changes.** Registering or retiring a model, setting an acceptance bar and setting a budget each need a Founder approval bound to the exact change, used once. The HTTP API has no endpoint to change any of them.
- **Records.** Models, bars, budgets, benchmark results and every call attempt (model, caller, tokens, cost, success or failure) are kept append-only.
- **Provider loss.** C holds no task state and no memory. When a provider is lost, the next model on the route answers; B's thread lives in I and D's tasks in D.

## B: Conversation Engine (`conversation.py`)

- **Understands.** Each message goes to the model through C with the thread's history from I and the Founder's language (Hindi, English or Hinglish). The reply comes back in that language.
- **Persona.** B's instructions are built from the approved AMD register entries read from I. If the register can't be read, B does nothing and says so.
- **Checks the model in code.** The model's answer is only a proposal. B checks it:
  - the tool must be one G's registry admits;
  - the Receptor must be one that tool serves; if the tool serves several and none was named, B asks which;
  - the QA/QC standard comes from the tool catalog, not from the model.
- **Asks instead of guessing.** An unclear request, an unknown tool, an unreadable model answer, or speech flagged as possibly misheard each produce a question. Nothing is started.
- **Prepares, never executes.** A checked plan goes to D with the message ID as its idempotency key, so the same message cannot start two tasks. The plan has no approval field. B has no tool client and calls no approval, budget, admission or deployment function.
- **Proposes, never applies.** Rule or workflow improvements go to A as proposals. The Founder decides them on Direct Founder Controls.
- **Honest status.** What the Founder reads about a task is fixed text based on D's task state, never model text. Only `completed-verified`, which needs F's verdict and cited evidence, is reported as done. A tool's "200 OK" changes nothing.

## Hermes (`hermes/`, `deploy/hermes.compose.yml`)

- **What runs in the container.** The `hermes` package may import only the Python standard library (`collections`, `datetime`, `typing`, `uuid`), `pydantic`, `dyson_contracts` and the provider-neutral shapes in `models.py`. It has no database driver, network library, model SDK, secret store, audit or evidence writer.
- **Network.** In the compose file, Hermes is only on an internal network whose other members are C and G. It has no volumes, no published ports, a read-only filesystem and no Linux capabilities. Its only secret is its own caller credential for C and G. Only C has a network that leaves Layer A.
- **Thinks through C, acts through G.** Model calls go through C's API with Hermes's credential and are recorded as `hermes`. Tool calls go to G as `Component.HERMES`, so G's six checks apply and G decides.
- **Skills.** Hermes loads a skill, plugin or MCP server only if A's integration gate admitted it. One revoked later is dropped at once.
- **Candidate.** `gate.may_rely_on_hermes` is true only when Hermes is admitted and its benchmark for that class of task meets the Founder's acceptance bar.
- **No self-certification.** Hermes's output is always marked unverified and produced by Hermes. Only F's verdict can make it count.

## Requirements owned by this step

| ID | Proven by |
|---|---|
| LA-G-02 | `test_improvements_are_proposed_never_applied` |
| LA-G-06 | `test_losing_a_provider_keeps_task_state_and_memory`, `test_no_model_vendor_sdk_or_raw_network_client_anywhere` |
| LA-CONV-01 | `test_hindi_english_hinglish_with_whole_thread` |
| LA-CONV-02 | `test_action_becomes_a_prepared_instruction_for_d`, `test_the_same_message_twice_starts_one_task`, `test_b_has_no_power_to_approve_spend_or_deploy` |
| LA-CONV-03 | `test_ambiguous_requests_are_clarified_not_guessed`, `test_two_receptors_and_none_named_asks_which`, `test_uncertain_speech_is_confirmed_before_anything` |
| LA-CONV-04 | `test_persona_is_grounded_in_the_approved_register` |
| LA-CONV-05 | `test_improvements_are_proposed_never_applied`, `test_b_has_no_power_to_approve_spend_or_deploy` |
| LA-CONV-07 | `test_200_ok_is_never_reported_as_done` |
| LA-RTR-01 | `test_only_b_and_hermes_may_call_a_model`, `test_api_identifies_the_caller_by_credential`, `test_no_model_vendor_sdk_or_raw_network_client_anywhere` |
| LA-RTR-02 | `test_cheapest_model_that_meets_the_bar_is_chosen` |
| LA-RTR-03 | `test_no_model_is_preapproved`, `test_qualification_alone_admits_nothing` |
| LA-RTR-04 | `test_falls_back_to_the_tested_alternative`, `test_untested_model_is_never_a_fallback`, `test_losing_a_provider_keeps_task_state_and_memory`, `test_no_route_at_all_starts_nothing` |
| LA-RTR-05 | `test_token_limit_is_enforced_before_any_call`, `test_daily_budget_is_enforced_before_the_call`, `test_a_budget_is_never_spent_in_another_currency` |
| LA-RTR-06 | `test_registration_needs_gate_admission_and_exact_approval`, `test_retiring_a_model_needs_approval`, `test_revoked_at_the_gate_leaves_the_route`, `test_api_has_no_way_to_change_configuration`, `test_routing_records_are_append_only` |
| LA-HER-01 | `test_hermes_code_has_no_way_out_but_its_two_ports`, `test_hermes_container_reaches_only_c_and_g` |
| LA-HER-02 | `test_hermes_thinks_only_through_c`, `test_hermes_cannot_use_a_model_c_has_not_approved_for_it`, `test_api_identifies_the_caller_by_credential` |
| LA-HER-03 | `test_hermes_acts_only_through_g_as_itself`, `test_hermes_container_reaches_only_c_and_g` |
| LA-HER-06 | `test_skills_enter_only_through_the_integration_gate` |
| LA-HER-07 | `test_nothing_relies_on_hermes_until_qualified` |
| LA-HER-08 | `test_hermes_cannot_certify_its_own_work` |

## Settings the Founder sets later

The PRD gives no numbers for these, so none were invented. The tests use made-up values.

- The acceptance bar (minimum quality share and p95 latency) for each task class, starting with `conversation.interpret`.
- The daily budget and per-call output-token limit for each task class.
- Which models to admit, after the gate 5 / Step 10 benchmark.

## Left for later steps

- **Step 9:**
  - Wire B to I (thread context, register), A (proposals), D (submit and status) and G's admitted-tool catalog.
  - Wire C to A's registry and approvals, and Hermes's clients to C's and G's APIs.
  - Merge `deploy/hermes.compose.yml` into the full stack.
  - Route Hermes's outputs to F.
- **Step 10:** real model adapters and the benchmark that qualifies them (LA-RTR-07).

## Contract additions to make before Step 9

- `ModelRequest`, `RoutedResponse`, `AcceptanceBar`, `ModelBudget`, `Qualification` and `HermesOutput` should move into `dyson_contracts`.
- B's `PreparedPlan` and D's `TaskPlan` are the same shape and should become one contract.
- `external_action_digest` is now copied in A, G, D and C; it should live in `dyson_contracts`.

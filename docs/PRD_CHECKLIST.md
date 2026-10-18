# Layer A PRD checklist

Every requirement in `docs/traceability/requirements.yaml` (Layer A PRD v1.0) with its status on 18 Oct 2026.
Steps 1 to 9 are proven by the tests named in each step's NOTES.md (CI green). Step 10 items were checked on AWS.

| Status | Count |
|---|---|
| ✅ Done | 162 |
| 🟡 Partial | 10 |
| ⏸ Deferred | 2 |
| ❌ Gap | 0 |

## Not done yet

| ID | Status | What is missing |
|---|---|---|
| LA-G-01 | 🟡 Partial | Text in Hindi, English and Hinglish is live on DeepSeek v3.2 (D-019). Voice deferred (D-016). |
| LA-APP-02 | 🟡 Partial | Text accepts all three languages. Voice deferred (D-016). |
| LA-APP-08 | ⏸ Deferred | Voice vendor benchmark deferred by the Founder (D-016). |
| LA-RTR-07 | 🟡 Partial | C replaces email, UPI, PAN, IFSC, card, Aadhaar, mobile and other 9+ digit numbers with placeholders before any model call and restores them inside Layer A (`redaction.py`, `test_personal_and_financial_identifiers_never_reach_a_model`). Names and free-text addresses are not detected yet. |
| LA-MEM-05 | 🟡 Partial | PostgreSQL in use, encrypted S3 backups, restore tested, access control and retrieval tested. Attachment bytes are not yet stored in S3. |
| LA-DASH-05 | 🟡 Partial | J's verified data API is built (GET-only, tested). The Founder-visible dashboard screens are not built; they wait for gate 8. |
| LA-SEC-02 | 🟡 Partial | Least-privilege roles in use (`infra/iam/`). No periodic usage review scheduled yet; the deployer access key is still active. |
| LA-SEC-07 | 🟡 Partial | Same filter as LA-RTR-07 (names and addresses not yet detected). Cross-Receptor isolation exists (row-level security per Receptor); only T0 runs (D-017). |
| LA-COST-03 | 🟡 Partial | Model cost and latency measured (benchmark, `intelligence.calls`). Server CPU, RAM and task throughput not yet measured. |
| LA-COST-04 | 🟡 Partial | Sydney prices for Bedrock and Lightsail checked; 100 USD credits budgeted. Free-tier eligibility not checked separately. |
| LA-PERF-02 | ⏸ Deferred | Voice thresholds deferred with voice (D-016). |
| LA-PRIV-01 | 🟡 Partial | Policy approved (D-017). No in-app deletion control yet; deleting on request is done by hand. |

Also from the Step 10 build list: Layer A's runtime secret store is still the file in `/data` (backed up encrypted); deploy-time secrets are in Parameter Store, but the AWS secret store behind the secret-store interface is not built.


## 2. Goals, non-goals and success criteria

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-G-01 | 10 | 🟡 Partial | Converse with the Founder in natural Hindi, English and Hinglish, with live voice and text sharing one history and one memory. | Text in Hindi, English and Hinglish is live on DeepSeek v3.2 (D-019). Voice deferred (D-016). |
| LA-G-02 | 7 | ✅ Done | Reason independently, challenge assumptions respectfully, understand the constitutional rules and propose improvements or amendments, without ever self-authorizing a constitutional change. | services/intelligence/NOTES.md: `test_improvements_are_proposed_never_applied` |
| LA-G-03 | 2 | ✅ Done | Preserve conversations, project context, decisions, evidence and reasoning across days, sessions, devices and model changes. | services/memory/NOTES.md: `test_transcript_survives_*`, `test_backup_and_restore` |
| LA-G-04 | 9 | ✅ Done | Direct and monitor separately governed Layer B Receptors, and receive truthful, verified results from them. | integration/NOTES.md: `test_command_to_verified_answer`, `test_planted_fault_is_caught_and_held` |
| LA-G-05 | 9 | ✅ Done | Observe, diagnose and take bounded low-risk repair actions inside preapproved policies; escalate or stop within AMD-3 and AMD-5 limits. | integration/NOTES.md: `test_inspect_repair_and_return_evidence`, `test_repairs_stop_at_the_founder_set_limit` |
| LA-G-06 | 7 | ✅ Done | Stay provider-neutral: losing or replacing a model or voice provider must not destroy task state, Founder decisions or accumulated memory. | services/intelligence/NOTES.md: `test_losing_a_provider_keeps_task_state_and_memory`, `test_no_model_vendor_sdk_or_raw_network_client_anywhere` |
| LA-G-07 | 1 | ✅ Done | Run independently of any active ChatGPT conversation and without GitHub Actions in the live command-execution path. | Runtime never calls GitHub; CI only (`.github/workflows/ci.yml`). |
| LA-G-08 | 8 | ✅ Done | Spare the Founder from jumping between many tools, models and Receptor dashboards for routine operations. | apps/founder-app/NOTES.md: `test_founder_talks_only_to_dyson` (one page for conversation and tasks; dashboard screens wait for gate 8) |
| LA-G-09 | 8 | ✅ Done | Acknowledge commands fast and show continuously updated activity, without promising zero-latency completion. | apps/founder-app/NOTES.md: `test_acknowledgment_is_honest_and_immediate`, `test_acknowledgment_is_immediate_and_never_completion`, `test_status_streams_until_verified` |

## 7.1.1 Dyson Voice / Chat App (Natural Language Interface)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-APP-01 | 8 | ✅ Done | The app shall be a Dyson-owned, branded conversation environment (Web, with Android as the target) offering near-real-time two-way voice and text on the same authoritative Dyson backend. | apps/founder-app/NOTES.md: `test_branded_dyson_text_first_page`, `test_voice_is_a_slot_until_gate_5` (Android is later) |
| LA-APP-02 | 10 | 🟡 Partial | The app shall accept Hindi, English and mixed Hinglish in voice and text. Quality thresholds are set by benchmark (gate 5). | Text accepts all three languages. Voice deferred (D-016). |
| LA-APP-03 | 8 | ✅ Done | Voice and text shall share one conversation history and one memory. | apps/founder-app/NOTES.md: `test_voice_and_text_share_one_thread` |
| LA-APP-04 | 8 | ✅ Done | For every command the app shall show an immediate honest acknowledgment ( accepted or approval-needed ), then stream task progress, and show a final result only when verified evidence exists. An acknowledgment shall never be presented as completion. | apps/founder-app/NOTES.md: `test_acknowledgment_is_honest_and_immediate`, `test_live_status_says_done_only_with_verified_evidence`, `test_status_label_never_calls_anything_else_done`, `test_acknowledgment_is_immediate_and_never_completion` |
| LA-APP-05 | 8 | ✅ Done | Ending a voice call shall not erase any task or its history. On reconnect the app shall retrieve task states and relevant conversation context from AWS. | apps/founder-app/NOTES.md: `test_reconnect_restores_tasks_and_context`, `test_reconnect_gets_tasks_and_context_back` |
| LA-APP-06 | 8 | ✅ Done | Access shall be Founder-only, with sessions handled through the Entry Gateway. The app holds no authority of its own. | apps/founder-app/NOTES.md: `test_founder_only_through_the_gateway`, `test_session_cookie_is_protected`, `test_app_holds_no_authority_and_no_records` |
| LA-APP-07 | 8 | ✅ Done | The app shall flag uncertain speech transcription instead of acting on it silently. | apps/founder-app/NOTES.md: `test_uncertain_speech_is_confirmed_never_sent_silently`, `test_uncertain_speech_is_passed_on_flagged` |
| LA-APP-08 | 10 | ⏸ Deferred | The voice technology shall be chosen only after benchmarking GPT-Live / Realtime, Gemini Live and chained STT to LLM to TTS options (including Hindi-oriented providers), and transport such as LiveKit or Pipecat. None is preapproved. | Voice vendor benchmark deferred by the Founder (D-016). |
| LA-APP-09 | 8 | ✅ Done | The app shall not be the system of record or a source of authorization. Any other front end, for example a ChatGPT adapter, is optional, later and tested first. | apps/founder-app/NOTES.md: `test_app_holds_no_authority_and_no_records` |

## 7.1.2 Entry Gateway (Identity, Session, Rate Limiting), on AWS

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-GW-01 | 8 | ✅ Done | The Gateway shall authenticate the Founder for every session and issue a session token. | apps/founder-app/NOTES.md: `test_every_session_is_authenticated`, `test_sessions_expire_and_end`, `test_session_token_is_not_stored_in_clear` |
| LA-GW-02 | 8 | ✅ Done | The Gateway shall apply rate limiting and abuse protection to all inbound traffic. | apps/founder-app/NOTES.md: `test_all_traffic_is_rate_limited`, `test_failed_logins_lock_the_address_out` |
| LA-GW-03 | 8 | ✅ Done | The Gateway shall enforce access controls and route authenticated requests to the Dyson Conversation Engine (B). | apps/founder-app/NOTES.md: `test_authenticated_requests_go_to_b_only` |
| LA-GW-04 | 10 | ✅ Done | The Gateway shall run on AWS and be the only public entry point to Layer A. | No open ports; the only public path is the Cloudflare Tunnel. The app reaches Layer A only through the Gateway; Direct Founder Controls is its own endpoint by design (LA-DEP-03). |
| LA-GW-05 | 10 | ✅ Done | Network exposure, DNS and TLS shall be decided before paid deployment (gate 2). | Decided before paid deployment: D-013, D-018. DNS and TLS through Cloudflare. |

## 7.1.3 Direct Founder Controls

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-DFC-01 | 8 | ✅ Done | Approve / Reject and Emergency STOP / PAUSE shall be reachable on an independently authenticated path that does not pass through the app, the Conversation Engine or any LLM. | apps/founder-app/NOTES.md: `test_stop_and_pause_work_with_app_gateway_and_models_down`, `test_gateway_has_no_approval_or_control_endpoint`, `test_app_holds_no_authority_and_no_records`, `test_resume_is_requested_then_approved_never_commanded` |
| LA-DFC-02 | 8 | ✅ Done | Both controls shall connect only to the Governance Core (A). | apps/founder-app/NOTES.md: `test_controls_reach_only_the_governance_core` |
| LA-DFC-03 | 8 | ✅ Done | Consequential approvals shall require an independently authenticated Founder confirmation. The method (passkey, hardware key or other), signed-approval semantics, expiry and audit are decided at gate 3. | apps/founder-app/NOTES.md: `test_every_action_needs_its_own_fresh_confirmation`, `test_another_device_cannot_confirm` |
| LA-DFC-04 | 8 | ✅ Done | STOP and PAUSE shall work when the voice model, any LLM or the app is unavailable. | apps/founder-app/NOTES.md: `test_stop_and_pause_work_with_app_gateway_and_models_down`, `test_the_cli_stops_everything` |
| LA-DFC-05 | 8 | ✅ Done | An approval shall bind to the exact action or diff shown to the Founder and be recorded with time and approver. | apps/founder-app/NOTES.md: `test_approval_binds_to_the_exact_action_shown`, `test_a_changed_action_cannot_be_approved`, `test_reject_is_recorded_too` |
| LA-DFC-06 | 10 | ✅ Done | How STOP treats operations already running or irreversible shall be documented as a Founder decision before any live write testing (gate 4). | Founder decision D-015 before live writes. |

## 7.1.4 Bank statement intake (zone 3 into the Financial Controller)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-VLT-01 | 6 | ✅ Done | The only path from the Founder's bank records into Dyson shall be a Founder-initiated bank statement upload to the Financial Controller (H). | services/assurance/NOTES.md: `test_only_the_founder_uploads_statements`, `test_statement_must_match_its_hash_and_period` |
| LA-VLT-02 | 6 | ✅ Done | Dyson shall have no direct bank API access, bank credentials or payment capability. | services/assurance/NOTES.md: `test_no_bank_payment_network_or_model_client_anywhere` |
| LA-VLT-03 | 6 | ✅ Done | The vault's private financial records stay Founder-only. Layer A shall keep only the uploaded statement data needed for reconciliation. | services/assurance/NOTES.md: `test_statement_keeps_only_what_reconciliation_needs` |
| LA-VLT-04 | 10 | ✅ Done | Uploaded statements shall be treated as personal financial data under the classification and retention policy decided at gate 6. | D-017: only parsed statement fields are kept, never the file; narration, account number and balance dropped (`parse_statement`). |

## 7.2.1 A. Governance Core (Policy & Control Authority)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-GOV-01 | 3 | ✅ Done | The Policy Engine shall hold machine-checkable policy derived from the approved AMD register, with a version and effective date for each rule. | services/governance/NOTES.md: `test_every_rule_has_version_and_effective_date`, `test_tampered_register_is_refused` |
| LA-GOV-02 | 3 | ✅ Done | The Founder Approval Engine shall create, track and close approval requests, accept decisions only from the independently authenticated Founder channel, and refuse approval from any model, agent or Receptor. | services/governance/NOTES.md: `test_decision_without_valid_channel_proof_is_refused`, `test_models_agents_and_receptors_cannot_approve`, `test_decision_binds_to_exact_action_and_expiry`, `test_rejected_stays_blocked` |
| LA-GOV-03 | 3 | ✅ Done | Emergency STOP / PAUSE shall be deterministic control code with no LLM in its path. It shall act on the Tool Hub, Hermes and all Receptors. | services/governance/NOTES.md: `test_master_stop_reaches_everything_without_any_model`, `test_governance_imports_no_model_or_network_client`, `test_listener_failure_does_not_block_stop` |
| LA-GOV-04 | 3 | ✅ Done | Budget & Permission Controls shall store each Receptor's permissions, authority and spending limits as set by the Founder, and change them only on Founder approval. | services/governance/NOTES.md: `test_recommendation_changes_nothing_until_founder_approves`, `test_spend_checks_against_limits` |
| LA-GOV-05 | 3 | ✅ Done | Every financial action shall stay blocked until a Founder approval for it exists. | services/governance/NOTES.md: `test_financial_action_blocked_until_founder_approves_then_usable_once` |
| LA-GOV-06 | 3 | ✅ Done | The Supply Chain / Integration Gate shall admit each package, plugin, API, MCP server and integration only after security checks and an auditable change record. High-risk items need Founder approval; suspect items can be blocked or isolated. | services/governance/NOTES.md: `test_nothing_is_admitted_before_a_security_check`, `test_failed_check_blocks`, `test_high_risk_needs_founder_approval`, `test_suspect_integration_is_isolated_at_once` |
| LA-GOV-07 | 3 | ✅ Done | Legal & Compliance Controls shall keep Receptor-specific compliance records and route new legal policies, regulated activities or activation to the Founder. Required legal review is never replaced by an AI guess. | services/governance/NOTES.md: `test_legal_review_must_be_a_person`, `test_compliance_goes_to_founder_and_needs_review_first` |
| LA-GOV-08 | 3 | ✅ Done | After a serious security or financial breach the Core shall not resume automatically. | services/governance/NOTES.md: `test_no_automatic_resume_after_breach`, `test_resume_only_through_an_approval_for_the_current_stop` |
| LA-GOV-09 | 3 | ✅ Done | Recovery attempts shall be bounded and recorded one by one, and repeated failure shall escalate for Founder or human authorization. | services/governance/NOTES.md: `test_recovery_is_bounded_recorded_and_escalated` |
| LA-GOV-10 | 3 | ✅ Done | A Safe Continuity mode shall be reserved in the design. The 48-hour automatic trigger shall not be implemented until Founder presence detection is defined and validated. | services/governance/NOTES.md: `test_safe_continuity_trigger_stays_blocked` |

## 7.2.2 B. Dyson Conversation Engine (Understand, Decide, Prepare)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-CONV-01 | 7 | ✅ Done | B shall interpret each Founder request in Hindi, English or Hinglish and keep the context of the whole thread. | services/intelligence/NOTES.md: `test_hindi_english_hinglish_with_whole_thread` |
| LA-CONV-02 | 7 | ✅ Done | B shall decide which tools and Receptors a request needs and hand a prepared instruction to the Orchestrator (D). It shall not execute tools itself. | services/intelligence/NOTES.md: `test_action_becomes_a_prepared_instruction_for_d`, `test_the_same_message_twice_starts_one_task`, `test_b_has_no_power_to_approve_spend_or_deploy` |
| LA-CONV-03 | 7 | ✅ Done | B shall ask the Founder to clarify an ambiguous request instead of guessing. | services/intelligence/NOTES.md: `test_ambiguous_requests_are_clarified_not_guessed`, `test_two_receptors_and_none_named_asks_which`, `test_uncertain_speech_is_confirmed_before_anything` |
| LA-CONV-04 | 7 | ✅ Done | B shall carry persistent persona and role instructions grounded in the approved AMD register. | services/intelligence/NOTES.md: `test_persona_is_grounded_in_the_approved_register` |
| LA-CONV-05 | 7 | ✅ Done | B shall propose improvements to rules and workflows on its own initiative. It shall never silently rewrite a policy, approve new spend or deploy an unapproved Receptor. | services/intelligence/NOTES.md: `test_improvements_are_proposed_never_applied`, `test_b_has_no_power_to_approve_spend_or_deploy` |
| LA-CONV-06 | 9 | ✅ Done | B shall run policy and approval checks with the Governance Core (A) before it prepares an action, and shall return responses to the Founder through the Entry Gateway. | integration/NOTES.md: `test_b_offers_only_what_a_permits`, `test_command_to_verified_answer` |
| LA-CONV-07 | 7 | ✅ Done | B shall not report an action as complete because a tool answered 200 OK . Completion is reported only after verification. | services/intelligence/NOTES.md: `test_200_ok_is_never_reported_as_done` |

## 7.2.3 C. Model Router & Fallback (Only approved path to external models)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-RTR-01 | 7 | ✅ Done | C shall be the only approved path from Layer A, including Hermes, to external models. No model access shall exist outside governance. | services/intelligence/NOTES.md: `test_only_b_and_hermes_may_call_a_model`, `test_api_identifies_the_caller_by_credential`, `test_no_model_vendor_sdk_or_raw_network_client_anywhere` |
| LA-RTR-02 | 7 | ✅ Done | C shall pick, per task, the least expensive approved model that reliably meets the Founder-defined acceptance bar. | services/intelligence/NOTES.md: `test_cheapest_model_that_meets_the_bar_is_chosen` |
| LA-RTR-03 | 7 | ✅ Done | No model or vendor shall be preapproved or mandatory. Qualification compares real task outcomes, latency and cost. | services/intelligence/NOTES.md: `test_no_model_is_preapproved`, `test_qualification_alone_admits_nothing` |
| LA-RTR-04 | 7 | ✅ Done | C shall fall back to a tested alternative on failure without losing task state or memory. | services/intelligence/NOTES.md: `test_falls_back_to_the_tested_alternative`, `test_untested_model_is_never_a_fallback`, `test_losing_a_provider_keeps_task_state_and_memory`, `test_no_route_at_all_starts_nothing` |
| LA-RTR-05 | 7 | ✅ Done | C shall enforce cost control and token limits inside approved budgets. | services/intelligence/NOTES.md: `test_token_limit_is_enforced_before_any_call`, `test_daily_budget_is_enforced_before_the_call`, `test_a_budget_is_never_spent_in_another_currency` |
| LA-RTR-06 | 7 | ✅ Done | Model identities, routes and fallbacks shall be recorded and stay under governance. Changes need approval. | services/intelligence/NOTES.md: `test_registration_needs_gate_admission_and_exact_approval`, `test_retiring_a_model_needs_approval`, `test_revoked_at_the_gate_leaves_the_route`, `test_api_has_no_way_to_change_configuration`, `test_routing_records_are_append_only` |
| LA-RTR-07 | 10 | 🟡 Partial | Data sent to external models shall follow the redaction rules decided at gate 6. | C replaces email, UPI, PAN, IFSC, card, Aadhaar, mobile and other 9+ digit numbers with placeholders before any model call and restores them inside Layer A (`redaction.py`, `test_personal_and_financial_identifiers_never_reach_a_model`). Names and free-text addresses are not detected yet. |

## 7.2.4 D. Dyson Orchestrator (Task Planning & Routing)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-ORC-01 | 5 | ✅ Done | D shall assign a task ID to every accepted instruction and manage its lifecycle through the durable states in section 9. | services/orchestrator/NOTES.md: `test_every_instruction_gets_a_task_id_once`, `test_happy_path_completes_only_after_independent_verification` |
| LA-ORC-02 | 5 | ✅ Done | D shall run tasks from a durable queue so that work continues when the voice session closes. | services/orchestrator/NOTES.md: `test_work_survives_a_restart_with_no_session`, `test_two_workers_never_run_the_same_task_twice` |
| LA-ORC-03 | 5 | ✅ Done | D shall attach an idempotency key to every action so that a retry after a network failure cannot duplicate it. | services/orchestrator/NOTES.md: `test_network_retry_reuses_the_key_and_never_duplicates`, `test_every_instruction_gets_a_task_id_once`, `test_tool_answer_is_not_completion` |
| LA-ORC-04 | 5 | ✅ Done | D shall apply retry and escalation logic, and shall move a task to Held after three consecutive QA/QC failures. | services/orchestrator/NOTES.md: `test_qa_failure_retests_with_a_new_attempt`, `test_three_consecutive_qa_failures_hold_and_notify`, `test_only_a_person_releases_a_qa_hold`, `test_denial_or_tool_failure_escalates_without_blind_retries` |
| LA-ORC-05 | 5 | ✅ Done | D shall route all tool use through the Governed Tool Hub (G) and have no other path to a tool. | services/orchestrator/NOTES.md: `test_orchestrator_has_no_tool_or_model_client`. D builds `ToolCallRequest`s for G and holds no adapters or tool credentials. |
| LA-ORC-06 | 5 | ✅ Done | D shall not mark a task completed-verified until the QA/QC Controller has verified the real output. | services/orchestrator/NOTES.md: `test_happy_path_completes_only_after_independent_verification`, `test_tool_answer_is_not_completion` |
| LA-ORC-07 | 9 | ✅ Done | D shall write task state and evidence references to the Memory & Evidence Layer (I). | integration/NOTES.md: `test_command_to_verified_answer` (every transition and the evidence reference in I) |

## 7.2.5 E. Receptor Monitoring & Health Controller

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-MON-01 | 6 | ✅ Done | E shall monitor all Receptors (R11 to Rn) through the Monitoring / Health lane. | services/assurance/NOTES.md: `test_tracks_status_kpis_and_failures_per_receptor` |
| LA-MON-02 | 6 | ✅ Done | E shall track task status, KPIs and failures per Receptor. | services/assurance/NOTES.md: `test_tracks_status_kpis_and_failures_per_receptor` |
| LA-MON-03 | 6 | ✅ Done | E shall detect repeated-failure and pause conditions and escalate them to the Governance Core and to the Founder Dashboard (J). | services/assurance/NOTES.md: `test_failure_and_repeated_failure_escalate_to_governance_and_dashboard`, `test_silence_is_reported_as_unknown_or_unverified_never_healthy`, `test_founder_is_reminded_hourly_until_acting`, `test_hold_stops_reminders_until_released`, `test_only_the_founder_closes_or_holds_an_alert`, `test_a_new_occurrence_after_action_is_a_new_alert`, `test_alert_history_is_append_only` |
| LA-MON-04 | 6 | ✅ Done | E shall supply health status and KPI views to the Founder Dashboard as read-only data. | services/assurance/NOTES.md: `test_dashboard_is_read_only_and_shows_verified_data` (`/health`) |
| LA-MON-05 | 6 | ✅ Done | E shall have no authority to act on a Receptor. It observes and escalates; the Governance Core decides. | services/assurance/NOTES.md: `test_monitor_has_no_way_to_act` |
| LA-MON-06 | 6 | ✅ Done | Monitoring shall report truthfully when a Receptor, model, tool or the Core itself is offline or unverified. | services/assurance/NOTES.md: `test_silence_is_reported_as_unknown_or_unverified_never_healthy`, `test_models_tools_and_core_are_monitored_too` |

## 7.2.6 F. Independent QA/QC Controller

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-QA-01 | 6 | ✅ Done | F shall define the quality standards for all Receptors and verify their outputs and evidence independently of the Receptor that produced them. | services/assurance/NOTES.md: `test_standards_are_versioned_and_immutable`, `test_standard_must_fit_the_receptor` |
| LA-QA-02 | 6 | ✅ Done | F shall check technical success and practical fitness for purpose separately. | services/assurance/NOTES.md: `test_passes_only_when_technical_and_fitness_both_pass` |
| LA-QA-03 | 6 | ✅ Done | A failure shall trigger correction and retest. After three consecutive failures F shall trigger HOLD and notify a human reviewer / Founder. | services/assurance/NOTES.md: `test_three_consecutive_failures_trigger_hold_and_notify_once` |
| LA-QA-04 | 6 | ✅ Done | F shall audit task results and logs, and receive escalations from Receptors. | services/assurance/NOTES.md: `test_audit_and_receptor_escalations` |
| LA-QA-05 | 6 | ✅ Done | F shall accept no Receptor self-certification. Completion needs an independent verification step that proves the intended real output. | services/assurance/NOTES.md: `test_receptor_self_certification_never_passes`, `test_no_observation_means_no_verdict` |
| LA-QA-06 | 6 | ✅ Done | F shall record evidence in the registry using the eight stages, and shall not accept "connected" or "working" as evidence. | services/assurance/NOTES.md: `test_superficial_answers_are_not_evidence`, `test_passes_only_when_technical_and_fitness_both_pass` |

## 7.2.7 G. Governed Tool Hub (All tool use must pass through this hub)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-TOOL-01 | 4 | ✅ Done | G shall authorize each individual tool call by checking identity and permission, Receptor scope, risk and spend limits, approval status and current STOP state. | services/toolhub/NOTES.md: `test_all_six_checks_are_evaluated_every_time`, `test_credential_must_match_the_claimed_caller`, `test_caller_must_be_allowed_for_the_tool`, `test_scope_rules`, `test_money_needs_an_approval_for_the_exact_action_used_once`, `test_spend_limits_use_g_own_spend_record`, `test_callers_cannot_declare_a_risky_tool_safe` |
| LA-TOOL-02 | 4 | ✅ Done | G shall be the only path to any tool, API, plugin or MCP connector. Neither the Orchestrator nor Hermes has another path. | In code, adapters exist only inside G. On AWS, Hermes can reach nothing but G and C through the edge (see LA-DEP-01). `test_hermes_in_its_own_process_reaches_only_c_and_g`. |
| LA-TOOL-03 | 4 | ✅ Done | G shall keep a governed registry of APIs, plugins and MCP connectors. Nothing is callable until it has passed the Supply Chain / Integration Gate. | services/toolhub/NOTES.md: `test_unknown_or_unadmitted_tools_are_not_callable` |
| LA-TOOL-04 | 4 | ✅ Done | G shall deny and audit any call that fails a check. First milestone: unauthorized tool execution is denied and audited. | `integration/tests/test_safety.py::test_tool_without_permission_or_outside_registry_is_denied_and_audited`. |
| LA-TOOL-05 | 9 | ✅ Done | G shall route work to Receptors, Hermes, QA/QC and Financial Control as needed, within per-tool scope. | integration/NOTES.md: `test_g_routes_to_hermes_qa_and_finance_within_scope` |
| LA-TOOL-06 | 4 | ✅ Done | G shall support revocation and kill switches per tool and connector. | services/toolhub/NOTES.md: `test_kill_switches_and_revival`: a kill is immediate; a revival needs a Founder approval naming that exact revival |
| LA-TOOL-07 | 4 | ✅ Done | G shall be deterministic: no LLM sits in its decision path. | services/toolhub/NOTES.md: `test_toolhub_imports_no_model_or_network_client` |

## 7.2.8 H. Financial Control & Reconciliation Controller

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-FIN-01 | 6 | ✅ Done | H shall keep a Receptor-wise revenue ledger and track payments for all Receptors. | services/assurance/NOTES.md: `test_payments_need_an_approval_and_net_profit_uses_verified_revenue_only` |
| LA-FIN-02 | 6 | ✅ Done | H shall reconcile Receptor-reported revenue against Founder-uploaded bank statements, and mark revenue final only after a match. | services/assurance/NOTES.md: `test_revenue_is_only_a_claim_until_a_statement_proves_it`, `test_no_match_stays_not_final`, `test_one_bank_line_proves_one_report` |
| LA-FIN-03 | 6 | ✅ Done | Every money-out action shall require Founder approval. Payments are made outside Dyson. | services/assurance/NOTES.md: `test_payments_need_an_approval_and_net_profit_uses_verified_revenue_only` (approval is mandatory; H has no payment capability) |
| LA-FIN-04 | 6 | ✅ Done | H shall hold verified receipts derived from bank statements. | services/assurance/NOTES.md: `test_revenue_is_only_a_claim_until_a_statement_proves_it` (stage-8 evidence and verified receipt) |
| LA-FIN-05 | 9 | ✅ Done | Financial data shown on the Founder Financial Dashboard shall originate in H and reach J through the Memory & Evidence Layer (I). | integration/NOTES.md: `test_finance_reaches_j_only_through_verified_records_in_i` |
| LA-FIN-06 | 6 | ✅ Done | Revenue and performance claims shall carry separate verified business evidence (AMD-3 stage 8). | services/assurance/NOTES.md: `test_revenue_is_only_a_claim_until_a_statement_proves_it` (stage-8 evidence and verified receipt) |
| LA-FIN-07 | 6 | ✅ Done | Receptor performance for incentives shall be judged on verified net profit, not on unsupported revenue claims. | services/assurance/NOTES.md: `test_payments_need_an_approval_and_net_profit_uses_verified_revenue_only` |
| LA-FIN-08 | 6 | ✅ Done | Prepaid-credit delegation and any automatic ad-spend allowance shall not be built or enabled without separate Founder authorization after testing. | services/assurance/NOTES.md: No prepaid-credit or automatic ad-spend path exists anywhere (`test_no_bank_payment_network_or_model_client_anywhere`). The governance control `blanket_automatic_ad_spend_allowance` is `false` in the policy register. |

## 7.2.9 I. Memory & Evidence Layer (Controlled store, not an authority)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-MEM-01 | 2 | ✅ Done | I shall archive conversations with dated messages or transcripts, thread IDs, participants, attachments and search. The raw transcript is saved when configured and successfully recorded. | services/memory/NOTES.md: `test_voice_and_text_share_one_history`, `test_search_cites_records_and_flags_uncertain_speech` |
| LA-MEM-02 | 2 | ✅ Done | I shall hold long-term memory (facts, preferences, project status, summaries) and retrieve original records with provenance, instead of sending the whole history to each model call. | services/memory/NOTES.md: `test_recall_with_provenance_and_uncertainty`, `test_superseded_memory_is_not_recalled` |
| LA-MEM-03 | 2 | ✅ Done | I shall keep the decision and amendment register with status (PROPOSED, OPEN, DESIGN LOCKED, APPROVED, SUPERSEDED), exact approved text, version, decision date, evidence and authenticated Founder approval. | services/memory/NOTES.md: `test_seed_loads_all_rules_and_decisions_once`, `test_locked_entry_needs_founder_approval` |
| LA-MEM-04 | 2 | ✅ Done | I shall isolate memory, credentials, financial and customer data by Receptor. Shared verified learnings need separate approval. | services/memory/NOTES.md: `test_receptors_are_isolated`, `test_receptor_evidence_is_isolated`, `test_secret_store_scopes_and_file_permissions` |
| LA-MEM-05 | 10 | 🟡 Partial | PostgreSQL is the proposed transactional store; S3 holds documents and encrypted backups. Backup restoration, access control and memory retrieval shall be tested. | PostgreSQL in use, encrypted S3 backups, restore tested, access control and retrieval tested. Attachment bytes are not yet stored in S3. |
| LA-MEM-06 | 2 | ✅ Done | The secret store shall hold every credential. None shall appear in prompts, public repositories or conversational memory. | services/memory/NOTES.md: `test_canary_credential_never_reaches_memory` (checks every row of every table) |
| LA-MEM-07 | 2 | ✅ Done | The audit log shall record each consequential action, tool call, approval, STOP event and configuration change, and AI components shall not be able to alter it. | services/memory/NOTES.md: `test_app_role_cannot_alter_audit`, `test_owner_cannot_alter_audit_either`, `test_tampering_by_superuser_is_detected`, `test_caller_cannot_supply_its_own_hash` |
| LA-MEM-08 | 2 | ✅ Done | I is a controlled store, not an authority. It informs decisions and never grants permission. | services/memory/NOTES.md: `test_no_endpoint_grants_or_approves` |
| LA-MEM-09 | 2 | ✅ Done | Retrieval shall cite the underlying records, flag uncertain speech transcription, and never present an unlocked rule as locked. | services/memory/NOTES.md: `test_search_cites_*`, `test_recall_with_provenance_*`, `test_unlocked_rule_is_never_presented_as_locked` |
| LA-MEM-10 | 9 | ✅ Done | Switching LLM or voice vendors shall not delete history or change the authoritative decision register. | integration/NOTES.md: `test_switching_the_model_keeps_history_tasks_and_register` |

## 7.2.10 J. Founder Financial Dashboard (Visibility only, no authority)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-DASH-01 | 6 | ✅ Done | J shall show verified financial data: revenue, payments, profitability, Receptor performance, and financial audit / reconciliation status. | services/assurance/NOTES.md: `test_dashboard_is_read_only_and_shows_verified_data` |
| LA-DASH-02 | 6 | ✅ Done | J shall have no authority to execute actions and no write path into Core controls. | services/assurance/NOTES.md: `test_dashboard_is_read_only_and_shows_verified_data` |
| LA-DASH-03 | 6 | ✅ Done | J shall not connect to the bank directly. | services/assurance/NOTES.md: `test_no_bank_payment_network_or_model_client_anywhere` |
| LA-DASH-04 | 9 | ✅ Done | J shall request data from the Memory & Evidence Layer (I) read-only, and I answers with verified data. | integration/NOTES.md: `test_finance_reaches_j_only_through_verified_records_in_i` |
| LA-DASH-05 | 6 | 🟡 Partial | The live, Founder-visible observability dashboard is a locked commitment. Its detailed design is deferred to its development stage. | J's verified data API is built (GET-only, tested). The Founder-visible dashboard screens are not built; they wait for gate 8. |

## 7.2.11 Hermes (zone 4): Isolated Hermes Runtime (Candidate Intelligence Engine)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-HER-01 | 7 | ✅ Done | Hermes shall run in an isolated environment, with no direct access to secrets, the audit log, evidence stores, the bank path or the STOP controls. | services/intelligence/NOTES.md: `test_hermes_code_has_no_way_out_but_its_two_ports`, `test_hermes_container_reaches_only_c_and_g` |
| LA-HER-02 | 7 | ✅ Done | Hermes shall reach external models only through the Model Router (C). | services/intelligence/NOTES.md: `test_hermes_thinks_only_through_c`, `test_hermes_cannot_use_a_model_c_has_not_approved_for_it`, `test_api_identifies_the_caller_by_credential` |
| LA-HER-03 | 7 | ✅ Done | Hermes shall reach every tool only through the Governed Tool Hub (G). | services/intelligence/NOTES.md: `test_hermes_acts_only_through_g_as_itself`, `test_hermes_container_reaches_only_c_and_g` |
| LA-HER-04 | 8 | ✅ Done | The Founder shall talk only to Dyson, never directly to Hermes. | apps/founder-app/NOTES.md: `test_founder_talks_only_to_dyson`, `test_authenticated_requests_go_to_b_only` |
| LA-HER-05 | 9 | ✅ Done | The STOP path from the Governance Core shall reach Hermes, and a stopped Hermes shall not be able to resume itself. | integration/NOTES.md: `test_stop_with_models_and_voice_down_reaches_everything` (C refuses Hermes while stopped; G denies; only the Founder's approved resume lifts it) |
| LA-HER-06 | 7 | ✅ Done | Hermes skills, agents, subagents and plugins shall enter through the Supply Chain / Integration Gate. | services/intelligence/NOTES.md: `test_skills_enter_only_through_the_integration_gate` |
| LA-HER-07 | 7 | ✅ Done | Hermes is a candidate. It shall be qualified against Dyson's governance and acceptance bar before anything relies on it. | services/intelligence/NOTES.md: `test_nothing_relies_on_hermes_until_qualified` |
| LA-HER-08 | 7 | ✅ Done | Hermes shall not certify its own results. Its outputs are verified by F like any other. | services/intelligence/NOTES.md: `test_hermes_cannot_certify_its_own_work` |

## 7.3 Core R&D and continuous improvement (separate function)

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-RD-01 | 1 | ✅ Done | Core R&D shall be an independent function that evaluates and improves the Dyson Core: model routing, safety, runtime, performance, capabilities and future possibilities. | `docs/process/CORE_RD.md`. |
| LA-RD-02 | 1 | ✅ Done | Its output shall be researched proposals. It shall never make automatic constitutional changes. | `docs/process/CORE_RD.md`. |
| LA-RD-03 | 1 | ✅ Done | It shall stay separate from the Layer B Receptor Genesis Engine. | `docs/process/CORE_RD.md`. |
| LA-RD-04 | 9 | ✅ Done | Its proposals shall enter the Governed Amendment Workflow (7.4) like any other. | integration/NOTES.md: `test_core_rd_proposals_enter_the_amendment_workflow` |
| LA-RD-05 | 1 | ✅ Done | External reviews, for example by Claude or Gemini, are advisory and remain subject to data and permission rules. | `docs/process/CORE_RD.md`. |

## 7.4 Governed Amendment Workflow

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-AMD-01 | 3 | ✅ Done | No model, agent, third-party consultant or Receptor shall self-approve a rule change. | services/governance/NOTES.md: `test_rule_change_cannot_be_self_approved_and_is_never_applied_at_runtime` |
| LA-AMD-02 | 3 | ✅ Done | Operational parameter changes and core AMD amendments shall have distinct rights and validation paths. | services/governance/NOTES.md: `test_parameters_and_amendments_take_different_paths` |
| LA-AMD-03 | 9 | ✅ Done | Financial controls, per-Receptor scopes, isolation, AMD-5 STOP, AMD-3 QC-failure holds and audit logging shall stay effective at every stage. | integration/NOTES.md: `test_controls_stay_effective_while_an_amendment_is_in_flight` |
| LA-AMD-04 | 2 | ✅ Done | Each register entry shall show an authoritative status and keep immutable history. | services/memory/NOTES.md: `test_register_history_is_immutable_and_status_is_latest` |
| LA-AMD-05 | 1 | ✅ Done | AMD-1 to AMD-13 stay unchanged by AMD-14 and by this PRD. | Register locked by digest: `tools/policy_lock.py`, `tests/test_policy.py`. |

## 8. Layer A to Layer B interface

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-IF-01 | 9 | ✅ Done | Layer A shall talk to Receptors only through the five lanes above. | integration/NOTES.md: `test_layer_a_reaches_t0_only_through_the_five_lanes` |
| LA-IF-02 | 9 | ✅ Done | Every task to a Receptor shall pass through G and carry a task ID and an idempotency key. | integration/NOTES.md: `test_every_task_to_t0_goes_through_g_with_id_and_key`, `test_command_to_verified_answer` |
| LA-IF-03 | 9 | ✅ Done | STOP / PAUSE / RESUME shall reach every Receptor on the red path and work whatever the AI model does. Resuming after a serious security or financial breach needs explicit authorization. | integration/NOTES.md: `test_stop_with_models_and_voice_down_reaches_everything`, `test_breach_never_resumes_without_authorization` |
| LA-IF-04 | 9 | ✅ Done | A Receptor's report is not proof. F shall verify the real output independently before D marks a task completed-verified. | integration/NOTES.md: `test_planted_fault_is_caught_and_held` |
| LA-IF-05 | 6 | ✅ Done | Receptor revenue is not final until H matches it to a Founder-uploaded bank statement. | services/assurance/NOTES.md: `test_revenue_is_only_a_claim_until_a_statement_proves_it`, `test_no_match_stays_not_final`, `test_one_bank_line_proves_one_report` |
| LA-IF-06 | 6 | ✅ Done | Layer A shall never sit in the customer payment flow. Customer payments go by UPI / QR to a bank account outside Dyson. | services/assurance/NOTES.md: `test_no_bank_payment_network_or_model_client_anywhere` |
| LA-IF-07 | 2 | ✅ Done | Layer A shall isolate each Receptor's data, credentials, sensitive data and finances. Only governed, verified information is shared. | services/memory/NOTES.md: `test_receptors_are_isolated`, `test_receptor_evidence_is_isolated`, `test_secret_store_scopes_and_file_permissions` |
| LA-IF-08 | 4 | ✅ Done | Optional receptor-to-receptor support shall be limited in scope and pass through Governance / Tool Hub. | services/toolhub/NOTES.md: `test_receptor_support_is_limited_and_governed` |
| LA-IF-09 | 3 | ✅ Done | A Receptor's permissions, authority and spending limits shall be set by the Founder and held in A. | services/governance/NOTES.md: `test_recommendation_changes_nothing_until_founder_approves`, `test_spend_checks_against_limits` |
| LA-IF-10 | 3 | ✅ Done | A Receptor may be paused, archived and replaced only on the Founder's final decision, and its records are kept through governed archiving. | services/governance/NOTES.md: `test_archive_needs_pause_and_founder_decision_and_keeps_records`, `test_replacement_is_the_founders_decision` |
| LA-IF-11 | 3 | ✅ Done | No real Receptor goes live on AMD-14 alone. Each needs its own activation decision, approved budget, tools, access and acceptance evidence. | services/governance/NOTES.md: `test_activation_needs_its_own_decision_budget_tools_and_evidence` |
| LA-IF-12 | 9 | ✅ Done | The first Receptor shall be a synthetic, no-money Test T0 with a planted fault and an independent verifier. | integration/NOTES.md: `test_t0_is_synthetic_with_no_money`, `test_planted_fault_is_caught_and_held` |

## 10. Cross-cutting requirements

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-SEC-01 | 2 | ✅ Done | All credentials shall stay in controlled secret storage, never in prompts, public repositories or conversational memories. | services/memory/NOTES.md: `test_canary_credential_never_reaches_memory` (checks every row of every table) |
| LA-SEC-02 | 10 | 🟡 Partial | IAM shall be least-privilege, with explicit limits and periodic usage review. | Least-privilege roles in use (`infra/iam/`). No periodic usage review scheduled yet; the deployer access key is still active. |
| LA-SEC-03 | 8 | ✅ Done | The Founder shall be authenticated at the Entry Gateway for every session. Consequential approvals need a separate, independently authenticated confirmation. | apps/founder-app/NOTES.md: `test_every_session_is_authenticated`, `test_every_action_needs_its_own_fresh_confirmation` |
| LA-SEC-04 | 3 | ✅ Done | Every package, plugin, API, MCP server and integration shall enter through Central Governance monitoring and an auditable change process. | services/governance/NOTES.md: `test_nothing_is_admitted_before_a_security_check`, `test_failed_check_blocks`, `test_high_risk_needs_founder_approval`, `test_suspect_integration_is_isolated_at_once` |
| LA-SEC-05 | 10 | ✅ Done | External AI and voice APIs shall be used only behind sanctioned, monitored interfaces and approved budgets. | Bedrock only through C, with an approved budget (0.16 USD/day, D-019) and every call logged in `intelligence.calls`. |
| LA-SEC-06 | 1 | ✅ Done | GitHub shall be used for private source control, code review, version history and controlled CI/CD only. It shall not be the live intelligence, conversational runtime, scheduler or command bus, and no pull request or GitHub Action shall sit in the runtime response loop. | GitHub is source control and CI only (`.github/workflows/ci.yml`, `README.md`). |
| LA-SEC-07 | 10 | 🟡 Partial | Data sent to external models shall follow redaction rules, and cross-Receptor isolation rules shall be defined before real data is used (gate 6). | Same filter as LA-RTR-07 (names and addresses not yet detected). Cross-Receptor isolation exists (row-level security per Receptor); only T0 runs (D-017). |
| LA-SAF-01 | 3 | ✅ Done | The master STOP and per-Receptor STOP / PAUSE / RESUME shall work independently of any LLM or voice provider. | services/governance/NOTES.md: `test_master_stop_reaches_everything_without_any_model`, `test_governance_imports_no_model_or_network_client`, `test_listener_failure_does_not_block_stop` |
| LA-SAF-02 | 4 | ✅ Done | The Tool Hub shall check the current STOP state on every call. | services/toolhub/NOTES.md: `test_stop_state_is_checked_on_every_call`, `test_governance_unreachable_means_deny` |
| LA-SAF-03 | 3 | ✅ Done | Emergency recovery shall be bounded, recorded per attempt, and escalated after repeated failure. | services/governance/NOTES.md: `test_recovery_is_bounded_recorded_and_escalated` |
| LA-SAF-04 | 3 | ✅ Done | There shall be no automatic resume after a serious security or financial breach. | services/governance/NOTES.md: `test_no_automatic_resume_after_breach`, `test_resume_only_through_an_approval_for_the_current_stop` |
| LA-SAF-05 | 9 | ✅ Done | Dyson may take bounded low-risk repair actions only inside preapproved policies. Anything else escalates or stops. | integration/NOTES.md: `test_inspect_repair_and_return_evidence`, `test_repairs_stop_at_the_founder_set_limit` |
| LA-EVD-01 | 9 | ✅ Done | No command is called complete until an independent verification step proves the intended real output. | integration/NOTES.md: `test_command_to_verified_answer`, `test_app_never_shows_a_failed_verification_as_done` |
| LA-EVD-02 | 6 | ✅ Done | A 200 OK from a tool, generated code, a passing superficial test or reassuring language is not evidence of completion. | services/assurance/NOTES.md: `test_superficial_answers_are_not_evidence`, `test_passes_only_when_technical_and_fitness_both_pass` |
| LA-EVD-03 | 2 | ✅ Done | Capability status shall be recorded per capability and provider on the eight AMD-3 stages, with environment, time, expiry and failed or negative evidence. | services/memory/NOTES.md: `test_stages_are_separate_and_failures_are_kept`, `test_expired_evidence_is_flagged`, `test_live_stages_cannot_be_self_certified_even_in_sql` |
| LA-EVD-04 | 6 | ✅ Done | Reports shall say plainly when something is offline, unverified or uncertain. | services/assurance/NOTES.md: `test_silence_is_reported_as_unknown_or_unverified_never_healthy`, `test_models_tools_and_core_are_monitored_too` |
| LA-EVD-05 | 6 | ✅ Done | Revenue and performance claims need separate verified business evidence. | services/assurance/NOTES.md: `test_revenue_is_only_a_claim_until_a_statement_proves_it` (stage-8 evidence and verified receipt) |
| LA-REL-01 | 5 | ✅ Done | Durable tasks shall run on Dyson-controlled infrastructure and not depend on an open voice conversation. | services/orchestrator/NOTES.md: `test_work_survives_a_restart_with_no_session`, `test_two_workers_never_run_the_same_task_twice` |
| LA-REL-02 | 5 | ✅ Done | Task IDs and idempotency keys shall prevent duplicate actions after retries. | services/orchestrator/NOTES.md: `test_network_retry_reuses_the_key_and_never_duplicates`, `test_every_instruction_gets_a_task_id_once`, `test_tool_answer_is_not_completion` |
| LA-REL-03 | 10 | ✅ Done | Backups shall be encrypted and a restore shall be tested. | Database and `/data` backups encrypted; restore test and disaster-recovery drill passed (17 Oct 2026). |
| LA-REL-04 | 9 | ✅ Done | The design shall be tested against these failure modes: Receptor down, model outage, tool compromise, duplicate or retried action, Founder disconnected, session lost, central server down, approval pending. | integration/NOTES.md: Receptor down: `test_receptor_down_fails_safely_and_is_reported`; model outage: `test_model_outage_falls_back_and_total_outage_starts_nothing`; tool compromise: `test_tool_compromise_is_contained_at_once`; duplicate or retried action: `test_same_command_twice_after_a_network_retry_runs_once`; Founder disconnected and session lost: `test_founder_disconnected_and_session_lost_lose_nothing`; central server down: `test_central_server_restart_resumes_from_the_database`; approval pending: `test_approval_pending_then_founder_approves_once` |
| LA-REL-05 | 10 | ✅ Done | Disaster recovery objectives shall be defined before production launch (gate 9). | D-020 (up to 24 hours of data) and D-021 (up to 2 hours down), before production (D-022). |
| LA-REL-06 | 9 | ✅ Done | Losing or replacing a model or voice provider shall not destroy task state, Founder decisions or memory. | integration/NOTES.md: `test_switching_the_model_keeps_history_tasks_and_register` |
| LA-COST-01 | 10 | ✅ Done | AWS budgets, alarms and explicit spend limits shall exist before any paid deployment. | Budget `dyson-credits-100` with alerts, created before any paid resource; hourly spend guard. |
| LA-COST-02 | 10 | ✅ Done | The initial planning target is 2 vCPU, 4 GB RAM and 50 to 80 GB persistent disk for a small isolated prototype. It is a hypothesis, not a guaranteed capacity or an approved budget. | 2 vCPU, 4 GB, 80 GB server (D-018). |
| LA-COST-03 | 10 | 🟡 Partial | CPU, RAM, database, task throughput, stream latency, model and voice API costs and recovery behavior shall be measured, and resources scaled up only from evidence. | Model cost and latency measured (benchmark, `intelligence.calls`). Server CPU, RAM and task throughput not yet measured. |
| LA-COST-04 | 10 | 🟡 Partial | Free-tier eligibility and prices shall be verified against the Founder's actual AWS account. | Sydney prices for Bedrock and Lightsail checked; 100 USD credits budgeted. Free-tier eligibility not checked separately. |
| LA-PERF-01 | 8 | ✅ Done | Command acknowledgment shall be fast and honest. Completion latency is not promised. | apps/founder-app/NOTES.md: `test_acknowledgment_is_honest_and_immediate`, `test_acknowledgment_is_immediate_and_never_completion`, `test_status_streams_until_verified` |
| LA-PERF-02 | 10 | ⏸ Deferred | Acceptable spoken-response latency and Hindi / Hinglish quality thresholds shall be set by benchmark before a voice vendor is chosen (gate 5). | Voice thresholds deferred with voice (D-016). |
| LA-PERF-03 | 9 | ✅ Done | Task status shall stream continuously while a task runs. | integration/NOTES.md: `test_status_streams_while_the_task_runs` |
| LA-PRIV-01 | 10 | 🟡 Partial | Retention period, deletion controls, voice audio retention and data sharing shall be approved as implementation-level policy (gate 6). | Policy approved (D-017). No in-app deletion control yet; deleting on request is done by hand. |
| LA-PRIV-02 | 10 | ✅ Done | Personal-data classification shall be defined before real data is used (gate 6). | Classification decided in D-017 before real data. |
| LA-PRIV-03 | 2 | ✅ Done | Existing ChatGPT conversations shall not migrate automatically. Any import needs an explicit, separately approved data transfer. | services/memory/NOTES.md: `test_no_automatic_chatgpt_import` |

## 12. Deployment on AWS

| ID | Step | Status | Requirement | Proof |
|---|---|---|---|---|
| LA-DEP-01 | 10 | ✅ Done | The Hermes runtime shall be deployed as an isolated environment, separate from the Governance Core, Tool Hub, Memory & Evidence Layer and secret store, with network paths limited to the Model Router and the Tool Hub. | Hermes runs in its own container on an internal network (`layer-a-fd29384`). Checked from inside it on 18 Oct 2026: the internet, AWS, Postgres, the Gateway, DFC and every other Layer A port are unreachable; only the Hermes edge (C, G, read-only registry) answers. `integration/tests/test_isolation.py`. |
| LA-DEP-02 | 10 | ✅ Done | The STOP path shall be deployed so that it keeps working when the Conversation Engine, Model Router and Hermes are down. | DFC runs in its own container with only A and I; STOP goes to A's event log and the main process passes it to D and T0. With layer-a and Hermes stopped on 18 Oct 2026, the controls page and its passkey check kept answering. `test_stop_from_the_separate_controls_process_reaches_d_and_t0`, `test_stop_from_another_process_reaches_this_ones_listeners`. |
| LA-DEP-03 | 10 | ✅ Done | Direct Founder Controls shall be a separately authenticated endpoint from the app. | `control.designinfra.in`, passkey step-up, separate from the app login. |
| LA-DEP-04 | 10 | ✅ Done | Encrypted S3 backups shall sit under keys and permissions that the application runtime cannot use to delete or alter them. | Object Lock (GOVERNANCE, 35 days); the server role can write backups but never delete them. |
| LA-DEP-05 | 10 | ✅ Done | A deployment shall be reproducible from private source control and shall have a rollback artifact. | Each release is a `git archive` of one commit in S3; earlier releases stay in S3 and on the server for rollback. |

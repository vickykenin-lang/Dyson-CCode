# Assurance plane (cards F, E, H, J): Step 6 notes

The package is `dyson_assurance`, and it uses the PostgreSQL schema `assurance`, where every table is append-only. It depends only on `dyson_contracts`. Its outbound ports (`EvidenceSink`, `EscalationSink`, `Probe`) are faked in tests until Step 9.

None of these components can act on a Receptor, move money or reach a bank. Tests check this: the packages import no bank, payment, network or model client, Monitoring has no method that acts, and J has only GET endpoints.

## F: Independent QA/QC Controller (`qa.py`)

- **Standards.** Each quality standard is versioned, and a published version never changes. A standard holds two separate lists of deterministic checks:
  - **technical:** run on what the tool returned;
  - **fitness:** run on F's own independent observation of the real result (`Probe`).
- **Passing.** A task passes only when both lists pass.
- **What F never uses or accepts:**
  - The Receptor's own report: it is kept for audit, never used to decide.
  - Superficial answers: "200 OK", "ok", "connected", "working", empty output or a bare `true` fail every check.
- **No observation, no verdict.** If F can't make its own observation, it gives no verdict at all.
- **Evidence.** Every verdict writes stage-7 (*real output verified*) evidence, passed or failed.
- **Hold.** After 3 consecutive failures, F notifies the human reviewer and A, once.

## E: Monitoring & Health Controller (`monitoring.py`)

- **What it tracks.** Health, KPIs, task counts and failures for each Receptor (from the Monitoring lane) and for models, tools and Core components.
- **Truthful reporting.** A subject that never reported shows as `unknown`. One whose last report is older than `stale_after` shows as `unknown / unverified`, never "healthy".
- **Escalation.** When a subject turns failing or offline, or after 3 bad reports in a row (D-010), E escalates to A, J and the Founder. `sweep()` does the same for subjects that have gone silent.
- **Founder alerts (D-009).** Each issue becomes one alert that stays open. Dyson reminds the Founder every hour (`remind()`, run by the worker) until the Founder acts on it or puts it on hold. A subject recovering on its own does not close it; the reminder says how it looks now. While an alert is open or held, the same issue isn't raised again. After the Founder acts, a new occurrence opens a new alert. Only the Founder can close, hold or release an alert, and the alert history is append-only.
- **No power to act.** E only observes and escalates; A decides.

## H: Financial Control & Reconciliation (`finance.py`)

- **Revenue.** A revenue report starts as `reported_not_final`. It becomes `final` only when a credit line on a bank statement you uploaded matches it:
  - same amount and currency;
  - dated inside the report's period;
  - containing the report's reference, if the report gave one.

  One bank line can prove only one report. Each match writes stage-8 (*real business outcome verified*) evidence and a verified receipt.
- **Bank statements.**
  - The upload must match its sha256 and its stated period.
  - Only date, direction, amount, currency and reference are stored. Balances, account numbers, narration and the file itself are not.
  - Long digit runs in references are masked to their last 4 digits.
- **Payments.** A payment is recorded only with the approval that allowed it. H can't pay anything. Payments are matched to debit lines on the statement.
- **Verified net profit** = verified revenue minus every recorded payment. Claimed revenue that the bank hasn't confirmed earns nothing. Receptor performance is ranked on this figure.

## J: Founder Dashboard data (`dashboard.py`)

GET-only endpoints: ledger, receipts, reconciliation status, performance, health, QA summary and alerts. The screens themselves wait for gate 8.

## Requirements owned by this step

| ID | Proven by |
|---|---|
| LA-QA-01 | `test_standards_are_versioned_and_immutable`, `test_standard_must_fit_the_receptor` |
| LA-QA-02 | `test_passes_only_when_technical_and_fitness_both_pass` |
| LA-QA-03 | `test_three_consecutive_failures_trigger_hold_and_notify_once` |
| LA-QA-04 | `test_audit_and_receptor_escalations` |
| LA-QA-05 | `test_receptor_self_certification_never_passes`, `test_no_observation_means_no_verdict` |
| LA-QA-06, LA-EVD-02 | `test_superficial_answers_are_not_evidence`, `test_passes_only_when_technical_and_fitness_both_pass` |
| LA-MON-01, LA-MON-02 | `test_tracks_status_kpis_and_failures_per_receptor` |
| LA-MON-03 | `test_failure_and_repeated_failure_escalate_to_governance_and_dashboard`, `test_silence_is_reported_as_unknown_or_unverified_never_healthy`, `test_founder_is_reminded_hourly_until_acting`, `test_hold_stops_reminders_until_released`, `test_only_the_founder_closes_or_holds_an_alert`, `test_a_new_occurrence_after_action_is_a_new_alert`, `test_alert_history_is_append_only` |
| LA-MON-04 | `test_dashboard_is_read_only_and_shows_verified_data` (`/health`) |
| LA-MON-05 | `test_monitor_has_no_way_to_act` |
| LA-MON-06, LA-EVD-04 | `test_silence_is_reported_as_unknown_or_unverified_never_healthy`, `test_models_tools_and_core_are_monitored_too` |
| LA-VLT-01 | `test_only_the_founder_uploads_statements`, `test_statement_must_match_its_hash_and_period` |
| LA-VLT-02, LA-DASH-03, LA-IF-06 | `test_no_bank_payment_network_or_model_client_anywhere` |
| LA-VLT-03 | `test_statement_keeps_only_what_reconciliation_needs` |
| LA-FIN-01, LA-FIN-07 | `test_payments_need_an_approval_and_net_profit_uses_verified_revenue_only` |
| LA-FIN-02, LA-IF-05 | `test_revenue_is_only_a_claim_until_a_statement_proves_it`, `test_no_match_stays_not_final`, `test_one_bank_line_proves_one_report` |
| LA-FIN-03 | `test_payments_need_an_approval_and_net_profit_uses_verified_revenue_only` (approval is mandatory; H has no payment capability) |
| LA-FIN-04, LA-FIN-06, LA-EVD-05 | `test_revenue_is_only_a_claim_until_a_statement_proves_it` (stage-8 evidence and verified receipt) |
| LA-FIN-08 | No prepaid-credit or automatic ad-spend path exists anywhere (`test_no_bank_payment_network_or_model_client_anywhere`). The governance control `blanket_automatic_ad_spend_allowance` is `false` in the policy register. |
| LA-DASH-01, LA-DASH-02 | `test_dashboard_is_read_only_and_shows_verified_data` |
| LA-DASH-05 | J's verified data API is built; the screens are deferred to gate 8 as locked. |

The append-only history is tested too (`test_ledger_is_append_only`).

## Founder decisions

- **D-009:** hourly reminders until the Founder acts or holds.
- **D-010:** `repeated_failure_threshold` is 3.

Still open before Step 9 wires E and H:

1. **`stale_after`:** how long a Receptor can go without reporting before it counts as silent. The tests use 10 minutes; that is a test value, not a decision.
2. **Bank statement format.** The prototype format is CSV with `date, direction, amount, currency, reference`. Your bank's real export (column names, debit/credit layout) needs confirming; adapting the parser touches only `parse_statement`.

## Left for later steps

- **Step 9:**
  - Wire F's `Probe` to the Test T0 independent verifier.
  - Send evidence to I's registry and escalations to A and J.
  - Send H's data to J through I (LA-FIN-05, LA-DASH-04).
  - G records payments in H after using an approval.
- **Gate 6:** retention of statement data.

## Contract additions to make before Step 9

`QualityStandard`, `Check`, `HealthView`, `LedgerLine`, `Receipt` and `Payment` should move into `dyson_contracts`.

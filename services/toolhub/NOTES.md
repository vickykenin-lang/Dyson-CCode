# Governed Tool Hub (card G): Step 4 notes

The package is `dyson_toolhub`, and it uses the PostgreSQL schema `toolhub`. It depends only on `dyson_contracts`. It reaches the Governance Core (A) through `GovernancePort`, faked in tests until Step 9.

## How a call is decided

`ToolHub.call(request, credential)` runs all six checks on every call. A check that can't be answered, for example because A is unreachable, **fails**: G fails closed.

| Check | Passes only when |
|---|---|
| `identity_permission` | The credential authenticates a component, it matches `requested_by`, and the tool allows that caller (only the Orchestrator and Hermes). |
| `receptor_scope` | Core tools take no Receptor. Receptor tools need one, and the tool must be in that Receptor's Founder-set permissions. Receptor-support tools also need a different target Receptor and a named allowed operation. |
| `risk_spend_limits` | Risk is never lower than the tool's floor. Any spend must fit the per-action and monthly limits, measured from G's own durable spend record. |
| `approval_status` | Spending money needs a FINANCIAL approval of this exact action (AMD-2). A high-risk action needs an approval too. Each approval is consumed exactly once, just before the tool runs. |
| `stop_state` | A reports the master and Receptor state as RUNNING. |
| `registry` | The tool is in G's catalog, admitted in A's integration registry, and neither the tool nor its connector is killed. |

Every decision, allowed or denied, is written to `toolhub.decisions` and sent to the audit sink. A retry with the same idempotency key never runs the tool twice. "Executed" only means the tool ran. It is never task completion, which comes from QA/QC verification (Steps 5 and 6).

## Requirements owned by this step

| ID | Proven by |
|---|---|
| LA-TOOL-01 | `test_all_six_checks_are_evaluated_every_time`, `test_credential_must_match_the_claimed_caller`, `test_caller_must_be_allowed_for_the_tool`, `test_scope_rules`, `test_money_needs_an_approval_for_the_exact_action_used_once`, `test_spend_limits_use_g_own_spend_record`, `test_callers_cannot_declare_a_risky_tool_safe` |
| LA-TOOL-02 | Adapters exist only inside G's `Catalog`, and `call` is the only way to invoke one. The network rules that stop D and Hermes from reaching tools any other way come with Step 7 (Hermes sandbox) and Step 10 (AWS). |
| LA-TOOL-03 | `test_unknown_or_unadmitted_tools_are_not_callable` |
| LA-TOOL-04 (first milestone) | `test_unauthorized_call_is_denied_and_audited`, `test_audit_outage_keeps_decision_durable` |
| LA-TOOL-06 | `test_kill_switches_and_revival`: a kill is immediate; a revival needs a Founder approval naming that exact revival |
| LA-TOOL-07 | `test_toolhub_imports_no_model_or_network_client` |
| LA-SAF-02 | `test_stop_state_is_checked_on_every_call`, `test_governance_unreachable_means_deny` |
| LA-IF-08 | `test_receptor_support_is_limited_and_governed` |

Also tested:
- A retry never runs twice (`test_retry_with_same_key_never_runs_twice`).
- A failed execution doesn't count as spend.
- After a restart, idempotency, the monthly spend total and the append-only tables all hold (`test_durable_idempotency_spend_and_append_only`).
- The HTTP API: credential header required, and only the Governance Core can throw kill switches (`test_api`).

## Left for later steps

- **Step 9:**
  - Connect `GovernancePort` to the real Governance Core.
  - Route work to Receptors, Hermes, QA/QC and Financial Control (LA-TOOL-05).
  - Forward `audit_backlog` from G's decision log to the audit log in I.
  - Replace `StaticTokens` with real service identities.
- **Step 7:** Hermes's network reaches only C and G.
- **Gate 4:** the risk-classification rules. Today each tool's `min_risk` sets its floor.

## Contract additions to make before Step 9

- **`external_action_digest`:** G and A each compute the same canonical digest for approvals. It should move into `dyson_contracts`, with a shared test vector.
- **`ToolResult` and `ToolSpec`:** these should move into the contracts too.

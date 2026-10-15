# Governance Core (card A): Step 3 notes

The package is `dyson_governance`, and it uses the PostgreSQL schema `governance`. It depends only on `dyson_contracts` and `policy/`.

## How it works

Every change in A is an event in one append-only log (`governance.events`). Current state is rebuilt by replaying the log, which is how STOP survives a restart. Each change is validated against the current state while holding an exclusive lock, so two running instances can't make conflicting decisions.

Every consequential change follows the same path:

1. **Proposal.** A component proposes it. The proposal carries a sha256 digest of the exact payload.
2. **Decision.** The Founder approves or rejects it on Direct Founder Controls. A checks the channel proof, the digest and the expiry.
3. **Action.** A carries out *internal* proposals itself:
   - limits
   - operational parameters
   - integration admission
   - Receptor activation, archive and replacement
   - resume
   - recovery authorization
   - compliance clearance

   For *external* proposals (financial and other actions, AMD amendments), A only records the approval. The component that acts uses it exactly once.

STOP and PAUSE skip this path. They apply immediately, need no approval and involve no model.

## Requirements owned by this step

| ID | How it is met | Proven by |
|---|---|---|
| LA-GOV-01 | `PolicyEngine` loads `policy/amd_register.yaml` with each rule's version and effective date. It refuses to load if AMD-1..13 no longer match the lock. | `test_every_rule_has_version_and_effective_date`, `test_tampered_register_is_refused` |
| LA-GOV-02 | Proposals are created, tracked and closed. Decisions are accepted only with a valid channel proof, and the contract refuses any decider other than the Founder. | `test_decision_without_valid_channel_proof_is_refused`, `test_models_agents_and_receptors_cannot_approve`, `test_decision_binds_to_exact_action_and_expiry`, `test_rejected_stays_blocked` |
| LA-GOV-03, LA-SAF-01 | STOP / PAUSE is deterministic code that imports no model or network client. The new state is pushed to every control listener (G, Hermes and the Receptor lanes once Step 9 wires them). G reads `effective_mode` on every call. | `test_master_stop_reaches_everything_without_any_model`, `test_governance_imports_no_model_or_network_client`, `test_listener_failure_does_not_block_stop` |
| LA-GOV-04, LA-IF-09 | Per-Receptor permissions, authority and spending limits change only through an approved proposal. Recommendations are separate records and change nothing. | `test_recommendation_changes_nothing_until_founder_approves`, `test_spend_checks_against_limits` |
| LA-GOV-05 | A financial action is an external proposal. It stays blocked until approved, binds to the exact digest, and can be used once. | `test_financial_action_blocked_until_founder_approves_then_usable_once` |
| LA-GOV-06, LA-SEC-04 | Integration gate: proposed → security-checked → admitted. High-risk items need Founder approval. Blocking, isolating or revoking is immediate. | `test_nothing_is_admitted_before_a_security_check`, `test_failed_check_blocks`, `test_high_risk_needs_founder_approval`, `test_suspect_integration_is_isolated_at_once` |
| LA-GOV-07 | Compliance items per Receptor are routed to the Founder. If legal review is required, a person must record it first; the contract refuses AI reviewers. | `test_legal_review_must_be_a_person`, `test_compliance_goes_to_founder_and_needs_review_first` |
| LA-GOV-08, LA-SAF-04 | A breach stops the scope and marks it. Nothing resumes automatically. A resume needs Founder approval of a proposal that names the exact stop it lifts. | `test_no_automatic_resume_after_breach`, `test_resume_only_through_an_approval_for_the_current_stop` |
| LA-GOV-09, LA-SAF-03 | Each recovery attempt is recorded. Attempts are capped by `recovery_attempt_limit`; past the cap the incident escalates, and only the Founder can authorize more attempts. | `test_recovery_is_bounded_recorded_and_escalated` |
| LA-GOV-10 | Safe Continuity mode is reserved but never on. The automatic trigger raises `GateClosed`. | `test_safe_continuity_trigger_stays_blocked` |
| LA-AMD-01 | No component can approve a rule change. Approval needs the Founder's channel proof. | `test_rule_change_cannot_be_self_approved_and_is_never_applied_at_runtime` |
| LA-AMD-02 | Operational parameters come from a fixed catalog and are validated and applied by A. AMD amendments are recorded but never applied at runtime; they go through the amendment workflow. | `test_parameters_and_amendments_take_different_paths` |
| LA-IF-10 | Archive or replacement needs the Receptor paused or stopped plus a Founder decision. Records are never deleted. | `test_archive_needs_pause_and_founder_decision_and_keeps_records`, `test_replacement_is_the_founders_decision` |
| LA-IF-11 | Activation needs its own approval plus all of: Founder-set limits, every tool admitted through the gate, compliance cleared, and acceptance evidence. | `test_activation_needs_its_own_decision_budget_tools_and_evidence` |

The following are also tested:
- STOP survives a restart.
- The event log is append-only for the app role and for a superuser.
- Two instances see each other's changes.
- The audit is never blocked by an unreachable I.
- The HTTP API refuses unsigned or non-Founder commands.

## `recovery_attempt_limit` = 3 (Founder decision D-008)

The PRD says recovery is bounded but gives no number. You set it to **3** (D-008). The value lives in `policy/parameters.yaml`, which cites D-008. `load_initial_parameters` refuses any value that doesn't cite a recorded Founder decision. Each incident gets 3 recorded attempts, then escalates to you.

To change the value later, approve an operational-parameter proposal. The approved value replaces the file value (`test_founder_decided_recovery_limit_is_three_until_changed`).

## Left for later steps

- **Step 8:** the real Direct Founder Controls replaces `HmacChannel` with the step-up method chosen at gate 3. `ChannelVerifier` is the interface.
- **Step 9:**
  - Wire the control listeners to G, Hermes and the Receptor lanes.
  - Forward the event log to the audit log in I. `audit_backlog` covers I being down; the event log stays the durable source.
  - Bind HTTP callers to service identities.
  - Ask I to archive a Receptor's records when it is archived.
- **Gate 4:** how a STOP treats operations already in progress, and how risk is classified.
- **Gate 7:** AMD-12 presence detection.

## Contract additions to make before Step 9

`ReceptorLimits`, `ProposalKind` and the proposal and decision request bodies used by the API should move into `dyson_contracts`.

# Contracts

`contracts/` (package `dyson_contracts`) holds every message and state that crosses a component boundary. Steps 2 to 8 build components that depend **only** on these contracts, never on each other. That is what lets each step finish in one go without clashing with another.

## What is in v1.1.0

| Module | Holds | PRD source |
|---|---|---|
| `common` | `Component`, `RiskLevel`, `Money`, ID and timestamp types | §4, §5 |
| `tasks` | `TaskState`, `TaskTrigger`, `TRANSITIONS`, `next_state`, `Task`, `TaskTransition` | §9, D-001 to D-003 |
| `approvals` | `ApprovalRequest`, `ApprovalDecision` (Founder and Direct Founder Controls only) | LA-GOV-02, LA-DFC |
| `control` | `ControlCommand` (STOP / PAUSE / RESUME), `ControlState` | AMD-5 |
| `toolcalls` | `ToolCallRequest`, the six `CheckName`s, `ToolCallDecision` | LA-TOOL-01 |
| `evidence` | The eight `EvidenceStage`s, `EvidenceRecord` | AMD-3 |
| `audit` | `AuditEvent` | LA-MEM-07 |
| `lanes` | The five lanes and their messages, `LANE_OWNER` | §8 |
| `finance` | `RevenueReport`, `BankStatementUpload`, `ReconciliationResult` | LA-VLT, LA-FIN |
| `receptor` | `ReceptorManifest` | §8 minimum obligations |
| `interface` | `FounderMessage`, `CommandAcknowledgment`, `TaskStatusUpdate` | LA-APP |
| `integrations` | `IntegrationRecord` | AMD-13 |
| `digests` (v1.1.0) | `canonical_digest`, `external_action_digest`, `tool_action_payload`, `signing_bytes`: the one definition of what an approval binds to and what a Founder-channel proof signs | LA-DFC-05, LA-GOV-02 |

## Rules that live in the contracts themselves

These are enforced by validation, so no component can produce a message that breaks them:

- Only the Founder, on Direct Founder Controls, can make an approval decision. A decision binds to the exact action digest and expires with its request.
- Only the Founder can RESUME, and every RESUME carries an authorization.
- A tool call is allowed only when all six checks are present and passed.
- Only the Orchestrator or Hermes can request a tool call.
- Evidence stages 6 to 8 can only be passed by an independent verifier: QA/QC (F) or Financial Control (H).
- `completed-verified` must cite evidence. An acknowledgment can only be `accepted` or `approval-needed`.
- Revenue is `final` exactly when it matches a Founder-uploaded statement.
- A high-risk integration is admitted only with a Founder approval.

## Task state machine

The names come from closure §9 (D-001), plus `rejected` (D-003) and `closed` for housekeeping.

- PAUSE moves any active task to `held` (D-002).
- STOP moves any active task to `stopped`.
- **RESUME returns the task to the state it was in when STOP or PAUSE hit it (D-007).** For example, a task paused while waiting for approval goes back to `approval-needed`, not straight to `running`. This keeps a resume from skipping a pending approval. The PRD's `stopped → running` row (Derived) is the `running` case of this rule.
- `rejected` can only move to `closed`. A rejected task never restarts.

## Changing a contract

Contracts are frozen inside Steps 2 to 8. If a step finds it needs a change:

1. Record the need in that step's notes. Do not edit `contracts/` inside the step.
2. Raise a separate contract-change PR that bumps `CONTRACTS_VERSION` (minor for an additive change, major for a breaking one) and updates the tests.
3. Apply all such changes before Step 9 connects the components.

## Change log

- **1.1.0 (before Step 9, additive).** Added `digests`. A, G, D, C and Direct Founder Controls had identical private copies of these functions; they now import the shared ones, so approval digests and channel proofs cannot drift apart. Existing digests are unchanged (pinned by `contracts/tests/test_digests.py`). The other shapes the step notes listed (model-call shapes, B's reply, D's plan) stay inside their components: Step 9's adapters translate them, and none crosses a component boundary unconverted.

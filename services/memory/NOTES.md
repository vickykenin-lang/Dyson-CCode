# Memory & Evidence Layer (card I): Step 2 notes

The package is `dyson_memory`, and it uses the PostgreSQL schema `memory`. It depends only on `dyson_contracts`.

## Requirements owned by this step

| ID | Where it is met | Proven by |
|---|---|---|
| LA-G-03 | Durable archive, memory, register, evidence and audit, all append-only | `test_transcript_survives_*`, `test_backup_and_restore` |
| LA-MEM-01 | `memory.threads`, `memory.messages` (dated, thread IDs, participants, attachments, raw-transcript reference, full-text search) | `test_voice_and_text_share_one_history`, `test_search_cites_records_and_flags_uncertain_speech` |
| LA-MEM-02 | `memory.memory_items`: every item must cite at least one source; `recall` returns only current items, with their sources | `test_recall_with_provenance_and_uncertainty`, `test_superseded_memory_is_not_recalled` |
| LA-MEM-03 | `memory.register_entries`: status, exact text, version, decision date, evidence, Founder approval reference. Locked and approved entries must carry an approval. | `test_seed_loads_all_rules_and_decisions_once`, `test_locked_entry_needs_founder_approval` |
| LA-MEM-04, LA-IF-07 | Row-level security on every Receptor-scoped table; credentials are namespaced by scope | `test_receptors_are_isolated`, `test_receptor_evidence_is_isolated`, `test_secret_store_scopes_and_file_permissions` |
| LA-MEM-06, LA-SEC-01 | `SecretStore` interface, `LocalSecretStore`, and `SecretGuard`, which refuses any write that contains a known secret or a common key format | `test_canary_credential_never_reaches_memory` (checks every row of every table) |
| LA-MEM-07 | `memory.audit_log`: insert-only grants, append-only triggers, and a hash chain computed by the database | `test_app_role_cannot_alter_audit`, `test_owner_cannot_alter_audit_either`, `test_tampering_by_superuser_is_detected`, `test_caller_cannot_supply_its_own_hash` |
| LA-MEM-08 | No API path grants, approves or checks permission | `test_no_endpoint_grants_or_approves` |
| LA-MEM-09 | Search and recall carry citations; uncertain speech is flagged and carried into memories made from it; "locked" is derived from the latest register entry only | `test_search_cites_*`, `test_recall_with_provenance_*`, `test_unlocked_rule_is_never_presented_as_locked` |
| LA-AMD-04 | Register history is append-only; the authoritative status is the latest entry | `test_register_history_is_immutable_and_status_is_latest` |
| LA-EVD-03 | `memory.evidence`: the 8 stages kept separate, with environment, scope, time and expiry. Failed and negative evidence is kept. Stages 6 to 8 can be passed only by F or H, enforced in SQL too. | `test_stages_are_separate_and_failures_are_kept`, `test_expired_evidence_is_flagged`, `test_live_stages_cannot_be_self_certified_even_in_sql` |
| LA-PRIV-03 | `messages.source` can only be `dyson`. Importing ChatGPT history needs a schema change and its own approval. | `test_no_automatic_chatgpt_import` |

## Database roles

- **Owner:** runs migrations and owns the schema. Its credentials are never given to any AI component.
- **App:** what the running service uses. It can only `SELECT` and `INSERT`. Row-level security is forced on it, and the append-only triggers apply to it.
- **Backup:** read-only, with `BYPASSRLS`, used for `pg_dump` only.
- **Restore:** an operator action, run as a superuser.

Even a superuser who disables the triggers and edits the audit log is caught: `verify_audit_chain` reports the first broken link.

## Scope

Each transaction sets `dyson.scope`:
- `core` means Layer A components.
- `T0`, `R11` and so on mean one Receptor.
- No scope sees nothing.

**Open item for Step 9:** today the HTTP API takes the scope from the `X-Dyson-Scope` header and trusts the caller. Step 9 must bind scope to an authenticated service identity, for example one database role per Receptor. Until then, this service must only be reachable from inside Layer A.

## Deferred to later steps

- **Step 10:** encrypted S3 backups the runtime cannot delete, the AWS secret store, and attachment bytes in S3 (LA-MEM-05, LA-REL-03, LA-DEP-04).
- **Step 9:** proof that switching the model or voice provider leaves memory unchanged (LA-MEM-10).
- **Gate 6:** retention and deletion rules. Today everything is kept, nothing is deleted.

## Contract additions to make before Step 9 (per docs/CONTRACTS.md)

Other components will send or read these over HTTP, so they should move from `dyson_memory.models` into `dyson_contracts`:
- `ArchivedMessage`, `Attachment`, `Citation` and `MessageHit`
- `MemoryItem` and `MemoryKind`
- `RegisterEntry`, `RegisterStatus` and `RegisterView`
- `StageStatus`

## Running the tests

The tests need PostgreSQL 16. Set `DYSON_TEST_PG_ADMIN` to a superuser DSN; the default is `postgresql://postgres@127.0.0.1:5433/postgres`. `pg_dump` and `pg_restore` must be on PATH, or set `DYSON_PG_BIN`.

The real server-restart test runs only when `DYSON_TEST_RESTART_CMD` holds a command that restarts the server. CI cannot restart its database container, so that test is skipped there.

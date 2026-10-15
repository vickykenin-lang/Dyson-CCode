# Founder Interface (App, Entry Gateway, Direct Founder Controls): Step 8 notes

Step 8 builds three separate packages. Each depends only on `dyson_contracts` and needs no database. Their outbound ports are faked in tests until Step 9.

| Package | Path | Talks to |
|---|---|---|
| `dyson_founder_app` | `apps/founder-app/` | the Entry Gateway only |
| `dyson_gateway` | `services/gateway/` | B (conversation), and D and I read-only (task status, thread history) |
| `dyson_founder_controls` | `services/founder-controls/` | the Governance Core (A) only |

The app's tests run through the real Gateway, with B, D and I faked behind it.

## Entry Gateway (`services/gateway/`)

- **Login.** The Founder logs in for every session and gets a random session token. The Gateway keeps only its sha256. The login method is pluggable, and gate 3 picks the real one. The development stand-in is a password stored as an scrypt hash.
- **Sessions.** They end on logout, after a maximum age, or after an idle timeout. They are held in memory, so a Gateway restart means logging in again; no task or history is lost, because those live in D and I.
- **Rate limiting.** Every request is limited per client address, and per session once logged in. Repeated failed logins lock that address out for a while, even for the right password. Every refusal is audited.
- **Routing.** Logged-in requests go to B and nowhere else. There is no route to Hermes, and no approve, reject, STOP, PAUSE or RESUME endpoint.
- **Honest acknowledgment.** `POST /messages` answers as soon as B has accepted the message. The acknowledgment uses the contract that allows only `accepted` or `approval-needed`. A backend that claims completion gets no acknowledgment at all.
- **Live status.** `GET /tasks/{id}/events` streams the task's state until it settles. `GET /threads/{id}` and `/threads/{id}/tasks` let a reconnecting app recover everything.

## Direct Founder Controls (`services/founder-controls/`)

- **Its own authentication.** Every action needs a fresh confirmation for exactly that action:
  - A single-use challenge is issued for one purpose, such as "approve approval X with digest Y" or "STOP master".
  - The Founder's device answers it.
  - A confirmation for anything else, an expired or reused challenge, another device, or the Gateway's session token is refused.
  - The real method (passkey, hardware key or other) is chosen at gate 3. The stand-in is a device key held only on the Founder's device.
- **Approve / Reject.** The decision binds to the exact action digest the Founder was shown. If A now holds a different digest, nothing is decided. The decision carries the time, the approver (Founder), the channel and the confirmation method. It is signed for A with the channel key A already verifies (Step 3) and recorded in the audit.
- **STOP / PAUSE.** These go straight to A, signed. No app, Gateway, B or model is involved, so they work when all of those are down.
- **RESUME.** It is never a direct command. A resume request becomes an approval, which the Founder then decides like any other (D-007, Step 3).
- **`dyson-control` client.** A command-line client for STOP, PAUSE, listing pending approvals, approve, reject and resume requests, needing nothing but this service. It reads the device key from a file and never prints or sends it. Approve and reject show the summary and digest and ask for a typed confirmation.

## Founder app (`apps/founder-app/`)

- **Format.** Web first, served from Python as plain HTML with a little JavaScript, branded Dyson. Android is the later target.
- **What it holds.** It talks only to the Gateway. It stores only two HttpOnly, SameSite=strict cookies: the session and the current thread. It has no approve, reject, STOP or PAUSE control; the page points to Direct Founder Controls.
- **Acknowledgment and status.** After a command it shows "Accepted, not done yet" or "Waiting for your approval on Direct Founder Controls", then updates each open task every 2 seconds. A task is shown as done only when it is `completed-verified` with cited evidence.
- **Reconnecting.** After a dropped call, an app restart or a new session, the page rebuilds the thread and its tasks from the Gateway.
- **Voice slot.** The vendor is picked at gate 5. Voice and text go into the same thread. A transcript the vendor is unsure of is shown back as "I may have misheard ... Nothing was sent", and is sent only after the Founder confirms or corrects it. Until a vendor is connected, voice says it is not available.

## Requirements owned by this step

| ID | Proven by |
|---|---|
| LA-G-08 | `test_founder_talks_only_to_dyson` (one page for conversation and tasks; dashboard screens wait for gate 8) |
| LA-G-09, LA-PERF-01 | `test_acknowledgment_is_honest_and_immediate`, `test_acknowledgment_is_immediate_and_never_completion`, `test_status_streams_until_verified` |
| LA-APP-01 | `test_branded_dyson_text_first_page`, `test_voice_is_a_slot_until_gate_5` (Android is later) |
| LA-APP-03 | `test_voice_and_text_share_one_thread` |
| LA-APP-04 | `test_acknowledgment_is_honest_and_immediate`, `test_live_status_says_done_only_with_verified_evidence`, `test_status_label_never_calls_anything_else_done`, `test_acknowledgment_is_immediate_and_never_completion` |
| LA-APP-05 | `test_reconnect_restores_tasks_and_context`, `test_reconnect_gets_tasks_and_context_back` |
| LA-APP-06 | `test_founder_only_through_the_gateway`, `test_session_cookie_is_protected`, `test_app_holds_no_authority_and_no_records` |
| LA-APP-07 | `test_uncertain_speech_is_confirmed_never_sent_silently`, `test_uncertain_speech_is_passed_on_flagged` |
| LA-APP-09 | `test_app_holds_no_authority_and_no_records` |
| LA-GW-01 | `test_every_session_is_authenticated`, `test_sessions_expire_and_end`, `test_session_token_is_not_stored_in_clear` |
| LA-GW-02 | `test_all_traffic_is_rate_limited`, `test_failed_logins_lock_the_address_out` |
| LA-GW-03 | `test_authenticated_requests_go_to_b_only` |
| LA-DFC-01 | `test_stop_and_pause_work_with_app_gateway_and_models_down`, `test_gateway_has_no_approval_or_control_endpoint`, `test_app_holds_no_authority_and_no_records`, `test_resume_is_requested_then_approved_never_commanded` |
| LA-DFC-02 | `test_controls_reach_only_the_governance_core` |
| LA-DFC-03 | `test_every_action_needs_its_own_fresh_confirmation`, `test_another_device_cannot_confirm` |
| LA-DFC-04 | `test_stop_and_pause_work_with_app_gateway_and_models_down`, `test_the_cli_stops_everything` |
| LA-DFC-05 | `test_approval_binds_to_the_exact_action_shown`, `test_a_changed_action_cannot_be_approved`, `test_reject_is_recorded_too` |
| LA-HER-04 | `test_founder_talks_only_to_dyson`, `test_authenticated_requests_go_to_b_only` |
| LA-SEC-03 | `test_every_session_is_authenticated`, `test_every_action_needs_its_own_fresh_confirmation` |

## Settings decided later

None of these numbers come from the PRD, so none were invented. Each is a required constructor setting, and the tests use made-up values.

- **Gate 3:** the login method, the step-up method, signed-approval semantics, how long a challenge lasts, and approval expiry.
- **Gate 2 / Step 10:** session maximum age and idle timeout, requests per minute and burst, and the number of failed logins before lockout and its length.
- **Gate 5:** the voice vendor and the Hindi / Hinglish uncertainty thresholds.

## Left for later steps

- **Step 9:**
  - Connect the Gateway to B (`ConversationEngine.handle`), D (task status) and I (thread history).
  - Connect Direct Founder Controls to A: A needs a "pending approvals" read and a `propose_resume` endpoint over HTTP.
  - Run the full chain locally.
- **Step 10:** TLS, the real login and step-up methods after gate 3, the voice vendor after gate 5, and Android.

## Contract additions to make before Step 9

- B's reply (`ConversationReply` here, `Reply` in Step 7) and `ThreadMessage` should become one contract.
- `signing_bytes` is copied from A's `channel.py` and should move into `dyson_contracts`.

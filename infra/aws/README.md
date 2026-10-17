# AWS resources created for Step 10

Each entry is created by the `dyson-deployer` identity and checked by reading it back.

| Date | Resource | Definition |
|---|---|---|
| 16 Oct 2026 | Budget `dyson-credits-100`: 100 USD from 1 Oct 2026 to 13 Apr 2027, credits not netted off, email alerts when actual spend passes 25, 50, 75, 90 and 95 USD | `budget.json`, `budget-notifications.json` |
| 16 Oct 2026 | IAM role `dyson-server`, trusted by Systems Manager, with `AmazonSSMManagedInstanceCore` | D-018 |
| 17 Oct 2026 | Inline policy `dyson-server-policy` on `dyson-server`: read releases, write backups only, read `/dyson/*` parameters, call Bedrock in Sydney; never delete | `../iam/dyson-server-policy.json` |
| 17 Oct 2026 | Bucket `dyson-releases-501430758577` (public access blocked) | release bundles |
| 17 Oct 2026 | Bucket `dyson-backups-501430758577`: versioning, Object Lock GOVERNANCE 35 days, AES256, public access blocked | D-013 |
| 17 Oct 2026 | Lightsail `dyson-server`: `medium_3_2`, Ubuntu 24.04, ap-southeast-2a, all public ports closed, registered with Systems Manager by a one-use activation | D-018 |
| 17 Oct 2026 | SecureString parameters `/dyson/postgres_password`, `/dyson/db_password`, `/dyson/founder_password`, generated without being shown; the Founder reads the password in the console | D-013 |

Releases are deployed with `../deploy/deploy.sh` through Systems Manager; the one-use activation was deleted after the server registered.

## Milestones

- 17 Oct 2026: `https://dyson.designinfra.in` served through a Cloudflare Tunnel (no open ports); the Founder logged in and the command "Tally 1 and 2 on T0" reached `completed-verified` on AWS (task `c917d52a-89b3-4f50-8d37-bf4f574920e0`, checked in `orchestrator.tasks`).
- 17 Oct 2026: `https://control.designinfra.in` reaches Direct Founder Controls through the same tunnel.
- 17 Oct 2026: nightly backup timer installed (21:00 UTC). First backup `db/dyson-2026-10-17T113156Z.dump` (267,765 bytes, AES256) uploaded; a restore into a throwaway Postgres brought back 1 of 1 tasks and 2 evidence records (`RESTORE_OK`). The bucket's default Object Lock (GOVERNANCE, 35 days) applies to new objects; reading an object's retention needs `s3:GetObjectRetention`, which no Dyson identity has, so it was not read back.
- 17 Oct 2026: hourly spend guard installed (`infra/deploy/spend-guard.sh`). It reads the budget's actual spend (0.01 USD at install) and at 95 USD stops Layer A and the tunnel and keeps Postgres and the backup timer running. Tested: a dry run with the line at 0 USD reported it would stop both; the live run at 95 USD did nothing. The server itself keeps running (and billing) so backups continue.
- 17 Oct 2026: the Founder's device key was copied from the server's secret store into the SecureString parameter `/dyson/founder_device_key` without being printed; the one-time `ssm:PutParameter` permission used for it was removed from the server role afterwards.
- 17 Oct 2026: passkey step-up (gate 3, D-014) deployed as `layer-a-4851f84` (CI green). The Founder registered the first passkey, "Founder phone", at 13:24 UTC; the server holds 1 passkey in `/data/passkeys.json` (mode 600). From now on the device key confirms nothing.
- 17 Oct 2026: approval expiry (24 hours) and hourly reminders (D-014) deployed as `layer-a-e7f9c7f` (CI green). Reminders go to the Founder inbox and I's audit log; they are not yet pushed to the Founder's phone or app.

- 17 Oct 2026: DeepSeek v3.2 on Bedrock (Sydney) is C's model for `conversation.interpret` (D-019), deployed as `layer-a-8f73f30`. The Founder approved the three changes (model with its prices, acceptance bar 90% / 5,000 ms, budget 0.16 USD a day) on Direct Founder Controls; the route is now `['deepseek.v3.2']`. The stand-in's real score (18/26) is recorded, so it no longer passes the bar. Checked through B on the server: "T0 par 7 aur 8 jod do" became `t0.tally` with numbers [7, 8] on T0 and reached `completed-verified` (task `f81875a7-dc8b-4b91-9934-b0ddf2d2b2ab`); "Aap kaun ho aur kya kar sakte ho?" got an answer in Hinglish. One call cost about 0.00045 USD.

- 17 Oct 2026: Step 10's done-when met: evidence on AWS reaches AMD-3 stages 5 to 7 (`layer-a-5d4186c`). Stage 5, production deployed, is recorded once per release by Core R&D (`release:layer-a-5d4186c`, environment `aws-ap-southeast-2`). For "Tally 12, 30 and 58 on T0" (task `59b0313f-aa32-4512-9878-122cc5e50cfa`, `completed-verified`), F recorded stage 6, live request verified, and stage 7, real output verified, both passed for `STD-T0-TALLY`. Earlier stage-7 records said `local` because F did not yet know where it ran. Voice is deferred (D-016); production launch still needs gate 9.

Still open: a backup passkey (the Founder will add it later), showing reminders to the Founder, and deleting the deployer's access key (`../iam/README.md`).


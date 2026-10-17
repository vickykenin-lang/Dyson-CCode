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

Still open: the Founder's device key for `dyson-control`, and a real model behind C.


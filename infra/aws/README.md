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

Still open: `control.designinfra.in` route, nightly backups to the locked bucket with a restore test, the automatic 95 USD stop, and a real model behind C.

The 95 USD stop (everything except backups) is not automatic yet; it is wired once the server exists.

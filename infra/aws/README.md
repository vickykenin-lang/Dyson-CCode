# AWS resources created for Step 10

Each entry is created by the `dyson-deployer` identity and checked by reading it back.

| Date | Resource | Definition |
|---|---|---|
| 16 Oct 2026 | Budget `dyson-credits-100`: 100 USD from 1 Oct 2026 to 13 Apr 2027, credits not netted off, email alerts when actual spend passes 25, 50, 75, 90 and 95 USD | `budget.json`, `budget-notifications.json` |
| 16 Oct 2026 | IAM role `dyson-server`, trusted by Systems Manager, with `AmazonSSMManagedInstanceCore` | D-018 |

The 95 USD stop (everything except backups) is not automatic yet; it is wired once the server exists.

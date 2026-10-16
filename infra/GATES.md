# Step 10: Founder gates to close first

Step 10 connects Layer A to AWS, real model APIs and (later) a voice vendor. The PRD (§14, Closure §11) makes each gate below a Founder decision that must close before its part starts. Nothing in `infra/` provisions anything until they are recorded in `policy/decisions.yaml`.

Each gate has a **recommendation**. It is a proposal only, not a decision, and no value in it is used until you confirm or change it.

## Gate 1: AWS account (decided: D-012)

- **Account:** a fresh account named Dyson Sphere, on the AWS Free plan.
- **Region:** `ap-southeast-2` (Sydney).
- **Spending cap:** the plan's 100.00 USD of credits, available for 180 days, until 12 Apr 2027. AWS access stops when either runs out.
- **Later:** you top up after the free period, expecting revenue from about month six.

What this means for Step 10:
- **Budget:** a budget of 100 USD over the period, with alerts as it is used.
- **Hard limit:** no resource whose running cost could pass the credits in the period.
- **No reserved or prepaid purchases.**

## Gate 2: compute, network, database, backups, IAM, secrets

Recommendation, revised to fit 100 USD over 180 days (D-012):

- **Compute.** One small fixed-price instance (Lightsail or a small EC2 instance, whichever the current price page shows is cheapest for about 2 vCPU and 2 to 4 GB) running the same containers as `docker-compose.yml`. That includes Postgres in its own container on an encrypted disk: a managed database (RDS) would use most of the credits on its own.
  - Direct Founder Controls runs as its own container with its own key.
  - Hermes runs on an internal-only network (LA-DEP-01..03).
  - Prices are checked on your account before anything is created (LA-COST-04).
- **Network.**
  - Only the Gateway and Direct Founder Controls are public, behind TLS on two separate subnames of a domain you own (LA-GW-04, LA-GW-05).
  - Everything else is reachable only inside the instance.
- **Backups.** Nightly encrypted database dumps to an S3 bucket with versioning and Object Lock, under a role the running application cannot use to delete them (LA-DEP-04). A restore is tested before launch (LA-REL-03).
- **IAM.** One least-privilege role for the instance, no long-lived keys on the server, and a monthly usage review (LA-SEC-02).
- **Secrets.** Kept encrypted on the instance (SSM Parameter Store, standard tier), behind the existing secret-store interface.
- **Scaling.** Moving to managed services and separate hosts waits for the top-up and measured need (LA-COST-03).
- **Deployment.** Infrastructure as code, deployed from this private repository. Each release keeps a rollback image (LA-DEP-05).

You provide: the domain name to use.

## Gate 3: step-up authentication and signed approvals

Recommendation:
- **Method.** Passkeys (WebAuthn) on your phone for every approval, rejection, STOP, PAUSE and resume request on Direct Founder Controls. A second passkey (or hardware key) is kept as backup.
- **Approval expiry.** An unanswered approval expires after a time you choose; expired requests must be asked again.
- **Audit.** Every decision is recorded with time, device and the exact action digest. This already exists in Steps 3 and 8.

You provide: the approval expiry time.

## Gate 4: STOP for actions already running; what counts as high risk

Recommendation:
- **STOP.** STOP blocks every new tool call at once, as it does now.
  - A call already sent to a Receptor finishes, but its result is held for your review and never continues on its own.
  - Nothing is rolled back automatically.
- **High risk** (always needs your approval):
  - anything that spends money;
  - anything that publishes outside Dyson;
  - anything that contacts a customer;
  - deleting data;
  - changing a Receptor's limits.
- **Restoration.** Only through a resume request that you approve (already built).

## Gate 5: voice vendor (voice only; does not block the text deployment)

Recommendation: deploy text first.
- **Benchmark.** Run the voice benchmark (GPT Realtime, Gemini Live, and a chained speech-to-text → model → text-to-speech option) on your real Hindi, English and Hinglish phrases (LA-APP-08).
- **Choice.** Pick the cheapest one that meets the latency and quality bars you set (LA-PERF-02).

You provide (when we reach voice):
- acceptable spoken-response latency;
- the quality bar.

## Gate 6: data retention, classification, isolation, redaction (before real data)

Recommendation:
- **Kept permanently:**
  - conversations, decisions and evidence (they are Dyson's permanent memory);
  - deletion only on your explicit request.
- **Voice audio:** not stored; transcripts only.
- **Bank statements:** only the parsed fields H needs (already the case); the uploaded file is not kept.
- **Classification:** personal and financial data are "restricted". They never go to an external model, which receives only redacted text.
- **Isolation:** each Receptor sees only its own data (already enforced in memory).
- **Until gate 6 closes:** only the synthetic Test T0 runs on AWS.

## What Step 10 then builds, in order

1. Budgets, alarms and IAM, before any paid resource (LA-COST-01).
2. Network, database and the encrypted backup bucket.
3. Secrets Manager behind the existing secret-store interface.
4. The Layer A containers.
5. A real model adapter behind C, chosen by benchmark against the acceptance bars you set (AMD-4).
6. Evidence at AMD-3 stages 5 to 7 on Test T0.

Production launch still needs gate 9.

## Credentials

AWS access must be set up by you, for example GitHub's OIDC link to an AWS role, or keys entered into the environment's secret settings. Keys are never pasted into chat, and I never handle or reveal them.

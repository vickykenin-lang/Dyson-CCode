# IAM usage review (LA-SEC-02)

Once a month, and whenever an identity is added or removed. The Founder does the steps that need
IAM read access (no Dyson identity has it); the drift check runs from the deployment session.

## Steps

1. **Drift check** (deployment session): `bash tools/iam_review.sh`. It compares the live
   `dyson-server` role policy with `infra/iam/dyson-server-policy.json` and lists the role's
   attached policies and last use.
2. **Users and keys** (Founder, IAM console → Users): only `dyson-deployer` should exist besides
   the root login. Under *Security credentials*, note each access key's *Last used*. A key unused
   for 30 days, or any key once deployments stop, is deleted.
3. **Last accessed** (Founder, IAM console → Users → dyson-deployer → *Last Accessed* tab, and
   Roles → dyson-server → *Last Accessed*): a service not used in 90 days is a candidate to remove
   from the policy. Write it below; the policy change goes through the repo.
4. Record the review below.

## Log

| Date | By | Result |
|---|---|---|
| 18 Oct 2026 | Deployment session | `dyson-server` inline policy matches the repo; attached `AmazonSSMManagedInstanceCore` only; role last used 18 Oct 2026 in ap-southeast-2. The one-time `ssm:PutParameter` is not in it. Users and keys not reviewed: needs the Founder (step 2). `dyson-deployer` key still active, to delete when deployments stop. |

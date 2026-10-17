# Access for the deployment session

The deployment session (Claude Code in the cloud environment) needs its own AWS identity. You
create it; the keys never go into chat or into this repository.

1. In IAM, create a user named `dyson-deployer` with no console access.
2. Attach `dyson-deployer-policy.json` (this folder) as an inline policy. It allows only what
   Step 10 needs, only in ap-southeast-2. It denies deleting backups, changing billing, and
   creating users or keys.
3. Also attach `dyson-deployer-ssm-policy.json` as a customer managed policy (inline policies share a 2048-character limit per user), named
   `dyson-deployer-ssm-policy`. It lets the session register the server with Systems Manager,
   run deployment commands on it and ship release bundles to `dyson-*` buckets (D-018).
4. Create one access key for that user.
5. In the cloud environment's settings (environment menu in the session title bar → Edit),
   add three environment variables:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_DEFAULT_REGION` = `ap-southeast-2`

   If network access is Limited, add `amazonaws.com` to Allowed domains.
6. Start a new session. The first thing it runs is `aws sts get-caller-identity`, a read-only
   check that the identity is `dyson-deployer`.

Delete or rotate the key once Step 10 is done.

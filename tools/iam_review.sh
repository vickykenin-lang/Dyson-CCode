#!/bin/bash
# Monthly IAM drift check (infra/iam/REVIEW.md, LA-SEC-02). Read-only.
set -euo pipefail
cd "$(dirname "$0")/.."
LIVE=$(mktemp); trap 'rm -f "$LIVE"' EXIT
aws iam get-role-policy --role-name dyson-server --policy-name dyson-server-policy \
  --query PolicyDocument --output json > "$LIVE"
python3 - "$LIVE" <<'PY'
import json, sys
norm = lambda p: json.dumps(json.load(open(p)), sort_keys=True)
same = norm(sys.argv[1]) == norm("infra/iam/dyson-server-policy.json")
print("dyson-server-policy matches the repo:", same)
sys.exit(0 if same else 1)
PY
aws iam list-attached-role-policies --role-name dyson-server --query 'AttachedPolicies[].PolicyName' --output text
aws iam get-role --role-name dyson-server --query 'Role.RoleLastUsed' --output text

#!/bin/bash
# Runs hourly on dyson-server (D-013): when actual AWS spend reaches the stop line (95 USD),
# everything stops except backups. Layer A and the public tunnel are stopped and stay stopped;
# Postgres and the nightly backup timer keep running. Restarting is a Founder decision.
#   DYSON_STOP_AT  stop line in USD (default 95)   DRY_RUN=1  report only, change nothing
set -euo pipefail
export PATH=$PATH:/snap/bin
STOP_AT=${DYSON_STOP_AT:-95}
MARK=/etc/dyson/spend-stopped
SPENT=$(aws budgets describe-budget --region us-east-1 --account-id 501430758577 \
  --budget-name dyson-credits-100 --query 'Budget.CalculatedSpend.ActualSpend.Amount' --output text)
if python3 -c "import sys; sys.exit(0 if float('$SPENT') >= float('$STOP_AT') else 1)"; then
  echo "spend $SPENT USD >= stop line $STOP_AT USD"
  if [ "${DRY_RUN:-0}" = 1 ]; then echo "DRY_RUN: would stop layer-a and dyson-tunnel"; exit 0; fi
  touch "$MARK"
  docker stop dyson-layer-a-1 || true
  systemctl stop dyson-tunnel || true
  systemctl disable dyson-tunnel || true
  echo "STOPPED: layer-a and tunnel; postgres and backups keep running"
else
  echo "spend $SPENT USD < stop line $STOP_AT USD: nothing to do"
fi

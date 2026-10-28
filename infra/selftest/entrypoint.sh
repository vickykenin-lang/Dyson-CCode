#!/bin/sh
# The self-test container's start-up: seal egress, wait for the throwaway Postgres, run the server.
# Deploy-tested (needs the built image). See services/selftest.
set -e

# Egress seal (defence in depth; the selftest network is internal already). Allow loopback (Docker
# DNS lives here) and replies to Layer A's requests; allow the one new connection the runner needs —
# the throwaway Postgres — and then refuse every other inward range, so the runner can never reach
# back into the core, Layer A or the cloud metadata endpoint even while it runs model-written code.
if command -v iptables >/dev/null 2>&1; then
  iptables -A OUTPUT -o lo -j ACCEPT || true
  iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT || true
  iptables -A OUTPUT -d "${DYSON_SELFTEST_PG_IP:-172.36.0.2}" -p tcp --dport 5432 -j ACCEPT || true
  for cidr in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10; do
    iptables -A OUTPUT -d "$cidr" -j REJECT || true
  done
fi

# Wait for the throwaway test database to accept connections.
until pg_isready -h "${DYSON_SELFTEST_PG_HOST:-selftest-pg}" -U postgres >/dev/null 2>&1; do
  echo "waiting for selftest-pg..."
  sleep 1
done

exec python -m dyson_selftest

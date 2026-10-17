#!/bin/bash
# Installs the nightly backup timer: 21:00 UTC (02:30 IST, 08:00 Sydney summer time).
set -euo pipefail
install -m 700 /opt/dyson/current/infra/deploy/backup.sh /usr/local/bin/dyson-backup
install -m 700 /opt/dyson/current/infra/deploy/restore-test.sh /usr/local/bin/dyson-restore-test
cat > /etc/systemd/system/dyson-backup.service <<'UNIT'
[Unit]
Description=Dyson nightly database backup to S3
[Service]
Type=oneshot
ExecStart=/usr/local/bin/dyson-backup
UNIT
cat > /etc/systemd/system/dyson-backup.timer <<'UNIT'
[Unit]
Description=Run the Dyson backup every night
[Timer]
OnCalendar=*-*-* 21:00:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now dyson-backup.timer
systemctl list-timers dyson-backup.timer --no-pager --no-legend || true
# Hourly spend guard (95 USD stop line, D-013)
install -m 700 /opt/dyson/current/infra/deploy/spend-guard.sh /usr/local/bin/dyson-spend-guard
cat > /etc/systemd/system/dyson-spend-guard.service <<'UNIT'
[Unit]
Description=Stop Dyson (except backups) at the 95 USD spend line
[Service]
Type=oneshot
ExecStart=/usr/local/bin/dyson-spend-guard
UNIT
cat > /etc/systemd/system/dyson-spend-guard.timer <<'UNIT'
[Unit]
Description=Check AWS spend every hour
[Timer]
OnCalendar=hourly
Persistent=true
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now dyson-spend-guard.timer
# Role credentials for Bedrock behind C (D-013): the Systems Manager agent keeps root's
# short-lived credentials fresh; a copy readable only by the container user is refreshed every
# 5 minutes. They carry only the dyson-server role's permissions.
install -d -m 700 -o 10001 /opt/dyson/aws
cat > /usr/local/bin/dyson-aws-relay <<'SCRIPT'
#!/bin/bash
set -e
install -m 400 -o 10001 /root/.aws/credentials /opt/dyson/aws/credentials.new
mv /opt/dyson/aws/credentials.new /opt/dyson/aws/credentials
SCRIPT
chmod 700 /usr/local/bin/dyson-aws-relay
cat > /etc/systemd/system/dyson-aws-relay.service <<'UNIT'
[Unit]
Description=Copy the server role credentials for Dyson's Bedrock calls
[Service]
Type=oneshot
ExecStart=/usr/local/bin/dyson-aws-relay
UNIT
cat > /etc/systemd/system/dyson-aws-relay.timer <<'UNIT'
[Unit]
Description=Refresh Dyson's Bedrock credentials every 5 minutes
[Timer]
OnBootSec=30
OnUnitActiveSec=5min
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now dyson-aws-relay.timer
/usr/local/bin/dyson-aws-relay

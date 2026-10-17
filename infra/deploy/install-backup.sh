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
systemctl list-timers dyson-backup.timer --no-pager | head -2

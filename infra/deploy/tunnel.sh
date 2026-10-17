#!/bin/bash
# Runs on dyson-server through Systems Manager. Installs cloudflared and runs the Cloudflare
# Tunnel as a service. The token comes from Parameter Store into a root-only file; never printed.
set -euo pipefail
export PATH=$PATH:/snap/bin
if ! command -v cloudflared >/dev/null; then
  mkdir -p --mode=0755 /usr/share/keyrings
  curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o /usr/share/keyrings/cloudflare-main.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main" > /etc/apt/sources.list.d/cloudflared.list
  apt-get update -y -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq cloudflared
fi
install -d -m 700 /etc/dyson
umask 077
printf 'TUNNEL_TOKEN=%s\n' "$(aws ssm get-parameter --region ap-southeast-2 --name /dyson/cloudflared_token --with-decryption --query Parameter.Value --output text | tr -d '\n ')" > /etc/dyson/tunnel.env
cat > /etc/systemd/system/dyson-tunnel.service <<'UNIT'
[Unit]
Description=Cloudflare Tunnel for Dyson
After=network-online.target docker.service
Wants=network-online.target
[Service]
EnvironmentFile=/etc/dyson/tunnel.env
ExecStart=/usr/bin/cloudflared --no-autoupdate tunnel run
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now dyson-tunnel
sleep 8
cloudflared --version
systemctl is-active dyson-tunnel
journalctl -u dyson-tunnel --no-pager -n 30 | grep -o -E 'Registered tunnel connection[^"]*|ERR.*' | sed -E 's/token[^ ]*/token=<hidden>/g' | head -8

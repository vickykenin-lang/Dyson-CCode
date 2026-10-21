#!/bin/sh
# The sandbox container's start-up: seal egress, bring up a virtual screen, relay it view-only,
# then run the control server. Deploy-tested (needs the built image). See services/sandbox.
set -e

# 1. Egress firewall (defence in depth; Docker network isolation already blocks other networks).
#    Allow loopback and the public internet; refuse every inward/private range so the browser can
#    never reach the core, Layer A, the database, or the cloud metadata endpoint.
if command -v iptables >/dev/null 2>&1; then
  iptables -A OUTPUT -o lo -j ACCEPT || true
  iptables -A OUTPUT -m state --state ESTABLISHED,RELATED -j ACCEPT || true
  for cidr in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 169.254.0.0/16 100.64.0.0/10; do
    iptables -A OUTPUT -d "$cidr" -j REJECT || true
  done
fi

# 2. Virtual screen + a minimal window manager.
export DISPLAY=:0
rm -f /tmp/.X0-lock || true
Xvfb :0 -screen 0 "${DYSON_SANDBOX_GEOMETRY:-1280x800x24}" -nolisten tcp &
sleep 1
fluxbox >/dev/null 2>&1 &

# 3. Screen relay: x11vnc + noVNC over websocket. Interactive, so the Founder can take control
#    of the sandbox as well as watch; Dyson drives through Playwright. Input reaches the sealed
#    sandbox only — it is sealed from the core either way. The public hostname MUST sit behind
#    Cloudflare Access (Founder-only); without it, anyone reaching the stream could drive it.
x11vnc -display :0 -forever -shared -nopw -rfbport 5900 -quiet -bg
websockify --web=/usr/share/novnc "${DYSON_SANDBOX_VNC_PORT:-6080}" localhost:5900 &

# 4. The control server (Chromium is launched by it, headful, on this display).
exec python -m dyson_sandbox

# The sandbox container (D-026, Dyson-native): Chromium driven by Playwright, its screen relayed
# view-only to the dashboard. Build from the repository root (docker compose does). No Hermes.
# The running container has internet (to browse) but no route to the core (Docker network
# isolation plus an egress firewall in the entrypoint). It holds no secret and no model.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# Virtual display, window manager, and the view-only VNC -> websocket relay.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb fluxbox x11vnc novnc websockify iptables ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY services/sandbox/ sandbox/
RUN pip install --no-cache-dir "./sandbox[browser]" \
    && python -m playwright install --with-deps chromium \
    && rm -rf /root/.cache

COPY infra/sandbox/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8097 6080
ENTRYPOINT ["/entrypoint.sh"]

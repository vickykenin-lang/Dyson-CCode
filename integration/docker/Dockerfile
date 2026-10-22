# Layer A for local runs (Step 9). Build from the repository root:
#   docker compose build
# Wheels in integration/docker/wheels (if any) are used first; otherwise pip uses PyPI.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
ARG PIP_NO_INDEX=""
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --create-home --uid 10001 dyson && mkdir /data /hermes && chown dyson /data /hermes
# noVNC's static client, served same-origin by the app so the Founder's sandbox panel needs no
# second hostname and no second login (D-028). The screen's websocket is bridged by the app itself.
RUN apt-get update && apt-get install -y --no-install-recommends novnc \
    && rm -rf /var/lib/apt/lists/* \
    # Force the Founder's panel interactive: without this noVNC can fall back to a stored/stale
    # view_only setting (the panel began as view-only), so the screen shows but clicks and keys go
    # nowhere. mandatory.json overrides any URL, cookie or saved value and locks it (D-028). The
    # sandbox is sealed from the core and Founder-only behind Cloudflare Access, so full control is safe.
    && printf '%s' '{"view_only": false}' > /usr/share/novnc/mandatory.json
WORKDIR /app
COPY integration/docker/wheels/ /wheels/
COPY contracts/ contracts/
COPY services/ services/
COPY apps/ apps/
COPY integration/ integration/
COPY policy/ policy/
RUN pip install ${PIP_NO_INDEX:+--no-index} --find-links /wheels \
      ./contracts ./services/memory ./services/governance ./services/toolhub \
      ./services/orchestrator ./services/assurance ./services/intelligence \
      ./services/gateway ./services/founder-controls ./apps/founder-app ./integration \
    && rm -rf /wheels /root/.cache
USER dyson
EXPOSE 8080 8081 8082 8083 8090 8095
CMD ["python", "-m", "dyson_integration.serve"]

# The self-test container: Dyson's own ruff + pytest, run in a sealed sandbox instead of on GitHub.
# Build from the repository root (docker compose does). It bakes the repo source and installs every
# package with its [dev] extras, exactly as CI does, so `ruff` and `pytest` run against the real
# tree. It copies source directories only — never local-secrets — so the image holds no secret, and
# at runtime the entrypoint seals egress to all but its throwaway Postgres. No model, no key.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        iptables postgresql-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/repo
# Source only — the root pyproject (ruff + pytest config), the packages, and policy. Never the
# release root's local-secrets, so no credential can be baked into this image.
COPY pyproject.toml ./
COPY contracts/ contracts/
COPY services/ services/
COPY apps/ apps/
COPY integration/ integration/
COPY policy/ policy/
RUN python -m pip install --upgrade pip \
    && pip install --no-cache-dir \
        -e contracts -e "services/memory[dev]" -e "services/governance[dev]" \
        -e "services/toolhub[dev]" -e "services/orchestrator[dev]" -e "services/assurance[dev]" \
        -e "services/intelligence[dev]" -e "services/knowledge[dev]" -e "services/gateway[dev]" \
        -e "services/founder-controls[dev]" -e "services/voice[dev]" -e "apps/founder-app[dev]" \
        -e "integration[dev]" -e "services/selftest[dev]" "pyyaml>=6" pytest ruff \
    && rm -rf /root/.cache

COPY infra/selftest/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8099
ENTRYPOINT ["/entrypoint.sh"]

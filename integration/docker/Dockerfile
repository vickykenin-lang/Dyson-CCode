# Layer A for local runs (Step 9). Build from the repository root:
#   docker compose build
# Wheels in integration/docker/wheels (if any) are used first; otherwise pip uses PyPI.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
ARG PIP_NO_INDEX=""
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --create-home --uid 10001 dyson && mkdir /data && chown dyson /data
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
EXPOSE 8080 8081 8082 8083
CMD ["python", "-m", "dyson_integration.serve"]

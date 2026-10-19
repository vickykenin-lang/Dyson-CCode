# The voice container (D-024): IndicConformer hears the Founder on Dyson's own server.
# Build from the repository root (docker compose does). The model is fetched once here at a pinned
# revision and checked against pinned SHA-256s; the running container has no internet.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd --create-home --uid 10002 listener
WORKDIR /app
COPY services/voice/ voice/
RUN pip install --no-cache-dir "./voice[model]" "huggingface_hub>=0.24,<2" \
    && python voice/fetch_model.py /model \
    && pip uninstall -y huggingface_hub \
    && rm -rf /root/.cache \
    && chmod -R a-w /model
USER listener
ENV HF_HUB_OFFLINE=1 DYSON_VOICE_MODEL=/model
EXPOSE 8096
CMD ["python", "-m", "dyson_voice"]

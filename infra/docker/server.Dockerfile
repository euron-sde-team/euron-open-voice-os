# syntax=docker/dockerfile:1.7
# ─────────────────────────────────────────────────────────────────────────────
# Python services, one Dockerfile, three targets that differ only in extras:
#   api      control plane API, worker, CLI and the mock providers   (no extras)
#   runtime  voice runtime: Pipecat, WebRTC, WebSocket                (extra: runtime)
#   speech   local Whisper and Kokoro behind OpenAI-compatible APIs    (extra: speech)
#   docker build -f infra/docker/server.Dockerfile --target runtime -t voiceos-runtime apps/api
# ─────────────────────────────────────────────────────────────────────────────
ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.9.17 AS uv

# ── Build stages: one virtualenv per target, from the lockfile ────────────────
FROM ${PYTHON_IMAGE} AS build-base
COPY --from=uv /uv /uvx /bin/
# Bytecode is compiled here because the runtime root filesystem is read-only.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src

FROM build-base AS build-api
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md ./
COPY src src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-editable

FROM build-base AS build-runtime
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project --extra runtime
COPY pyproject.toml uv.lock README.md ./
COPY src src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --extra runtime

FROM build-base AS build-speech
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project --extra speech
COPY pyproject.toml uv.lock README.md ./
COPY src src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --extra speech

# ── Shared runtime base: non-root user, tini, read-only friendly ──────────────
FROM ${PYTHON_IMAGE} AS base
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=UTC PORT=8080
# tini reaps zombies and forwards SIGTERM, so services drain and sessions end cleanly.
RUN apt-get update && apt-get install -y --no-install-recommends tini ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 voiceos \
 && useradd --system --uid 10001 --gid voiceos --home-dir /app --no-create-home \
      --shell /usr/sbin/nologin voiceos
WORKDIR /app
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8080'), timeout=2).status == 200 else 1)"
ENTRYPOINT ["/usr/bin/tini", "--", "voiceos"]

FROM base AS api
COPY --from=build-api /opt/venv /opt/venv
RUN mkdir -p /data/objects && chown voiceos:voiceos /data/objects
USER 10001:10001
EXPOSE 8080 4550
CMD ["serve", "--host", "0.0.0.0", "--port", "8080"]

FROM base AS runtime
COPY --from=build-runtime /opt/venv /opt/venv
# Silero VAD and Smart Turn v3 weights ship inside the pipecat package: no download.
USER 10001:10001
EXPOSE 8080
CMD ["runtime", "--host", "0.0.0.0", "--port", "8080"]

FROM base AS speech
# espeak-ng (GPL-3.0) is Kokoro's phonemizer, installed from Debian as a separate
# program in this image only. VoiceOS source does not include or link it at build time;
# see docs/architecture/licenses.md.
RUN apt-get update && apt-get install -y --no-install-recommends espeak-ng \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /models && chown voiceos:voiceos /models
COPY --from=build-speech /opt/venv /opt/venv
ENV SPEECH_MODELS_DIR=/models HF_HOME=/models/hf
USER 10001:10001
EXPOSE 8080
CMD ["speech", "--host", "0.0.0.0", "--port", "8080"]

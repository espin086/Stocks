# syntax=docker/dockerfile:1.7
# One image, the CLI as entrypoint: `docker run aisolutionslab/sobres <anything sobres accepts>`.
#
# Stages:
#   frontend  Node builds the SPA (0004) — discarded.
#   wheel     Python builds the wheel from this checkout — discarded.
#   prebuilt  The release pipeline passes the exact wheel it publishes to PyPI.
#   runtime   A slim Python image with the wheel installed; no Node, no build tools.
#
# WHEEL_SOURCE=wheel (default) builds from source; the release sets prebuilt.

ARG PYTHON_VERSION=3.12
ARG WHEEL_SOURCE=wheel

# ---------------------------------------------------------------- frontend
FROM node:22-alpine AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# vite writes to ../src/sobres/api/static; the build fails over the bundle budget.
RUN mkdir -p ../src/sobres/api && npm run build

# ------------------------------------------------------------------- wheel
FROM python:${PYTHON_VERSION}-slim AS wheel
WORKDIR /build
RUN pip install --no-cache-dir build
COPY pyproject.toml README.md LICENSE CHANGELOG.md ./
COPY src/ ./src/
COPY --from=frontend /build/src/sobres/api/static/ ./src/sobres/api/static/
RUN python -m build --wheel --outdir /wheels

# ---------------------------------------------------------------- prebuilt
FROM scratch AS prebuilt
COPY dist/*.whl /wheels/

# ----------------------------------------------------------------- runtime
FROM ${WHEEL_SOURCE} AS wheel-source
FROM python:${PYTHON_VERSION}-slim AS runtime

# A fixed, documented identity so files on the mounted volume are usable from the host.
ARG UID=1000
ARG GID=1000
RUN groupadd --gid "${GID}" sobres \
 && useradd --uid "${UID}" --gid "${GID}" --create-home --shell /usr/sbin/nologin sobres \
 && mkdir -p /data && chown sobres:sobres /data

COPY --from=wheel-source /wheels/ /tmp/wheels/
RUN pip install --no-cache-dir "$(ls /tmp/wheels/*.whl)[data,econ,web,otel]" \
 && rm -rf /tmp/wheels

# Configuration is runtime-only: environment or a config file on the volume.
ENV SOBRES_CONTAINER=1 \
    SOBRES_DB_URL=sqlite:////data/sobres.db \
    SOBRES_CONFIG_FILE=/data/config.toml \
    SOBRES_LOG_FORMAT=json \
    PYTHONUNBUFFERED=1

USER sobres
WORKDIR /data
VOLUME ["/data"]
EXPOSE 8787

# Readiness = the same doctor checks `sobres doctor` runs, via the API's health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["sobres", "deploy", "health", "--port", "8787"]

ENTRYPOINT ["sobres"]

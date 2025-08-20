# ---------- builder ----------
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install only what's needed to fetch uv
RUN apt-get update && apt-get install -y --no-install-recommends curl \
  && rm -rf /var/lib/apt/lists/*

# Install uv (binary in /root/.local/bin)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# Copy resolver inputs first for maximum cache hits
COPY pyproject.toml ./
COPY uv.lock ./

# Create venv and sync only runtime deps (no dev, no project install)
# Use BuildKit cache for uv (speeds up rebuilds)
#   docker buildx build ...  (BuildKit enabled)
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv --python 3.13 && \
    uv sync --frozen --no-dev --no-install-project

# Bring in app code last
COPY --chown=app:app . .

# ---------- runtime ----------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Non-root user
ARG userid=10001
ARG groupid=10001
RUN groupadd --gid "${groupid}" app && \
    useradd -g app --uid "${userid}" --shell /usr/sbin/nologin --create-home app


ENV HOST=0.0.0.0 \
    PORT=8000


# Copy only what we need from builder; keep ownership tight
COPY --from=builder --chown=app:app /app /app

# Prepare writable mounts
RUN mkdir -p /mnt/uploads && \
    chown -R app:app /mnt/uploads

WORKDIR /app

USER app

EXPOSE $PORT
CMD ["sh", "-c", ".venv/bin/uvicorn main:app --host ${HOST} --port ${PORT} --root-path ${ROOT_URL_PATH} --proxy-headers --forwarded-allow-ips='*'"]

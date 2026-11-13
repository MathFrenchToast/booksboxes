# ==============================================================================
# Stage 1 : Build de l'environnement virtuel avec uv
# ==============================================================================
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Installation des dépendances tierces en cache
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-install-project --no-dev

# Copie du code source et installation du package allbal
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ==============================================================================
# Stage 2 : Image de runtime minimale non-root
# ==============================================================================
FROM python:3.12-slim AS runtime

RUN groupadd -g 10001 allbal && \
    useradd -u 10001 -g allbal -m -s /usr/sbin/nologin allbal

WORKDIR /app

COPY --from=builder --chown=allbal:allbal /app /app
COPY --chown=allbal:allbal docker-entrypoint.sh /app/docker-entrypoint.sh

RUN chmod +x /app/docker-entrypoint.sh && \
    mkdir -p /app/data/raw && \
    chown -R allbal:allbal /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    ALLBAL_DB_PATH="/app/data/allbal.db" \
    PORT=8000

USER allbal

EXPOSE 8000

VOLUME ["/app/data"]

ENTRYPOINT ["/app/docker-entrypoint.sh"]

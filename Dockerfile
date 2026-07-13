# Camoufox-based Turnstile solver API

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_LINK_MODE=copy \
    HOME=/home/appuser \
    XDG_CACHE_HOME=/home/appuser/.cache

# System libraries required by Camoufox (Firefox) in headless mode
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdbus-glib-1-2 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    libxt6 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

RUN useradd -m -u 1000 -s /bin/bash appuser \
    && mkdir -p /app /home/appuser/.cache \
    && chown -R appuser:appuser /app /home/appuser

WORKDIR /app
USER appuser

# ── Dependency layer (invalidated only when lockfiles change) ─────────────
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# ── Browser layer (cached across code-only rebuilds) ──────────────────────
# Camoufox installs under $XDG_CACHE_HOME/camoufox.
# MUST stay above "COPY . ." so editing source does not re-download.
RUN uv run camoufox fetch && uv run camoufox path

# ── Application layer (changes often; does NOT re-fetch browser) ──────────
COPY --chown=appuser:appuser . .
RUN uv sync --frozen --no-dev \
    && printf '# Add proxies one per line\n' > /app/proxies.txt

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

# Healthcheck is defined in docker-compose.yml only (single source of truth).

CMD ["python", "main.py", "api"]

# Dockerfile for Turnstile Solver
FROM python:3.11-slim

# Install system dependencies for browser automation
RUN apt-get update && apt-get install -y \
    # Xvfb for headless display
    xvfb \
    # Browser dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libatspi2.0-0 \
    # Fonts
    fonts-liberation \
    fonts-noto-color-emoji \
    # Utils
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv system-wide
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    cp /root/.local/bin/uv /usr/local/bin/uv && \
    cp /root/.local/bin/uvx /usr/local/bin/uvx

# Set working directory
WORKDIR /app

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock* ./

# Install Python dependencies
RUN uv sync

# Fetch Camoufox browser
RUN uv run python -m camoufox fetch

# Copy application code
COPY main.py ./

# Create logs directory
RUN mkdir -p logs

# Create non-root user for security
RUN useradd -m -u 1000 solver && \
    chown -R solver:solver /app
USER solver

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# Run with xvfb for headless display
CMD ["xvfb-run", "--auto-servernum", "--server-args=-screen 0 1920x1080x24", "uv", "run", "main.py"]

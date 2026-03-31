# =============================================================================
# A2A Commerce Platform — Production Docker Image
# =============================================================================
# Build:  docker build -t a2a-gateway .
# Run:    docker run -p 8000:8000 -v a2a-data:/var/lib/a2a --env-file .env a2a-gateway
# =============================================================================

FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd --system a2a && useradd --system --gid a2a --no-create-home a2a

# Install system deps (sqlite3 for backups/debugging)
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends sqlite3 curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---------------------------------------------------------------------------
# Dependencies layer (cached unless pyproject.toml files change)
# ---------------------------------------------------------------------------
FROM base AS deps

# Copy only dependency manifests first for layer caching
COPY gateway/pyproject.toml gateway/pyproject.toml
COPY sdk/pyproject.toml sdk/pyproject.toml
COPY products/billing/pyproject.toml products/billing/pyproject.toml
COPY products/paywall/pyproject.toml products/paywall/pyproject.toml
COPY products/payments/pyproject.toml products/payments/pyproject.toml
COPY products/marketplace/pyproject.toml products/marketplace/pyproject.toml
COPY products/trust/pyproject.toml products/trust/pyproject.toml
COPY products/shared/pyproject.toml products/shared/pyproject.toml
COPY products/identity/pyproject.toml products/identity/pyproject.toml
COPY products/messaging/pyproject.toml products/messaging/pyproject.toml
COPY products/reputation/pyproject.toml products/reputation/pyproject.toml

# Install core runtime deps
RUN pip install --no-cache-dir \
    "fastapi>=0.115" \
    "uvicorn>=0.29" \
    "httpx>=0.27" \
    "aiosqlite>=0.20" \
    "pydantic>=2.0" \
    "cryptography>=46.0.6"

# ---------------------------------------------------------------------------
# Application layer
# ---------------------------------------------------------------------------
FROM deps AS app

# Copy application code
COPY pricing.json pricing.json
COPY gateway/ gateway/
COPY products/ products/
COPY sdk/ sdk/

# Install SDK in the image
RUN pip install --no-cache-dir -e sdk/ 2>/dev/null || pip install --no-cache-dir sdk/

# Data directory (mount a volume here for persistence)
RUN mkdir -p /var/lib/a2a && chown a2a:a2a /var/lib/a2a
VOLUME /var/lib/a2a

# Default environment
ENV HOST=0.0.0.0 \
    PORT=8000 \
    A2A_DATA_DIR=/var/lib/a2a \
    BILLING_DSN=sqlite:////var/lib/a2a/billing.db \
    PAYWALL_DSN=sqlite:////var/lib/a2a/paywall.db \
    PAYMENTS_DSN=sqlite:////var/lib/a2a/payments.db \
    MARKETPLACE_DSN=sqlite:////var/lib/a2a/marketplace.db \
    TRUST_DSN=sqlite:////var/lib/a2a/trust.db \
    EVENT_BUS_DSN=sqlite:////var/lib/a2a/events.db \
    WEBHOOK_DSN=sqlite:////var/lib/a2a/webhooks.db \
    IDENTITY_DSN=sqlite:////var/lib/a2a/identity.db \
    MESSAGING_DSN=sqlite:////var/lib/a2a/messaging.db \
    DISPUTE_DSN=sqlite:////var/lib/a2a/disputes.db \
    LOG_LEVEL=INFO

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/v1/health || exit 1

# Run as non-root
USER a2a

# Start gateway
CMD ["python", "-m", "uvicorn", "gateway.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info", "--access-log"]

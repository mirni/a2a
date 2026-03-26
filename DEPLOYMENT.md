# Deployment Guide

Step-by-step instructions for deploying the A2A commerce platform and making its products available to agents.

## Prerequisites

- Python 3.12+
- pip
- SQLite 3.35+ (included with Python)
- (Optional) PostgreSQL 14+ if using the Postgres connector
- (Optional) Docker for containerized deployment

## 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install core dependencies
pip install aiosqlite httpx pydantic

# Install MCP SDK (for running connectors as servers)
pip install mcp

# Install connector-specific dependencies
pip install asyncpg          # PostgreSQL connector only

# Install dev/test dependencies
pip install pytest pytest-asyncio pytest-cov ruff
```

## 2. Configure Environment

```bash
# Copy the example and fill in your values
cp .env.example .env

# At minimum, set the API keys for connectors you plan to use:
#   STRIPE_API_KEY   — for Stripe connector
#   GITHUB_TOKEN     — for GitHub connector
#   PG_*             — for PostgreSQL connector

# For production, set database paths to persistent files:
#   BILLING_DB=sqlite:///data/billing.db
#   TRUST_DB=sqlite:///data/trust.db
#   etc.
```

Create the data directory:

```bash
mkdir -p data
```

## 3. Set Up PYTHONPATH

The monorepo uses a flat structure. Set PYTHONPATH so products can find each other:

```bash
export PYTHONPATH="$PWD/products/shared:$PWD/products/billing:$PWD/products/trust:$PWD/products/paywall:$PWD/products/marketplace:$PWD/products/payments:$PWD/products/reputation"
```

Add this to your shell profile or deployment script.

## 4. Verify Installation

Run the full test suite to confirm everything works:

```bash
# Quick smoke test — run each product's tests
PYTHONPATH=$PWD/products/shared python -m pytest products/shared/tests/ -q
PYTHONPATH=$PWD/products/billing python -m pytest products/billing/tests/ -q
PYTHONPATH=$PWD/products/trust python -m pytest products/trust/tests/ -q
PYTHONPATH=$PWD/products/marketplace python -m pytest products/marketplace/tests/ -q

# Expected: 962 tests, all passing
```

---

## 5. Deploy Connectors (MCP Servers)

Connectors are MCP servers that agents connect to via stdio transport. Each connector runs as a separate process.

### Stripe Connector

```bash
export STRIPE_API_KEY=sk_test_...
export PYTHONPATH=$PWD/products/shared/src:$PWD/products/connectors/stripe

python -m src.server
# Runs on stdio — agents connect via MCP client
```

**Claude Desktop / MCP client config** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "stripe": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/products/connectors/stripe",
      "env": {
        "STRIPE_API_KEY": "sk_test_...",
        "PYTHONPATH": "/path/to/products/shared/src:/path/to/products/connectors/stripe"
      }
    }
  }
}
```

### GitHub Connector

```bash
export GITHUB_TOKEN=ghp_...
export PYTHONPATH=$PWD/products:$PWD/products/connectors/github

python -m src.server
```

**MCP client config:**

```json
{
  "mcpServers": {
    "github": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/products/connectors/github",
      "env": {
        "GITHUB_TOKEN": "ghp_...",
        "PYTHONPATH": "/path/to/products:/path/to/products/connectors/github"
      }
    }
  }
}
```

### PostgreSQL Connector

```bash
export PG_HOST=localhost
export PG_PORT=5432
export PG_DATABASE=mydb
export PG_USER=myuser
export PG_PASSWORD=mypass
export PYTHONPATH=$PWD/products:$PWD/products/connectors/postgres

python -m src.server
```

**MCP client config:**

```json
{
  "mcpServers": {
    "postgres": {
      "command": "python",
      "args": ["-m", "src.server"],
      "cwd": "/path/to/products/connectors/postgres",
      "env": {
        "PG_HOST": "localhost",
        "PG_DATABASE": "mydb",
        "PG_USER": "myuser",
        "PG_PASSWORD": "mypass",
        "PYTHONPATH": "/path/to/products:/path/to/products/connectors/postgres"
      }
    }
  }
}
```

---

## 6. Deploy Core Services

Core services (billing, trust, marketplace, payments, reputation) are Python libraries, not standalone servers. They run embedded in your application.

### Minimal Application Setup

Create a `main.py` that wires everything together:

```python
"""Minimal A2A platform startup."""

import asyncio
import os

# Billing
from src.storage import StorageBackend as BillingStorage
from src.tracker import UsageTracker
from src.wallet import Wallet

async def main():
    # 1. Initialize billing (foundation for everything)
    billing_dsn = os.environ.get("BILLING_DB", "sqlite:///:memory:")
    tracker = UsageTracker(storage=billing_dsn)
    await tracker.connect()
    wallet = Wallet(tracker.storage)

    # 2. Create agent wallets (run once, or check-and-create)
    try:
        await wallet.create("my-agent", initial_balance=100.0)
    except ValueError:
        pass  # Already exists

    # 3. Define metered tools
    @tracker.metered(cost=1, require_balance=True)
    async def my_tool(agent_id: str, query: str) -> dict:
        return {"result": "ok", "query": query}

    # 4. Use the tool (billing happens automatically)
    result = await my_tool(agent_id="my-agent", query="test")
    print(f"Result: {result}")
    print(f"Balance: {await wallet.get_balance('my-agent')}")

    await tracker.close()


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
PYTHONPATH=$PWD/products/billing BILLING_DB=sqlite:///data/billing.db python main.py
```

### Full Platform with Paywall + Marketplace

```python
"""Full platform with paywall-protected connectors and marketplace."""

import asyncio
import os

# Billing
from src.storage import StorageBackend as BillingStorage
from src.tracker import UsageTracker
from src.wallet import Wallet

async def main():
    # --- Billing ---
    tracker = UsageTracker(storage=os.environ.get("BILLING_DB", "sqlite:///data/billing.db"))
    await tracker.connect()
    wallet = Wallet(tracker.storage)

    # --- Paywall ---
    # Import with PYTHONPATH including products/paywall
    import importlib
    paywall_middleware = importlib.import_module("products.paywall.src.middleware")
    paywall_storage_mod = importlib.import_module("products.paywall.src.storage")
    paywall_keys = importlib.import_module("products.paywall.src.keys")

    pw_storage = paywall_storage_mod.PaywallStorage(
        dsn=os.environ.get("PAYWALL_DB", "sqlite:///data/paywall.db")
    )
    await pw_storage.connect()

    middleware = paywall_middleware.PaywallMiddleware(
        tracker=tracker,
        connector="stripe",
        paywall_storage=pw_storage,
    )
    await middleware.initialize()

    # --- Create API key for an agent ---
    key_mgr = paywall_keys.KeyManager(storage=pw_storage)
    api_key = await key_mgr.create_key(agent_id="trading-bot", tier="pro")
    print(f"API Key (save this): {api_key}")

    # --- Gate a tool behind the paywall ---
    @middleware.gated(tier="free", cost=1)
    async def query_data(agent_id: str, query: str) -> dict:
        return {"data": [1, 2, 3]}

    # --- Use it ---
    try:
        result = await query_data(agent_id="trading-bot", query="SELECT *")
        print(f"Result: {result}")
    except Exception as e:
        print(f"Blocked: {e}")

    await pw_storage.close()
    await tracker.close()


if __name__ == "__main__":
    asyncio.run(main())
```

### Start Reputation Pipeline

```python
"""Start continuous monitoring of registered MCP servers."""

import asyncio
import os

async def main():
    # Initialize trust storage
    from products.trust.src.storage import StorageBackend as TrustStorage
    trust_storage = TrustStorage(dsn=os.environ.get("TRUST_DB", "sqlite:///data/trust.db"))
    await trust_storage.connect()

    # Initialize reputation storage
    from products.reputation.src.storage import ReputationStorage
    rep_storage = ReputationStorage(dsn=os.environ.get("REPUTATION_DB", "sqlite:///data/reputation.db"))
    await rep_storage.connect()

    # Initialize workers
    from products.reputation.src.probe_worker import ProbeWorker
    from products.reputation.src.scan_worker import ScanWorker
    from products.reputation.src.aggregator import Aggregator
    from products.reputation.src.pipeline import ReputationPipeline

    pipeline = ReputationPipeline(
        trust_storage=trust_storage,
        reputation_storage=rep_storage,
        probe_worker=ProbeWorker(trust_storage=trust_storage),
        scan_worker=ScanWorker(trust_storage=trust_storage),
        aggregator=Aggregator(trust_storage=trust_storage),
    )

    # Register servers to monitor
    await pipeline.add_target(
        url="https://your-stripe-mcp.example.com/health",
        server_id="stripe-connector",
        probe_interval=300,
        scan_interval=3600,
    )

    # Run continuously
    print("Starting reputation pipeline...")
    await pipeline.start()

    # Keep running until interrupted
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        await pipeline.stop()
        await rep_storage.close()
        await trust_storage.close()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## 7. Production Considerations

### Data Persistence

All products use SQLite. For production:

```bash
# Create persistent data directory
mkdir -p /var/lib/a2a/data

# Set all DB paths to this directory
BILLING_DB=sqlite:////var/lib/a2a/data/billing.db
TRUST_DB=sqlite:////var/lib/a2a/data/trust.db
PAYWALL_DB=sqlite:////var/lib/a2a/data/paywall.db
MARKETPLACE_DB=sqlite:////var/lib/a2a/data/marketplace.db
PAYMENTS_DB=sqlite:////var/lib/a2a/data/payments.db
REPUTATION_DB=sqlite:////var/lib/a2a/data/reputation.db
```

### Backup

SQLite databases can be backed up while running:

```bash
# Backup all databases
for db in billing trust paywall marketplace payments reputation; do
    sqlite3 /var/lib/a2a/data/${db}.db ".backup /var/lib/a2a/backups/${db}_$(date +%Y%m%d).db"
done
```

### Logging

Set the log level via environment:

```bash
export LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

### Monitoring

Key metrics to track:
- SQLite file sizes (watch for unbounded growth)
- Stripe/GitHub API rate limit headers (logged in audit)
- Wallet balances (alert on negative or near-zero)
- Probe success rates (from reputation pipeline)
- Subscription charge failures (from payment scheduler)

### Security Checklist

- [ ] Stripe API key is `sk_live_*` (not test) for production
- [ ] GitHub token has minimum required scopes
- [ ] PostgreSQL user has minimum required permissions (read-only if possible)
- [ ] `.env` file is not committed to git (check `.gitignore`)
- [ ] Database files are not world-readable (`chmod 600 data/*.db`)
- [ ] API keys generated via paywall are distributed securely
- [ ] Audit logs are being written and retained

---

## 8. Running Examples

Verify the platform works end-to-end:

```bash
# Metered connector example
PYTHONPATH=$PWD/products/billing python examples/metered_connector.py

# Multi-agent rate limiting
PYTHONPATH=$PWD/products/billing python examples/multi_agent_workflow.py

# Full A2A commerce flow
PYTHONPATH=$PWD/products/billing:$PWD/products/marketplace python examples/a2a_commerce_flow.py
```

---

## Architecture Overview

```
Agents (MCP clients)
    │
    ├── Stripe Connector (MCP server, stdio)
    ├── GitHub Connector (MCP server, stdio)
    ├── Postgres Connector (MCP server, stdio)
    │
    ├── Paywall Middleware (decorates connector tools)
    │       └── Billing Layer (wallets, usage tracking)
    │
    ├── Marketplace (service discovery)
    │       └── Trust Scoring (reputation data)
    │
    ├── Payments (agent-to-agent transactions)
    │       └── Billing Layer (fund transfers)
    │
    └── Reputation Pipeline (background process)
            ├── Probe Worker (health checks)
            ├── Scan Worker (security scans)
            └── Aggregator (score computation)
```

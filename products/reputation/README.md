# Reputation Data Collection Pipeline

Continuous monitoring infrastructure for MCP server trustworthiness. Automatically probes registered servers, runs security scans, and feeds data into the trust scoring engine.

## Components

| Component | Description |
|-----------|-------------|
| `ReputationPipeline` | Orchestrates the full monitoring lifecycle |
| `ProbeWorker` | HTTP health probes with error classification |
| `ScanWorker` | TLS, security headers, and auth verification |
| `Aggregator` | Recomputes trust scores from collected data |
| `ReputationStorage` | SQLite persistence for probe targets |

## Quick Start

```python
from src.pipeline import ReputationPipeline
from src.probe_worker import ProbeWorker
from src.scan_worker import ScanWorker
from src.aggregator import Aggregator
from src.storage import ReputationStorage

# Initialize storage
rep_storage = ReputationStorage("sqlite:///reputation.db")
await rep_storage.connect()

# Initialize workers
probe_worker = ProbeWorker(trust_storage=trust_storage)
scan_worker = ScanWorker(trust_storage=trust_storage)
aggregator = Aggregator(trust_storage=trust_storage)

# Create pipeline
pipeline = ReputationPipeline(
    trust_storage=trust_storage,
    reputation_storage=rep_storage,
    probe_worker=probe_worker,
    scan_worker=scan_worker,
    aggregator=aggregator,
)
```

## Register Targets

```python
await pipeline.add_target(
    url="https://mcp-stripe.example.com",
    server_id="stripe-connector",
    probe_interval=300,   # 5 min
    scan_interval=3600,   # 1 hr
)
```

## Run Monitoring

```python
# Single cycle (probe + scan + score)
result = await pipeline.run_once()
# {"probed": 3, "scanned": 1, "scored": 3}

# Continuous background monitoring
await pipeline.start()
# ... later ...
await pipeline.stop()
```

## Probe Error Classification

The probe worker classifies errors into categories:
- `success` - HTTP 2xx response
- `timeout` - Request timeout
- `connection_refused` - Target not accepting connections
- `dns_error` - Name resolution failure
- `http_4xx` - Client error response
- `http_5xx` - Server error response
- `ssl_error` - TLS/certificate failure

## Security Scans

Scans check:
- TLS certificate validity and protocol version
- Security headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy)
- Authentication requirement (401/403 responses, WWW-Authenticate header)

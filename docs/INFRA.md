# Infrastructure & CI/CD Reference

This document describes the complete development, testing, packaging, and deployment pipeline. It is written to be self-contained so an AI agent can reproduce this workflow in a new project with minimal adaptation.

---

## Architecture Overview

```
Developer
  │
  ├─ push to feature branch ──► CI (lint, typecheck, semgrep, security, dep-audit, test, docker, package)
  │
  ├─ open PR to main ──► CI (same) + Staging (build → deploy to test server → smoke tests)
  │
  ├─ merge PR to main ──► CI (same, runs on push to main)
  │
  └─ manual workflow_dispatch on main ──► Production Deploy (approval gate → deploy → smoke)
```

**Key principle:** CI runs on every push/PR. Staging deploys on PRs to main. Production is manual-only with confirmation.

---

## 1. Workflows

### 1.1 CI Pipeline (`.github/workflows/ci.yml`)

**Triggers:** Every `push` and `pull_request` on all branches.

**Jobs (all run in parallel unless noted):**

| Job | Tool | What it does |
|-----|------|--------------|
| `lint` | `ruff` | `ruff check .` (linting) + `ruff format --check .` (formatting) |
| `typecheck` | `mypy` | Type-checks all `src/` directories |
| `security` | `bandit` | Security scan, skips B101 (assert), B108, B608 |
| `dependency-audit` | `pip-audit` | Checks pinned deps for known vulnerabilities |
| `semgrep` | `semgrep` | SAST scan with `--config auto`, excludes tests |
| `test` | `pytest` | Runs per-module tests on Python 3.12 + 3.13 matrix |
| `docker-build` | `docker` | Builds image, starts container, health-checks it |
| `package` | `create_package.sh` | Builds .deb and .whl artifacts (depends on `test`) |

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install ruff
      - name: Lint with ruff
        run: ruff check .
      - name: Check formatting with ruff
        run: ruff format --check .

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install mypy and runtime deps
        run: pip install mypy pydantic aiosqlite cryptography httpx starlette
      - name: Type check with mypy
        run: mypy $(find gateway/src products/*/src -maxdepth 0 -type d 2>/dev/null | sort)

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install bandit
      - name: Security scan with bandit
        run: bandit -r gateway/src products/ -ll -q --skip B101,B108,B608 --exclude '*/tests/*'

  dependency-audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps and audit tool
        run: |
          pip install pip-audit
          pip install -r requirements.txt
      - name: Dependency audit
        run: pip-audit

  semgrep:
    runs-on: ubuntu-latest
    container:
      image: semgrep/semgrep
    steps:
      - uses: actions/checkout@v4
      - name: SAST with Semgrep
        run: semgrep scan --config auto --error --exclude='**/tests/**' .

  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ matrix.python-version }}-${{ hashFiles('**/pyproject.toml') }}
          restore-keys: |
            ${{ runner.os }}-pip-${{ matrix.python-version }}-
      - name: Install dependencies
        run: scripts/ci/install_deps.sh --with-test
      - name: Test gateway
        run: scripts/run_tests.sh gateway --cov=gateway --cov-fail-under=70
      # Repeat for each module:
      # scripts/run_tests.sh products/billing
      # scripts/run_tests.sh products/payments
      # etc.

  docker-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build and verify Docker image
        run: scripts/ci/docker_build_verify.sh

  package:
    runs-on: ubuntu-latest
    needs: [test]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install wheel setuptools
      - name: Build all packages
        run: scripts/create_package.sh ALL
      - uses: actions/upload-artifact@v4
        with:
          name: deb-packages
          path: dist/*.deb
          retention-days: 14
      - uses: actions/upload-artifact@v4
        with:
          name: sdk-wheel
          path: dist/*.whl
          retention-days: 14
```

### 1.2 Staging Pipeline (`.github/workflows/staging.yml`)

**Triggers:** `pull_request` targeting `main` only.

**Jobs (sequential chain):**

```
ci-check → package → staging-deploy → staging-smoke → staging-report
```

| Job | What it does |
|-----|--------------|
| `ci-check` | Gate — CI status checks are enforced via required status checks |
| `package` | Builds all .deb packages |
| `staging-deploy` | Connects via Tailscale VPN, SCPs .deb to staging server, installs it |
| `staging-smoke` | Health check (10 retries, 5s apart) + lightweight stress test (5 customers, 15s) |
| `staging-report` | Posts deploy/smoke results as a PR comment |

```yaml
name: Staging

on:
  pull_request:
    branches: [main]

concurrency:
  group: staging-${{ github.head_ref }}
  cancel-in-progress: true

jobs:
  ci-check:
    runs-on: ubuntu-latest
    steps:
      - run: echo "CI checks are enforced via required status checks on the PR"

  package:
    runs-on: ubuntu-latest
    needs: [ci-check]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install wheel setuptools
      - run: scripts/create_package.sh ALL
      - uses: actions/upload-artifact@v4
        with:
          name: staging-deb-packages
          path: dist/*.deb
          retention-days: 7

  staging-deploy:
    runs-on: ubuntu-latest
    needs: [package]
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: staging-deb-packages
          path: dist/
      - name: Connect to Tailscale
        uses: tailscale/github-action@v4
        with:
          oauth-client-id: ${{ secrets.TS_OAUTH_CLIENT_ID }}
          oauth-secret: ${{ secrets.TS_OAUTH_SECRET }}
          tags: tag:ci
      - name: Deploy to staging server
        env:
          DEPLOY_HOST: ${{ secrets.TAILSCALE_IP }}
        run: |
          DEB_FILE=$(ls dist/a2a-gateway-test_*.deb | head -1)
          DEB_BASENAME=$(basename "$DEB_FILE")
          scp -o StrictHostKeyChecking=accept-new "$DEB_FILE" "root@${DEPLOY_HOST}:/tmp/"
          ssh -o StrictHostKeyChecking=accept-new "root@${DEPLOY_HOST}" bash -s << REMOTE
            set -euo pipefail
            dpkg -i "/tmp/${DEB_BASENAME}" || apt-get install -f -y
            sleep 3
            systemctl is-active a2a-gateway-test
            rm -f "/tmp/${DEB_BASENAME}"
          REMOTE

  staging-smoke:
    runs-on: ubuntu-latest
    needs: [staging-deploy]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: scripts/ci/install_deps.sh --with-test
      - name: Health check
        run: |
          for i in $(seq 1 10); do
            if curl -sf "https://test.example.com/v1/health" -o /dev/null; then
              echo "Health check passed (attempt $i)"
              exit 0
            fi
            sleep 5
          done
          exit 1
      - name: Smoke test
        run: |
          python scripts/stress_test.py \
            --base-url "https://test.example.com" \
            --customers 5 \
            --duration 15

  staging-report:
    runs-on: ubuntu-latest
    needs: [staging-smoke]
    if: always()
    steps:
      - name: Post staging result to PR
        uses: actions/github-script@v7
        with:
          script: |
            const smokeResult = '${{ needs.staging-smoke.result }}';
            const deployResult = '${{ needs.staging-deploy.result }}';
            const icon = smokeResult === 'success' ? '✅' : '❌';
            const status = smokeResult === 'success' ? 'PASSED' : 'FAILED';
            const body = [
              `## ${icon} Staging ${status}`,
              '',
              `| Step | Result |`,
              `|------|--------|`,
              `| Deploy | ${deployResult === 'success' ? '✅' : '❌'} ${deployResult} |`,
              `| Smoke tests | ${smokeResult === 'success' ? '✅' : '❌'} ${smokeResult} |`,
            ].join('\n');
            await github.rest.issues.createComment({
              owner: context.repo.owner,
              repo: context.repo.repo,
              issue_number: context.issue.number,
              body: body,
            });
```

### 1.3 Production Deployment (`.github/workflows/deploy-production.yml`)

**Triggers:** `workflow_dispatch` only, on `main` branch, requires typing "deploy" to confirm.

**Jobs (sequential chain):**

```
validate → package → deploy (requires 'production' environment approval) → smoke
```

| Job | What it does |
|-----|--------------|
| `validate` | Ensures branch is `main` and confirmation input is "deploy" |
| `package` | Builds production .deb |
| `deploy` | Connects via Tailscale, SCPs .deb, installs with auto-rollback on failure |
| `smoke` | Health check + stress test against production URL |

**Rollback strategy:** Before installing the new package, the deploy step:
1. Records the current package version
2. Backs up the currently installed .deb via `dpkg-repack`
3. Installs the new package
4. If the service fails to start, automatically reinstalls the backed-up .deb

```yaml
name: Deploy Production

on:
  workflow_dispatch:
    inputs:
      confirm:
        description: "Type 'deploy' to confirm production deployment"
        required: true

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - name: Validate branch and confirmation
        env:
          GIT_REF: ${{ github.ref }}
          CONFIRM: ${{ github.event.inputs.confirm }}
        run: |
          if [[ "$GIT_REF" != "refs/heads/main" ]]; then
            echo "Production deployments can only be triggered from main"
            exit 1
          fi
          if [[ "$CONFIRM" != "deploy" ]]; then
            echo "Confirmation required: type 'deploy' to proceed"
            exit 1
          fi

  package:
    runs-on: ubuntu-latest
    needs: [validate]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install wheel setuptools
      - run: scripts/create_package.sh a2a-gateway
      - uses: actions/upload-artifact@v4
        with:
          name: production-deb
          path: dist/*.deb
          retention-days: 30

  deploy:
    runs-on: ubuntu-latest
    needs: [package]
    environment: production   # <-- GitHub environment with approval gate
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: production-deb
          path: dist/
      - uses: tailscale/github-action@v4
        with:
          oauth-client-id: ${{ secrets.TS_OAUTH_CLIENT_ID }}
          oauth-secret: ${{ secrets.TS_OAUTH_SECRET }}
          tags: tag:ci
      - name: Deploy with rollback
        env:
          DEPLOY_HOST: ${{ secrets.TAILSCALE_IP }}
        run: |
          DEB_FILE=$(ls dist/a2a-gateway_*.deb | head -1)
          DEB_BASENAME=$(basename "$DEB_FILE")
          scp -o StrictHostKeyChecking=accept-new "$DEB_FILE" "root@${DEPLOY_HOST}:/tmp/"
          ssh -o StrictHostKeyChecking=accept-new "root@${DEPLOY_HOST}" bash -s -- "$DEB_BASENAME" << 'REMOTE'
            set -euo pipefail
            DEB_BASENAME="$1"
            BACKUP_DIR="/var/backups/a2a/deploy-$(date +%Y%m%d-%H%M%S)"
            mkdir -p "$BACKUP_DIR"
            dpkg-query -W -f='${Package}_${Version}_${Architecture}.deb\n' a2a-gateway 2>/dev/null \
              > "$BACKUP_DIR/previous_version.txt" || true
            if dpkg -s a2a-gateway >/dev/null 2>&1; then
              dpkg-repack a2a-gateway 2>/dev/null && mv a2a-gateway_*.deb "$BACKUP_DIR/" || true
            fi
            if dpkg -i "/tmp/$DEB_BASENAME"; then
              sleep 3
              if systemctl is-active a2a-gateway; then
                echo "[+] Service is active"
              else
                echo "[x] Service failed — rolling back"
                ROLLBACK_DEB=$(ls "$BACKUP_DIR"/a2a-gateway_*.deb 2>/dev/null | head -1)
                [[ -n "$ROLLBACK_DEB" ]] && dpkg -i "$ROLLBACK_DEB" && systemctl restart a2a-gateway || true
                exit 1
              fi
            else
              echo "[x] dpkg -i failed — rolling back"
              ROLLBACK_DEB=$(ls "$BACKUP_DIR"/a2a-gateway_*.deb 2>/dev/null | head -1)
              [[ -n "$ROLLBACK_DEB" ]] && dpkg -i "$ROLLBACK_DEB" && systemctl restart a2a-gateway || true
              exit 1
            fi
            rm -f "/tmp/$DEB_BASENAME"
          REMOTE

  smoke:
    runs-on: ubuntu-latest
    needs: [deploy]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: scripts/ci/install_deps.sh --with-test
      - name: Health check
        run: |
          for i in $(seq 1 10); do
            curl -sf "https://api.example.com/v1/health" -o /dev/null && exit 0
            sleep 5
          done
          exit 1
      - name: Smoke test
        run: |
          python scripts/stress_test.py \
            --base-url "https://api.example.com" \
            --customers 5 \
            --duration 15
```

### 1.4 Nightly Stress Test (`.github/workflows/nightly-stress.yml`)

**Triggers:** Cron `0 3 * * *` (daily 03:00 UTC) + manual `workflow_dispatch`.

Starts a local gateway server, provisions test agents, runs a configurable stress test (default: 20 concurrent customers, 60 seconds), uploads the report as an artifact.

---

## 2. Required GitHub Configuration

### 2.1 Repository Secrets

| Secret | Purpose |
|--------|---------|
| `TS_OAUTH_CLIENT_ID` | Tailscale OAuth client ID for VPN access to deploy targets |
| `TS_OAUTH_SECRET` | Tailscale OAuth secret |
| `TAILSCALE_IP` | IP address of the deploy target on the Tailscale network |
| `STRESS_ADMIN_KEY` | (Optional) Admin API key for nightly stress tests |

### 2.2 GitHub Environments

Create a `production` environment with:
- **Required reviewers** (approval gate before production deploy)
- Optionally restrict to `main` branch only

### 2.3 Required Branch Protection Rules (on `main`)

Enable these as **required status checks** before merge:
- `lint`
- `typecheck`
- `semgrep`
- `test`
- `security`
- `dependency-audit`

Recommended additional settings:
- Require PR reviews before merging
- Squash merge only
- Delete branches after merge

---

## 3. Git Workflow

```
main (protected)
  └── feat/my-feature    ← developer works here
  └── fix/bug-name
  └── refactor/cleanup
```

- Never push directly to `main`.
- Create `feat/`, `fix/`, `refactor/` branches.
- Open PRs to `main`. CI + Staging run automatically.
- Squash merge PRs to `main`.
- Production deploy is manual via `workflow_dispatch`.

---

## 4. Tool Configuration

### 4.1 Ruff (Linter + Formatter)

No `ruff.toml` needed if using defaults. If customization is needed:

```toml
# pyproject.toml or ruff.toml
[tool.ruff]
line-length = 120
target-version = "py312"

[tool.ruff.lint]
# Default rules are sufficient. CI runs:
#   ruff check .          (lint)
#   ruff format --check . (formatting)
```

### 4.2 Mypy (Type Checker)

```toml
# pyproject.toml
[tool.mypy]
python_version = "3.12"
strict = true
disallow_untyped_defs = true
plugins = ["pydantic.mypy"]
ignore_missing_imports = true
```

### 4.3 Pytest

```toml
# pyproject.toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### 4.4 Bandit (Security Scanner)

```toml
# pyproject.toml
[tool.bandit]
exclude_dirs = ["tests", "venv", ".venv"]
skips = ["B101"]   # allow assert in non-test code
```

CI invocation: `bandit -r <src_dirs> -ll -q --skip B101,B108,B608 --exclude '*/tests/*'`

### 4.5 Semgrep (SAST)

Runs in the official `semgrep/semgrep` container with `--config auto` (community rules). Excludes test files.

---

## 5. Supporting Scripts

### 5.1 `scripts/ci/install_deps.sh`

Installs Python runtime + optional test dependencies.

```bash
#!/usr/bin/env bash
set -euo pipefail

pip install --upgrade pip

# Runtime deps
pip install -r requirements.txt

# Test deps (when --with-test is passed)
if [[ "${1:-}" == "--with-test" ]]; then
  pip install pytest pytest-asyncio pytest-cov hypothesis
fi

# Install SDK in editable mode (if applicable)
pip install -e sdk/ 2>/dev/null || pip install sdk/ || true
```

### 5.2 `scripts/run_tests.sh`

Runs pytest per module with isolated PYTHONPATH.

```bash
#!/usr/bin/env bash
# Usage: scripts/run_tests.sh <module> [extra pytest args]
# Example: scripts/run_tests.sh gateway --cov=gateway --cov-fail-under=70
# Example: scripts/run_tests.sh products/billing

MODULE="$1"; shift
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

case "$MODULE" in
  gateway|sdk)
    export PYTHONPATH="$REPO_ROOT"
    ;;
  products/*)
    export PYTHONPATH="$REPO_ROOT:$REPO_ROOT/$MODULE"
    ;;
esac

python -m pytest "$MODULE" "$@" -q
```

### 5.3 `scripts/create_package.sh`

Builds Debian packages from `package/` definitions and SDK wheels.

```bash
#!/usr/bin/env bash
# Usage: scripts/create_package.sh ALL
# Usage: scripts/create_package.sh a2a-gateway

# For each package definition in package/<name>/:
#   1. Create staging dir
#   2. Copy DEBIAN/ control files
#   3. Copy opt/ content (dereference symlinks with cp -rL)
#   4. Copy usr/ content
#   5. Strip: .git, __pycache__, tests, *.pyc, .env, node_modules, caches
#   6. dpkg-deb --build → dist/<name>_<version>_all.deb

# For SDK: pip wheel --no-deps → dist/<name>.whl
```

### 5.4 `scripts/ci/docker_build_verify.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
TAG="${1:-a2a-gateway:ci}"
docker build -t "$TAG" .
CID=$(docker run -d -p 8000:8000 "$TAG")
trap "docker stop $CID && docker rm $CID" EXIT
sleep 5
curl -sf http://localhost:8000/v1/health
echo "Docker image verified"
```

---

## 6. Debian Packaging

### 6.1 Directory Layout

```
package/
├── a2a-gateway/                # Production package
│   ├── DEBIAN/
│   │   ├── control             # Package metadata + dependencies
│   │   ├── postinst            # Post-install: create user, migrate DB, enable+start service
│   │   └── prerm               # Pre-remove: stop service
│   ├── opt/a2a/                # Application code (symlinks to repo content)
│   └── usr/lib/systemd/system/ # Systemd unit file
│
├── a2a-gateway-test/           # Staging package (port 8001, data in /var/lib/a2a-test/)
│   ├── DEBIAN/
│   ├── opt/a2a-test/
│   └── usr/lib/systemd/system/
│
└── a2a-sdk/                    # Python wheel (built separately)
```

### 6.2 Control File Template

```
Package: a2a-gateway
Version: 0.3.0
Architecture: all
Depends: python3 (>= 3.12), nginx, sqlite3, curl, ufw
Maintainer: Team <team@example.com>
Description: Application gateway — production deployment
```

### 6.3 Deployment Strategy

- **Staging:** `a2a-gateway-test` package on port 8001, data in `/var/lib/a2a-test/`
- **Production:** `a2a-gateway` package on port 8000, data in `/var/lib/a2a/`
- Both coexist on the same server if needed (different service names, ports, data dirs)

---

## 7. Docker

### 7.1 Dockerfile Pattern

```dockerfile
# Stage 1: Base
FROM python:3.12-slim AS base
RUN groupadd -r app && useradd -r -g app app
RUN apt-get update && apt-get install -y --no-install-recommends sqlite3 curl && rm -rf /var/lib/apt/lists/*

# Stage 2: Dependencies (cached layer)
FROM base AS deps
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 3: Application
FROM deps AS app
COPY . .
RUN mkdir -p /var/lib/app && chown app:app /var/lib/app
VOLUME ["/var/lib/app"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
  CMD curl -sf http://localhost:8000/v1/health || exit 1
USER app
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
```

### 7.2 Docker Compose

```yaml
services:
  gateway:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - app-data:/var/lib/app
    env_file: .env
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:8000/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  app-data:
```

---

## 8. Monitoring (Optional)

A `monitoring/docker-compose.yml` runs the observability stack:

| Service | Port | Purpose |
|---------|------|---------|
| Prometheus | 9090 | Metrics collection (scrapes `/v1/metrics`) |
| Grafana | 3030 | Dashboards and alerting |
| Node Exporter | 9100 | Host-level system metrics |

---

## 9. Networking

### 9.1 Tailscale VPN

CI/CD connects to deploy targets via Tailscale mesh VPN:

1. CI runner joins the tailnet using `tailscale/github-action@v4` with OAuth credentials
2. Communicates with deploy server via its Tailscale IP (stored in `TAILSCALE_IP` secret)
3. Uses `tag:ci` for ACL-based access control

This avoids exposing SSH on the public internet.

### 9.2 Staging vs Production URLs

| Environment | URL | Package |
|-------------|-----|---------|
| Staging | `https://test.example.com` | `a2a-gateway-test` (port 8001) |
| Production | `https://api.example.com` | `a2a-gateway` (port 8000) |

Nginx handles TLS termination and reverse-proxies to the local uvicorn process.

---

## 10. Environment Variables

```bash
# Server
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=INFO

# Data directory
A2A_DATA_DIR=/var/lib/a2a

# Database DSNs (one per module, SQLite by default)
BILLING_DSN=sqlite:////var/lib/a2a/billing.db
PAYWALL_DSN=sqlite:////var/lib/a2a/paywall.db
PAYMENTS_DSN=sqlite:////var/lib/a2a/payments.db
MARKETPLACE_DSN=sqlite:////var/lib/a2a/marketplace.db
TRUST_DSN=sqlite:////var/lib/a2a/trust.db
EVENT_BUS_DSN=sqlite:////var/lib/a2a/events.db
WEBHOOK_DSN=sqlite:////var/lib/a2a/webhooks.db
IDENTITY_DSN=sqlite:////var/lib/a2a/identity.db
MESSAGING_DSN=sqlite:////var/lib/a2a/messaging.db
DISPUTE_DSN=sqlite:////var/lib/a2a/disputes.db

# Feature flags
DEFAULT_TIER=free

# External service keys (if applicable)
STRIPE_API_KEY=sk_test_...
GITHUB_TOKEN=ghp_...
```

---

## 11. Stress Test

The stress test (`scripts/stress_test.py`) simulates concurrent API usage:

**Pass criteria:**
- Error rate < 5%
- P95 latency < 5000ms
- P99 latency < 10000ms
- Throughput > 5 req/s

**Usage:**
```bash
python scripts/stress_test.py \
  --base-url "http://localhost:8000" \
  --customers 20 \
  --duration 60 \
  --ramp-up 10 \
  --admin-key "$ADMIN_KEY"
```

Outputs a markdown report uploaded as a CI artifact.

---

## 12. Adaptation Checklist

To apply this pipeline to a new project:

1. **Copy workflow files** from `.github/workflows/` (ci.yml, staging.yml, deploy-production.yml, nightly-stress.yml)
2. **Copy scripts/** (ci/install_deps.sh, run_tests.sh, create_package.sh, ci/docker_build_verify.sh, stress_test.py)
3. **Set up `pyproject.toml`** with ruff, mypy, pytest, bandit config (Section 4)
4. **Create `requirements.txt`** with pinned runtime dependencies
5. **Create `package/` directory** with Debian package definitions (Section 6)
6. **Create `Dockerfile`** (Section 7)
7. **Configure GitHub:**
   - Add secrets: `TS_OAUTH_CLIENT_ID`, `TS_OAUTH_SECRET`, `TAILSCALE_IP`
   - Create `production` environment with required reviewers
   - Enable branch protection on `main` with required status checks (Section 2.3)
8. **Set up Tailscale** on deploy target servers
9. **Update URLs** in staging.yml and deploy-production.yml to match your domain
10. **Update module paths** in ci.yml test steps and run_tests.sh to match your project structure

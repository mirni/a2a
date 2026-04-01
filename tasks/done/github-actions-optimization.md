# Prompt -- Optimization of github actions minutes usage

## Goal
I want to minimize the usage of GH actions minutes, since I am close to reaching limit on this repo (3000 mins/month) and I don't think I can upgrade.
At the same, I want a bullet-proof CI/CD pipeline for production code changes and tight release process. I also want to be able to bypass the CI/CD and push changes directly to `main` as needed (e.g. docs-only changes).

## Tasks
* Brainstorm ideas on how to save GH Actions minutes, e.g.
  ** Change workflow to run CI/CD only pre-merge not on each push or run some quality checks on nightly job only?
  ** Run some of the jobs locally: lint (fails often, then pipelines need to rerun), docker-build (takes longer), run semgrep and dependency audit only at night? I want to have high probability of the pipeline jobs passing once it's run on GH actions (as to not waste minutes on failed jobs).
  ** Is it possible to use GH Codespaces instead of Actions to offload work? How can we use Codespaces to our advantage?
  ** Self-hosted runner? Generate instructions on how to do this (Linux, either Ubuntu 24.04 or Debian 12).
* Summarize pros/cons of each solution, do not implement any changes.

## Output
* Actionable todo list for human to review.

---

## Analysis

### Current minute consumption per CI run

Each full CI run (PR or push-to-main) triggers **10 parallel jobs** on `ubuntu-latest`. GitHub bills per-job in **1-minute increments** (rounded up), so a 9-second lint job costs 1 billed minute.

| Job | Wall clock | Billed minutes |
|-----|-----------|----------------|
| lint | 9s | 1 |
| typecheck | 18s | 1 |
| security (bandit) | 13s | 1 |
| semgrep | 55s | 1 |
| dependency-audit | 18s | 1 |
| test (3.12) | ~2m30s | 3 |
| test (3.13) | ~2m30s | 3 |
| docker-build | 37s | 1 |
| package | 18s | 1 |
| staging (3 sub-jobs) | ~15s total | 3 (minimum 1 each) |
| **Total per CI run** | | **~16 billed minutes** |

**Additional workflows:**
- **Push to main** after PR merge: another ~16 minutes (duplicate run)
- **Nightly stress test**: ~15 minutes/night = ~450 min/month
- **Production deploy** (manual): ~5 minutes each

### Estimated monthly burn rate

Assuming 5 PRs/week with 2 push iterations each = 10 PR CI runs/week:

| Trigger | Runs/month | Minutes each | Total |
|---------|-----------|-------------|-------|
| PR pushes (CI) | ~40 | 16 | 640 |
| PR merge → push to main | ~20 | 16 | 320 |
| Failed PR runs (reruns) | ~15 | 10 (partial) | 150 |
| Nightly stress test | ~30 | 15 | 450 |
| Production deploy | ~4 | 5 | 20 |
| **Estimated total** | | | **~1,580** |

This is on the high side for 3,000 min/month. Double the PR activity or add more reruns from lint failures and you hit the cap.

---

## Options

### 1. Path-based filtering (skip CI for docs/config changes)

Skip the full pipeline when only docs, markdown, or non-code files changed.

**Implementation:** Add `paths-ignore` to `ci.yml`:
```yaml
on:
  pull_request:
    paths-ignore:
      - 'docs/**'
      - '*.md'
      - 'tasks/**'
      - 'reports/**'
      - 'plans/**'
      - 'logs/**'
      - '.gitignore'
      - 'LICENSE'
```

| Pros | Cons |
|------|------|
| Zero effort, immediate savings | Only helps for docs-only changes |
| No impact on code quality | Need to trust that docs changes don't break anything |
| Allows pushing docs direct to main without CI | |

**Savings:** ~5-10% (depends on doc-only push frequency)

---

### 2. Move fast-fail checks to a pre-commit hook / local script

Run lint + format locally before pushing, so the GH lint job almost never fails.

**Implementation:** Create a `scripts/pre-push-check.sh` that runs:
```bash
ruff check . && ruff format --check .
```
Or use a proper `pre-commit` framework (`.pre-commit-config.yaml`).

| Pros | Cons |
|------|------|
| Prevents wasted minutes on lint failures (most common failure) | Requires developer discipline / setup |
| Faster feedback loop (instant vs 1-2 min) | Claude Code already runs ruff, so this mainly protects human pushes |
| Free — no GH minutes used | Still need CI lint as safety net |

**Savings:** Eliminates ~100-200 min/month from lint-failure reruns.

---

### 3. Move semgrep + dependency-audit to nightly schedule

These are "audit" checks that catch supply-chain or SAST issues. They rarely fail on normal code changes and don't need to gate every PR.

**Implementation:** Move semgrep and dependency-audit into `nightly-stress.yml` (or a new `nightly-audit.yml`), remove from `ci.yml`.

| Pros | Cons |
|------|------|
| Saves 2 billed min per CI run (~80-100 min/month) | New vulnerabilities won't block PRs immediately |
| These checks are slow to surface actionable issues anyway | Nightly failures need a notification/alerting mechanism |
| Reduces CI job count from 10 → 8 | Audit debt could accumulate if nightly failures ignored |

**Savings:** ~80-120 min/month

---

### 4. Drop one Python version from the matrix (test only 3.13)

Currently testing on both 3.12 and 3.13. The test job is the most expensive (~3 billed min x 2 = 6 min).

**Implementation:** Remove `3.12` from the matrix, or run 3.12 only on nightly.

| Pros | Cons |
|------|------|
| Saves ~3 billed min per CI run (~120-150 min/month) | Misses Python 3.12-only regressions |
| 3.13 is a superset for most purposes | If you deploy on 3.12, this is risky |
| Can still run 3.12 nightly as safety net | |

**Savings:** ~120-150 min/month (or ~60-75 if you move 3.12 to nightly)

---

### 5. Skip push-to-main CI when PR was already green

When a PR merges to main, the push-to-main event triggers another full CI run. This is redundant since the PR CI already passed on the same code.

**Implementation:** Add a condition to skip the push-to-main run if the commit was a merge commit from a PR:
```yaml
on:
  push:
    branches: [main]
    paths-ignore:
      - 'docs/**'
      - '*.md'
```
Or more aggressively, remove the `push: branches: [main]` trigger entirely (rely on PR CI only).

| Pros | Cons |
|------|------|
| Saves ~16 min per merge (~320 min/month) | Main branch no longer has its own green check |
| Identical code was already tested in the PR | Squash merges slightly change the commit, but tests should still pass |
| Biggest single savings | Need branch protection to enforce "PR required" |

**Savings:** ~250-320 min/month (largest single optimization)

---

### 6. Docker build — only on PRs targeting main, not on every push

Docker build (37s wall, 1 billed min) verifies the image builds and the health check passes. This only matters for deployment-affecting changes.

**Implementation:** Add a path filter or make it conditional:
```yaml
docker-build:
  if: github.event_name == 'pull_request' && github.base_ref == 'main'
```

Or skip it on non-gateway changes:
```yaml
  paths:
    - 'gateway/**'
    - 'Dockerfile'
    - 'products/**'
```

| Pros | Cons |
|------|------|
| Saves 1 min per non-deployment CI run | Could miss Dockerfile regressions on other changes |
| Docker build is already covered by staging deploy | Low risk since it rarely fails independently |

**Savings:** ~20-40 min/month

---

### 7. Consolidate small jobs into one "quality" job

Lint (9s), typecheck (18s), security (13s) each cost 1 billed minute despite running for <20s. Combining them into a single job saves 2 billed minutes per run.

**Implementation:**
```yaml
quality:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
    - run: pip install ruff mypy pydantic aiosqlite cryptography httpx fastapi bandit
    - run: ruff check .
    - run: ruff format --check .
    - run: mypy ...
    - run: bandit ...
```

| Pros | Cons |
|------|------|
| Saves 2 billed min per run (~80-120 min/month) | If lint fails, typecheck doesn't run (slower feedback) |
| Fewer parallel jobs = less runner spin-up overhead | Single job failure message is less granular |
| Simpler workflow file | |

**Savings:** ~80-120 min/month

---

### 8. GitHub Codespaces as CI alternative

Codespaces is designed for development, not CI. It cannot replace Actions.

| What it can do | What it can't do |
|----------------|-----------------|
| Pre-configured dev environment (devcontainer.json) | Cannot be triggered by push/PR events |
| Human can run lint/tests interactively before pushing | No webhook integration for CI gates |
| Shared environment means consistent local checks | Minutes come from a separate quota (120 core-hours/month free) |

**Verdict:** Codespaces does not replace CI, but it can help you run checks locally before pushing (similar to option 2). Not actionable for minute savings.

---

### 9. Self-hosted runner

Run CI on your own hardware. GH Actions minutes for self-hosted runners are **free** (unlimited).

**Setup instructions for Ubuntu 24.04 / Debian 12:**

```bash
# 1. Create a dedicated user
sudo useradd -m -s /bin/bash github-runner
sudo usermod -aG docker github-runner  # if docker builds needed

# 2. Download the runner
cd /home/github-runner
sudo -u github-runner bash
mkdir actions-runner && cd actions-runner
curl -o actions-runner-linux-x64-2.322.0.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.322.0/actions-runner-linux-x64-2.322.0.tar.gz
tar xzf ./actions-runner-linux-x64-2.322.0.tar.gz

# 3. Configure (get token from: Settings > Actions > Runners > New self-hosted runner)
./config.sh --url https://github.com/mirni/a2a --token YOUR_RUNNER_TOKEN

# 4. Install as systemd service
sudo ./svc.sh install github-runner
sudo ./svc.sh start

# 5. Install CI dependencies
sudo apt-get update && sudo apt-get install -y \
  python3.12 python3.13 python3-pip python3-venv \
  docker.io curl sqlite3 git

# 6. Update ci.yml to use self-hosted runner
# Change: runs-on: ubuntu-latest
# To:     runs-on: self-hosted
```

| Pros | Cons |
|------|------|
| **Unlimited free minutes** — all CI concerns vanish | You maintain the hardware (uptime, security, updates) |
| Faster builds (no cold-start, cached deps persist) | Runner must be online 24/7 or jobs queue |
| Can reuse Docker layer cache across runs | Security risk: PR code runs on your machine |
| Can run on your existing staging server | Single point of failure |
| Pre-installed deps = faster pip installs | Need to keep runner version updated |

**Savings:** All ~1,580 min/month → 0 billed minutes

**Security note:** For public repos, self-hosted runners are risky (anyone can open a PR that runs arbitrary code on your machine). For private repos, this is safe. If your repo is public, use a **dedicated VM** (not your staging server) and consider ephemeral runners.

---

## Recommended action plan (ordered by impact)

### Tier 1: Do now (largest savings, minimal risk)

| # | Action | Est. savings | Effort |
|---|--------|-------------|--------|
| 1 | **Remove `push: main` trigger from CI** — rely on PR CI only | ~300 min/month | 1 line change |
| 2 | **Add `paths-ignore` for docs/md/tasks** | ~50 min/month | 5 lines |
| 3 | **Consolidate lint+typecheck+security into one "quality" job** | ~100 min/month | 30 min refactor |
| 4 | **Move semgrep + dep-audit to nightly** | ~100 min/month | 15 min refactor |

**Tier 1 total: ~550 min/month saved** (reduces burn from ~1,580 → ~1,030)

### Tier 2: Do soon (moderate savings)

| # | Action | Est. savings | Effort |
|---|--------|-------------|--------|
| 5 | **Drop Python 3.12 from PR matrix, run nightly only** | ~75 min/month | 10 min |
| 6 | **Add pre-push hook for ruff** | ~100 min/month (fewer reruns) | 20 min |
| 7 | **Skip docker-build on non-gateway changes** | ~30 min/month | 5 lines |

**Tier 1+2 total: ~755 min/month saved** (reduces burn to ~825)

### Tier 3: If still hitting limits

| # | Action | Est. savings | Effort |
|---|--------|-------------|--------|
| 8 | **Self-hosted runner** | All remaining minutes | 1-2 hours setup |

### Not recommended

| Action | Why |
|--------|-----|
| Codespaces as CI | Doesn't work as CI replacement, different quota |
| Remove docker-build entirely | Catches real issues; keep it but make conditional |
| Remove push-to-main AND PR CI | Need at least one gate |

## Completed
- 2026-03-31 — Analysis completed, no code changes made (research-only task)

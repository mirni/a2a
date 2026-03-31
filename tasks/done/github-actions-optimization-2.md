# Prompt 2 -- Optimization of github actions minutes usage -- changes

## Goal
I want to minimize the usage of GH actions minutes, since I am close to reaching limit on this repo (3000 mins/month) and I don't think I can upgrade.
At the same, I want a bullet-proof CI/CD pipeline for production code changes and tight release process. I also want to be able to bypass the CI/CD and push changes directly to `main` as needed (e.g. docs-only changes).
Keep the CI light.
Make the release thorough.


## Tasks
* Per your feedback in `done/github-actions-optimization.md`, please do the following changes:
  ** Do not run CI pipeline on each push into feature branch. I want the CI to be run only at the point of merge into `main`.
  ** Do not add pre-push hooks, I want to be able to push anything anywhere (hotfix).
  ** The server is currently using python 3.12.3. Do not run the "test (3.13)" job, but keep it in the yml file (commented or inactive) for future use.
  ** Combine the short jobs (lint, typecheck, security) into one job, called `quality`.
  ** Run `quality` job locally before opening a PR (using the same script that the CI pipeline uses).
  ** Consolidate the staging sub-jobs into one `staging` job which does the staging, smoke test and report.
  ** Do not run `docker-build` in CI (only in release pipeline).
  ** Consolidate `dependency_audit` and `semgrep` into one job (called `sast`) and run only at release.
  ** Add `paths-ignore` for docs/md/tasks/...
* Do not implement nightly build.
* Make sure the `release.sh` trigger to release runs all jobs (full CI/CD):
  ** test, quality, docker-build, sast, staging (staging to test, smoke test, staging report), deploy to live server.

## Completed

**Date:** 2026-03-31

**Summary:** Optimized CI/CD pipeline to reduce billed minutes from ~16 to ~5 per PR run.

**Changes:**
- **`ci.yml`** — Rewritten: PR-only trigger, `paths-ignore` for docs/reports/tasks/plans/logs/*.md, 3 jobs (quality, test, package) + staging for PRs targeting main. Removed: separate lint/typecheck/security jobs, semgrep, dep-audit, test(3.13), docker-build.
- **`release.yml`** — NEW: Full pipeline for `release/*` branches (quality, sast, test, docker-build, package, staging). Triggered by `release.sh` step 7.
- **`staging.yml`** — Consolidated 3 jobs (deploy, smoke, report) into 1 job with sequential steps.
- **`scripts/ci/quality.sh`** — NEW: Local quality check script (ruff + mypy + bandit).

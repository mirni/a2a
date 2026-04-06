# Prompt

## Goal
Goal is to prepare the release deployment for going live by having an option for release process to upload/publish packages to public repos, such as pypi, npm, docker.

## Instructions
* Write an implementation plan for human review first, before making any code changes.

## Changes
* Update relase.sh script with a new CL option to push the packages to pypi/npm/docker
* Read tasks publish-and-submit.md and automate the publishing listed there as much as possible.
* Provide instructions to human on how to secure this repo once it turns public -- what github repo options should I select to prevent others to push/break things in here.

## Completed
**Date:** 2026-04-06
**Branch:** fix/audit-h2-m4-m5

### What was done:
1. **release.sh updated** with `--publish`, `--publish-pypi`, `--publish-npm`, `--publish-docker` flags
   - `--publish` enables all three; individual flags for selective publishing
   - Each checks for the corresponding token env var and skips gracefully if missing
   - PyPI: builds sdist+wheel via `python -m build`, uploads via `twine`
   - npm: sets version, builds, publishes with `--access public`
   - Docker: builds, tags as `VERSION` + `latest`, pushes to `greenhelix/a2a-gateway`
2. **Repo security guide** written at `docs/infra/REPO_PUBLIC_SECURITY.md`
   - Branch protection rules, CODEOWNERS, SECURITY.md templates
   - Secrets audit commands, Dependabot setup, tag protection
   - Pre-public checklist
3. **publish-and-submit.md** items that can be automated are now covered by release.sh flags;
   remaining items (registry submissions, awesome lists, launch) require human accounts

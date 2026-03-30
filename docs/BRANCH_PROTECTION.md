# GitHub Branch Protection Setup

Configure branch protection rules for the `main` branch to enforce the
feature-branch workflow with mandatory CI + staging gates.

## Steps

### 1. Navigate to branch protection settings

1. Go to **Settings** → **Branches** in the GitHub repository
2. Click **Add branch protection rule** (or edit existing rule for `main`)
3. Set **Branch name pattern** to `main`

### 2. Configure required checks

Enable the following options:

- [x] **Require a pull request before merging**
  - [x] Require approvals (at least 1)
  - [x] Dismiss stale pull request approvals when new commits are pushed
  - [ ] Require review from Code Owners (optional)

- [x] **Require status checks to pass before merging**
  - [x] Require branches to be up to date before merging
  - Add these **required status checks**:
    - `lint`
    - `test (3.12)`
    - `test (3.13)`
    - `staging-smoke`

- [x] **Do not allow bypassing the above settings**
  - Prevents admins from bypassing the rules

### 3. Restrict direct pushes

- [x] **Restrict who can push to matching branches**
  - Leave the list empty to block all direct pushes
  - All changes must go through pull requests

### 4. Optional but recommended

- [x] **Require linear history** — keeps commit history clean (squash or rebase)
- [x] **Require signed commits** — if your team uses GPG signing
- [ ] **Include administrators** — check this to enforce on repo admins too

## Verification

After configuring:

1. Create a test branch and push a commit
2. Open a PR targeting `main`
3. Verify that the PR cannot be merged until `lint`, `test`, and `staging-smoke` pass
4. Verify that direct pushes to `main` are rejected

## Required GitHub Secrets

These secrets must be configured in **Settings** → **Secrets and variables** → **Actions**:

| Secret | Purpose |
|--------|---------|
| `STAGING_SSH_KEY` | SSH private key for deploying to the staging server |
| `STAGING_HOST` | Hostname/IP of the staging server |
| `PROD_SSH_KEY` | SSH private key for deploying to production |
| `PROD_HOST` | Hostname/IP of the production server |

## Required GitHub Environment

Create a `production` environment in **Settings** → **Environments**:

1. Click **New environment**, name it `production`
2. Enable **Required reviewers** and add at least one team member
3. Optionally restrict to the `main` branch only

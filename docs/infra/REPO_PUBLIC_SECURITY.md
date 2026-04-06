# Securing the Repository for Public Access

**Audience:** Repository owner (human) preparing to make `mirni/a2a` public.

---

## 1. Branch Protection Rules

Go to **Settings > Branches > Add rule** for `main`:

- [x] **Require a pull request before merging**
  - Require approvals: 1
  - Dismiss stale PR approvals when new commits are pushed
  - Require review from code owners
- [x] **Require status checks to pass before merging**
  - Require branches to be up to date
  - Add required checks: `quality`, `sast`, `docker-build` (from CI workflow)
- [x] **Require signed commits** (optional but recommended)
- [x] **Do not allow bypassing the above settings** (even for admins)
- [x] **Restrict who can push to matching branches** — only the repo owner
- [x] **Do not allow force pushes**
- [x] **Do not allow deletions**

## 2. Repository Settings

Go to **Settings > General**:

- **Default branch**: `main`
- **Features**: disable Wiki (use `docs/` instead), disable Projects if unused
- **Pull Requests**: enable "Automatically delete head branches"
- **Merge button**: allow only "Squash and merge" (keeps main history clean)

## 3. Secrets Audit

**Before going public**, verify none of these are committed:

```bash
# Search for potential secrets
grep -rn "sk_live_\|sk_test_\|whsec_\|github_pat_\|pypi-\|npm_\|dckr_pat_" \
  --include="*.py" --include="*.sh" --include="*.yml" --include="*.md" \
  --include="*.json" --include="*.toml" . | grep -v ".env" | grep -v node_modules
```

**Critical files that must NOT be committed:**
- `.env` (should be in `.gitignore`)
- Any file containing API keys, tokens, or passwords
- `live-wallets.json` or any audit credential bundles

**Verify `.gitignore` includes:**
```
.env
*.db
live-wallets.json
dist/
```

## 4. GitHub Actions Secrets

Go to **Settings > Secrets and variables > Actions**:

Ensure these are stored as **repository secrets** (not in code):
- `GITHUB_DEPLOYMENT_TOKEN` — for CI/CD
- `STRIPE_API_KEY` — Stripe secret key (for staging smoke tests)
- `STRIPE_WEBHOOK_SECRET` — webhook signing secret
- `PYPI_DEPLOYMENT_TOKEN` — PyPI publish token
- `NPM_DEPLOYMENT_TOKEN` — npm publish token
- `DOCKER_DEPLOYMENT_TOKEN` — Docker Hub PAT
- `TS_OAUTH_CLIENT_ID` / `TS_OAUTH_SECRET` / `TAILSCALE_IP` — staging deploy

## 5. CODEOWNERS

Create `.github/CODEOWNERS`:

```
# Default owner for everything
* @mirni

# Critical paths require explicit review
.github/workflows/ @mirni
scripts/release.sh @mirni
scripts/deploy*.sh @mirni
Dockerfile @mirni
.env.example @mirni
```

## 6. Security Policy

Create `.github/SECURITY.md`:

```markdown
# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities via email to security@greenhelix.net.

Do NOT open a public GitHub issue for security vulnerabilities.

We will acknowledge receipt within 48 hours and provide a timeline for a fix.

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest  | Yes       |
| < latest | No       |
```

## 7. Dependency Security

- Enable **Dependabot alerts** (Settings > Security > Code security)
- Enable **Dependabot security updates** (auto-PRs for vulnerable deps)
- Enable **Secret scanning** (detects accidentally committed tokens)
- Enable **Push protection** (blocks pushes containing secrets)

## 8. Tag Protection

Go to **Settings > Tags > Add rule**:
- Pattern: `v*`
- Only maintainers can create matching tags

## 9. Pre-Public Checklist

- [ ] Run `grep -rn` secrets scan (step 3)
- [ ] Review git history for accidentally committed secrets: `git log --all -p | grep -i "sk_live_\|password\|secret" | head -50`
- [ ] If secrets found in history, rotate them and consider using `git filter-repo` to remove
- [ ] Set up branch protection (step 1)
- [ ] Add CODEOWNERS file (step 5)
- [ ] Add SECURITY.md (step 6)
- [ ] Enable Dependabot + secret scanning (step 7)
- [ ] Verify `.env.example` has no real values (only placeholders)
- [ ] Set repository visibility to **Public**

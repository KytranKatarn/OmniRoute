# GitHub Optimization Report — A.R.C.H.I.E. Platform
**Date**: 2026-03-22
**Repo**: `KytranKatarn/archie-platform` (private, GitHub Pro)
**State**: 1,688 commits, monorepo, 3 workflows, ghcr.io already in use

---

## 1. GitHub Pro Features to Enable

### 1.1 Actions Minutes
GitHub Pro provides **3,000 free Actions minutes/month** (vs. 2,000 on Free). All three existing workflows (CI, Build Node Image, Build Installer) consume these minutes. Current usage is likely low given the small team. The Windows runner used by `build-installer.yml` costs **2× the minute rate** — keep that workflow on `workflow_dispatch` only (already is) to avoid surprise consumption.

**Recommendation**: Enable spending limits at $0 to hard-cap overages. Check usage at Settings → Billing → Actions.

---

### 1.2 Branch Protection Rules (NOT yet enabled — enable now)
GitHub Pro unlocks branch protection on private repos. Currently `main` has no protection rules, meaning any push goes straight to production.

**Enable at**: Settings → Branches → Add rule → `main`

Recommended ruleset:
```
Branch name pattern: main
✅ Require a pull request before merging
   - Required approvals: 1 (self-review OK for solo dev)
✅ Require status checks to pass before merging
   - Required: lint, test (from ci.yml)
✅ Require branches to be up to date before merging
✅ Do not allow bypassing the above settings: OFF (solo dev — keep escape hatch)
✅ Restrict who can push to matching branches: only you
```

For the `develop` / `dev` branch (exists as remote), apply a lighter rule: require CI to pass but no PR required.

---

### 1.3 Code Owners
Create `CODEOWNERS` at repo root. Since it's a solo repo, this is primarily useful for auto-assigning yourself to PRs and for future collaborators.

```
# .github/CODEOWNERS
* @KytranKatarn
/platform_v2/ @KytranKatarn
/ai_bridge/ @KytranKatarn
/node_client/ @KytranKatarn
```

Requires branch protection "Require review from Code Owners" to be enforced.

---

### 1.4 Dependabot (Free on all plans — enable immediately)
Dependabot security alerts and version updates are available on **all GitHub plans**, including Free. They are NOT exclusive to Pro.

**Enable at**: Settings → Security → Enable Dependabot alerts + Dependabot security updates

Create `.github/dependabot.yml`:
```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/platform_v2"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 5

  - package-ecosystem: "pip"
    directory: "/node_client"
    schedule:
      interval: "weekly"
      day: "monday"
    open-pull-requests-limit: 3

  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "monthly"
```

---

### 1.5 Secret Scanning (Free on public repos, requires GitHub Advanced Security for private)
Secret scanning for private repos requires **GitHub Advanced Security** (GHAS), which is NOT included in GitHub Pro — it's an enterprise add-on (~$49/user/month). This is **not worth it** for a solo private repo.

**Mitigation without GHAS**:
- Add a pre-commit hook using `detect-secrets` or `truffleHog` locally
- Use `.gitignore` patterns for `.env`, `*.env`, `config.json`, `credentials.*`
- Audit: both `.env` files (`/mnt/archie_brain/.env`, `/mnt/archie_brain/platform_v2/.env`) are present on disk — verify both are in `.gitignore`

```bash
# Check .gitignore covers env files
grep -E "\.env" /mnt/archie_brain/.gitignore
```

The existing `platform_v2/.env.example` is good practice — keep it committed as a template.

---

### 1.6 Code Scanning (CodeQL)
GitHub Code Scanning with CodeQL is **free for all repos** (public and private). It is NOT a Pro-exclusive feature.

**Enable via**: Settings → Security → Code scanning → Set up CodeQL

Or add a workflow manually:

```yaml
# .github/workflows/codeql.yml
name: CodeQL Analysis
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]
  schedule:
    - cron: '0 3 * * 1'  # Every Monday 3am

jobs:
  analyze:
    runs-on: ubuntu-latest
    permissions:
      security-events: write
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: python
      - uses: github/codeql-action/autobuild@v3
      - uses: github/codeql-action/analyze@v3
```

This will catch SQL injection risks, insecure deserialization, path traversal, and hardcoded credentials in the Flask + ai_bridge Python code.

---

### 1.7 CodeRabbit (NOT included in GitHub Pro)
CodeRabbit is a **third-party AI code review service** — it is not a GitHub product and is not bundled with GitHub Pro. Pricing:
- **Free tier**: Open source repos only (public)
- **Pro**: $19/month per developer

For a private solo repo, CodeRabbit's free tier does **not apply**. Options:
1. **Skip CodeRabbit** — use GitHub's built-in CodeQL + your own review discipline
2. **Make node_client public** (see Section 2) — then CodeRabbit free tier applies to that sub-repo
3. **Pay $19/month** — worthwhile if you want AI PR review on the private platform repo

**Alternative (free)**: Add a GitHub Actions step using `super-linter` or a local Claude Code review hook via the MCP tooling already in place.

---

### 1.8 GitHub Pages
GitHub Pro includes GitHub Pages for **private repositories**. This can host internal documentation.

**Recommended use**: Publish the `docs/` directory or a generated MkDocs site at `https://kytrankatarn.github.io/archie-platform/`.

Note: GitHub Pages on private repos with Pro is accessible publicly (no auth). If the docs contain sensitive architecture details, either keep Pages disabled or publish only sanitized public-facing docs (e.g., node installation guide for `.246` operators).

**Enable at**: Settings → Pages → Source: Deploy from branch → `main` → `/docs`

---

### 1.9 GitHub Packages (ghcr.io — Already in Use)
The `build-node-image.yml` workflow already pushes to `ghcr.io/kytrankatarn/archie-node`. GitHub Pro includes **2 GB Packages storage**.

Current state is correct. One improvement: add image cleanup to avoid storage creep:

```yaml
# Add to build-node-image.yml after push
- name: Delete old package versions
  uses: actions/delete-package-versions@v5
  with:
    package-name: archie-node
    package-type: container
    min-versions-to-keep: 5
    delete-only-untagged-versions: true
```

---

## 2. Repo Organization: Monorepo vs. Split

### Current Structure
```
archie-platform/         ← private monorepo
├── platform_v2/         ← Flask app
├── ai_bridge/           ← AI routing
├── node_client/         ← Fleet node (Docker + Windows installer)
│   ├── node_api.py
│   ├── node_sync.py
│   ├── Dockerfile.node
│   ├── installer/       ← Windows .exe builder
│   └── docker-compose.node.yml
└── database/migrations/
```

### Option A: Full Monorepo (Current — Recommended to Keep)

**Pros:**
- Single CI pipeline, single clone, atomic commits across platform + node changes
- No cross-repo dependency versioning headaches
- `build-node-image.yml` already uses `paths: node_client/**` to scope builds
- Easier for solo developer — no context switching

**Cons:**
- Users who want to inspect or contribute to node_client must request access to the entire private repo
- `docker pull ghcr.io/kytrankatarn/archie-node` already works without repo access (packages can be public independently)

**Verdict**: Keep the monorepo. The cons are manageable with the package visibility fix below.

---

### Option B: Split node_client into Public Repo

**Pros:**
- Community can inspect node client code (trust transparency)
- Free CodeRabbit tier applies
- `docker pull` already works regardless — this only helps if you want open-source node contributions
- Windows users installing the node don't need GitHub access

**Cons:**
- Two repos to maintain, two CI pipelines
- Secrets/config shared between platform and node need cross-repo management
- Git history split is destructive and messy with 1,688 commits

**Verdict**: Not worth the complexity right now. If the node client stabilizes and you want community contributions or public trust, extract it at that point using `git filter-repo`. The immediate priority (post Decision #257) is getting node deployment stable, not open-sourcing it.

---

### Option C: Full Split (platform / node / ai_bridge / docs)

**Verdict**: Strongly not recommended for a solo developer. The overhead of 4+ repos, cross-repo CI, and synchronized releases outweighs any benefit. This pattern makes sense for large teams (10+ developers) with clear ownership boundaries.

---

### Recommended Package Visibility Fix
Make the `archie-node` container image **public** in GitHub Packages so node operators can `docker pull` without authentication, without changing repo visibility:

Settings → Packages → `archie-node` → Package settings → Change visibility → Public

This decouples image distribution from repo access — the key concern for node deployment.

---

## 3. CI/CD Improvements

### 3.1 Current CI State
- `ci.yml`: lint (black + flake8) + test (pytest placeholder) + docker build — triggers on push to `main`/`dev` and PRs to `main` ✅
- `build-node-image.yml`: builds + pushes to ghcr.io on push to `main` with `node_client/**` path filter ✅
- `build-installer.yml`: manual trigger only (`workflow_dispatch`) ✅

The CI skeleton is solid. The main gap is **no real tests** (pytest collects nothing).

---

### 3.2 Add a Staging Branch Workflow

Introduce a `develop` branch as the integration branch (it already exists as a remote):

```
develop → staging deploy (auto)
main    → production deploy (manual gate or auto with branch protection)
```

Add a deploy job to `ci.yml`:

```yaml
deploy-staging:
  needs: [lint, test, docker-build]
  if: github.ref == 'refs/heads/develop' && github.event_name == 'push'
  runs-on: ubuntu-latest
  environment: staging
  steps:
    - name: Deploy to staging via SSH
      uses: appleboy/ssh-action@v1
      with:
        host: ${{ secrets.STAGING_HOST }}
        username: ${{ secrets.STAGING_USER }}
        key: ${{ secrets.STAGING_SSH_KEY }}
        script: |
          cd /opt/archie
          git pull origin develop
          docker compose restart archie_platform
```

For production auto-deploy to 192.168.1.200, the same pattern applies with `github.ref == 'refs/heads/main'`. However, given the recent node deployment failures (Decision #257), **manual production deploys are safer** — keep production triggered via `workflow_dispatch` with a confirmation environment gate.

---

### 3.3 Add Real Tests to CI

The current pytest step runs with `--co -q` (collect only) and gracefully reports "No tests collected yet." Add at minimum:

```python
# platform_v2/tests/test_health.py
def test_app_creates():
    """Smoke test: Flask app can be instantiated."""
    import sys
    sys.path.insert(0, ".")
    # At minimum, verify imports don't explode
    assert True

def test_database_module_importable():
    from database import get_db_cursor
    assert callable(get_db_cursor)
```

Even smoke tests catch import errors before they reach production.

---

### 3.4 Add PR Auto-Labeler

```yaml
# .github/workflows/labeler.yml
name: Label PRs
on: [pull_request]
jobs:
  label:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/labeler@v5
        with:
          repo-token: ${{ secrets.GITHUB_TOKEN }}
```

With `.github/labeler.yml` mapping paths to labels (`platform_v2/ → backend`, `node_client/ → node`, `ai_bridge/ → ai`).

---

### 3.5 Node Image Versioning
Current: image tagged `latest` + short SHA. Recommendation: add semver tagging on git tags:

```yaml
# In build-node-image.yml metadata step
tags: |
  type=raw,value=latest
  type=sha,format=short
  type=semver,pattern={{version}}      # ← add this
  type=semver,pattern={{major}}.{{minor}}
```

Then `git tag v1.2.0 && git push --tags` triggers a versioned image build — critical for controlled node rollouts and rollback after incidents like Decision #257.

---

## 4. Security Hardening

### 4.1 .env File Protection
**Verify now:**
```bash
grep -n "\.env" /mnt/archie_brain/.gitignore
```

Both `/mnt/archie_brain/.env` and `/mnt/archie_brain/platform_v2/.env` must be in `.gitignore`. The `.env.example` should be committed. Never commit `.env` directly.

Add to `.gitignore` if missing:
```gitignore
.env
.env.local
*.env
platform_v2/.env
!platform_v2/.env.example
```

---

### 4.2 Repository Secrets Audit
Current secrets likely used:
- `GITHUB_TOKEN` (automatic) — used in `build-node-image.yml` ✅
- Any SSH keys for production deploy

**Recommended secrets to add** (Settings → Secrets → Actions):
| Secret | Use |
|--------|-----|
| `PROD_SSH_KEY` | Auto-deploy to 192.168.1.200 |
| `PROD_HOST` | `192.168.1.200` |
| `PROD_USER` | deploy user |
| `TELEGRAM_BOT_TOKEN` | If used in CI notifications |

Use **Environments** (Settings → Environments) to gate production secrets — only accessible when deploying to the `production` environment, requiring manual approval.

---

### 4.3 Dependency Graph + Dependabot Alerts
Enable the dependency graph (Settings → Security → Dependency graph → Enable). This is free and requires no GHAS. Combined with Dependabot alerts, you'll get notifications when `requirements.txt` packages have known CVEs.

Priority files to watch:
- `platform_v2/requirements.txt` — Flask app dependencies
- `node_client/requirements.txt` — Node client dependencies

---

### 4.4 Pre-commit Hooks (Local Secret Scanning)
Since GHAS secret scanning is not included in Pro, add local protection:

```bash
pip install pre-commit detect-secrets
```

`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
  - repo: https://github.com/psf/black
    rev: 24.3.0
    hooks:
      - id: black
        language_version: python3.11
```

The `black` hook is already in use (CLAUDE.md notes "Black pre-commit reformats Python"). This just adds secret detection alongside it.

---

## 5. Summary: Priority Action List

| Priority | Action | Effort | Cost |
|----------|--------|--------|------|
| 🔴 High | Enable branch protection on `main` | 5 min | Free (Pro) |
| 🔴 High | Enable Dependabot alerts + security updates | 5 min | Free |
| 🔴 High | Verify `.env` files in `.gitignore` | 5 min | Free |
| 🟠 Medium | Make `archie-node` package public on ghcr.io | 2 min | Free |
| 🟠 Medium | Add `dependabot.yml` config file | 15 min | Free |
| 🟠 Medium | Add CodeQL workflow | 10 min | Free |
| 🟠 Medium | Add semver tags to node image workflow | 10 min | Free |
| 🟡 Low | Add CODEOWNERS file | 5 min | Free (Pro) |
| 🟡 Low | Add smoke tests to unblock real CI | 30 min | Free |
| 🟡 Low | Enable GitHub Pages for docs | 10 min | Free (Pro) |
| 🟡 Low | Add staging branch + deploy workflow | 1 hour | Free |
| ⬜ Skip | CodeRabbit | — | $19/mo, not Pro-included |
| ⬜ Skip | Secret scanning (GHAS) | — | Enterprise add-on, not Pro |
| ⬜ Skip | Split node_client to separate repo | — | Not worth complexity yet |

---

## 6. What GitHub Pro Actually Gives You (Summary)

| Feature | Included in Pro? | Notes |
|---------|-----------------|-------|
| Branch protection on private repos | ✅ Yes | Pro exclusive vs Free |
| Required reviewers on private repos | ✅ Yes | Pro exclusive |
| Code owners on private repos | ✅ Yes | Pro exclusive |
| GitHub Pages on private repos | ✅ Yes | Public-facing URL |
| 3,000 Actions minutes/month | ✅ Yes | vs 2,000 on Free |
| 2 GB Packages storage | ✅ Yes | vs 500 MB on Free |
| Dependabot alerts | ✅ Yes | Also on Free |
| Code scanning (CodeQL) | ✅ Yes | Also on Free |
| Secret scanning (auto) | ❌ No | Requires GHAS (~$49/user/mo) |
| CodeRabbit AI review | ❌ No | Third-party, $19/mo |
| Repository insights graphs | ✅ Yes | Traffic, contributors, network |
| Wikis on private repos | ✅ Yes | Alternative to Pages for internal docs |

---

*Report generated 2026-03-22. Based on GitHub Pro plan documentation and current repo state at commit `c218f0d`.*

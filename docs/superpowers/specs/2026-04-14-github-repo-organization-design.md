# GitHub Repository Organization — Design Spec

> **Goal:** Separate all standalone products and websites from `archie_brain` into independent git repos with proper documentation, security, and public-facing polish. Prepare Kytran Empowerment's GitHub presence for public visibility — portfolio, open source community, and grant/funding credibility.

**Approach:** B + C hybrid — incremental migration (one repo at a time), with fresh history pushes for repos that have leaked secrets or internal data.

---

## 1. Directory Structure

```
/mnt/archie_brain/                          → archie-platform (PRIVATE)
  platform_v2/                              Only platform code remains here
  ai_bridge/
  database/
  docker-compose.yml
  ...

/mnt/standalone/                            → All standalone products + websites
  kytran-server-manager/                    → kytran-system-operations (PUBLIC, fresh history)
  kytran-creed/                             → kytran-creed (PUBLIC, keep history)
  kytran-business-suite/                    → kytran-business-suite (PRIVATE)
  kytran-civic-watch/                       → kytran-civic-watch (PRIVATE)
  kytran-legal-watch/                       → kytran-legal-watch (PRIVATE)
  kytran-market-watch/                      → kytran-market-watch (PRIVATE)
  kytran-gov-watch/                         → kytran-gov-watch (PRIVATE)
  kytran-news/                              → kytran-news (PRIVATE)
  archie-code/                              → archie-code (PUBLIC, keep history)
  websites/
    kytranempowerment.com/                  → kytranempowerment-site (PUBLIC, fresh push)
    creed-ai.org/                           → creed-ai-site (PUBLIC, fresh)
    what-the-fact.com/                      → what-the-fact-site (PUBLIC, fresh)
    thenews.kytranempowerment.com/          → kytran-news-site (PUBLIC, fresh)
```

### Key Principles
- `archie_brain` becomes clean — only private platform code, no nested repos
- Each product has its own directory, own git repo, own GitHub remote
- Docker compose files reference `/mnt/standalone/` paths (symlinks as fallback)
- `archie-node` stays as-is on GitHub (Docker image, not local code)
- `archie-platform-1` gets archived on GitHub (stale duplicate, 30 commits from March 2026)

---

## 2. Repo Registry

### Already on GitHub

| Repo | Visibility | Action | History |
|------|-----------|--------|---------|
| `archie-platform` | PRIVATE | Keep as-is, clean up gitignore | Keep |
| `archie-platform-1` | PRIVATE | Archive | N/A |
| `archie-code` | PUBLIC | Move to `/mnt/standalone/` | Keep (clean) |
| `archie-node` | PUBLIC | No local changes needed | Keep (clean) |
| `kytran-system-operations` | PUBLIC | Move to `/mnt/standalone/`, fresh history push | Fresh (leaked IPs) |
| `kytran-creed` | PUBLIC | Move to `/mnt/standalone/` | Keep (clean) |
| `kytranempowerment-site` | PUBLIC | Nuke, re-push with current site | Fresh (stale content) |

### New GitHub Repos — Products (PRIVATE)

| Repo | Source Path | Notes |
|------|------------|-------|
| `kytran-civic-watch` | `/mnt/archie_brain/watch-api/` | Runs on VPS :8099 |
| `kytran-legal-watch` | `/mnt/archie_brain/legal-watch/` | Runs on VPS :8100 |
| `kytran-market-watch` | `/mnt/archie_brain/market-watch/` | Runs on VPS :8101 |
| `kytran-gov-watch` | `/mnt/archie_brain/kytran-gov-watch/` | Runs on VPS :8102, already has git |
| `kytran-news` | `/mnt/archie_brain/kytran-news/` | Runs on VPS :8103 |
| `kytran-business-suite` | `/mnt/archie_brain/kytran-business-suite/` | Runs on Hub :8091 |

### New GitHub Repos — Websites (PUBLIC)

| Repo | Source Path | Hosted On |
|------|------------|-----------|
| `creed-ai-site` | `/mnt/archie_brain/website/creed-ai.org/` | Hostinger |
| `what-the-fact-site` | `/mnt/archie_brain/website/what-the-fact.com/` | Hostinger |
| `kytran-news-site` | `/mnt/archie_brain/website/thenews.kytranempowerment.com/` | Hostinger |

### Final Repo Count

| Category | Count |
|----------|-------|
| Private repos | 8 (platform + 6 products + platform-1 archived) |
| Public repos | 9 (3 AI/platform + 2 products + 4 websites) |
| **Total** | **17** |

---

## 3. Naming Convention

- `archie-*` — AI/platform infrastructure (archie-platform, archie-code, archie-node)
- `kytran-*` — standalone products (kytran-creed, kytran-news, kytran-civic-watch, etc.)
- `*-site` — website repos (creed-ai-site, what-the-fact-site, kytran-news-site)
- `kytranempowerment-site` — main company website (existing name, keep for continuity)

---

## 4. Repo Standards

### Required Files (ALL repos)

| File | Purpose |
|------|---------|
| `README.md` | What it is, install, run, screenshots if UI |
| `LICENSE` | AGPL-3.0 (public) or proprietary notice (private) |
| `.gitignore` | Language-appropriate, blocks .env and secrets |
| `.env.example` | All env vars with placeholder values and comments |
| `Dockerfile` + `docker-compose.yml` | Containerized deployment |
| `CHANGELOG.md` | Version history, start at v1.0.0 |

### Additional for Public Repos

| File | Purpose |
|------|---------|
| `CONTRIBUTING.md` | How to contribute, code style, PR process |
| `SECURITY.md` | Vulnerability reporting (email, not public issues) |
| `CODE_OF_CONDUCT.md` | Contributor Covenant |
| `.github/ISSUE_TEMPLATE/bug_report.md` | Bug report template |
| `.github/ISSUE_TEMPLATE/feature_request.md` | Feature request template |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR checklist |

### README Structure (Public Product Repos)

```markdown
# Product Name
One-line description

## What It Does
2-3 sentences + screenshot/badge

## Quick Start
docker compose up -d  (3 commands max to running)

## Features
Bullet list

## Configuration
Env vars table with descriptions

## API (if applicable)
Link to docs or brief endpoint list

## Tech Stack
What's under the hood

## License
AGPL-3.0 — link to LICENSE

## Part of the Kytran Empowerment ecosystem
Link to kytranempowerment.com
```

### GitHub Repo Settings (All Repos)

- Description filled in (one line)
- Topics/tags added (e.g. `docker`, `flask`, `lcars`, `ai-governance`)
- Website URL set (if deployed)
- Disable wiki (not using it)
- Enable issues
- Default branch: `main`
- Branch protection on `main` for public repos (require PR, no force push)

---

## 5. Security Rules

### Pre-Push Checklist

| Rule | Enforcement |
|------|------------|
| No hardcoded IPs | Env vars only, `.env.example` has placeholders |
| No passwords/tokens/keys | All via env vars or Docker secrets |
| No `.env` files committed | `.gitignore` blocks them |
| No internal hostnames | Use `example.com` in docs/comments |
| No private platform code in public repos | Repos are isolated, no cross-contamination |

### Fresh Start Protocol (repos getting clean history)

1. Copy current files only (no `.git/` directory)
2. Run secrets scan before first commit (grep for IPs, passwords, tokens, keys)
3. Init new git repo, commit clean state as "Initial release v1.0.0"
4. Push to new or existing GitHub repo (force push to replace old history)
5. Verify: clone from GitHub, scan again, confirm clean

### Ongoing Protection

- `pre-commit` hook scanning for `192.168.`, passwords, API keys
- Public repos: branch protection on `main` — all changes via PR
- Repair Bay (future): same rules — feature branch, PR, secrets scan, never force push

---

## 6. Phased Execution

### Phase 1: Foundation + Already-Separate Repos
- Create `/mnt/standalone/` and `/mnt/standalone/websites/`
- Move `kytran-creed/` → keep git history (confirmed clean)
- Move `kytran-server-manager/` → fresh start (leaked IPs in old history)
- Move `archie-code/` → keep history (confirmed clean)
- Update `archie_brain/.gitignore`
- Archive `archie-platform-1` on GitHub
- Add standard files (README updates, LICENSE, .env.example) to each

### Phase 2: Private Product Repos
- Extract Watch products one at a time: civic, legal, market, gov
- Extract The News
- Extract Business Suite
- Each: init git, add standard files, create private GitHub repo, push
- Update Docker compose paths or add symlinks
- Test each service after move

### Phase 3: Website Repos
- `kytranempowerment.com` → nuke old repo history, push current site fresh
- `creed-ai.org` → new `creed-ai-site` repo
- `what-the-fact.com` → new `what-the-fact-site` repo
- `thenews.kytranempowerment.com` → new `kytran-news-site` repo
- Each gets README with screenshot, deploy instructions, link to parent product

### Phase 4: Polish + Profile
- GitHub profile README (KytranKatarn)
- Pin top 6 repos: KSO, C.R.E.E.D., archie-code, archie-node, kytranempowerment-site, what-the-fact-site
- Topics/tags on all repos
- Branch protection on public repos
- Write shared docs (CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md), copy to all public repos
- Final secrets scan across all public repos

### Phase 5: Future — Repair Bay Integration
- Repair Bay learns repo map (product → repo → remote)
- Self-evolution pipeline gains `git push` + `gh pr create` capability
- Same rules: feature branch, secrets scan, PR to main, never force push
- Tracked as future project, not part of this implementation

### Rollback Plan
If any move breaks a running service, symlink the old path to the new location. Docker doesn't care where files live as long as the path resolves.

---

## 7. GitHub Profile

### Pinned Repos (6)
1. `kytran-system-operations` — Self-hosted server management dashboard
2. `kytran-creed` — AI governance scoring platform (AGPL-3.0)
3. `archie-code` — AI-powered CLI development tool
4. `archie-node` — Self-registering fleet compute node
5. `kytranempowerment-site` — Company website
6. `what-the-fact-site` — AI-powered transparent news platform

### Profile README
- Kytran Empowerment Inc. branding
- What the company builds (AI platform, governance, transparency tools)
- Links to live products
- Tech stack badges
- Link to C.R.E.E.D. (open source highlight)

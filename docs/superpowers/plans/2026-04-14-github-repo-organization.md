# GitHub Repository Organization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate all standalone products and websites from `archie_brain` into independent git repos with proper documentation, security, and public-facing polish across 17 total repos.

**Architecture:** Incremental migration (B) with fresh history pushes for repos with leaked data (C). Products move to `/mnt/standalone/`, websites to `/mnt/standalone/websites/`. Each gets standard files (README, LICENSE, .gitignore, .env.example). Public repos get community docs (CONTRIBUTING, SECURITY, CODE_OF_CONDUCT).

**Tech Stack:** Git, GitHub CLI (`gh`), Bash, Docker

**Spec:** `docs/superpowers/specs/2026-04-14-github-repo-organization-design.md`

---

## Shared Templates

These templates are referenced by multiple tasks. They are defined once here.

### TEMPLATE: .gitignore (Python product)

```gitignore
# Python
__pycache__/
*.py[cod]
*.so
*.egg-info/
dist/
build/

# Environment
.env
.env.local
*.env

# IDE
.vscode/
.idea/

# OS
.DS_Store
Thumbs.db

# Logs
*.log
logs/

# Database
*.db
*.sqlite
*.sqlite3

# Secrets
secrets/
credentials/
*.key
*.pem

# Docker
*.tar.gz

# Test
.coverage
htmlcov/
test-results/
```

### TEMPLATE: .gitignore (static website)

```gitignore
.env
.DS_Store
Thumbs.db
node_modules/
*.log
```

### TEMPLATE: LICENSE (AGPL-3.0 header — public repos)

```
GNU AFFERO GENERAL PUBLIC LICENSE
Version 3, 19 November 2007

Copyright (C) 2026 Kytran Empowerment Inc.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as published
by the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <https://www.gnu.org/licenses/>.
```

### TEMPLATE: LICENSE (proprietary — private repos)

```
Copyright (C) 2026 Kytran Empowerment Inc. All rights reserved.

This software is proprietary and confidential. Unauthorized copying,
distribution, or use of this software, via any medium, is strictly prohibited.
```

### TEMPLATE: CONTRIBUTING.md

```markdown
# Contributing to [REPO_NAME]

Thank you for your interest in contributing!

## How to Contribute

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/your-feature`)
3. Make your changes
4. Run tests if available
5. Commit with a descriptive message
6. Push to your fork and open a Pull Request

## Code Style

- Python: Black formatter, flake8 linting
- JavaScript: Standard style
- HTML/CSS: 2-space indentation

## Reporting Bugs

Use [GitHub Issues](../../issues) with the bug report template.

## Security

For security vulnerabilities, see [SECURITY.md](SECURITY.md). Do NOT open a public issue.

## License

By contributing, you agree that your contributions will be licensed under the project's existing license.
```

### TEMPLATE: SECURITY.md

```markdown
# Security Policy

## Reporting a Vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Email: **security@kytranempowerment.com**

Include:
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a timeline for resolution.

## Supported Versions

Only the latest release is supported with security updates.
```

### TEMPLATE: CODE_OF_CONDUCT.md

```markdown
# Contributor Covenant Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in our
community a harassment-free experience for everyone.

## Our Standards

Examples of behavior that contributes to a positive environment:
- Using welcoming and inclusive language
- Being respectful of differing viewpoints
- Gracefully accepting constructive criticism
- Focusing on what is best for the community

Examples of unacceptable behavior:
- Trolling, insulting/derogatory comments, and personal or political attacks
- Public or private harassment
- Publishing others' private information without explicit permission

## Enforcement

Instances of abusive behavior may be reported to **conduct@kytranempowerment.com**.

All complaints will be reviewed and investigated promptly and fairly.

## Attribution

This Code of Conduct is adapted from the [Contributor Covenant](https://www.contributor-covenant.org), version 2.1.
```

### TEMPLATE: .github/ISSUE_TEMPLATE/bug_report.md

```markdown
---
name: Bug Report
about: Report a bug to help us improve
title: "[BUG] "
labels: bug
assignees: ''
---

## Describe the Bug
A clear description of what the bug is.

## Steps to Reproduce
1. Go to '...'
2. Click on '...'
3. See error

## Expected Behavior
What you expected to happen.

## Screenshots
If applicable, add screenshots.

## Environment
- OS: [e.g. Ubuntu 22.04]
- Browser: [e.g. Chrome 120]
- Version: [e.g. 1.0.0]
```

### TEMPLATE: .github/ISSUE_TEMPLATE/feature_request.md

```markdown
---
name: Feature Request
about: Suggest an idea for this project
title: "[FEATURE] "
labels: enhancement
assignees: ''
---

## Problem
A description of the problem this would solve.

## Proposed Solution
Your suggested approach.

## Alternatives Considered
Any alternative solutions you've considered.

## Additional Context
Any other context or screenshots.
```

### TEMPLATE: .github/PULL_REQUEST_TEMPLATE.md

```markdown
## Summary
Brief description of changes.

## Changes
- [ ] Change 1
- [ ] Change 2

## Testing
How was this tested?

## Checklist
- [ ] Code follows project style
- [ ] No hardcoded IPs, passwords, or secrets
- [ ] .env.example updated if new env vars added
- [ ] README updated if behavior changed
```

### TEMPLATE: CHANGELOG.md

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-04-14

### Added
- Initial public release
- [Feature list specific to each product]
```

---

## Phase 1: Foundation + Already-Separate Repos

### Task 1: Create Directory Structure

**Files:**
- Create: `/mnt/standalone/`
- Create: `/mnt/standalone/websites/`

- [ ] **Step 1: Create the standalone directory tree**

```bash
mkdir -p /mnt/standalone/websites
```

- [ ] **Step 2: Verify structure**

```bash
ls -la /mnt/standalone/
```

Expected: empty directory with `websites/` subdirectory.

---

### Task 2: Move kytran-creed (keep history)

**Context:** kytran-creed has clean git history — no secrets found in audit. Move the entire directory including `.git/`.

- [ ] **Step 1: Move the directory**

```bash
mv /mnt/archie_brain/kytran-creed /mnt/standalone/kytran-creed
```

- [ ] **Step 2: Verify git repo is intact**

```bash
cd /mnt/standalone/kytran-creed
git remote -v
git log --oneline -3
```

Expected: `origin` pointing to `KytranKatarn/kytran-creed.git`, recent commits visible.

- [ ] **Step 3: Verify archie_brain .gitignore already excludes it**

```bash
grep "kytran-creed" /mnt/archie_brain/.gitignore
```

Expected: `kytran-creed/` already listed (added in earlier session).

- [ ] **Step 4: Create symlink for Docker compatibility (if needed)**

```bash
ln -s /mnt/standalone/kytran-creed /mnt/archie_brain/kytran-creed
```

- [ ] **Step 5: Add CHANGELOG.md**

Create `/mnt/standalone/kytran-creed/CHANGELOG.md` with content:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-04-14

### Added
- Initial public release
- AI governance scoring platform with REST API
- Live compliance dashboards and badge generation
- C.R.E.E.D. ethics framework enforcement
- Docker deployment with PostgreSQL
- AGPL-3.0 open source license
- Grant application materials
```

- [ ] **Step 6: Add community docs**

Create these files using the shared templates above:
- `/mnt/standalone/kytran-creed/CONTRIBUTING.md` — replace `[REPO_NAME]` with `C.R.E.E.D.`
- `/mnt/standalone/kytran-creed/SECURITY.md`
- `/mnt/standalone/kytran-creed/CODE_OF_CONDUCT.md`
- `/mnt/standalone/kytran-creed/.github/ISSUE_TEMPLATE/bug_report.md`
- `/mnt/standalone/kytran-creed/.github/ISSUE_TEMPLATE/feature_request.md`
- `/mnt/standalone/kytran-creed/.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 7: Secrets scan**

```bash
cd /mnt/standalone/kytran-creed
grep -r "192\.168\." --include="*.py" --include="*.js" --include="*.html" --include="*.md" --include="*.yml" .
grep -ri "password.*=.*[a-zA-Z0-9]" --include="*.py" --include="*.yml" . | grep -v "environ\|getenv\|\.get(\|change-me\|example\|placeholder\|_hash\|check_pass\|set_pass\|complexity"
```

Expected: No matches. If matches found, fix before committing.

- [ ] **Step 8: Commit and push**

```bash
cd /mnt/standalone/kytran-creed
git add CHANGELOG.md CONTRIBUTING.md SECURITY.md CODE_OF_CONDUCT.md .github/
git commit -m "docs: add community docs, changelog, issue/PR templates"
git push origin main
```

- [ ] **Step 9: Update GitHub repo settings**

```bash
gh repo edit KytranKatarn/kytran-creed \
  --description "C.R.E.E.D. — Open-source AI governance scoring platform. Compliance, Rights & Ethical Enforcement Directive." \
  --homepage "https://creed.kytranempowerment.com" \
  --add-topic "ai-governance" --add-topic "compliance" --add-topic "ethics" --add-topic "docker" --add-topic "flask" --add-topic "open-source"
```

---

### Task 3: Move kytran-server-manager (fresh history)

**Context:** KSO has leaked internal IPs in git history. We copy current files only (no `.git/`), init a new repo, and force-push to replace the old history.

- [ ] **Step 1: Copy current files (no git history)**

```bash
mkdir /mnt/standalone/kytran-server-manager
rsync -a --exclude='.git' /mnt/archie_brain/kytran-server-manager/ /mnt/standalone/kytran-server-manager/
```

- [ ] **Step 2: Secrets scan before first commit**

```bash
cd /mnt/standalone/kytran-server-manager
grep -r "192\.168\." --include="*.py" --include="*.js" --include="*.html" --include="*.md" --include="*.yml" .
grep -ri "password.*=.*[a-zA-Z0-9]" --include="*.py" --include="*.yml" . | grep -v "environ\|getenv\|\.get(\|change-me\|example\|placeholder\|_hash\|check_pass\|set_pass\|complexity\|input.*password\|type.*password"
```

Expected: Zero matches (we cleaned these in the earlier session). If any found, fix before continuing.

- [ ] **Step 3: Add .gitignore (Python product template)**

Create `/mnt/standalone/kytran-server-manager/.gitignore` using the Python product template from Shared Templates above.

- [ ] **Step 4: Add LICENSE (AGPL-3.0)**

Create `/mnt/standalone/kytran-server-manager/LICENSE` using the AGPL-3.0 template.

- [ ] **Step 5: Add .env.example**

Create `/mnt/standalone/kytran-server-manager/.env.example`:

```env
# Kytran System Operations — Environment Variables

# Database (PostgreSQL)
DB_HOST=
DB_PORT=5432
DB_NAME=archie
DB_USER=archie
DB_PASSWORD=

# Application
SECRET_KEY=change-me-in-production
KSO_PORT=8085

# ARCHIE Hub connection (for SSO + compliance reporting)
KSO_ARCHIE_HUB_URL=
KSO_ARCHIE_CLIENT_ID=kytran-sysops
KSO_ARCHIE_CLIENT_SECRET=

# OAuth (Kytran Auth)
KYTRAN_AUTH_URL=
KYTRAN_CLIENT_ID=
KYTRAN_CLIENT_SECRET=
KYTRAN_REDIRECT_URI=

# Host monitoring
HOST_IP=
HOST_FQDN=
```

- [ ] **Step 6: Add CHANGELOG.md**

Create `/mnt/standalone/kytran-server-manager/CHANGELOG.md`:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-04-14

### Added
- Initial public release (clean history)
- Server monitoring dashboard (CPU, RAM, disk, network, Docker)
- Compliance scanning with 5 rule packs (Ubuntu STIG, Docker STIG, HIPAA, Network STIG, CIS Ubuntu)
- Live compliance badges (SVG)
- Host command client for one-click remediation
- LCARS-themed responsive UI
- Docker deployment
- AGPL-3.0 open source license
```

- [ ] **Step 7: Add community docs**

Create these files using the shared templates:
- `/mnt/standalone/kytran-server-manager/CONTRIBUTING.md` — replace `[REPO_NAME]` with `Kytran System Operations`
- `/mnt/standalone/kytran-server-manager/SECURITY.md`
- `/mnt/standalone/kytran-server-manager/CODE_OF_CONDUCT.md`
- `/mnt/standalone/kytran-server-manager/.github/ISSUE_TEMPLATE/bug_report.md`
- `/mnt/standalone/kytran-server-manager/.github/ISSUE_TEMPLATE/feature_request.md`
- `/mnt/standalone/kytran-server-manager/.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 8: Update README.md**

Read the existing README.md first. Update it to match the spec README structure:
- Product name and one-line description
- What It Does (2-3 sentences)
- Quick Start (docker compose up)
- Features (bullet list)
- Configuration (env vars table from .env.example)
- Tech Stack
- License (AGPL-3.0)
- Kytran Empowerment ecosystem link

- [ ] **Step 9: Init fresh git repo and push**

```bash
cd /mnt/standalone/kytran-server-manager
git init
git add .
git commit -m "Initial release v1.0.0 — Kytran System Operations

Self-hosted server management dashboard with compliance scanning,
live monitoring, and LCARS-themed UI.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
git remote add origin https://github.com/KytranKatarn/kytran-system-operations.git
git push --force origin main
```

**WARNING:** This force-push replaces ALL history on the public repo. This is intentional — we're scrubbing leaked IPs from history.

- [ ] **Step 10: Verify clean push**

```bash
cd /tmp && rm -rf kso-verify && git clone https://github.com/KytranKatarn/kytran-system-operations.git kso-verify
cd kso-verify
git log --oneline
grep -r "192\.168\." --include="*.py" --include="*.js" --include="*.html" --include="*.md" .
```

Expected: Single commit "Initial release v1.0.0", zero IP matches.

- [ ] **Step 11: Create symlink for Docker compatibility**

```bash
rm -rf /mnt/archie_brain/kytran-server-manager
ln -s /mnt/standalone/kytran-server-manager /mnt/archie_brain/kytran-server-manager
```

- [ ] **Step 12: Update GitHub repo settings**

```bash
gh repo edit KytranKatarn/kytran-system-operations \
  --description "Self-hosted server management dashboard — CPU, RAM, disk, Docker, network, firewall, compliance scanning" \
  --homepage "https://server.kytranempowerment.com" \
  --add-topic "server-monitoring" --add-topic "docker" --add-topic "flask" --add-topic "compliance" --add-topic "lcars" --add-topic "self-hosted"
```

---

### Task 4: Move archie-code (keep history)

**Context:** archie-code has clean history. Move the entire directory.

- [ ] **Step 1: Move the directory**

```bash
mv /mnt/archie_brain/archie-code /mnt/standalone/archie-code
```

- [ ] **Step 2: Verify git repo intact**

```bash
cd /mnt/standalone/archie-code
git remote -v
git log --oneline -3
```

- [ ] **Step 3: Create symlink**

```bash
ln -s /mnt/standalone/archie-code /mnt/archie_brain/archie-code
```

- [ ] **Step 4: Add community docs if missing**

Check for existing CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md. Add any that are missing using templates. Add `.github/` templates if missing.

- [ ] **Step 5: Commit and push if changes made**

```bash
cd /mnt/standalone/archie-code
git add -A
git commit -m "docs: add community docs and issue/PR templates"
git push origin main
```

- [ ] **Step 6: Update GitHub repo settings**

```bash
gh repo edit KytranKatarn/archie-code \
  --description "A.R.C.H.I.E. Code CLI — AI-powered terminal development tool with LCARS-themed interface" \
  --add-topic "cli" --add-topic "ai" --add-topic "developer-tools" --add-topic "lcars"
```

---

### Task 5: Archive archie-platform-1

- [ ] **Step 1: Archive the repo on GitHub**

```bash
gh repo archive KytranKatarn/archie-platform-1 --yes
```

- [ ] **Step 2: Verify archived**

```bash
gh repo view KytranKatarn/archie-platform-1 --json isArchived --jq '.isArchived'
```

Expected: `true`

---

### Task 6: Update archie_brain .gitignore

**Files:**
- Modify: `/mnt/archie_brain/.gitignore`

- [ ] **Step 1: Update .gitignore to exclude all standalone repos**

Add to the "Nested git repos" section of `/mnt/archie_brain/.gitignore`:

```gitignore
# Standalone products (live at /mnt/standalone/, symlinked here)
archie-code/
kytran-creed/
kytran-server-manager/
kytran-gov-watch/
kytran-business-suite/
kytran-news/
watch-api/
legal-watch/
market-watch/
```

- [ ] **Step 2: Commit**

```bash
cd /mnt/archie_brain
git add .gitignore
git commit -m "chore: update gitignore for standalone repo separation"
```

---

## Phase 2: Private Product Repos

### Task 7: Extract Civic Watch (watch-api → kytran-civic-watch)

**Context:** Civic Watch source is at `/mnt/archie_brain/watch-api/`. It runs on VPS :8099. This becomes a private repo.

- [ ] **Step 1: Copy files to standalone**

```bash
mkdir /mnt/standalone/kytran-civic-watch
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.env' /mnt/archie_brain/watch-api/ /mnt/standalone/kytran-civic-watch/
```

- [ ] **Step 2: Secrets scan**

```bash
cd /mnt/standalone/kytran-civic-watch
grep -r "192\.168\." --include="*.py" --include="*.js" --include="*.html" --include="*.yml" .
grep -ri "password.*=.*[a-zA-Z0-9]" --include="*.py" --include="*.yml" . | grep -v "environ\|getenv\|\.get(\|change-me\|example\|placeholder\|_hash\|check_pass\|set_pass\|complexity\|input.*password\|type.*password"
```

Fix any findings before proceeding.

- [ ] **Step 3: Add .gitignore (Python product template)**

Create `.gitignore` using the Python product template.

- [ ] **Step 4: Add LICENSE (proprietary)**

Create `LICENSE` using the proprietary template.

- [ ] **Step 5: Add .env.example**

Read `app.py` and `docker-compose.yml` to identify all env vars. Create `.env.example` with placeholder values and comments for each.

- [ ] **Step 6: Add CHANGELOG.md**

```markdown
# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-04-14

### Added
- Initial release
- Civic data monitoring and alerting
- REST API for civic watch data
- Docker deployment
```

- [ ] **Step 7: Write README.md**

```markdown
# Kytran Civic Watch

Real-time civic data monitoring and alerting platform.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your configuration
docker compose up -d
```

## Configuration

See `.env.example` for all available environment variables.

## Tech Stack

- Python / Flask
- PostgreSQL
- Docker

## License

Copyright (C) 2026 Kytran Empowerment Inc. All rights reserved.

## Part of the Kytran Empowerment ecosystem

[kytranempowerment.com](https://kytranempowerment.com)
```

- [ ] **Step 8: Init git and create private repo**

```bash
cd /mnt/standalone/kytran-civic-watch
git init
git add .
git commit -m "Initial release v1.0.0 — Kytran Civic Watch"
gh repo create KytranKatarn/kytran-civic-watch --private --source=. --push \
  --description "Civic data monitoring and alerting platform"
```

- [ ] **Step 9: Create symlink**

```bash
rm -rf /mnt/archie_brain/watch-api
ln -s /mnt/standalone/kytran-civic-watch /mnt/archie_brain/watch-api
```

---

### Task 8: Extract Legal Watch

**Context:** Same pattern as Task 7. Source: `/mnt/archie_brain/legal-watch/`. Runs on VPS :8100.

- [ ] **Step 1: Copy files**

```bash
mkdir /mnt/standalone/kytran-legal-watch
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.env' /mnt/archie_brain/legal-watch/ /mnt/standalone/kytran-legal-watch/
```

- [ ] **Step 2: Secrets scan**

```bash
cd /mnt/standalone/kytran-legal-watch
grep -r "192\.168\." --include="*.py" --include="*.js" --include="*.html" --include="*.yml" .
grep -ri "password.*=.*[a-zA-Z0-9]" --include="*.py" --include="*.yml" . | grep -v "environ\|getenv\|\.get(\|change-me\|example\|placeholder\|_hash\|check_pass\|set_pass\|complexity\|input.*password\|type.*password"
```

- [ ] **Step 3: Add .gitignore, LICENSE (proprietary), .env.example, CHANGELOG.md, README.md**

Follow same pattern as Task 7. Read `app.py` and `docker-compose.yml` for env vars. README description: "Real-time legal data monitoring and case tracking platform."

- [ ] **Step 4: Init git and create private repo**

```bash
cd /mnt/standalone/kytran-legal-watch
git init
git add .
git commit -m "Initial release v1.0.0 — Kytran Legal Watch"
gh repo create KytranKatarn/kytran-legal-watch --private --source=. --push \
  --description "Legal data monitoring and case tracking platform"
```

- [ ] **Step 5: Create symlink**

```bash
rm -rf /mnt/archie_brain/legal-watch
ln -s /mnt/standalone/kytran-legal-watch /mnt/archie_brain/legal-watch
```

---

### Task 9: Extract Market Watch

**Context:** Source: `/mnt/archie_brain/market-watch/`. Runs on VPS :8101.

- [ ] **Step 1: Copy files**

```bash
mkdir /mnt/standalone/kytran-market-watch
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.env' /mnt/archie_brain/market-watch/ /mnt/standalone/kytran-market-watch/
```

- [ ] **Step 2: Secrets scan**

Same grep pattern as Task 7.

- [ ] **Step 3: Add .gitignore, LICENSE (proprietary), .env.example, CHANGELOG.md, README.md**

Follow same pattern. README description: "Real-time market data monitoring and financial alerting platform."

- [ ] **Step 4: Init git and create private repo**

```bash
cd /mnt/standalone/kytran-market-watch
git init
git add .
git commit -m "Initial release v1.0.0 — Kytran Market Watch"
gh repo create KytranKatarn/kytran-market-watch --private --source=. --push \
  --description "Market data monitoring and financial alerting platform"
```

- [ ] **Step 5: Create symlink**

```bash
rm -rf /mnt/archie_brain/market-watch
ln -s /mnt/standalone/kytran-market-watch /mnt/archie_brain/market-watch
```

---

### Task 10: Extract Gov Watch

**Context:** Source: `/mnt/archie_brain/kytran-gov-watch/`. Already has a `.git` repo. Runs on VPS :8102. Check if history is clean — if not, fresh start.

- [ ] **Step 1: Check git history for secrets**

```bash
cd /mnt/archie_brain/kytran-gov-watch
git log --all -p | grep -i "192\.168\.\|password.*=.*[a-zA-Z]" | grep -v "environ\|getenv\|\.get(\|change-me\|example\|placeholder\|_hash\|check_pass\|input.*password\|type.*password" | head -20
```

If clean → move with history (like Task 2). If secrets found → fresh start (like Task 3).

- [ ] **Step 2A: If clean — move with history**

```bash
mv /mnt/archie_brain/kytran-gov-watch /mnt/standalone/kytran-gov-watch
ln -s /mnt/standalone/kytran-gov-watch /mnt/archie_brain/kytran-gov-watch
```

- [ ] **Step 2B: If secrets found — copy without history**

```bash
mkdir /mnt/standalone/kytran-gov-watch
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.env' /mnt/archie_brain/kytran-gov-watch/ /mnt/standalone/kytran-gov-watch/
cd /mnt/standalone/kytran-gov-watch
git init
```

- [ ] **Step 3: Add .gitignore, LICENSE (proprietary), .env.example, CHANGELOG.md, README.md**

Follow same pattern. README description: "Government data monitoring and transparency platform."

- [ ] **Step 4: Create private repo on GitHub (if not already there)**

```bash
cd /mnt/standalone/kytran-gov-watch
git add .
git commit -m "Initial release v1.0.0 — Kytran Gov Watch"
gh repo create KytranKatarn/kytran-gov-watch --private --source=. --push \
  --description "Government data monitoring and transparency platform"
```

If repo already exists, set remote and push instead:
```bash
git remote add origin https://github.com/KytranKatarn/kytran-gov-watch.git
git push --force origin main
```

- [ ] **Step 5: Create symlink if not already done in 2A**

```bash
rm -rf /mnt/archie_brain/kytran-gov-watch
ln -s /mnt/standalone/kytran-gov-watch /mnt/archie_brain/kytran-gov-watch
```

---

### Task 11: Extract The News

**Context:** Source: `/mnt/archie_brain/kytran-news/`. Runs on VPS :8103.

- [ ] **Step 1: Copy files**

```bash
mkdir /mnt/standalone/kytran-news
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.env' /mnt/archie_brain/kytran-news/ /mnt/standalone/kytran-news/
```

- [ ] **Step 2: Secrets scan**

Same grep pattern as Task 7.

- [ ] **Step 3: Add .gitignore, LICENSE (proprietary), .env.example, CHANGELOG.md, README.md**

Follow same pattern. README description: "AI-powered news aggregation and analysis platform."

- [ ] **Step 4: Init git and create private repo**

```bash
cd /mnt/standalone/kytran-news
git init
git add .
git commit -m "Initial release v1.0.0 — Kytran News"
gh repo create KytranKatarn/kytran-news --private --source=. --push \
  --description "AI-powered news aggregation and analysis platform"
```

- [ ] **Step 5: Create symlink**

```bash
rm -rf /mnt/archie_brain/kytran-news
ln -s /mnt/standalone/kytran-news /mnt/archie_brain/kytran-news
```

---

### Task 12: Extract Business Suite

**Context:** Source: `/mnt/archie_brain/kytran-business-suite/`. Runs on Hub :8091.

- [ ] **Step 1: Copy files**

```bash
mkdir /mnt/standalone/kytran-business-suite
rsync -a --exclude='.git' --exclude='__pycache__' --exclude='.env' /mnt/archie_brain/kytran-business-suite/ /mnt/standalone/kytran-business-suite/
```

- [ ] **Step 2: Secrets scan**

Same grep pattern as Task 7.

- [ ] **Step 3: Add .gitignore, LICENSE (proprietary), .env.example, CHANGELOG.md, README.md**

Follow same pattern. README description: "Business management suite — CRM, invoicing, inventory, and operations."

- [ ] **Step 4: Init git and create private repo**

```bash
cd /mnt/standalone/kytran-business-suite
git init
git add .
git commit -m "Initial release v1.0.0 — Kytran Business Suite"
gh repo create KytranKatarn/kytran-business-suite --private --source=. --push \
  --description "Business management suite — CRM, invoicing, inventory, and operations"
```

- [ ] **Step 5: Create symlink**

```bash
rm -rf /mnt/archie_brain/kytran-business-suite
ln -s /mnt/standalone/kytran-business-suite /mnt/archie_brain/kytran-business-suite
```

---

## Phase 3: Website Repos

### Task 13: Push kytranempowerment.com (fresh start on existing repo)

**Context:** `kytranempowerment-site` repo already exists on GitHub but is stale (March 26). We push the current site with fresh history.

- [ ] **Step 1: Copy current site**

```bash
mkdir /mnt/standalone/websites/kytranempowerment.com
rsync -a --exclude='.git' /mnt/archie_brain/website/kytranempowerment.com/ /mnt/standalone/websites/kytranempowerment.com/
```

- [ ] **Step 2: Secrets scan**

```bash
cd /mnt/standalone/websites/kytranempowerment.com
grep -r "192\.168\." .
grep -ri "password\|api_key\|secret\|token" . | grep -v "placeholder\|example\|TODO"
```

- [ ] **Step 3: Add .gitignore (static website template)**

Create `.gitignore` using the static website template.

- [ ] **Step 4: Add LICENSE (AGPL-3.0), CHANGELOG.md**

- [ ] **Step 5: Write README.md**

```markdown
# Kytran Empowerment

Official website for Kytran Empowerment Inc. — AI-powered platform for business automation, governance, and transparency.

## About

Kytran Empowerment builds AI tools that help organizations operate more efficiently, ethically, and transparently. Our platform includes 130+ AI agents across 17 departments.

## Products

- **A.R.C.H.I.E.** — Autonomous Resource & Cognitive Hyperintelligence Engine
- **C.R.E.E.D.** — AI governance scoring platform ([creed-ai.org](https://creed-ai.org))
- **What The Fact** — AI-powered transparent news ([what-the-fact.com](https://what-the-fact.com))
- **Kytran System Operations** — Self-hosted server management dashboard
- **Kytran Business Suite** — Business management tools

## Deployment

Static site hosted on Hostinger. Deploy via Hostinger hPanel or API.

## License

AGPL-3.0 — see [LICENSE](LICENSE)
```

- [ ] **Step 6: Add community docs**

CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, `.github/` templates.

- [ ] **Step 7: Init and force-push**

```bash
cd /mnt/standalone/websites/kytranempowerment.com
git init
git add .
git commit -m "Initial release — Kytran Empowerment website

Company website with product pages, AI services showcase,
department overview, and trust center.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
git remote add origin https://github.com/KytranKatarn/kytranempowerment-site.git
git push --force origin main
```

- [ ] **Step 8: Update GitHub repo settings**

```bash
gh repo edit KytranKatarn/kytranempowerment-site \
  --description "Official website for Kytran Empowerment Inc. — AI platform, governance, and transparency tools" \
  --homepage "https://kytranempowerment.com" \
  --add-topic "website" --add-topic "ai" --add-topic "company"
```

---

### Task 14: Create creed-ai-site repo

**Context:** Static site at `/mnt/archie_brain/website/creed-ai.org/`. New public repo.

- [ ] **Step 1: Copy files**

```bash
mkdir /mnt/standalone/websites/creed-ai.org
rsync -a /mnt/archie_brain/website/creed-ai.org/ /mnt/standalone/websites/creed-ai.org/
```

- [ ] **Step 2: Secrets scan**

Same pattern — grep for IPs, passwords, secrets.

- [ ] **Step 3: Add .gitignore (static website), LICENSE (AGPL-3.0), CHANGELOG.md**

- [ ] **Step 4: Write README.md**

```markdown
# C.R.E.E.D. — creed-ai.org

Official website for the C.R.E.E.D. Institute — Compliance, Rights & Ethical Enforcement Directive.

## About

C.R.E.E.D. is an open-source AI governance framework that scores and enforces ethical compliance across AI systems. This is the public-facing website with governance methodology, case studies, and platform information.

## Deployment

Static site hosted on Hostinger at [creed-ai.org](https://creed-ai.org).

## Related

- [C.R.E.E.D. Platform](https://github.com/KytranKatarn/kytran-creed) — the governance scoring engine
- [Kytran Empowerment](https://kytranempowerment.com) — parent company

## License

AGPL-3.0 — see [LICENSE](LICENSE)
```

- [ ] **Step 5: Add community docs**

CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, `.github/` templates.

- [ ] **Step 6: Init and push**

```bash
cd /mnt/standalone/websites/creed-ai.org
git init
git add .
git commit -m "Initial release — creed-ai.org website"
gh repo create KytranKatarn/creed-ai-site --public --source=. --push \
  --description "Official website for C.R.E.E.D. — AI governance framework" \
  --homepage "https://creed-ai.org"
```

---

### Task 15: Create what-the-fact-site repo

**Context:** Landing page at `/mnt/archie_brain/website/what-the-fact.com/`. New public repo.

- [ ] **Step 1: Copy files**

```bash
mkdir /mnt/standalone/websites/what-the-fact.com
rsync -a /mnt/archie_brain/website/what-the-fact.com/ /mnt/standalone/websites/what-the-fact.com/
```

- [ ] **Step 2: Secrets scan, add .gitignore, LICENSE (AGPL-3.0), CHANGELOG.md**

- [ ] **Step 3: Write README.md**

```markdown
# What The Fact

Official website for What The Fact — AI-powered transparent news platform.

## About

What The Fact uses AI agents to detect bias, verify facts, and present news with full transparency. Every article shows its sources, bias analysis, and confidence scores.

## Team

Powered by 6 AI agents in the News & Media department:
- **F.A.C.T.** — Director
- **I.N.K.** — Content generation
- **B.I.A.S.** — Bias detection
- **V.E.R.I.F.Y.** — Fact checking
- **D.R.A.F.T.** — Article drafting
- **P.U.B.L.I.S.H.** — Publication management

## Deployment

Static site hosted on Hostinger at [what-the-fact.com](https://what-the-fact.com).

## Related

- [Kytran Empowerment](https://kytranempowerment.com) — parent company
- [C.R.E.E.D.](https://creed-ai.org) — governance framework used for ethical compliance

## License

AGPL-3.0 — see [LICENSE](LICENSE)
```

- [ ] **Step 4: Add community docs**

- [ ] **Step 5: Init and push**

```bash
cd /mnt/standalone/websites/what-the-fact.com
git init
git add .
git commit -m "Initial release — what-the-fact.com landing page"
gh repo create KytranKatarn/what-the-fact-site --public --source=. --push \
  --description "AI-powered transparent news platform — bias detection, fact checking, source transparency" \
  --homepage "https://what-the-fact.com"
```

---

### Task 16: Create kytran-news-site repo

**Context:** The News site at `/mnt/archie_brain/website/thenews.kytranempowerment.com/`. New public repo.

- [ ] **Step 1: Copy files**

```bash
mkdir /mnt/standalone/websites/thenews.kytranempowerment.com
rsync -a /mnt/archie_brain/website/thenews.kytranempowerment.com/ /mnt/standalone/websites/thenews.kytranempowerment.com/
```

- [ ] **Step 2: Secrets scan, add .gitignore, LICENSE (AGPL-3.0), CHANGELOG.md**

- [ ] **Step 3: Write README.md**

```markdown
# The News — thenews.kytranempowerment.com

Public-facing news site powered by Kytran's AI news pipeline.

## About

The News delivers AI-curated and analyzed news content. Articles are processed through bias detection and fact-checking pipelines before publication.

## Deployment

Hosted on Hostinger at [thenews.kytranempowerment.com](https://thenews.kytranempowerment.com).

## Related

- [What The Fact](https://what-the-fact.com) — transparency-focused news platform
- [Kytran Empowerment](https://kytranempowerment.com) — parent company

## License

AGPL-3.0 — see [LICENSE](LICENSE)
```

- [ ] **Step 4: Add community docs**

- [ ] **Step 5: Init and push**

```bash
cd /mnt/standalone/websites/thenews.kytranempowerment.com
git init
git add .
git commit -m "Initial release — The News website"
gh repo create KytranKatarn/kytran-news-site --public --source=. --push \
  --description "AI-curated news site — bias detection and fact-checking pipeline" \
  --homepage "https://thenews.kytranempowerment.com"
```

---

## Phase 4: Polish + Profile

### Task 17: GitHub Profile README

- [ ] **Step 1: Create profile repo (if not exists)**

```bash
gh repo create KytranKatarn/KytranKatarn --public --description "GitHub profile" 2>/dev/null || echo "Already exists"
```

- [ ] **Step 2: Clone and write README.md**

```bash
cd /tmp && rm -rf profile-repo
git clone https://github.com/KytranKatarn/KytranKatarn.git profile-repo 2>/dev/null || (mkdir profile-repo && cd profile-repo && git init && git remote add origin https://github.com/KytranKatarn/KytranKatarn.git)
```

Create `/tmp/profile-repo/README.md`:

```markdown
# Kytran Empowerment Inc.

Building AI-powered tools for business automation, ethical governance, and transparent journalism.

## What We Build

**A.R.C.H.I.E.** — Autonomous Resource & Cognitive Hyperintelligence Engine
> 130+ AI agents across 17 departments. Self-organizing, self-healing AI platform.

**C.R.E.E.D.** — AI Governance Scoring Platform
> Open-source compliance framework. Score, enforce, and report on AI ethics. [creed-ai.org](https://creed-ai.org)

**What The Fact** — Transparent News
> AI-powered bias detection and fact-checking. Every article shows its work. [what-the-fact.com](https://what-the-fact.com)

**Kytran System Operations** — Server Management
> Self-hosted monitoring dashboard with compliance scanning and live badges.

## Tech Stack

`Python` `Flask` `PostgreSQL` `Docker` `Ollama` `LCARS UI`

## Links

- [kytranempowerment.com](https://kytranempowerment.com)
- [creed-ai.org](https://creed-ai.org)
- [what-the-fact.com](https://what-the-fact.com)
```

- [ ] **Step 3: Commit and push**

```bash
cd /tmp/profile-repo
git add README.md
git commit -m "Add GitHub profile README"
git push origin main
```

---

### Task 18: Pin Repos and Set Topics

- [ ] **Step 1: Pin top 6 repos**

GitHub doesn't have a CLI for pinning repos. Do this manually:
1. Go to https://github.com/KytranKatarn
2. Click "Customize your pins"
3. Select: kytran-system-operations, kytran-creed, archie-code, archie-node, kytranempowerment-site, what-the-fact-site

- [ ] **Step 2: Add topics to archie-node**

```bash
gh repo edit KytranKatarn/archie-node \
  --add-topic "docker" --add-topic "fleet" --add-topic "compute-node" --add-topic "ai" --add-topic "self-registering"
```

- [ ] **Step 3: Set branch protection on public repos**

```bash
for repo in kytran-system-operations kytran-creed archie-code kytranempowerment-site creed-ai-site what-the-fact-site kytran-news-site; do
  gh api repos/KytranKatarn/$repo/branches/main/protection -X PUT \
    -f "required_pull_request_reviews[required_approving_review_count]=0" \
    -F "enforce_admins=false" \
    -F "required_status_checks=null" \
    -F "restrictions=null" 2>/dev/null && echo "$repo: protected" || echo "$repo: skipped"
done
```

Note: Branch protection with 0 required reviewers still requires PRs (no direct push to main). The owner can still merge their own PRs.

---

### Task 19: Final Secrets Scan

- [ ] **Step 1: Clone all public repos to /tmp and scan**

```bash
cd /tmp && mkdir -p final-scan && cd final-scan
for repo in kytran-system-operations kytran-creed archie-code archie-node kytranempowerment-site creed-ai-site what-the-fact-site kytran-news-site; do
  git clone https://github.com/KytranKatarn/$repo.git 2>/dev/null
done
```

- [ ] **Step 2: Scan all repos**

```bash
cd /tmp/final-scan
for dir in */; do
  echo "=== $dir ==="
  grep -r "192\.168\." "$dir" --include="*.py" --include="*.js" --include="*.html" --include="*.yml" --include="*.md" 2>/dev/null | grep -v ".git/" || echo "CLEAN"
  grep -ri "password.*=.*[a-zA-Z0-9]" "$dir" --include="*.py" --include="*.yml" 2>/dev/null | grep -v ".git/\|environ\|getenv\|\.get(\|change-me\|example\|placeholder\|_hash\|check_pass\|set_pass\|complexity\|input.*password\|type.*password" || echo "CLEAN"
done
```

Expected: ALL repos show "CLEAN" for both scans.

- [ ] **Step 3: Also scan git history of repos that kept their history**

```bash
for repo in kytran-creed archie-code archie-node; do
  echo "=== HISTORY: $repo ==="
  cd /tmp/final-scan/$repo
  git log --all -p | grep -i "192\.168\.\|password.*=.*[a-zA-Z]" | grep -v "environ\|getenv\|\.get(\|change-me\|example\|placeholder\|_hash\|check_pass\|input.*password\|type.*password" | head -5 || echo "CLEAN"
  cd /tmp/final-scan
done
```

- [ ] **Step 4: Clean up**

```bash
rm -rf /tmp/final-scan
```

- [ ] **Step 5: Report results to user**

Provide a final summary table:

| Repo | Current Files | Git History | Status |
|------|--------------|-------------|--------|
| kytran-system-operations | CLEAN | CLEAN (fresh) | OK |
| kytran-creed | CLEAN | CLEAN | OK |
| ... | ... | ... | ... |

---

## Phase 5: Future — Repair Bay Integration (NOT IMPLEMENTED NOW)

This phase is tracked as a future project. No tasks here — just documenting the intent.

**When Repair Bay gains GitHub access:**
- It reads a repo map (stored in DB or config) mapping: product → repo → remote URL
- Self-evolution pipeline gains `git checkout -b fix/...`, `git push`, `gh pr create`
- Same security rules: feature branch, secrets scan pre-push, PR to main, never force push
- Branch protection on all repos prevents accidental direct pushes

Create a project and tasks for this when the time comes.

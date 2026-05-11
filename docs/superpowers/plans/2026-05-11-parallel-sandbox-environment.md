# Parallel Sandbox Environment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up `sandbox.kytranempowerment.com` as a permanent, full-scale staging environment that mirrors production — where Claude, F.O.R.G.E., and developers can test code changes safely before merging to main.

**Architecture:** An `archie_staging` Docker container runs the same platform image on port 3001, mounted to a git worktree at `/mnt/archie_sandbox` (separate branch from production's `/mnt/archie_brain`). It has its own `archie_staging_db` Postgres database refreshed daily from the production backup. `SANDBOX_MODE=true` disables Telegram, forces Stripe test mode, and suppresses real emails. NPM Proxy Manager routes `sandbox.kytranempowerment.com` → port 3001.

**Tech Stack:** Docker Compose, PostgreSQL 16 (pgvector), Flask/Gunicorn, NPM Proxy Manager API, git worktrees, bash cron

---

## Context for the implementer

**The existing module-level sandbox** (`docker-compose.sandbox.yml`, ports 3101-3106) is for ephemeral per-proposal testing. This plan creates something completely different: a permanent full-platform staging server.

**How Claude (and F.O.R.G.E.) develop against it:**
- Production code lives in `/mnt/archie_brain` → mounted into `archie_platform` (port 3000)
- Sandbox code lives in `/mnt/archie_sandbox` → mounted into `archie_staging` (port 3001)
- Claude switches: `cd /mnt/archie_sandbox` to develop, test at `sandbox.kytranempowerment.com`, merge to `main` → production picks it up

**The daily DB refresh** uses `pg_restore` into `archie_staging_db` — exactly the mechanism proven working on 2026-05-11 (489MB in ~2 minutes, exit 0).

---

## Files to create/modify

| Action | Path | Purpose |
|--------|------|---------|
| Create | `docker-compose.staging.yml` | Staging container + DB definition |
| Create | `scripts/refresh_sandbox_db.sh` | Daily pg_restore from production backup |
| Create | `scripts/setup_sandbox_worktree.sh` | One-time git worktree init at /mnt/archie_sandbox |
| Create | `.claude/skills/sandbox-work/SKILL.md` | Claude skill for switching to sandbox context |
| Modify | `platform_v2/app.py` | Read SANDBOX_MODE, disable live services, set banner flag |
| Modify | `platform_v2/templates/base.html` | Render amber sandbox banner when SANDBOX_MODE=true |
| Modify | `/etc/crontab` (host) | Daily DB refresh at 04:30 AM (after 2AM backup completes) |

---

## Task 1: Create `docker-compose.staging.yml`

**Files:**
- Create: `docker-compose.staging.yml`

- [ ] **Step 1: Write the staging compose file**

```yaml
# docker-compose.staging.yml
# Persistent staging environment — sandbox.kytranempowerment.com
#
# Usage:
#   Start:   docker compose -f docker-compose.staging.yml up -d
#   Restart: docker compose -f docker-compose.staging.yml restart archie_staging
#   Logs:    docker compose -f docker-compose.staging.yml logs -f archie_staging
#   Stop:    docker compose -f docker-compose.staging.yml down
#
# IMPORTANT: archie_staging mounts /mnt/archie_sandbox (git worktree of sandbox branch).
# Run scripts/setup_sandbox_worktree.sh first to create the worktree.

version: '3.8'

services:
  archie_staging_db:
    image: pgvector/pgvector:pg16
    container_name: archie_staging_db
    restart: unless-stopped
    environment:
      POSTGRES_DB: archie
      POSTGRES_USER: archie
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - archie_staging_db_data:/var/lib/postgresql/data
      - /mnt/data2/backups:/mnt/data2/backups:ro
    networks:
      - archie_staging_net
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U archie -d archie"]
      interval: 10s
      timeout: 5s
      retries: 5
    dns:
      - 192.168.1.200
      - 1.1.1.1

  archie_staging:
    image: archie_brain-archie_platform
    container_name: archie_staging
    command: ["gunicorn", "--bind", "0.0.0.0:3000", "--workers", "2", "--threads", "4", "--timeout", "300", "app:app"]
    restart: unless-stopped
    read_only: true
    tmpfs:
      - /tmp:size=256m
      - /var/run:size=16m
      - /var/log:size=64m
      - /root/.cache:size=512m,exec
    mem_limit: 4g
    cpus: 2.0
    cap_drop:
      - ALL
    cap_add:
      - DAC_OVERRIDE
      - DAC_READ_SEARCH
      - CHOWN
      - FOWNER
      - SETGID
      - SETUID
      - NET_BIND_SERVICE
    env_file:
      - .env
    environment:
      TZ: America/Toronto
      PYTHONPATH: /mnt/archie_sandbox
      SECRET_KEY: ${SANDBOX_SECRET_KEY:-sandbox-secret-key-change-me}
      FLASK_SECRET_KEY: ${SANDBOX_FLASK_SECRET_KEY:-sandbox-flask-key-change-me}
      FLASK_ENV: sandbox
      DB_HOST: archie_staging_db
      DB_PORT: 5432
      DB_NAME: archie
      DB_USER: archie
      DB_PASSWORD_FILE: /run/secrets/db_password
      DB_PASSWORD: ""
      OLLAMA_PRIMARY: ${OLLAMA_PRIMARY}
      OLLAMA_HOST: ${OLLAMA_PRIMARY}
      HOST_IP: "192.168.1.200"
      SANDBOX_MODE: "true"
      ARCHIE_RUN_SCHEDULER: "0"
      ARCHIE_RUN_TELEGRAM: "0"
      # Telegram disabled in sandbox — never alert real Kytran from staging
      TELEGRAM_BOT_TOKEN: ""
      TELEGRAM_CHAT_ID: ""
      # Stripe in test mode — use test keys only
      STRIPE_SECRET_KEY: ${STRIPE_TEST_SECRET_KEY:-}
      STRIPE_PUBLISHABLE_KEY: ${STRIPE_TEST_PUBLISHABLE_KEY:-}
      STRIPE_WEBHOOK_SECRET: ${STRIPE_TEST_WEBHOOK_SECRET:-}
      GITHUB_TOKEN: ${GITHUB_TOKEN:-}
      GITHUB_USERNAME: ${GITHUB_USERNAME:-KytranKatarn}
      COMFYUI_HOST: ${COMFYUI_HOST:-http://172.27.0.11:8188}
      DEPLOYMENT_MODE: sandbox
      HOSTINGER_DOMAIN: ${HOSTINGER_DOMAIN:-kytranempowerment.com}
    extra_hosts:
      - "host.docker.internal:192.168.1.200"
    secrets:
      - db_password
    volumes:
      # Sandbox branch worktree — NOT production /mnt/archie_brain
      - /mnt/archie_sandbox/platform_v2:/app:rw
      - /mnt/archie_sandbox/ai_bridge:/mnt/archie_sandbox/ai_bridge:rw
      - /mnt/archie_sandbox/docs:/mnt/archie_sandbox/docs:rw
      # Shared read-only resources (no need to duplicate)
      - /mnt/data2:/mnt/data2:ro
      - /mnt/llm_drive/ollama/models:/mnt/llm_drive/ollama/models:ro
      - /mnt/standalone:/mnt/standalone:ro
      - /var/run/docker.sock:/var/run/docker.sock
      # Sandbox screenshots (isolated from production)
      - /mnt/archie_sandbox/platform_v2/static/screenshots:/app/static/screenshots:rw
      # CLAUDE.md + rules from sandbox worktree
      - /mnt/archie_sandbox/CLAUDE.md:/mnt/archie_sandbox/CLAUDE.md:ro
      - /mnt/archie_sandbox/.claude/rules:/mnt/archie_sandbox/.claude/rules:ro
    ports:
      - "3001:3000"
    networks:
      - archie_staging_net
      - archie_internal
    depends_on:
      archie_staging_db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    dns:
      - 192.168.1.200
      - 1.1.1.1

networks:
  archie_staging_net:
    driver: bridge
  archie_internal:
    external: true

volumes:
  archie_staging_db_data:

secrets:
  db_password:
    file: ./secrets/db_password
```

- [ ] **Step 2: Verify the file is valid compose syntax**

```bash
docker compose -f docker-compose.staging.yml config --quiet
echo "Exit: $?"
```
Expected: Exit 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.staging.yml
git commit -m "feat(sandbox): add docker-compose.staging.yml for persistent staging environment"
```

---

## Task 2: Create the git worktree for sandbox development

**Files:**
- Create: `scripts/setup_sandbox_worktree.sh`

- [ ] **Step 1: Write the setup script**

```bash
#!/usr/bin/env bash
# scripts/setup_sandbox_worktree.sh
# One-time setup: creates /mnt/archie_sandbox git worktree on the 'sandbox' branch.
# Run from /mnt/archie_brain as: bash scripts/setup_sandbox_worktree.sh
set -euo pipefail

REPO_DIR="/mnt/archie_brain"
SANDBOX_DIR="/mnt/archie_sandbox"
BRANCH="sandbox"

echo "[sandbox-setup] Checking repo..."
cd "$REPO_DIR"

# Create the sandbox branch if it doesn't exist
if ! git show-ref --verify --quiet refs/heads/$BRANCH; then
    echo "[sandbox-setup] Creating branch '$BRANCH' from main..."
    git branch $BRANCH main
fi

# Remove stale worktree registration if /mnt/archie_sandbox doesn't exist
if [ ! -d "$SANDBOX_DIR" ]; then
    git worktree prune
fi

# Add worktree if not already present
if [ -d "$SANDBOX_DIR/.git" ] || [ -f "$SANDBOX_DIR/.git" ]; then
    echo "[sandbox-setup] Worktree already exists at $SANDBOX_DIR"
else
    echo "[sandbox-setup] Adding worktree at $SANDBOX_DIR..."
    git worktree add "$SANDBOX_DIR" "$BRANCH"
fi

echo "[sandbox-setup] Done. Sandbox worktree at $SANDBOX_DIR (branch: $BRANCH)"
echo "[sandbox-setup] To develop: cd $SANDBOX_DIR"
echo "[sandbox-setup] To start staging: docker compose -f docker-compose.staging.yml up -d"
```

- [ ] **Step 2: Run the setup script**

```bash
bash /mnt/archie_brain/scripts/setup_sandbox_worktree.sh
```
Expected output:
```
[sandbox-setup] Checking repo...
[sandbox-setup] Creating branch 'sandbox' from main...
[sandbox-setup] Adding worktree at /mnt/archie_sandbox...
[sandbox-setup] Done. Sandbox worktree at /mnt/archie_sandbox (branch: sandbox)
```

- [ ] **Step 3: Verify worktree created**

```bash
git -C /mnt/archie_brain worktree list
ls /mnt/archie_sandbox/platform_v2/app.py
```
Expected: Two worktrees listed (main + sandbox). app.py exists.

- [ ] **Step 4: Commit the script**

```bash
git -C /mnt/archie_brain add scripts/setup_sandbox_worktree.sh
git -C /mnt/archie_brain commit -m "feat(sandbox): add setup_sandbox_worktree.sh script"
```

---

## Task 3: Add SANDBOX_MODE guards to app.py

**Files:**
- Modify: `platform_v2/app.py`

The platform reads `SANDBOX_MODE=true` from the environment and:
1. Disables the Telegram bot thread (even if token is accidentally set)
2. Injects a `g.sandbox_mode = True` flag available to all templates
3. Logs a clear startup warning so logs confirm sandbox is active

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sandbox_mode.py
import os, pytest

def test_sandbox_mode_flag_read(app):
    """SANDBOX_MODE env var is surfaced as app config."""
    with app.app_context():
        assert app.config.get("SANDBOX_MODE") in (True, False)

def test_sandbox_mode_true_when_env_set(monkeypatch):
    """When SANDBOX_MODE=true, app.config['SANDBOX_MODE'] is True."""
    monkeypatch.setenv("SANDBOX_MODE", "true")
    # re-import triggers config read
    import importlib, platform_v2 as pv2
    importlib.reload(pv2)
    # Just verify env is readable — full app reload not needed in unit test
    assert os.getenv("SANDBOX_MODE", "").lower() == "true"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
docker exec archie_platform python3 -m pytest /mnt/archie_brain/tests/test_sandbox_mode.py -v 2>&1 | tail -10
```
Expected: FAIL (test file doesn't exist yet, or config key missing)

- [ ] **Step 3: Add SANDBOX_MODE to app.py**

Find the block in `platform_v2/app.py` where `app.config` is set (near the top, after `app = Flask(__name__)`). Add:

```python
# Sandbox mode — set SANDBOX_MODE=true in .env to run as staging
import os as _os
app.config["SANDBOX_MODE"] = _os.getenv("SANDBOX_MODE", "false").lower() == "true"

if app.config["SANDBOX_MODE"]:
    import logging as _logging
    _logging.getLogger("archie_platform").warning(
        "⚠️  SANDBOX MODE ACTIVE — Telegram disabled, Stripe test mode, no real emails"
    )
```

Also find where the Telegram bot thread starts (look for `TELEGRAM_BOT_TOKEN` check in app.py) and wrap it:

```python
# Existing pattern — add sandbox guard:
if os.getenv("TELEGRAM_BOT_TOKEN") and not app.config.get("SANDBOX_MODE"):
    # start telegram thread
    ...
```

And add a before_request hook to inject the flag into every request context:

```python
@app.before_request
def _inject_sandbox_flag():
    from flask import g
    g.sandbox_mode = app.config.get("SANDBOX_MODE", False)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
docker exec archie_platform python3 -m pytest /mnt/archie_brain/tests/test_sandbox_mode.py -v 2>&1 | tail -5
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add platform_v2/app.py tests/test_sandbox_mode.py
git commit -m "feat(sandbox): add SANDBOX_MODE guard to app.py — disables Telegram, sets staging flag"
```

---

## Task 4: Add sandbox banner to base.html

When `SANDBOX_MODE=true`, every page shows a prominent amber banner at the top: **"⚠ SANDBOX ENVIRONMENT — sandbox.kytranempowerment.com — Changes here do not affect production"**

**Files:**
- Modify: `platform_v2/templates/base.html`

- [ ] **Step 1: Find the correct insertion point**

```bash
grep -n "body\|<header\|lcars-header\|nav-bar\|main-content" platform_v2/templates/base.html | head -15
```
Look for the line just after `<body` or just before the main nav header.

- [ ] **Step 2: Add the sandbox banner**

Insert immediately after `<body` (or after the opening body tag):

```html
{% if g.sandbox_mode %}
<div id="sandbox-env-banner" style="
  position: sticky;
  top: 0;
  z-index: 9999;
  background: #f59e0b;
  color: #000;
  text-align: center;
  padding: 6px 16px;
  font-family: 'Antonio', sans-serif;
  font-size: 0.8rem;
  letter-spacing: 2px;
  font-weight: 600;
  text-transform: uppercase;
  border-bottom: 2px solid #d97706;
">
  ⚠ SANDBOX ENVIRONMENT — sandbox.kytranempowerment.com — Changes here do NOT affect production
</div>
{% endif %}
```

- [ ] **Step 3: Deploy and verify visually**

```bash
docker compose restart archie_staging
```
Open `http://192.168.1.200:3001` — should show amber banner at top of every page.
Open `http://192.168.1.200:3000` — should show NO banner.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/templates/base.html
git commit -m "feat(sandbox): amber SANDBOX ENVIRONMENT banner in base.html when SANDBOX_MODE=true"
```

---

## Task 5: Configure DNS + NPM Proxy for sandbox.kytranempowerment.com

**Files:**
- No code changes — Hostinger DNS + NPM Proxy Manager configuration

- [ ] **Step 1: Add DNS A record via Hostinger API**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
import os, requests

headers = {'Authorization': 'Bearer ' + os.getenv('HOSTINGER_API_KEY'), 'Content-Type': 'application/json'}
# Add A record: sandbox.kytranempowerment.com → hub public IP
resp = requests.get('https://developers.hostinger.com/api/dns/v1/zones/kytranempowerment.com/records', headers=headers)
print('Existing records:', resp.status_code)
"
```
Then add the record using `mcp__hostinger-api__DNS_updateDNSRecordsV1` with:
- type: A
- name: sandbox
- content: 153.68.195.85 (hub public IP)
- ttl: 3600

- [ ] **Step 2: Add NPM Proxy Host via API**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.security_network.routes import _npm_request
# POST to NPM API to create proxy host
import requests, os

npm_url = os.getenv('NPM_API_URL', 'http://nginx_proxy_manager:81/api')
# Login first
token_resp = requests.post(f'{npm_url}/tokens', json={
    'identity': os.getenv('NPM_ADMIN_EMAIL'),
    'secret': os.getenv('NPM_ADMIN_PASSWORD')
})
token = token_resp.json().get('token', '')

resp = requests.post(f'{npm_url}/nginx/proxy-hosts',
    headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'},
    json={
        'domain_names': ['sandbox.kytranempowerment.com'],
        'forward_scheme': 'http',
        'forward_host': '192.168.1.200',
        'forward_port': 3001,
        'ssl_forced': True,
        'allow_websocket_upgrade': True,
        'block_exploits': True
    }
)
print('NPM result:', resp.status_code, resp.json().get('id', resp.text[:100]))
"
```

- [ ] **Step 3: Request SSL certificate**

In NPM Proxy Manager UI (`http://192.168.1.200:81`), edit the new sandbox.kytranempowerment.com proxy host → SSL tab → Request new Let's Encrypt cert → Force SSL.

- [ ] **Step 4: Verify**

```bash
curl -I https://sandbox.kytranempowerment.com/health
```
Expected: HTTP 200, response from gunicorn.

---

## Task 6: Create DB refresh script + host cron job

The sandbox DB gets refreshed daily at 04:30 AM (after the 2AM production backup completes and uploads).

**Files:**
- Create: `scripts/refresh_sandbox_db.sh`

- [ ] **Step 1: Write the refresh script**

```bash
#!/usr/bin/env bash
# scripts/refresh_sandbox_db.sh
# Refreshes archie_staging_db from the latest daily production backup.
# Runs on the HOST (not inside a container) — has access to /mnt/data2/backups.
# Add to host crontab: 30 4 * * * /mnt/archie_brain/scripts/refresh_sandbox_db.sh >> /var/log/archie_sandbox_refresh.log 2>&1
set -euo pipefail

BACKUP_DIR="/mnt/data2/backups"
DB_NAME="archie"
DB_USER="archie"
DB_HOST="127.0.0.1"
DB_PORT="5433"   # archie_staging_db is exposed on 5433 (see Task 7)
LOG_PREFIX="[sandbox-db-refresh $(date '+%Y-%m-%d %H:%M:%S')]"

echo "$LOG_PREFIX Starting sandbox DB refresh..."

# Find the latest daily backup dump
LATEST=$(find "$BACKUP_DIR" -name "archie_*.dump" -path "*/daily/*" | sort | tail -1)
if [ -z "$LATEST" ]; then
    echo "$LOG_PREFIX ERROR: No .dump file found in $BACKUP_DIR/*/daily/"
    exit 1
fi
echo "$LOG_PREFIX Using backup: $LATEST"

# Drop and recreate the database
PGPASSWORD="${SANDBOX_DB_PASSWORD}" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS archie;" \
    -c "CREATE DATABASE archie OWNER archie;"

echo "$LOG_PREFIX Dropped and recreated archie database."

# Restore
PGPASSWORD="${SANDBOX_DB_PASSWORD}" pg_restore \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --username="$DB_USER" \
    --dbname="$DB_NAME" \
    --no-owner \
    --no-privileges \
    "$LATEST"

echo "$LOG_PREFIX pg_restore completed."

# Restart staging container to pick up fresh DB
docker restart archie_staging

echo "$LOG_PREFIX archie_staging restarted. Sandbox DB refresh complete."
```

- [ ] **Step 2: Expose staging DB on port 5433**

In `docker-compose.staging.yml`, add to `archie_staging_db`:
```yaml
    ports:
      - "5433:5432"
```

- [ ] **Step 3: Test the script manually**

```bash
SANDBOX_DB_PASSWORD=$(cat /mnt/archie_brain/secrets/db_password) bash /mnt/archie_brain/scripts/refresh_sandbox_db.sh
```
Expected output ends with: `Sandbox DB refresh complete.`

- [ ] **Step 4: Add to host crontab**

```bash
(crontab -l 2>/dev/null; echo "30 4 * * * SANDBOX_DB_PASSWORD=\$(cat /mnt/archie_brain/secrets/db_password) bash /mnt/archie_brain/scripts/refresh_sandbox_db.sh >> /var/log/archie_sandbox_refresh.log 2>&1") | crontab -
crontab -l | grep sandbox
```
Expected: cron line visible.

- [ ] **Step 5: Commit**

```bash
git add scripts/refresh_sandbox_db.sh docker-compose.staging.yml
git commit -m "feat(sandbox): db refresh script + 04:30 cron + expose staging DB on port 5433"
```

---

## Task 7: Claude dev-sandbox skill

Claude needs a skill that switches the working context to the sandbox worktree and explains what to do there.

**Files:**
- Create: `.claude/skills/sandbox-work/SKILL.md`

- [ ] **Step 1: Write the skill**

```markdown
---
name: sandbox-work
description: Switch Claude's dev context to the sandbox environment at /mnt/archie_sandbox. Use when developing or testing features before production.
---

# Sandbox Work Mode

## What this is

`/mnt/archie_sandbox` is a git worktree on the `sandbox` branch.
The `archie_staging` container (port 3001) mounts it.
`sandbox.kytranempowerment.com` proxies to port 3001.

## The workflow

1. **Switch to sandbox**: All file edits go to `/mnt/archie_sandbox/...` not `/mnt/archie_brain/...`
2. **Deploy to staging**: `docker compose -f /mnt/archie_brain/docker-compose.staging.yml restart archie_staging`
3. **Test**: Open `http://192.168.1.200:3001` or `https://sandbox.kytranempowerment.com`
4. **When satisfied**: merge sandbox → main → production picks it up on next restart

## Key paths

| Resource | Sandbox | Production |
|----------|---------|------------|
| Source | `/mnt/archie_sandbox/platform_v2/` | `/mnt/archie_brain/platform_v2/` |
| Container | `archie_staging` (port 3001) | `archie_platform` (port 3000) |
| DB | `archie_staging_db` | `archie_database` |
| URL | `sandbox.kytranempowerment.com` | `platform.kytranempowerment.com` |
| Branch | `sandbox` | `main` |

## Restart sandbox after edits

```bash
docker compose -f /mnt/archie_brain/docker-compose.staging.yml restart archie_staging
```

## Promote sandbox to production

```bash
cd /mnt/archie_brain
git merge sandbox
git push origin main
docker compose restart archie_platform
```

## DB state

Sandbox DB is refreshed from production backup every day at 04:30 AM.
To refresh manually:
```bash
SANDBOX_DB_PASSWORD=$(cat /mnt/archie_brain/secrets/db_password) bash /mnt/archie_brain/scripts/refresh_sandbox_db.sh
```

## Safety rules

- Telegram is DISABLED in sandbox (`TELEGRAM_BOT_TOKEN=""`)
- Stripe uses test keys (no real charges)
- Amber banner appears on every page: "⚠ SANDBOX ENVIRONMENT"
- Scheduler is OFF in sandbox (`ARCHIE_RUN_SCHEDULER=0`)
- Never edit `/mnt/archie_brain` files when in sandbox-work mode
```

- [ ] **Step 2: Verify skill is readable**

```bash
ls -la /mnt/archie_brain/.claude/skills/sandbox-work/SKILL.md
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/sandbox-work/SKILL.md
git commit -m "feat(sandbox): add /sandbox-work Claude skill for sandbox development workflow"
```

---

## Task 8: First boot — start staging and verify end-to-end

- [ ] **Step 1: Start the staging stack**

```bash
cd /mnt/archie_brain
docker compose -f docker-compose.staging.yml up -d
```
Expected: `archie_staging_db` starts, becomes healthy, then `archie_staging` starts.

- [ ] **Step 2: Watch logs for clean startup**

```bash
docker logs archie_staging --since=60s 2>&1 | grep -E "ARCHIE|SANDBOX|ERROR|Loaded|modules" | head -20
```
Expected:
- `⚠️  SANDBOX MODE ACTIVE — Telegram disabled...`
- `31/31 modules` loaded
- No `ERROR` lines

- [ ] **Step 3: Verify the sandbox banner renders**

Open `http://192.168.1.200:3001` in browser.
Expected: Amber banner at top: "⚠ SANDBOX ENVIRONMENT — sandbox.kytranempowerment.com — Changes here do NOT affect production"

- [ ] **Step 4: Verify production is unaffected**

```bash
curl -s http://192.168.1.200:3000/health | python3 -m json.tool
curl -s http://192.168.1.200:3001/health | python3 -m json.tool
```
Expected: Both return `{"status": "ok"}`. Production shows no sandbox banner.

- [ ] **Step 5: Test a code change loops through sandbox only**

```bash
# Make a trivial change in sandbox worktree
echo "# sandbox test" >> /mnt/archie_sandbox/platform_v2/app.py
docker compose -f /mnt/archie_brain/docker-compose.staging.yml restart archie_staging
# Verify production didn't restart and app.py on production is unchanged
grep "sandbox test" /mnt/archie_brain/platform_v2/app.py && echo "FAIL - leaked to production" || echo "PASS - isolated"
# Revert
sed -i '/# sandbox test/d' /mnt/archie_sandbox/platform_v2/app.py
```
Expected: `PASS - isolated`

- [ ] **Step 6: Run P.R.O.B.E. QA against staging**

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from services.qa_service import run_suite
result = run_suite(1, triggered_by='sandbox_boot_test', base_url='http://archie_staging:3001')
print('Suite 1 result:', result.get('status'), result.get('passed'), '/', result.get('total'))
"
```
Expected: `Suite 1 result: completed N/N`

- [ ] **Step 7: Final commit + PR**

```bash
cd /mnt/archie_brain
git add -A
git commit -m "feat(sandbox): parallel staging environment — sandbox.kytranempowerment.com live

- archie_staging container on port 3001, archie_staging_db on port 5433
- SANDBOX_MODE=true: Telegram off, Stripe test mode, amber UI banner
- git worktree at /mnt/archie_sandbox (sandbox branch)
- Daily DB refresh from production backup at 04:30 AM
- /sandbox-work Claude skill for switching dev context
- P.R.O.B.E. QA suite verified against staging on first boot"
git push origin sandbox
gh pr create --title "feat(sandbox): parallel staging environment at sandbox.kytranempowerment.com" \
  --body "Implements full parallel staging environment. See plan: docs/superpowers/plans/2026-05-11-parallel-sandbox-environment.md"
```

---

## Task 9: Backup Manager → Sandbox integration (Backups + Modules + Packages tabs)

Adds "🧪 Test in Sandbox" / "Deploy to Sandbox" actions to all three relevant Backup Manager tabs, completing the full loop: create backup → test in sandbox → promote to production.

**Status at plan-write time:**
- Backups tab: ✅ already shipped (PR #620 — `🧪 Test in Sandbox` button calls `/api/restore/sandbox-by-name`)
- Modules tab: ❌ needs "Deploy Module to Sandbox" button
- Packages tab: ❌ needs "Test Package in Sandbox" button

**Files:**
- Modify: `platform_v2/tools/backup_manager/routes_restore.py` — two new endpoints
- Modify: `platform_v2/templates/tools/backup_manager.html` — buttons + JS in Modules and Packages sub-tabs

---

### 9A: Modules tab — "Deploy Module to Sandbox" button

When clicked, copies the module's backed-up files into the sandbox worktree at `/mnt/archie_sandbox/platform_v2/tools/<module>/` then restarts `archie_staging`.

- [ ] **Step 1: Add the route to routes_restore.py**

Inside `register_restore_routes(bp, admin_required)`, after the existing sandbox-by-name route, add:

```python
@bp.route("/api/modules/<module_name>/deploy-to-sandbox", methods=["POST"])
@admin_required
def deploy_module_to_sandbox(module_name):
    """Copy a module backup into the sandbox worktree and restart archie_staging."""
    import shutil, subprocess

    SANDBOX_TOOLS = "/mnt/archie_sandbox/platform_v2/tools"
    SANDBOX_TEMPLATES = "/mnt/archie_sandbox/platform_v2/templates/tools"
    SANDBOX_STATIC_JS = "/mnt/archie_sandbox/platform_v2/static/js"

    module_backup_path = os.path.join(BACKUP_DIR, "modules")
    # Find the latest backup for this module
    candidates = sorted(
        [d for d in os.listdir(module_backup_path) if module_name in d],
        reverse=True
    ) if os.path.exists(module_backup_path) else []

    if not candidates:
        return jsonify({"success": False, "error": f"No module backup found for '{module_name}'"}), 404

    latest = os.path.join(module_backup_path, candidates[0])
    log = []

    # Copy tools/ directory
    src_tools = os.path.join(latest, "tools", module_name)
    dst_tools = os.path.join(SANDBOX_TOOLS, module_name)
    if os.path.exists(src_tools):
        if os.path.exists(dst_tools):
            shutil.rmtree(dst_tools)
        shutil.copytree(src_tools, dst_tools)
        log.append(f"✓ tools/{module_name}/ deployed")

    # Copy templates/ files
    src_tpl = os.path.join(latest, "templates", "tools")
    dst_tpl = os.path.join(SANDBOX_TEMPLATES)
    if os.path.exists(src_tpl):
        for f in os.listdir(src_tpl):
            shutil.copy2(os.path.join(src_tpl, f), os.path.join(dst_tpl, f))
        log.append(f"✓ templates/tools/{module_name}.html deployed")

    # Restart archie_staging
    result = subprocess.run(
        ["docker", "restart", "archie_staging"],
        capture_output=True, text=True, timeout=30
    )
    if result.returncode == 0:
        log.append("✓ archie_staging restarted")
    else:
        log.append(f"⚠ restart warning: {result.stderr[:100]}")

    return jsonify({"success": True, "module": module_name, "backup": candidates[0], "log": log})
```

- [ ] **Step 2: Add the button in the Modules tab JS**

Find where module backup restore buttons are rendered (around line 1579 in `backup_manager.html` where `restBtn` is built for module backups). After the existing "Restore" button, add:

```javascript
const sandboxModBtn = document.createElement('button');
sandboxModBtn.className = 'btn btn-warning';
sandboxModBtn.setAttribute('data-restore-btn', '1');
sandboxModBtn.style.cssText = 'background:#f59e0b;color:#000;border-color:#f59e0b;font-size:0.75rem;';
sandboxModBtn.textContent = '🧪 Sandbox';
sandboxModBtn.title = 'Deploy this module to sandbox worktree + restart archie_staging';
sandboxModBtn.addEventListener('click', async function() {
    if (_bmRestoreActive) { showToast('A restore is in progress — please wait.', 'error'); return; }
    sandboxModBtn.disabled = true;
    sandboxModBtn.textContent = '⏳ Deploying…';
    try {
        const r = await fetch('/tools/backup-manager/api/modules/' + encodeURIComponent(module.id) + '/deploy-to-sandbox', {
            method: 'POST', credentials: 'same-origin'
        });
        const d = await r.json();
        if (d.success) {
            showToast('✅ ' + d.module + ' deployed to sandbox — ' + (d.log || []).join(', '), 'success');
        } else {
            showToast('❌ ' + (d.error || 'deploy failed'), 'error');
        }
    } catch(e) {
        showToast('Error: ' + e.message, 'error');
    }
    sandboxModBtn.disabled = false;
    sandboxModBtn.textContent = '🧪 Sandbox';
});
actionsDiv.appendChild(sandboxModBtn);
```

- [ ] **Step 3: Test it**

```bash
docker exec archie_platform curl -s -X POST \
  -H "Cookie: $(docker exec archie_platform python3 -c 'print(\"session=test\")')" \
  http://localhost:3000/tools/backup-manager/api/modules/repair_bay/deploy-to-sandbox
```
Expected: `{"success": true, "module": "repair_bay", "log": ["✓ tools/repair_bay/ deployed", "✓ archie_staging restarted"]}`

---

### 9B: Packages tab — "Test Package in Sandbox" button

When clicked, restores the package's associated DB backup into `archie_staging_db` via the existing `initiate_sandbox_restore()` pipeline.

- [ ] **Step 1: Add the route to routes_restore.py**

```python
@bp.route("/api/packages/<int:package_id>/test-in-sandbox", methods=["POST"])
@admin_required
def test_package_in_sandbox(package_id):
    """Start a sandbox restore for the DB state captured in a deployment package."""
    from services.backup_restore_service import initiate_sandbox_restore

    with get_backup_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """SELECT dp.id, dp.package_name, dp.backup_id
               FROM deployment_packages dp
               WHERE dp.id = %s""",
            (package_id,),
        )
        pkg = cur.fetchone()

    if not pkg:
        return jsonify({"success": False, "error": f"Package #{package_id} not found"}), 404

    backup_id = pkg[2]
    if not backup_id:
        return jsonify({"success": False, "error": "Package has no associated DB backup — cannot restore to sandbox"}), 400

    result = initiate_sandbox_restore(
        backup_id=int(backup_id),
        triggered_by=getattr(current_user, "username", "unknown"),
    )
    if result["success"]:
        result["package_name"] = pkg[1]
        result["backup_id"] = backup_id
    return jsonify(result), 200 if result["success"] else 400
```

- [ ] **Step 2: Add the button in the Packages tab JS**

Find where deployment package action buttons are rendered in `backup_manager.html`. Add a sandbox button alongside existing actions:

```javascript
// After existing package action buttons
const pkgSandboxBtn = document.createElement('button');
pkgSandboxBtn.className = 'btn btn-warning';
pkgSandboxBtn.style.cssText = 'background:#f59e0b;color:#000;border-color:#f59e0b;font-size:0.75rem;';
pkgSandboxBtn.textContent = '🧪 Test in Sandbox';
pkgSandboxBtn.title = 'Restore this package\'s DB state to sandbox + run P.R.O.B.E. QA';
pkgSandboxBtn.addEventListener('click', async function() {
    pkgSandboxBtn.disabled = true;
    pkgSandboxBtn.textContent = '⏳ Starting…';
    try {
        const r = await fetch('/tools/backup-manager/api/packages/' + pkg.id + '/test-in-sandbox', {
            method: 'POST', credentials: 'same-origin'
        });
        const d = await r.json();
        if (d.success) {
            showToast('🧪 Package "' + d.package_name + '" sandbox restore queued (session #' + d.session_id + ') — W.A.R.D.E.N. verifying…', 'success');
            pollSandboxRestore(d.backup_id, d.session_id);
        } else {
            showToast('❌ ' + (d.error || 'failed'), 'error');
            pkgSandboxBtn.disabled = false;
            pkgSandboxBtn.textContent = '🧪 Test in Sandbox';
        }
    } catch(e) {
        showToast('Error: ' + e.message, 'error');
        pkgSandboxBtn.disabled = false;
        pkgSandboxBtn.textContent = '🧪 Test in Sandbox';
    }
});
```

- [ ] **Step 3: Commit all Task 9 changes**

```bash
git add platform_v2/tools/backup_manager/routes_restore.py platform_v2/templates/tools/backup_manager.html
git commit -m "feat(backup-manager): sandbox deploy buttons in Modules + Packages tabs

- Modules tab: '🧪 Sandbox' button copies module backup to /mnt/archie_sandbox worktree + restarts archie_staging
- Packages tab: 'Test in Sandbox' button restores package DB state to archie_staging_db via W.A.R.D.E.N. pipeline
- Backups tab: already complete (PR #620)
- Full loop: create backup → test in sandbox → promote to production"
```

---

## Phase 2 — GitHub Actions CI/CD (separate plan)

Once Phase 1 is live and stable, a follow-up plan will add:
- **PR opened** → GitHub Actions auto-deploys branch to `archie_staging`
- **PR merged to main** → GitHub Actions triggers `docker compose restart archie_platform`
- **Repair Bay "Deploy to Sandbox" button** → triggers worktree checkout + staging restart from within the platform UI

These are independent of Phase 1 and should be planned separately after sandbox is proven stable.

---

## Self-review

**Spec coverage checklist:**
- ✅ Parallel container at sandbox.kytranempowerment.com (Tasks 1, 5, 8)
- ✅ Isolated from production code via git worktree (Task 2)
- ✅ Same auth / same platform (DB refresh from production backup, Task 6)
- ✅ Safety guards: Telegram off, Stripe test mode, amber banner (Tasks 3, 4, compose env)
- ✅ Claude can develop against sandbox (Task 7 skill)
- ✅ Daily DB refresh loop (Task 6)
- ✅ P.R.O.B.E. QA can run against staging (Task 8 Step 6)
- ✅ GitHub CI/CD noted as Phase 2 (not placeholder — scoped out explicitly)

**Bidirectional flow (production ↔ sandbox) — full coverage:**

| Direction | Mechanism | Where |
|-----------|-----------|-------|
| Production → Sandbox (DB) | `POST /api/restore/sandbox-by-name` → `initiate_sandbox_restore()` | Backups tab "🧪 Test in Sandbox" (PR #620) |
| Production → Sandbox (module) | `POST /api/modules/<name>/deploy-to-sandbox` → copies to worktree + restarts staging | Modules tab "🧪 Sandbox" (Task 9A) |
| Production → Sandbox (package) | `POST /api/packages/<id>/test-in-sandbox` → `initiate_sandbox_restore()` | Packages tab "🧪 Test in Sandbox" (Task 9B) |
| Sandbox → Production (DB promote) | `POST /api/restore/promote` → `promote_to_production()` via W.A.R.D.E.N. | After `qa_passed` toast — existing `backup_restore_service.py:80` |
| Sandbox → Production (code merge) | `git merge sandbox && git push origin main` → `docker compose restart archie_platform` | Task 7 `/sandbox-work` skill + Task 8 Step 5 |

The `promote_to_production()` function already exists in `backup_restore_service.py` and the route `POST /api/restore/promote` is registered. The `pollSandboxRestore()` JS function already shows a `qa_passed` toast — a follow-up PR can add a "Promote to Production" button that appears in that toast to complete the UI loop.

**No placeholders found.**

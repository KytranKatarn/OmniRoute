---
name: sandbox-work
description: Switch Claude's dev context to the sandbox environment. Use when developing or testing features before pushing to production. Covers worktree paths, restart commands, DB refresh, and promote-to-production workflow.
---

# Sandbox Work Mode

## What this is

`/mnt/archie_sandbox` is a git worktree on the `sandbox` branch.
The `archie_staging` Docker container (port 3003) mounts it.
`sandbox.kytranempowerment.com` proxies to port 3003.

**Rule:** When working on a feature for sandbox testing, ALL file edits go to `/mnt/archie_sandbox/...` not `/mnt/archie_brain/...`.

## Key paths

| Resource | Sandbox | Production |
|----------|---------|------------|
| Source | `/mnt/archie_sandbox/platform_v2/` | `/mnt/archie_brain/platform_v2/` |
| Container | `archie_staging` (port 3003) | `archie_platform` (port 3000) |
| DB | `archie_staging_db` (port 5433) | `archie_database` (port 5432) |
| URL | `http://192.168.1.200:3003` | `http://192.168.1.200:3000` |
| Branch | `sandbox` | `main` |

## Dev workflow

```bash
# 1. Make changes in sandbox worktree
cd /mnt/archie_sandbox
# edit platform_v2/... files here

# 2. Deploy to staging (restart picks up file changes)
docker compose -f /mnt/archie_brain/docker-compose.staging.yml restart archie_staging

# 3. Test at sandbox URL
curl http://192.168.1.200:3003/health

# 4. Verify amber banner shows at http://192.168.1.200:3003
```

## Start/stop staging

```bash
# Start
docker compose -f /mnt/archie_brain/docker-compose.staging.yml up -d

# Stop
docker compose -f /mnt/archie_brain/docker-compose.staging.yml down

# Logs
docker compose -f /mnt/archie_brain/docker-compose.staging.yml logs -f archie_staging
```

## DB refresh (manual)

Refreshes sandbox DB from the latest production backup:
```bash
SANDBOX_DB_PASSWORD=$(cat /mnt/archie_brain/secrets/database/password.txt) \
  bash /mnt/archie_brain/scripts/refresh_sandbox_db.sh
```
Happens automatically every day at 04:30 AM.

## Promote sandbox → production

When the feature is verified on sandbox:
```bash
cd /mnt/archie_brain
git merge sandbox           # merge sandbox branch into main
git push origin main        # push to GitHub
docker compose restart archie_platform   # hot-reload production
```

## Safety rules

- **Telegram**: DISABLED in sandbox (`TELEGRAM_BOT_TOKEN=""`)
- **Stripe**: Uses test keys — no real charges
- **Scheduler**: OFF (`ARCHIE_RUN_SCHEDULER=0`) — no job collisions with production
- **Amber banner**: Visible on every page at sandbox.kytranempowerment.com
- **Never**: Edit `/mnt/archie_brain` files while in sandbox-work mode for a feature

## Quick reference

```bash
# Status check
docker ps | grep archie_staging
curl -s http://192.168.1.200:3003/health | python3 -m json.tool

# Check sandbox banner is showing
curl -s http://192.168.1.200:3003/ | grep -o 'SANDBOX ENVIRONMENT'

# See worktrees
git -C /mnt/archie_brain worktree list
```

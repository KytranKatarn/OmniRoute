# Gov Watch Rules

**New file** — documents VPS path, tier bug, DB user, APScheduler jobs, WIP uncommitted files, Bridge routing.

## Locations — Always Verify Path

| Where | Path |
|-------|------|
| Hub source | `/mnt/standalone/kytran-gov-watch/` |
| VPS deployed | `/opt/archie-products/gov-watch/` |
| VPS container | `kytran_gov_watch` (port 8102) |
| Subdomain | gov.kytranempowerment.com |

**NEVER** use `/opt/archie-products/kytran-gov-watch/` on VPS — that path is empty and silently fails.

## Bridge URL (Headscale mesh — mandatory)

```
BRIDGE_URL = http://100.64.0.4:3000
```

**NEVER** `https://platform.kytranempowerment.com` — Hostinger CDN caps at 60s, bypasses queue, hides from `task_execution_log`.

Hub dispatch endpoint: `POST /api/procure/dispatch` (JWT bearer auth).

## DB Connection

The DB container user is NOT `postgres` or `govwatch` — check `docker-compose.yml` for the actual user. Run:
```bash
docker inspect kytran_gov_watch --format "{{json .Mounts}}"
# or check docker-compose.yml postgres service for POSTGRES_USER
```

## APScheduler Jobs

| Job ID | Schedule | What it does |
|--------|----------|-------------|
| `daily_award_ingest` | CronTrigger(hour=4, minute=0) — 04:00 UTC | PSPC contract awards |
| `proactive_disclosure_ingest` | CronTrigger(hour=5, minute=0) — 05:00 UTC | TBS federal contracts >$10k |
| `gic_appointments_ingest` | CronTrigger(day_of_week="wed", hour=6, minute=0) — Wed 06:00 UTC | GIC appointments |

## Proactive Disclosures

- Dataset: `d8f85d91-7dec-4fd1-8055-483b77225d8b` (TBS CKAN)
- Fetch cap: **16MB** (was 64MB — caused OOM in 768MB container, PR #24)
- 35,681 records ingested as of 2026-05-25
- Upsert key: `ON CONFLICT (reference_number, amendment_number, vendor_name)`
- 3 API routes: `/procure/api/proactive/recent`, `/procure/api/proactive/trends`, `/procure/api/proactive/ingest`

## Tier Sync — Never Downgrade (CRITICAL)

The `_sync_user_tier()` function at `app.py:1428` uses a numeric hierarchy to prevent free-tier resets:

```
kytran/owner/admin = 99
pro = 60
agency = 50
team = 40
solo = 30
starter = 10
```

**Rule: Only upgrade tier, never downgrade.** On conflict, keeps the HIGHER tier. Owner email variants (`kytranempowerment@gmail.com`, `kytran@kytranempowerment.com`, case variants) all map to the same person — never treat them as separate accounts needing a free-tier default.

If a session shows Kytran as `tier='free'` — that's a bug, not correct state. Check `_sync_user_tier()` logic.

## P.R.O.C.U.R.E. Agent

- Agent ID: #349 | Model: qwen2.5:7b
- Department: Analytics & Intelligence
- Capability: `procurement_analysis`
- Hub dispatch via `POST /api/procure/dispatch` (JWT bearer)
- 21 API endpoints total

## WIP Uncommitted Files (as of 2026-05-25)

These exist in `/mnt/standalone/kytran-gov-watch/` but are NOT committed:

| File | Purpose | Status |
|------|---------|--------|
| `procure/usage.py` | Per-tier draft limits enforcement | WIP |
| `static/js/intel-hub.js` | Federal procurement intel hub UI | WIP |
| `migrations/003_usage_billing.sql` | Usage/billing schema | WIP |
| `migrations/004_intel_hub_tables.sql` | Intel hub tables | WIP |
| `migrations/005_award_diff.sql` | Award diff tracking | WIP |
| `kytran-auth-pkg/kytran_auth.py` | Auth package changes | WIP |
| `kytran-auth-pkg/pyproject.toml` | Version bump | WIP |
| `kytran_auth.py` | Auth module | WIP |
| `docs/provincial-scrapers-design.md` | Design doc, not started | Draft |

**Do NOT commit these without reviewing first** — they may be part of an unfinished sprint.

## Kytran OAuth Identity Rule

`kytranempowerment@gmail.com`, `kytran@kytranempowerment.com`, `Kytran@KytranEmpowerment.com` are ALL the same person. Multiple DB rows from casing accidents are not duplicate accounts. Never propose merging or treating as separate users.

## Deploy Pattern

```bash
# From hub, sync to VPS then rebuild:
rsync -avz --exclude='.env' /mnt/standalone/kytran-gov-watch/ \
  kytran@76.13.107.109:/opt/archie-products/gov-watch/

# On VPS:
cd /opt/archie-products/gov-watch/
docker compose up -d --build kytran_gov_watch
```

VPS SSH key: `~/.ssh/id_ed25519` | User: `kytran@76.13.107.109`

## Gotchas

- VPS path: `gov-watch/` not `kytran-gov-watch/` — checked via `docker inspect ... --format "{{json .Mounts}}"`
- DB user: read from docker-compose.yml, NOT postgres or govwatch
- BRIDGE_URL: mesh only (`http://100.64.0.4:3000`) — public CDN times out in 60s
- `kytran` tier users (the owner) must NEVER be reset to `free` — numeric hierarchy prevents this
- WIP files in hub source are uncommitted — review before any `git add`
- `.env` files on VPS are gitignored — NEVER overwrite, append only

# Gov Watch Rules

**New file** — documents VPS path, tier bug, DB user, APScheduler jobs, WIP uncommitted files, Bridge routing.

## Locations — Always Verify Path

| Where | Path |
|-------|------|
| Hub source | `/mnt/standalone/kytran-gov-watch/` |
| Deployed (Citadel/boston-2, since 2026-06) | `root@100.64.0.10:/opt/archie-products/gov-watch/` (was outpost-us — stack removed there) |
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

**All times are `America/Toronto` (Eastern), NOT UTC** — every CronTrigger carries an explicit
`timezone="America/Toronto"`, and the `BackgroundScheduler` itself is constructed with it
(PR #42, 2026-07-21). Previously a mix of both, which made "why did it run then?" unanswerable.
Per `.claude/rules/timezone.md`, do not add a CronTrigger without the tz kwarg.

| Job ID | Schedule (Eastern) | What it does |
|--------|--------------------|-------------|
| `partner_scrape` | 23:30 daily | Partner source scrape |
| `daily_award_ingest` | 00:00 daily | CanadaBuys award notices (streamed) |
| `proactive_disclosure_ingest` | 01:00 daily | TBS federal contracts >$10k (streamed) |
| `contract_history_ingest` | 01:30 daily | CanadaBuys contract history |
| `gic_appointments_ingest` | Wed 02:00 | GIC appointments |
| `entity_graph_push` | 02:30 daily | Shared entity-graph adapter |
| `ag_reports` | Wed 03:00 | Auditor-General reports |
| `ingest_freshness_monitor` | 03:00 daily | Alarms on a stale last-SUCCESS (see below) |
| `weekly_digest` | Mon 04:00 | Subscriber digest |

`canadabuys_tender_sync` is NOT an APScheduler job — it is a **6h daemon thread**
(`_background_sync` in app.py). That is exactly why it was missed when heartbeats were added.

## Ingest health — monitor RUNS, not ROWS (#5062 / #5070)

On 2026-07-21 four ingest paths were found broken, 2 days to 2.5 months stale, and **not one was
visible in the logs**: an OOM SIGKILL is uncatchable so the job's own try/except logged nothing;
a 16MB cap silently truncated proactive to ~4% of its rows; contract_history had no job at all.

**Row counts are not a health signal.** A job that runs and inserts 0 is healthy when upstream
had nothing new (TBS updates ~quarterly). A job that never RUNS is the failure — and that is
invisible if you only watch the table.

- `procure/ingest_health.py` — `gov_watch.ingest_runs` heartbeat table + `record_ingest_run()`
  (called on BOTH success and failure paths of all four ingests) + `check_ingest_freshness()`,
  which alarms via the hub `POST /api/internal/notify` (Bearer, mesh IP `100.64.0.4`).
- Alarms on a stale last-**SUCCESS** (48h thresholds), never on recency of the newest attempt.
  A job with no heartbeat ever is reported `unknown` — deliberately not alarmed, so a fresh
  deploy does not page.
- ⚠️ A job listed in `INGEST_JOBS` with no `record_ingest_run` writer stays `unknown` FOREVER and
  can never alarm — unmonitored while APPEARING monitored. `tests/test_date_guard.py::
  test_every_monitored_job_has_a_heartbeat_writer` diffs INGEST_JOBS against every call site to
  make that a red test.

## ENTITY_INGEST_URL — the shared entity graph lives on CITADEL (#5799, fixed 2026-08-19)

```
ENTITY_INGEST_URL=http://100.64.0.10:8106     # Citadel/boston-2, wtf-ingest-api
```

⚠️ **NOT `100.64.0.4:8106` (the hub).** `wtf-ingest-api` moved to Citadel in the June
migration; gov-watch and legal-watch `.env`s did not follow, so both pushed at a port with
no listener (*Connection refused*) for ~**7 weeks**. Cross-Watch (#3331) looked like a UI
problem; it was a dead feed. Catch-up after the fix: **3,584 batches, 0 failed**;
gov mentions **290,790 → 1,958,093**. Backups `.env.bak-entitygraph-<ts>`.
Apply with `docker compose up -d` — `restart` does NOT re-read `env_file` (KB #268829).

**It was invisible because `entity_graph_push` was the ONE job with no `record_ingest_run`**
— zero `ingest_runs` rows ever ⇒ `unknown` ⇒ never alarms (see the section above; a job in
`INGEST_JOBS` with no writer is unmonitored while APPEARING monitored). Fixed in
**PR kytran-gov-watch#46** with three differentiated heartbeat paths (unset → ok+note ·
ran → `ok = failed==0` · raised → ok=False+error) plus
`test_every_monitored_job_has_a_heartbeat_writer`. legal-watch + civic-watch halves still
open under **#5799** — legal-watch has NO heartbeat infrastructure at all.

⚠️ **`shared.entity_mentions` has only `created_at`** — `max(created_at)` cannot distinguish
a dead feed from one re-upserting existing rows. Prove liveness via `shared.entities.updated_at`.
KB **#291054** (mistake) / **#291055** (coder ref) · ADR decision 1003.

## Date guard — impossible dates cannot re-enter (#5067 / #5069 / #5072)

`procure/date_guard.sane_date(value, field, *, event=False)` is wired into ALL FOUR parsers:
`feeds.CanadaBuysFeed._parse_date`, `procure.proactive._parse_date`,
`procure.contract_history._to_date`, and `procure.awards._to_date`.

⚠️ **`procure/awards.py` has its OWN `_to_date`** — it is NOT the feeds.py parser. It was
unguarded until #44, which is why `award_notices` held `award_date = 2030-12-31` while every
other table was clean. Guard both when touching date parsing.

Two families rejected: **epoch artifacts** (an empty cell via the Excel/Lotus 1900 serial system
lands on `1899-12-30` — every pre-1990 value found was exactly that date) and **sentinels**
(`9999-12-31` for "no end date").

**Bounds are deliberately loose, and the distinction matters:**

| `event=True` (retrospective — cannot be in the future) | default (forward-looking — future is LEGITIMATE) |
|---|---|
| `awards.award_date` | `feeds.deadline` (open solicitation) |
| `proactive.contract_date` | `proactive.delivery_date`, `proactive.period_start` |
| `feeds.posted_at` | `contract_history.contract_date` ← a contract **START** date |
| | `contract_history.contract_period_end` |

`contract_history.contract_date` comes from `contractStartDate-contratDateDebut` — a contract
signed today can take effect next quarter (30 such rows measured, all with `period_end > start`).
Marking it `event=True` silently drops long-lead contracts; a negative test now guards that.
Over-eager filtering is a WORSE bug than the one being fixed — it damages the long-horizon
government-vs-government spending view the backfill exists to support.

`drain_rejects()` returns and resets a per-COLUMN tally — a silent discard is how the bad data
got in; a jump in the count means upstream changed.

## Coverage floors (measured 2026-07-21, after backfill)

| Table | Date column | Oldest | Rows |
|---|---|---|---|
| `proactive_disclosures` | `contract_date` | 1999-01-11 (**usable from Dec 2003**) | 1,289,127 |
| `award_notices` | `award_date` | 1996-02-15 (**usable from 2010**) | 120,666 |
| `contract_history` | `contract_date` | 2005-10-24 | 221,149 |
| `tenders` | `posted_at` | 2010-03-16 | 86,760 |

Common floor where all four overlap: **2010-03-16** (`tenders` is the constraint). The 1996/1999
floors are thin tails, not usable eras — `award_notices` has only 10 rows pre-2000 and 114 in
2000-2009 vs 120,542 from 2010. For multi-government comparison use `proactive_disclosures` from
**Dec 2003** (Martin 40,599 / Harper 398,729 / Trudeau 768,784 / Carney 80,858). Chrétien has 157
rows — do NOT chart it.

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

## Internal Tier-Push Endpoint (added 2026-05-26)

Gov-watch exposes `/api/internal/set-tier` so the platform billing webhook can push tier
changes on subscribe/upgrade/cancel without the user needing to log in again.

**Auth**: `X-Internal-Key` header must match `INTERNAL_API_KEY` env var (same value as platform).

**Payload** (JSON POST):
```json
{ "email": "user@example.com", "tier": "solo" }
```
- `email` is required — gov-watch keys on email, not platform user_id.
- `tier` must be one of: `kytran, owner, admin, pro, agency, team, solo, starter, free`.
- No-downgrade invariant enforced via the same numeric CASE SQL as `_sync_user_tier()`.
- Returns `{"ok": true, "email": "...", "tier": "..."}` on success.

**Required `.env` keys** (VPS `/opt/archie-products/gov-watch/.env`):
```
INTERNAL_API_KEY=<same value as platform INTERNAL_API_KEY>
```
Key was added 2026-05-26. NEVER overwrite `.env` on VPS — append only.

**Platform side** (`services/watch_billing_handler.py`):
- `_get_user_email(user_id)` fetches email from platform `users` table.
- `_push_tier_to_standalone()` includes `email` in payload when available.
- All 3 webhook handlers (checkout.completed, sub.updated, sub.deleted) pass email.

**Verified live** (2026-05-26):
- Health 200 ✅ | Bad key 401 ✅ | Valid push 200 + `user_profiles.tier=solo` in DB ✅

## WIP Uncommitted Files (as of 2026-05-26)

These exist in `/mnt/standalone/kytran-gov-watch/` but are NOT committed:

| File | Purpose | Status |
|------|---------|--------|
| `procure/usage.py` | Per-tier draft limits enforcement | WIP |
| `migrations/003_usage_billing.sql` | Usage/billing schema | WIP |
| `migrations/004_intel_hub_tables.sql` | Intel hub tables | WIP |
| `migrations/005_award_diff.sql` | Award diff tracking | WIP |
| `kytran-auth-pkg/kytran_auth.py` | Auth package changes | WIP |
| `kytran-auth-pkg/pyproject.toml` | Version bump | WIP |
| `kytran_auth.py` | Auth module | WIP |
| `docs/provincial-scrapers-design.md` | Design doc, not started | Draft |

Committed 2026-05-26: `static/js/intel-hub.js` (SOSA display fix), `/api/internal/set-tier` in `app.py`.

**Do NOT commit remaining WIP without reviewing first** — they may be part of an unfinished sprint.

## Kytran OAuth Identity Rule

`kytranempowerment@gmail.com`, `kytran@kytranempowerment.com`, `Kytran@KytranEmpowerment.com` are ALL the same person. Multiple DB rows from casing accidents are not duplicate accounts. Never propose merging or treating as separate users.

## Deploy Pattern

```bash
# From hub, sync to VPS then rebuild:
rsync -avz --exclude='.env' /mnt/standalone/kytran-gov-watch/ \
  root@100.64.0.10:/opt/archie-products/gov-watch/   # Citadel/boston-2 (migrated 2026-06; was kytran@76.13.107.109)

# On VPS:
cd /opt/archie-products/gov-watch/
docker compose up -d --build kytran_gov_watch
```

SSH key: `~/.ssh/id_ed25519` | Host: `root@100.64.0.10` (Citadel/boston-2 — gov-watch migrated off outpost-us 2026-06)

## Gotchas

- VPS path: `gov-watch/` not `kytran-gov-watch/` — checked via `docker inspect ... --format "{{json .Mounts}}"`
- DB user: read from docker-compose.yml, NOT postgres or govwatch
- BRIDGE_URL: mesh only (`http://100.64.0.4:3000`) — public CDN times out in 60s
- `kytran` tier users (the owner) must NEVER be reset to `free` — numeric hierarchy prevents this
- WIP files in hub source are uncommitted — review before any `git add`
- `.env` files on VPS are gitignored — NEVER overwrite, append only

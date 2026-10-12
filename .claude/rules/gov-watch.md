# Gov Watch Rules

*Condensed 2026-10-12 (task 7179): incident statistics, the coverage-floors table, the stale WIP-files table and the duplicate Gotchas list were removed. Full previous text: `git show b3bd529dc:.claude/rules/gov-watch.md`; summary + pointers in KB #449512.*

## Locations — Always Verify Path

| Where | Path |
|-------|------|
| Hub source | `/mnt/standalone/kytran-gov-watch/` |
| Deployed (Citadel/boston-2, since 2026-06) | `root@100.64.0.10:/opt/archie-products/gov-watch/` (was outpost-us — stack removed there) |
| VPS container | `kytran_gov_watch` (port 8102) |
| Subdomain | gov.kytranempowerment.com |

**NEVER** use `/opt/archie-products/kytran-gov-watch/` on the VPS — that path is empty and silently fails. The DB container user is NOT `postgres` or `govwatch`: read `POSTGRES_USER` from `docker-compose.yml` (or `docker inspect kytran_gov_watch --format "{{json .Mounts}}"`).

## Bridge URL (Headscale mesh — mandatory)

`BRIDGE_URL = http://100.64.0.4:3000`. **NEVER** `https://platform.kytranempowerment.com` — the Hostinger CDN caps at 60s, bypasses the queue and hides the call from `task_execution_log`. Hub dispatch endpoint: `POST /api/procure/dispatch` (JWT bearer).

## APScheduler Jobs

**All times are `America/Toronto` (Eastern), NOT UTC** — every CronTrigger carries `timezone="America/Toronto"` and so does the `BackgroundScheduler` (PR #42). Never add a CronTrigger without the tz kwarg (`.claude/rules/timezone.md`).

| Job ID | Schedule (Eastern) | What it does |
|--------|--------------------|-------------|
| `partner_scrape` | 23:30 daily | Partner source scrape |
| `daily_award_ingest` | 00:00 daily | CanadaBuys award notices (streamed) |
| `proactive_disclosure_ingest` | 01:00 daily | TBS federal contracts >$10k (streamed) |
| `contract_history_ingest` | 01:30 daily | CanadaBuys contract history |
| `gic_appointments_ingest` | Wed 02:00 | GIC appointments |
| `entity_graph_push` | 02:30 daily | Shared entity-graph adapter |
| `ag_reports` | Wed 03:00 | Auditor-General reports |
| `ingest_freshness_monitor` | 03:00 daily | Alarms on a stale last-SUCCESS |
| `weekly_digest` | Mon 04:00 | Subscriber digest |

`canadabuys_tender_sync` is NOT an APScheduler job — it is a **6h daemon thread** (`_background_sync` in app.py), which is why heartbeats missed it.

## Ingest health — monitor RUNS, not ROWS (#5062 / #5070)

Row counts are not a health signal: a job that runs and inserts 0 is healthy when upstream had nothing new; a job that never RUNS is the failure, and an OOM SIGKILL is uncatchable so its own try/except logs nothing.
- `procure/ingest_health.py`: `gov_watch.ingest_runs` heartbeat table, `record_ingest_run()` on BOTH success and failure paths, `check_ingest_freshness()` alarming via the hub `POST /api/internal/notify` (Bearer, mesh `100.64.0.4`). It alarms on a stale last-**SUCCESS** (48h), never on the recency of the newest attempt; a job with no heartbeat ever reads `unknown` (deliberately not paged).
- ⚠️ A job in `INGEST_JOBS` with no `record_ingest_run` writer stays `unknown` FOREVER — unmonitored while APPEARING monitored. `tests/test_date_guard.py::test_every_monitored_job_has_a_heartbeat_writer` makes that a red test.

## ENTITY_INGEST_URL — the shared entity graph lives on CITADEL (#5799)

`ENTITY_INGEST_URL=http://100.64.0.10:8106` (Citadel/boston-2, `wtf-ingest-api`). ⚠️ **NOT `100.64.0.4:8106` (the hub)**: the service moved in the June migration, the `.env`s did not follow, and gov-watch + legal-watch pushed at a dead port for ~7 weeks with nothing alarming (`entity_graph_push` was the one job with no heartbeat; fixed in kytran-gov-watch#46; legal-watch and civic-watch halves still open under #5799). Apply an `.env` change with `docker compose up -d` — `restart` does NOT re-read `env_file` (KB #268829). `shared.entity_mentions` has only `created_at`, so prove a feed is live via `shared.entities.updated_at`. KB #291054 / #291055, ADR decision 1003.

## Date guard — impossible dates cannot re-enter (#5067 / #5069 / #5072)

`procure/date_guard.sane_date(value, field, *, event=False)` is wired into ALL FOUR parsers: `feeds.CanadaBuysFeed._parse_date`, `procure.proactive._parse_date`, `procure.contract_history._to_date`, `procure.awards._to_date`. ⚠️ `awards.py` has its OWN `_to_date` (unguarded until #44, which is how `award_date = 2030-12-31` got in) — guard both when touching date parsing.
- Rejects **epoch artifacts** (an empty Excel/Lotus-serial cell lands on `1899-12-30`) and **sentinels** (`9999-12-31`).
- `event=True` only for retrospective fields that cannot be in the future (`award_date`, `proactive.contract_date`, `feeds.posted_at`). Forward-looking fields (`deadline`, `delivery_date`, `period_start`, `contract_history.contract_date` = a contract START date, `contract_period_end`) must NOT be `event=True`: over-eager filtering silently drops long-lead contracts and is a WORSE bug than the one being fixed.
- `drain_rejects()` returns a per-column tally of discards; a jump means upstream changed.
- Coverage: the four tables overlap from **2010-03-16** (`tenders` is the constraint). For multi-government comparison use `proactive_disclosures` from **Dec 2003**; the 1996/1999 floors are thin tails, and Chrétien has 157 rows — do NOT chart it.

## Proactive Disclosures

Dataset `d8f85d91-7dec-4fd1-8055-483b77225d8b` (TBS CKAN). Fetch cap **16MB** (was 64MB; caused an OOM in the 768MB container, PR #24). Upsert key `ON CONFLICT (reference_number, amendment_number, vendor_name)`.

## Tier Sync — Never Downgrade (CRITICAL)

`_sync_user_tier()` (app.py) uses a numeric hierarchy: `kytran/owner/admin = 99`, `pro = 60`, `agency = 50`, `team = 40`, `solo = 30`, `starter = 10`. **Only upgrade, never downgrade**; on conflict keep the HIGHER tier. If a session shows Kytran as `tier='free'` that is a bug — check `_sync_user_tier()`.

**Owner identity:** `kytranempowerment@gmail.com`, `kytran@kytranempowerment.com` and `Kytran@KytranEmpowerment.com` (and case variants) are ALL the same person. Multiple DB rows from casing accidents are not duplicate accounts; never propose merging them or give any of them a free-tier default.

## P.R.O.C.U.R.E. Agent

Agent #349, `qwen2.5:7b`, Analytics & Intelligence, capability `procurement_analysis`, dispatched via `POST /api/procure/dispatch` (JWT bearer). 21 API endpoints.

## Internal Tier-Push Endpoint

`/api/internal/set-tier` lets the platform billing webhook push tier changes. Auth: `X-Internal-Key` must equal `INTERNAL_API_KEY` (same value as the platform). Payload `{"email": ..., "tier": ...}` — gov-watch keys on **email**, not user_id; `tier` is one of `kytran, owner, admin, pro, agency, team, solo, starter, free`; the same no-downgrade CASE SQL applies. VPS `.env` needs `INTERNAL_API_KEY=<same value>` — **NEVER overwrite `.env` on the VPS, append only** (it is gitignored and holds secrets). Platform side: `services/watch_billing_handler.py` (`_push_tier_to_standalone()` includes the email).

## Deploy Pattern

```bash
# From hub, sync to Citadel/boston-2 then rebuild (SSH key ~/.ssh/id_ed25519):
rsync -avz --exclude='.env' /mnt/standalone/kytran-gov-watch/ \
  root@100.64.0.10:/opt/archie-products/gov-watch/
# On the VPS:
cd /opt/archie-products/gov-watch/ && docker compose up -d --build kytran_gov_watch
```

The hub source dir can hold uncommitted WIP (usage/billing migrations, kytran_auth changes): `git status` and review before any `git add`.

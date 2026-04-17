# Backup System Redesign — Design Spec

**Date:** 2026-04-16
**Author:** Claude (Opus 4.6) + Kytran
**Status:** Design — awaiting user review before plan
**Context:** GitHub push freeze in effect through 2026-04-30; code and data integrity currently depends solely on host disks.

---

## 1. Problem

The existing backup manager module is architecturally complete (routes, DB dump, external storage, Google Drive shim, pre-change hooks, Repair Bay integration) but three independent failures have left the platform effectively un-backed-up:

1. **Scheduler never installed.** `scripts/archie_crontab.txt` was written to disk but never registered via `crontab`. No entries in `/etc/cron.d/`. Last successful backup: **2026-03-25** — 22 days stale as of 2026-04-16.
2. **USB retention never enforced.** `/mnt/external-backup/` (57 GB) is **100% full** with 9 daily snapshots at 9–12 GB each, spanning 2026-02-02 → 2026-03-20. The retention config said "keep 12 weeklies" but actual contents are unpruned dailies.
3. **Offsite storage never wired.** Google Drive service, encryption helper, and env vars (`GDRIVE_ENABLED`, `GDRIVE_SERVICE_ACCOUNT_PATH`, `GDRIVE_ENCRYPTION_PASSPHRASE_HASH`) are all present; no code path triggers uploads.

Additional context:
- `backup_log` table is empty (0 rows) — no history tracking is wired.
- Pre-change snapshot directory is empty — Repair Bay hooks are not firing.
- Branch `feat/probe-suite-account-center` has 5 commits ahead of origin that cannot be pushed until the freeze lifts, so `.git` is the only canonical copy of recent work.

## 2. Goals & Non-Goals

### Goals
- Restore working daily backups by end of session (triage).
- Tiered, per-component backups (DB, code, git bundles, config, volumes, VPS products) on cadences matched to change rate.
- Four storage tiers: on-host primary → USB hot → GDrive cold → VPS Outpost geographic.
- Config and offsite data encrypted at rest.
- Failures are observable: Telegram alerts on primary-tier failure or > 36 h gap; UI surface for tier health.
- Weekly automated integrity verification of every tier.

### Non-Goals
- Point-in-time recovery / WAL streaming (deferred; RPO of 24 h is acceptable at current stage).
- Automatic restore via UI (manual, deliberate, documented in runbook).
- Backing up regeneratable assets (Ollama model weights, Plex media, ComfyUI checkpoints, Docker images).
- Cross-region S3/B2 storage (GDrive + VPS already covers offsite).

## 3. Decisions Already Made

- **Recovery Point Objective (DB): 24 hours.** Daily `pg_dump` is sufficient.
- **Scope:** everything — platform, standalones, VPS products — but as tiered per-component backups, not one monolithic archive.
- **Storage tiers:** 4-tier (primary / USB hot / GDrive cold / VPS geographic).
- **Scheduling shape:** host cron as the supervisor; platform owns UI/observability/pre-change hooks.
- **Primary storage path:** `/mnt/data/backups/` (currently empty, 873 GB free). **Not** `/mnt/data2/backups/` — that path retains existing archives but has competing workloads and less slack.
- **USB encryption:** config tier only (encrypted), rest plaintext. Full-disk encryption adds restore overhead without meaningful uplift for an offline-held drive.

## 4. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   HOST (192.168.1.200)                      │
│                                                             │
│  /etc/cron.d/archie-backup   (root-owned, git-tracked)      │
│      │                                                      │
│      ▼                                                      │
│  scripts/backup/                                            │
│    ├── run_backup.sh            top-level orchestrator      │
│    ├── lib_common.sh            logging, lock, notify       │
│    ├── component_db.sh          pg_dump via docker exec     │
│    ├── component_code.sh        rsync platform_v2, ai_bridge│
│    ├── component_gitbundle.sh   git bundle --all            │
│    ├── component_config.sh      encrypted (.env, secrets/)  │
│    ├── component_volumes.sh     n8n, KBS, CREED, Stalwart   │
│    ├── component_vps_pull.sh    rsync from Outpost          │
│    ├── component_convlogs.sh    conversation_logs archive   │
│    ├── component_kb_export.sh   pg_dump -t knowledge_base   │
│    ├── tier_sync_usb.py         primary → USB               │
│    ├── tier_sync_gdrive.py      primary → GDrive (encrypted)│
│    ├── tier_sync_vps.sh         primary → Outpost (rsync)   │
│    ├── retention_prune.py       per-tier retention enforce  │
│    └── verify_backups.sh        integrity checks, weekly    │
│                                                             │
│  /mnt/data/backups/             PRIMARY tier (873 GB free)  │
│  /mnt/external-backup/          USB HOT tier (57 GB)        │
└─────────────────────────────────────────────────────────────┘
         │                             │
         │ pg_dump, docker exec        │ writes backup_log rows
         ▼                             ▼
┌─────────────────────────┐   ┌─────────────────────────────┐
│   archie_database       │   │   archie_platform           │
│   (PostgreSQL)          │   │   (Flask app)               │
│                         │◄──┤                             │
│  backup_log table       │   │  Backup Manager module      │
│  (source of truth)      │   │    Reads state for UI       │
└─────────────────────────┘   │    Telegram alerts          │
                              │    Pre-change hook          │
                              │      (APScheduler)          │
                              │                             │
                              │  Platform Watchdog (PR #84) │
                              │    - Reads backup_log       │
                              │    - Alert if > 36 h stale  │
                              │    - Alert if tier < 20%    │
                              └─────────────────────────────┘
         │                                    │
         ▼                                    │
┌─────────────────────────┐                   │
│   Google Drive          │                   │
│   (encrypted cold tier) │                   │
└─────────────────────────┘                   │
                                              │
         ┌────────────────────────────────────┘
         ▼ rsync over mesh (100.64.0.1)
┌─────────────────────────┐
│   VPS US Outpost        │
│   /var/backups/archie/  │
│   (encrypted, mesh only)│
└─────────────────────────┘
```

### Key decisions

- **Cron installs as `/etc/cron.d/archie-backup`** (root-owned, world-readable, lives in the repo, deployed by a bootstrap script). Not `crontab -e` for a user — too easy to miss on a new deploy, which is exactly how this outage happened.
- **All backup scripts in `scripts/backup/`**, git-tracked, POSIX-compatible bash + Python. Host cron calls them directly; platform can also invoke them via `docker exec --user root …` for manual triggers.
- **`backup_log` is single source of truth.** Every component run and every tier sync writes a row. UI and watchdog read this one table.
- **Atomic tier progression:** each tier runs only if the previous succeeded. Primary failure stops the run and alerts. USB/GDrive/VPS failures log a warning but don't fail the overall run — a tier being down isn't a reason to skip later tiers if they're still reachable.
- **Lock file:** `/mnt/data/backups/.backup_lock` with PID + ISO timestamp, 2 h timeout. Prevents overlapping runs.
- **Pre-change hooks stay on APScheduler inside the platform.** They only run when the platform is healthy and Repair Bay is deploying, so no need to move to cron.

## 5. Component Inventory

| # | Component | What | Est. Size | Cadence | Destinations |
|---|-----------|------|-----------|---------|--------------|
| 1 | PostgreSQL | `pg_dump -Fc archie` | ~500 MB | Daily 02:00 | Primary → USB → GDrive |
| 2 | Platform code | `platform_v2/`, `ai_bridge/`, `scripts/`, `database/migrations/` | ~800 MB | Daily 02:10 | Primary → USB → GDrive |
| 3 | Git bundles | `git bundle --all` for `archie_brain`, `kytran-business-suite`, `kytran-server-manager`, `kytran-creed` | ~2 GB day 1; ~100 MB/day after with `--since=1.month` | Daily 02:15 | Primary → USB → GDrive → VPS |
| 4 | Platform config | `.env`, `secrets/`, `docker-compose.yml`, `nginx/`, `.mcp.json`, `CLAUDE.md`, `.claude/rules/` — **encrypted** | ~5 MB | Daily 02:20 | Primary → USB → GDrive → VPS |
| 5 | Docker volumes | `persistence/n8n`, KBS tenant data, CREED db, Stalwart mail | ~3 GB | Daily 02:30 | Primary → USB (Sun) |
| 6 | Conversation logs | `conversation_logs/` | ~600 MB | Weekly Sun 03:00 | Primary only |
| 7 | KB export | `pg_dump --data-only -t knowledge_base` | ~200 MB | Weekly Sun 03:30 | Primary → GDrive |
| 8 | VPS product pull | rsync from Outpost for watch_api, civic, legal, gov, thenews containers + DBs | ~2 GB | Weekly Sun 04:00 | Primary only |
| 9 | Monthly full | tarball of #1 through #8 | ~10–15 GB | 1st of month 01:00 | Primary → GDrive |
| 10 | Pre-change snapshot | Light DB dump + git HEAD, existing `backup_integration_service.py` | ~500 MB | On Repair Bay deploy | Primary only (keep 20) |

### Explicit exclusions
- `/mnt/llm_drive/ollama/models/` — 90+ GB, redownloadable
- `/mnt/Plex/` — media, separately curated, too large
- `/mnt/data2/comfyui/models/checkpoints/` — redownloadable
- Container images — rebuilt from source
- `.git/` itself — covered by the git bundle in #3

## 6. Retention Matrix

Enforced by `retention_prune.py` after each tier sync. **Monotonic** — never deletes something that failed to sync.

| Component | Primary | USB Hot | GDrive Cold | VPS Outpost |
|-----------|---------|---------|-------------|-------------|
| DB dump | 30d + 12w + 6m | 14d + 4w | 4w + 6m | 7d |
| Platform code | 14d + 8w | 7d + 4w | 4w | — (git bundle covers it) |
| Git bundles | 14d + 12m | 7d + 4w | 4w + 6m | 7d |
| Config (encrypted) | 14d + 12m | 7d | 12m | 7d |
| Docker volumes | 14d + 4w | 4w | — | — |
| Conv. logs | 8w | — | — | — |
| KB export | 12w + 6m | — | 6m | — |
| VPS pull | 8w + 3m | — | — | — |
| Monthly full | 6m | — | 6m | — |
| Pre-change | 20 (keep-N) | — | — | — |

Legend: d=daily, w=weekly, m=monthly.

### Space budget (worst case)

| Tier | Capacity | Projected | Headroom |
|------|----------|-----------|----------|
| Primary `/mnt/data` | 873 GB free | ~280 GB | ✅ 593 GB slack |
| USB `/mnt/external-backup` | 57 GB | ~52 GB | ⚠️ tight |
| GDrive | 15 GB free / 100 GB paid ~$2/mo | ~55 GB | ⚠️ needs paid tier |
| VPS Outpost | ~20 GB free | ~18 GB | ⚠️ tight |

**Planned response to pinch points:** let actual retention run for two weeks, measure real sizes, tune retention counts down where needed. The `retention_prune.py` config is declarative (per-component, per-tier dict), so adjustments are 1-line edits.

**Specific pre-emptive mitigation:** git bundles use `--since=1.month.ago` on incremental days, with a full `--all` on the 1st of each month. Drops the daily git bundle from ~2 GB to <100 MB.

## 7. Encryption

| Destination | Method | Key source |
|-------------|--------|-----------|
| Primary `/mnt/data/backups/` | None (on-host, filesystem access-controlled) | — |
| USB `/mnt/external-backup/` | **Config tier only**, AES-256-GCM via `openssl enc` | `BACKUP_CONFIG_PASSPHRASE` env var |
| GDrive cold | **All uploads** encrypted client-side with AES-256-GCM via existing `gdrive_crypto.py` before upload. Drive connection reuses the user's existing Google Work Suite OAuth (no separate service account). | `BACKUP_GDRIVE_PASSPHRASE` env var |
| VPS Outpost | Transport: WireGuard mesh. At-rest: AES-256-GCM | `BACKUP_VPS_PASSPHRASE` env var |

- Passphrases live in host `/mnt/archie_brain/.env`, **never** in container env or git.
- Backup scripts `source` the .env at run time.
- Restore flow documented in `scripts/backup/README.md`. One-shot tool: `scripts/backup/decrypt_restore.sh <file> <passphrase-env-var>` pipes through `openssl enc -d -aes-256-gcm -pbkdf2`.
- Config tier (`.env`, `secrets/`, `.mcp.json`) is **always encrypted before leaving primary**, regardless of destination. A plaintext `.env` on a stolen USB is a full compromise.

## 8. Alerting & Monitoring

| Event | Mechanism | Destination |
|-------|-----------|-------------|
| Primary backup failed | Exit code != 0 → Telegram (existing A.R.C.H.I.E. bot) | You, immediate |
| No backup in 36 h | Watchdog reads `MAX(created_at) FROM backup_log` | You, every check cycle until fixed |
| Offsite tier (USB/GDrive/VPS) failed | Warning row in `backup_log`, surfaces in Backup Manager UI as yellow | UI only, no page |
| Disk < 20% free on any tier | Watchdog check, Telegram alert | You, hourly until acted |
| Restore verification failed (weekly) | See §9 | You, immediate |
| Successful daily | Silent — `backup_log` row only, no alert noise | — |

The Platform Watchdog (PR #84) is already running every 2 min with Telegram dedup; backup checks piggyback on its existing cycle. Additions are small: one extra query, one extra disk check.

## 9. Testing & Verification

Weekly, Sunday 05:00, after retention prune. Script: `scripts/backup/verify_backups.sh`.

1. **DB dump integrity** — `pg_restore --list` on latest daily. Validates archive metadata without restoring. ~30 s.
2. **Code archive integrity** — `tar -tzf` on latest code archive, must exit 0.
3. **Git bundle integrity** — `git bundle verify` on latest `archie_brain` bundle.
4. **Config encryption roundtrip** — decrypt latest config blob with passphrase from env, compare SHA-256 of a known sentinel file (`.backup_sentinel`) that's added to every config tier archive.
5. **Quarterly restore drill** — manual, not automated. Pick a random weekly backup. Actually restore into a sandbox container. Confirm the platform boots and a known KB query returns rows. Logged as a recurring quarterly task in Dev HQ.

All verification results write a row in `backup_log` with `verification_status` column (`verified`, `failed`, `not_yet_run`). UI surfaces unverified or failed backups in yellow.

## 10. Triage (executed before full implementation lands)

Goal: a known-good backup on disk and a working schedule by end of session 2026-04-16.

1. **Free the USB** — delete 7 oldest dailies, keep `20260319_*` and `20260320_*` as a safety net. Frees ~46 GB.
2. **Run one manual backup** — invoke `create_backup_programmatic('Manual_Triage', '/mnt/data2/backups')` via existing route. Copy result to USB. Verify extractability.
3. **Install host crontab** — `sudo cp scripts/archie_crontab.txt /etc/cron.d/archie-backup` (or equivalent user crontab). Confirm with `crontab -l` or `/etc/cron.d/` listing. Fire a one-shot test entry.
4. **Wire watchdog backup-freshness check** — add 10-line SQL query + alert path to Platform Watchdog. Commits locally (freeze).
5. **Code safety net** — `git bundle create /mnt/data/code_bundles/archie_20260416.bundle --all` and a second bundle for each standalone repo. Copy to USB + manually upload to GDrive. Belt and suspenders for the push freeze.

End state of triage: one verified backup on `/mnt/data2` + USB, one code bundle on USB + GDrive, cron running, watchdog alerting if no backup in 36 h.

## 11. Implementation Notes / Caveats

- **`scripts/archie_crontab.txt` already exists and describes the right schedule.** The fix is installation + retention-prune script + offsite tier scripts + watchdog integration. Not a green-field rewrite.
- **`gdrive_service.py` is a shim** pointing to `tools/google_work_suite/services/drive_service.py`. Reuse those functions directly (`backup_upload_file`, `backup_ensure_folder`, etc.) rather than duplicating logic. The Work Suite OAuth is already connected to the user's personal Drive — no service account setup, no separate credentials, no folder sharing needed. Encryption happens client-side (AES-256-GCM) before upload, so Google never sees plaintext.
- **`acquire_backup_lock()` already exists** in `backup_manager_routes.py` — the new scripts call into it, not re-implement.
- **`backup_log` table** needs to exist (currently 0 rows but might not even have the right schema). Plan task: check schema, migrate if needed.
- **VPS Outpost rsync** assumes SSH key already deployed for the mesh account. Verify before Session 2 of implementation. If not, add key-deploy step to the plan.
- **Passphrase generation**: use `openssl rand -base64 48` for each of the three passphrases; write to `.env` once and never rotate casually — rotation breaks all existing encrypted backups.
- **GDrive storage uses the user's personal Drive quota** (via Google Work Suite OAuth). Free tier = 15 GB; if the user is already on Google One 100 GB or 2 TB, quota is non-blocking. Implementation plan should include a quota-check step at GDrive tier start — if projected upload would exceed available quota, skip with a warning row in `backup_log` rather than fail.

## 12. Open Risks

| Risk | Mitigation |
|------|------------|
| GDrive passphrase loss → all cold backups unrecoverable | Passphrase printed on paper, stored in physical safe (off-system). Documented in runbook. |
| Cron install reverts on OS reinstall | `/etc/cron.d/archie-backup` is deployed by a bootstrap script that runs in A.R.C.H.I.E. Platform Watchdog's first-boot check. |
| USB drive physical failure | Retention is redundant across 4 tiers; USB failure = one tier lost, not catastrophic. |
| Hub fire/theft | GDrive + VPS Outpost are geographically separate. Passphrase safe must be off-site. |
| Large code bundle size if `--since` edge case | Monthly full `--all` bundle exists; worst case is a 1-month gap, not complete loss. |
| Encryption passphrase leaked in logs | Scripts use `read -s` / env var only; no passphrase in shell history or log files; verify at review time. |

## 13. Out of Scope (Documented for Later)

- WAL streaming replication for sub-hour RPO.
- Automated restore orchestrator (currently manual + documented).
- Backup browser UI for searching/previewing archive contents.
- PITR (point-in-time recovery) from WAL + base backup.
- Customer-data-specific retention (if KBS grows per-tenant backup needs, this will need extension).

---

## 14. Acceptance Criteria

Implementation is complete when:

1. Cron entry is present in `/etc/cron.d/archie-backup` and a test fire succeeds.
2. `backup_log` has at least one row per component-tier for the last 24 h.
3. USB, GDrive, and VPS each hold at least one successfully-synced backup, verified by `verify_backups.sh` output.
4. Platform Watchdog fires a Telegram test alert when `backup_log` is artificially stale (e.g., `UPDATE … SET created_at = NOW() - INTERVAL '40 hours'` on a test row, then revert).
5. Restoring the latest DB dump into a disposable Postgres container and running `SELECT COUNT(*) FROM knowledge_base;` returns a row count within 1% of production.
6. `scripts/backup/README.md` documents the restore procedure and passphrase recovery.
7. A row exists in Dev HQ projects for "Quarterly backup restore drill" with a recurring cadence.

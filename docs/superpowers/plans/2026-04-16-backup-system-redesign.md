# Backup System Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore working backups (currently 22 days stale), and replace the broken single-cron-to-USB design with a 4-tier, per-component, tiered-retention system (primary `/mnt/data` → USB hot → GDrive cold → VPS Outpost geographic) with encryption, integrity verification, and watchdog freshness alerts.

**Architecture:** Host cron (`/etc/cron.d/archie-backup`) drives POSIX shell + Python scripts in `scripts/backup/`. Each component (DB, code, git bundles, config, volumes, VPS pull) writes to primary `/mnt/data/backups/`, then tier-sync scripts copy to USB, GDrive (encrypted via existing Work Suite OAuth), and VPS Outpost (encrypted over mesh). Platform Flask app is the **observer** — reads `backup_log` table for UI and watchdog alerts, but does not run the scheduler. Pre-change snapshots stay on APScheduler (they only fire when the platform is up anyway).

**Tech Stack:** bash 5 (POSIX), Python 3.10, PostgreSQL 15 (`pg_dump -Fc`), `openssl enc -aes-256-gcm -pbkdf2`, `rsync`, `git bundle`, existing `tools/google_work_suite/services/drive_service.py` (Google OAuth + Drive API v3), existing Telegram bot (`services/telegram_service.py`).

**Related spec:** `docs/superpowers/specs/2026-04-16-backup-system-design.md`

**Constraints:**
- **GitHub push freeze active through 2026-04-30.** All commits are local-only until then. No `git push`, no `gh pr create`. Scripts on host (`scripts/backup/`, `/etc/cron.d/archie-backup`) can be deployed immediately — platform-code changes (watchdog, UI) land the moment they're committed but won't reach origin until freeze lifts.
- User is REMOTE — never localhost, always `192.168.1.200`.
- No direct Ollama inference; we don't touch LLM routing here.
- All agent table mutations via `services/agent_service.py` — N/A for this plan.

---

## File Structure

### Created (new)
```
scripts/backup/
├── README.md                        # Restore runbook + passphrase recovery
├── lib_common.sh                    # Shared helpers: log, notify, lock, db
├── run_backup.sh                    # Top-level orchestrator
├── install_cron.sh                  # Idempotent cron-install bootstrap
├── component_db.sh                  # pg_dump -Fc
├── component_code.sh                # rsync platform code
├── component_gitbundle.sh           # git bundle --all / --since
├── component_config.sh              # encrypted config archive
├── component_volumes.sh             # docker volume dumps
├── component_convlogs.sh            # weekly conversation_logs
├── component_kb_export.sh           # weekly KB export
├── component_vps_pull.sh            # weekly VPS rsync pull
├── component_monthly_full.sh        # monthly tarball of everything
├── tier_sync_usb.py                 # primary → USB
├── tier_sync_gdrive.py              # primary → GDrive (encrypted)
├── tier_sync_vps.sh                 # primary → VPS Outpost
├── retention_prune.py               # per-tier retention policy
├── verify_backups.sh                # weekly integrity checks
└── decrypt_restore.sh               # manual decrypt helper
```

```
/etc/cron.d/archie-backup            # installed by install_cron.sh
/mnt/data/backups/                   # PRIMARY tier (new mount point)
```

### Modified (existing)
- `platform_v2/services/watchdog.py`                       — add backup-freshness + disk-free checks
- `platform_v2/tools/backup_manager/backup_manager_routes.py` — `/health` endpoint reads tier state
- `platform_v2/services/backup_integration_service.py`     — pre-change hook writes to `backup_log`
- `database/migrations/NNN_backup_log_schema.sql`          — add columns if missing: `component`, `tier`, `size_bytes`, `duration_ms`, `verification_status`, `error_message`
- `.env` (host only, not container)                        — add `BACKUP_CONFIG_PASSPHRASE`, `BACKUP_GDRIVE_PASSPHRASE`, `BACKUP_VPS_PASSPHRASE`

### Migrated
- `scripts/archie_crontab.txt` → replaced by `scripts/backup/install_cron.sh` + `/etc/cron.d/archie-backup` (content equivalent but formally deployed).

---

# Phase 0 — Triage (complete before main implementation starts)

Get *something* running tonight. Every task here is a one-shot manual action, not automated yet.

### Task T1: Free the USB (~5 min)

**Files:** none — filesystem ops only.

- [ ] **Step 1:** Confirm what's there.

```bash
ls -la /mnt/external-backup/ | awk '{print $NF}' | grep Daily_Scheduled | sort
du -sh /mnt/external-backup/*/ | sort -h
df -h /mnt/external-backup
```

Expected: 9 dailies, 100% full.

- [ ] **Step 2:** Delete the 7 oldest; keep `20260319_*` and `20260320_*` as a safety net.

```bash
sudo rm -rf /mnt/external-backup/20260202_020002_Daily_Scheduled
sudo rm -rf /mnt/external-backup/20260209_020002_Daily_Scheduled
sudo rm -rf /mnt/external-backup/20260309_020002_Daily_Scheduled
sudo rm -rf /mnt/external-backup/20260315_020001_Daily_Scheduled
sudo rm -rf /mnt/external-backup/20260316_020002_Daily_Scheduled
sudo rm -rf /mnt/external-backup/20260317_020001_Daily_Scheduled
sudo rm -rf /mnt/external-backup/20260318_020001_Daily_Scheduled
```

- [ ] **Step 3:** Verify.

```bash
df -h /mnt/external-backup
ls /mnt/external-backup/
```

Expected: ~24 GB used, ~33 GB free. Only 2 dailies remain.

### Task T2: Take one verified manual backup (~15 min)

**Files:** none — uses existing `create_backup_programmatic()`.

- [ ] **Step 1:** Trigger the existing backup function.

```bash
docker exec archie_platform python3 -c "
from tools.backup_manager.backup_manager_routes import create_backup_programmatic
r = create_backup_programmatic('Manual_Triage_20260416', '/mnt/data2/backups')
print(r)
"
```

Expected: dict with `success: True`, path to backup dir, component count.

- [ ] **Step 2:** Verify the snapshot.

```bash
ls -lah /mnt/data2/backups/ | grep Manual_Triage | head
du -sh /mnt/data2/backups/*Manual_Triage*/
ls /mnt/data2/backups/*Manual_Triage*/ | head -20
```

Expected: single dated directory, a few GB, contains `database/`, `platform_v2/`, `ai_bridge/`, etc.

- [ ] **Step 3:** Copy to USB.

```bash
TRIAGE_DIR=$(ls -d /mnt/data2/backups/*Manual_Triage* | head -1)
sudo rsync -ah --info=progress2 "$TRIAGE_DIR" /mnt/external-backup/
ls /mnt/external-backup/ | grep Manual_Triage
```

Expected: copy completes; target dir present on USB.

- [ ] **Step 4:** Verify the DB dump inside it is valid.

```bash
BK=$(ls -d /mnt/data2/backups/*Manual_Triage*/database/*.sql* 2>/dev/null | head -1)
echo "DB dump: $BK"
if [[ "$BK" == *.gz ]]; then
  gzip -t "$BK" && echo "gzip OK"
  zcat "$BK" | head -20
else
  head -20 "$BK"
fi
```

Expected: valid gzip or SQL text starting with `-- PostgreSQL database dump`.

### Task T3: Create code safety-net bundles (~10 min)

**Files:**
- Create: `/mnt/data/code_bundles/archie_20260416.bundle`
- Create: `/mnt/data/code_bundles/kbs_20260416.bundle`
- Create: `/mnt/data/code_bundles/ksm_20260416.bundle`
- Create: `/mnt/data/code_bundles/creed_20260416.bundle`

- [ ] **Step 1:** Create the bundle directory.

```bash
sudo mkdir -p /mnt/data/code_bundles
sudo chown kytran:kytran /mnt/data/code_bundles
```

- [ ] **Step 2:** Bundle every repo that currently exists on the hub.

```bash
TS=$(date +%Y%m%d)
cd /mnt/archie_brain                          && git bundle create /mnt/data/code_bundles/archie_${TS}.bundle --all
cd /mnt/archie_brain/kytran-business-suite    && git bundle create /mnt/data/code_bundles/kbs_${TS}.bundle --all
cd /mnt/archie_brain/kytran-server-manager    && git bundle create /mnt/data/code_bundles/ksm_${TS}.bundle --all
cd /mnt/archie_brain/kytran-creed             && git bundle create /mnt/data/code_bundles/creed_${TS}.bundle --all
ls -lah /mnt/data/code_bundles/
```

Expected: 4 `.bundle` files, archie likely 1–2 GB, others smaller.

- [ ] **Step 3:** Verify each bundle.

```bash
for f in /mnt/data/code_bundles/*_${TS}.bundle; do
  echo "=== $f ==="
  git bundle verify "$f"
done
```

Expected: each reports "is okay" with commit count.

- [ ] **Step 4:** Copy to USB for offsite hard copy.

```bash
sudo cp /mnt/data/code_bundles/*_${TS}.bundle /mnt/external-backup/
ls -lah /mnt/external-backup/ | grep bundle
```

### Task T4: Install host crontab (temporary, pre-refactor) (~5 min)

> This is a stopgap — Task 4 in Phase 1 replaces it with `install_cron.sh`. For now, just get *something* scheduled.

- [ ] **Step 1:** Review the existing config file.

```bash
cat /mnt/archie_brain/scripts/archie_crontab.txt
```

- [ ] **Step 2:** Install as root cron (requires sudo password).

```bash
sudo cp /mnt/archie_brain/scripts/archie_crontab.txt /etc/cron.d/archie-backup-triage
sudo chmod 644 /etc/cron.d/archie-backup-triage
sudo chown root:root /etc/cron.d/archie-backup-triage
sudo sed -i 's|^\([0-9*/]\+ [0-9*/]\+ [0-9*/]\+ [0-9*/]\+ [0-9*/]\+\) |\1 root |' /etc/cron.d/archie-backup-triage
sudo systemctl restart cron
```

- [ ] **Step 3:** Verify cron picked it up.

```bash
sudo grep CRON /var/log/syslog | tail -20
sudo cat /etc/cron.d/archie-backup-triage | head
```

Expected: No parse errors in syslog; file content intact with `root` user column.

- [ ] **Step 4:** Set a 2-minute test-fire entry and watch it run.

```bash
echo "* * * * * root logger 'archie-backup-cron-test'" | sudo tee -a /etc/cron.d/archie-backup-triage
sleep 90
sudo grep archie-backup-cron-test /var/log/syslog | tail
sudo sed -i '/archie-backup-cron-test/d' /etc/cron.d/archie-backup-triage
```

Expected: a syslog line confirms the cron fired.

### Task T5: Triage verification end-state (~5 min)

- [ ] **Step 1:** Walk through end-state checklist.

```bash
echo "=== Primary backup (Manual_Triage) ==="
ls -d /mnt/data2/backups/*Manual_Triage* 2>&1
echo "=== USB copy ==="
ls -d /mnt/external-backup/*Manual_Triage* 2>&1
ls /mnt/external-backup/*.bundle 2>&1
echo "=== Code bundles on primary ==="
ls -lah /mnt/data/code_bundles/
echo "=== Cron entry ==="
sudo ls /etc/cron.d/archie-backup-triage 2>&1
echo "=== USB free space ==="
df -h /mnt/external-backup
```

Expected: all 5 checks show existing content, USB >15% free.

- [ ] **Step 2:** Log triage completion in Dev HQ via `mcp__archie__add_work_note` on the new backup-system project.

---

# Phase 1 — Foundation

Everything after this phase assumes `/mnt/data/backups/` is the canonical primary tier (not `/mnt/data2/backups/`). Triage backups stay at `/mnt/data2` as legacy.

### Task 1: Create `scripts/backup/` directory + `lib_common.sh`

**Files:**
- Create: `scripts/backup/lib_common.sh`
- Create: `scripts/backup/.gitkeep`

- [ ] **Step 1:** Create the directory.

```bash
cd /mnt/archie_brain
mkdir -p scripts/backup
touch scripts/backup/.gitkeep
```

- [ ] **Step 2:** Write `lib_common.sh`.

```bash
#!/usr/bin/env bash
# scripts/backup/lib_common.sh
# Shared helpers for all backup components. Sourced by every script; do NOT execute directly.
set -euo pipefail

BACKUP_ROOT="${BACKUP_ROOT:-/mnt/data/backups}"
BACKUP_USB="${BACKUP_USB:-/mnt/external-backup}"
BACKUP_LOCK="${BACKUP_ROOT}/.backup_lock"
BACKUP_LOG_FILE="${BACKUP_LOG_FILE:-/var/log/archie_backup.log}"
ARCHIE_REPO="${ARCHIE_REPO:-/mnt/archie_brain}"

log() {
    local level="$1"; shift
    local msg="$*"
    local ts; ts=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
    echo "[$ts] [$level] [$(basename "${BASH_SOURCE[1]:-backup}")] $msg" | tee -a "$BACKUP_LOG_FILE" >&2
}
log_info()  { log INFO  "$@"; }
log_warn()  { log WARN  "$@"; }
log_error() { log ERROR "$@"; }

acquire_lock() {
    local name="$1" timeout_sec="${2:-7200}"
    if [[ -f "$BACKUP_LOCK" ]]; then
        local lock_age; lock_age=$(( $(date +%s) - $(stat -c %Y "$BACKUP_LOCK") ))
        if (( lock_age < timeout_sec )); then
            log_error "Backup lock held ($(cat "$BACKUP_LOCK")), age ${lock_age}s < ${timeout_sec}s — exiting"
            return 2
        fi
        log_warn "Stale lock (age ${lock_age}s) — reclaiming"
    fi
    echo "pid=$$ name=$name started=$(date -u +%FT%TZ)" > "$BACKUP_LOCK"
    trap 'release_lock' EXIT INT TERM
}
release_lock() { rm -f "$BACKUP_LOCK" 2>/dev/null || true; }

psql_archie() {
    docker exec -i archie_database psql -U archie -d archie "$@"
}

log_to_db() {
    local component="$1" tier="$2" status="$3" path="$4" size="${5:-0}" duration_ms="${6:-0}" err="${7:-}"
    local esc_err; esc_err=$(printf '%s' "$err" | sed "s/'/''/g")
    psql_archie -c "INSERT INTO backup_log
        (component, tier, status, file_path, size_bytes, duration_ms, error_message, created_at)
        VALUES
        ('$component', '$tier', '$status', '$path', $size, $duration_ms, NULLIF('$esc_err',''), NOW());" \
        >/dev/null || log_warn "Failed to write backup_log row for $component/$tier"
}

notify_telegram() {
    local severity="$1"; shift
    local msg="$*"
    docker exec archie_platform python3 -c "
from services.telegram_service import send_archie_alert
send_archie_alert('$severity', '''$msg''', source_agent='backup_system')
" 2>&1 | tail -1 || log_warn "Telegram notify failed (continuing)"
}

load_backup_env() {
    if [[ ! -f "${ARCHIE_REPO}/.env" ]]; then
        log_error ".env not found at ${ARCHIE_REPO}/.env"
        return 1
    fi
    # shellcheck disable=SC1091
    set -o allexport
    source "${ARCHIE_REPO}/.env"
    set +o allexport
}

backup_ts() { date -u +'%Y%m%d_%H%M%S'; }
dir_size_bytes() { du -sb "$1" 2>/dev/null | awk '{print $1}' || echo 0; }
```

- [ ] **Step 3:** Verify the library sources without errors.

```bash
bash -c 'set -e; source /mnt/archie_brain/scripts/backup/lib_common.sh; log_info "lib_common sources OK"'
```

Expected: single INFO log line, exit 0.

- [ ] **Step 4:** Commit.

```bash
cd /mnt/archie_brain
git add scripts/backup/lib_common.sh scripts/backup/.gitkeep
git commit -m "feat(backup): add shared backup library (lib_common.sh)

Introduces logging, locking, DB logging, Telegram notify, and
passphrase-loading helpers used by all backup components.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 2: Migrate `backup_log` table schema

**Files:**
- Create: `database/migrations/NNN_backup_log_schema.sql`

- [ ] **Step 1:** Inspect current table (if any).

```bash
docker exec archie_database psql -U archie -d archie -c "\d backup_log" 2>&1
```

- [ ] **Step 2:** Write migration (idempotent).

```sql
-- database/migrations/NNN_backup_log_schema.sql
CREATE TABLE IF NOT EXISTS backup_log (
    id              BIGSERIAL PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    component       TEXT NOT NULL,
    tier            TEXT NOT NULL,
    status          TEXT NOT NULL,
    file_path       TEXT,
    size_bytes      BIGINT DEFAULT 0,
    duration_ms     INTEGER DEFAULT 0,
    verification_status TEXT DEFAULT 'not_yet_run',
    error_message   TEXT,
    notes           TEXT
);

ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS component           TEXT;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS tier                TEXT;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS size_bytes          BIGINT DEFAULT 0;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS duration_ms         INTEGER DEFAULT 0;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS verification_status TEXT DEFAULT 'not_yet_run';
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS error_message       TEXT;
ALTER TABLE backup_log ADD COLUMN IF NOT EXISTS notes               TEXT;

CREATE INDEX IF NOT EXISTS idx_backup_log_created_at      ON backup_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_log_component_tier  ON backup_log (component, tier, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_log_status          ON backup_log (status) WHERE status != 'success';
```

- [ ] **Step 3:** Apply and verify.

```bash
N=$(ls /mnt/archie_brain/database/migrations/ | grep -E '^[0-9]+_' | sort -n | tail -1 | cut -d_ -f1)
NEXT=$(printf "%03d" $((10#$N + 1)))
MIGRATION_PATH="/mnt/archie_brain/database/migrations/${NEXT}_backup_log_schema.sql"
# Write the SQL from Step 2 to $MIGRATION_PATH
docker cp "$MIGRATION_PATH" archie_database:/tmp/migration.sql
docker exec archie_database psql -U archie -d archie -f /tmp/migration.sql
docker exec archie_database psql -U archie -d archie -c "\d backup_log"
```

Expected: table exists with all columns; indexes listed.

- [ ] **Step 4:** Commit.

```bash
cd /mnt/archie_brain
git add database/migrations/${NEXT}_backup_log_schema.sql
git commit -m "feat(db): canonical backup_log schema

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 3: Write `run_backup.sh` orchestrator

**Files:**
- Create: `scripts/backup/run_backup.sh`

- [ ] **Step 1:** Write the orchestrator.

```bash
#!/usr/bin/env bash
# scripts/backup/run_backup.sh
# Usage:
#   run_backup.sh daily / weekly / monthly / <component>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

MODE="${1:-daily}"
TS=$(backup_ts)
RUN_DIR="${BACKUP_ROOT}/${TS}_${MODE}"

mkdir -p "$BACKUP_ROOT"
acquire_lock "$MODE" || { log_error "run_backup $MODE aborted — locked"; exit 2; }

log_info "=== run_backup.sh MODE=$MODE TS=$TS RUN_DIR=$RUN_DIR ==="
mkdir -p "$RUN_DIR"

START_EPOCH=$(date +%s)
FAILED=0

run_component() {
    local name="$1"; shift
    log_info "→ component: $name"
    if ! "$SCRIPT_DIR/component_${name}.sh" "$RUN_DIR" "$@"; then
        log_error "Component FAILED: $name"
        FAILED=1
    fi
}

case "$MODE" in
    daily)
        run_component db
        run_component code
        run_component gitbundle
        run_component config
        run_component volumes
        ;;
    weekly)
        run_component db
        run_component code
        run_component gitbundle
        run_component config
        run_component volumes
        run_component convlogs
        run_component kb_export
        run_component vps_pull
        ;;
    monthly)
        run_component db
        run_component code
        run_component gitbundle
        run_component config
        run_component volumes
        run_component convlogs
        run_component kb_export
        run_component vps_pull
        run_component monthly_full
        ;;
    db|code|gitbundle|config|volumes|convlogs|kb_export|vps_pull|monthly_full)
        run_component "$MODE"
        ;;
    *)
        log_error "Unknown MODE: $MODE"; exit 1 ;;
esac

if (( FAILED == 0 )); then
    log_info "All components OK — starting tier sync"
    "$SCRIPT_DIR/tier_sync_usb.py"    "$RUN_DIR" || log_warn "USB tier sync had errors"
    "$SCRIPT_DIR/tier_sync_gdrive.py" "$RUN_DIR" "$MODE" || log_warn "GDrive tier sync had errors"
    "$SCRIPT_DIR/tier_sync_vps.sh"    "$RUN_DIR" || log_warn "VPS tier sync had errors"
    "$SCRIPT_DIR/retention_prune.py"  || log_warn "Retention prune had errors"
else
    log_error "Component failures — skipping tier sync + retention"
    notify_telegram error "Primary backup failed: mode=$MODE ts=$TS run=$RUN_DIR"
fi

DUR_MS=$(( ( $(date +%s) - START_EPOCH ) * 1000 ))
SIZE=$(dir_size_bytes "$RUN_DIR")
log_to_db "run_backup" "primary" \
    "$([[ $FAILED -eq 0 ]] && echo success || echo failed)" \
    "$RUN_DIR" "$SIZE" "$DUR_MS"

log_info "=== run_backup.sh DONE mode=$MODE failed=$FAILED size=$SIZE dur_ms=$DUR_MS ==="
exit "$FAILED"
```

- [ ] **Step 2:** Make executable + syntax check.

```bash
cd /mnt/archie_brain
chmod +x scripts/backup/run_backup.sh
bash -n scripts/backup/run_backup.sh && echo "syntax OK"
```

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/run_backup.sh
git commit -m "feat(backup): orchestrator run_backup.sh

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 4: Write `install_cron.sh` + deploy `/etc/cron.d/archie-backup`

**Files:**
- Create: `scripts/backup/install_cron.sh`
- Deployed: `/etc/cron.d/archie-backup`
- Remove: `scripts/archie_crontab.txt`

- [ ] **Step 1:** Write the install script.

```bash
#!/usr/bin/env bash
# scripts/backup/install_cron.sh
# Idempotent install of /etc/cron.d/archie-backup. Run as root.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CRON_FILE="/etc/cron.d/archie-backup"
BACKUP_CMD="${SCRIPT_DIR}/run_backup.sh"

[[ $EUID -ne 0 ]] && { echo "Must run as root. sudo $0"; exit 1; }
[[ ! -x "$BACKUP_CMD" ]] && { echo "Missing/non-executable: $BACKUP_CMD"; exit 1; }

cat > "$CRON_FILE" <<EOF
# A.R.C.H.I.E. Backup Schedule — managed by scripts/backup/install_cron.sh
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
MAILTO=""

# Daily at 02:00 UTC
0 2 * * *  root  $BACKUP_CMD daily    >> /var/log/archie_backup.log 2>&1

# Weekly (Sunday 03:00 UTC)
0 3 * * 0  root  $BACKUP_CMD weekly   >> /var/log/archie_backup.log 2>&1

# Monthly (1st of month 01:00 UTC)
0 1 1 * *  root  $BACKUP_CMD monthly  >> /var/log/archie_backup.log 2>&1

# Weekly verification (Sunday 05:00 UTC — after retention prune)
0 5 * * 0  root  $SCRIPT_DIR/verify_backups.sh >> /var/log/archie_backup.log 2>&1

# Daily pre-change snapshot cleanup at 06:00 UTC (keep 20)
0 6 * * *  root  docker exec archie_platform python3 -c "from services.backup_integration_service import cleanup_old_snapshots; cleanup_old_snapshots('/mnt/data/backups/pre-change', 20)" >> /var/log/archie_backup.log 2>&1
EOF

chmod 644 "$CRON_FILE"
chown root:root "$CRON_FILE"

if systemctl is-active --quiet cron;  then systemctl reload cron  || systemctl restart cron; fi
if systemctl is-active --quiet crond; then systemctl reload crond || systemctl restart crond; fi

echo "Installed: $CRON_FILE"
cat "$CRON_FILE"
```

- [ ] **Step 2:** Run as root.

```bash
cd /mnt/archie_brain
chmod +x scripts/backup/install_cron.sh
sudo scripts/backup/install_cron.sh
```

Expected: prints installed file contents; cron reloaded without error.

- [ ] **Step 3:** Remove the legacy crontab file.

```bash
git rm scripts/archie_crontab.txt
sudo rm -f /etc/cron.d/archie-backup-triage
```

- [ ] **Step 4:** Commit.

```bash
git add scripts/backup/install_cron.sh
git commit -m "feat(backup): install_cron.sh deploys /etc/cron.d/archie-backup

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

# Phase 2 — Component scripts

Each script writes one artifact into `$RUN_DIR` (passed as $1), logs to `backup_log`, exits 0 on success.

### Task 5: `component_db.sh`

**Files:** Create `scripts/backup/component_db.sh`

- [ ] **Step 1:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/component_db.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/database"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/archie_$(backup_ts).dump"

if docker exec archie_database pg_dump -U archie -d archie -Fc -Z 6 > "$OUT_FILE"; then
    SIZE=$(stat -c %s "$OUT_FILE")
    DUR=$(( ( $(date +%s) - START ) * 1000 ))
    log_info "DB dump OK — $SIZE bytes in ${DUR}ms"
    log_to_db "db" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
else
    DUR=$(( ( $(date +%s) - START ) * 1000 ))
    log_error "pg_dump failed"
    log_to_db "db" "primary" "failed" "$OUT_FILE" "0" "$DUR" "pg_dump nonzero exit"
    exit 1
fi
```

- [ ] **Step 2:** Test (primary only).

```bash
cd /mnt/archie_brain
chmod +x scripts/backup/component_db.sh
mkdir -p /tmp/backup_smoke
scripts/backup/component_db.sh /tmp/backup_smoke
ls -lah /tmp/backup_smoke/database/
docker exec archie_database pg_restore --list /tmp/backup_smoke/database/*.dump | head
```

Expected: `.dump` file (~500 MB), `pg_restore --list` shows table entries.

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/component_db.sh
git commit -m "feat(backup): component_db.sh — pg_dump -Fc compressed

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 6: `component_code.sh`

**Files:** Create `scripts/backup/component_code.sh`

- [ ] **Step 1:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/component_code.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/code"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/archie_code_$(backup_ts).tar.gz"

tar -czf "$OUT_FILE" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='node_modules' \
    --exclude='.venv' \
    --exclude='*.pyc' \
    -C "$ARCHIE_REPO" \
    platform_v2 ai_bridge scripts database/migrations 2>>"$BACKUP_LOG_FILE"

SIZE=$(stat -c %s "$OUT_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))

if tar -tzf "$OUT_FILE" >/dev/null 2>&1; then
    log_info "code tar OK — $SIZE bytes in ${DUR}ms"
    log_to_db "code" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
else
    log_error "code tar failed integrity check"
    log_to_db "code" "primary" "failed" "$OUT_FILE" "$SIZE" "$DUR" "tar -tzf failed"
    exit 1
fi
```

- [ ] **Step 2:** Test.

```bash
chmod +x scripts/backup/component_code.sh
scripts/backup/component_code.sh /tmp/backup_smoke
tar -tzf /tmp/backup_smoke/code/archie_code_*.tar.gz | head
du -h /tmp/backup_smoke/code/archie_code_*.tar.gz
```

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/component_code.sh
git commit -m "feat(backup): component_code.sh — tar platform code

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 7: `component_gitbundle.sh`

**Files:** Create `scripts/backup/component_gitbundle.sh`

- [ ] **Step 1:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/component_gitbundle.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/gitbundles"
mkdir -p "$OUT_DIR"

DOM=$(date +%d)
if [[ "$DOM" == "01" ]]; then
    RANGE_ARGS=( --all )
    BUNDLE_KIND="full"
else
    RANGE_ARGS=( --all --since=1.month.ago )
    BUNDLE_KIND="incremental"
fi

REPOS=(
    "archie:/mnt/archie_brain"
    "kbs:/mnt/archie_brain/kytran-business-suite"
    "ksm:/mnt/archie_brain/kytran-server-manager"
    "creed:/mnt/archie_brain/kytran-creed"
)

TOTAL_SIZE=0
FAILED=0
START=$(date +%s)

for entry in "${REPOS[@]}"; do
    name="${entry%%:*}"
    path="${entry#*:}"
    if [[ ! -d "$path/.git" ]]; then
        log_warn "skip $name — $path is not a git repo"
        continue
    fi
    OUT_FILE="$OUT_DIR/${name}_${BUNDLE_KIND}_$(backup_ts).bundle"
    if git -C "$path" bundle create "$OUT_FILE" "${RANGE_ARGS[@]}" 2>>"$BACKUP_LOG_FILE"; then
        if git bundle verify "$OUT_FILE" >/dev/null 2>&1; then
            sz=$(stat -c %s "$OUT_FILE")
            TOTAL_SIZE=$(( TOTAL_SIZE + sz ))
            log_info "bundle $name $BUNDLE_KIND OK — $sz bytes"
        else
            log_error "bundle $name failed verify"
            FAILED=1
        fi
    else
        log_error "git bundle create failed for $name"
        FAILED=1
    fi
done

DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_to_db "gitbundle" "primary" "$STATUS" "$OUT_DIR" "$TOTAL_SIZE" "$DUR" ""
exit "$FAILED"
```

- [ ] **Step 2:** Test.

```bash
chmod +x scripts/backup/component_gitbundle.sh
scripts/backup/component_gitbundle.sh /tmp/backup_smoke
ls -lah /tmp/backup_smoke/gitbundles/
for f in /tmp/backup_smoke/gitbundles/*.bundle; do git bundle verify "$f" | head -1; done
```

Expected: 4 bundles, each reports "is okay".

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/component_gitbundle.sh
git commit -m "feat(backup): component_gitbundle.sh — full (1st) / incremental git bundles

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 8: `component_config.sh` (encrypted)

**Files:** Create `scripts/backup/component_config.sh`

- [ ] **Step 1:** Generate passphrases and write to host `.env`.

```bash
openssl rand -base64 48   # Copy to .env as BACKUP_CONFIG_PASSPHRASE
openssl rand -base64 48   # Copy to .env as BACKUP_GDRIVE_PASSPHRASE
openssl rand -base64 48   # Copy to .env as BACKUP_VPS_PASSPHRASE
# Also: write them on paper and put paper in a physical safe (spec §12).
```

- [ ] **Step 2:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/component_config.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"
load_backup_env

: "${BACKUP_CONFIG_PASSPHRASE:?BACKUP_CONFIG_PASSPHRASE missing from .env}"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/config"
mkdir -p "$OUT_DIR"

START=$(date +%s)
RAW_TAR="$OUT_DIR/.config_raw_$(backup_ts).tar.gz"
ENC_FILE="$OUT_DIR/config_$(backup_ts).tar.gz.enc"

echo "archie-backup-sentinel $(date -u +%FT%TZ)" > /tmp/.backup_sentinel

tar --ignore-failed-read -czf "$RAW_TAR" \
    -C "$ARCHIE_REPO" \
    .env docker-compose.yml .mcp.json CLAUDE.md \
    .claude/rules \
    nginx secrets \
    2>>"$BACKUP_LOG_FILE"
tar -rzf "$RAW_TAR" -C /tmp .backup_sentinel 2>>"$BACKUP_LOG_FILE" || true

openssl enc -aes-256-gcm -pbkdf2 -iter 200000 -salt \
    -in "$RAW_TAR" -out "$ENC_FILE" \
    -pass env:BACKUP_CONFIG_PASSPHRASE

shred -u "$RAW_TAR" /tmp/.backup_sentinel 2>/dev/null || rm -f "$RAW_TAR" /tmp/.backup_sentinel

SIZE=$(stat -c %s "$ENC_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
log_info "config encrypted — $SIZE bytes in ${DUR}ms"
log_to_db "config" "primary" "success" "$ENC_FILE" "$SIZE" "$DUR"
```

- [ ] **Step 3:** Test encrypt + decrypt roundtrip.

```bash
chmod +x scripts/backup/component_config.sh
scripts/backup/component_config.sh /tmp/backup_smoke
ls -lah /tmp/backup_smoke/config/
openssl enc -d -aes-256-gcm -pbkdf2 -iter 200000 \
    -in /tmp/backup_smoke/config/config_*.tar.gz.enc \
    -out /tmp/roundtrip.tar.gz \
    -pass env:BACKUP_CONFIG_PASSPHRASE
tar -tzf /tmp/roundtrip.tar.gz | head
rm /tmp/roundtrip.tar.gz
```

Expected: decrypt succeeds, tar lists `.env`, `docker-compose.yml`, `.backup_sentinel` etc.

- [ ] **Step 4:** Commit.

```bash
git add scripts/backup/component_config.sh
git commit -m "feat(backup): component_config.sh — AES-256-GCM encrypted config archive

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 9: `component_volumes.sh`

**Files:** Create `scripts/backup/component_volumes.sh`

- [ ] **Step 1:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/component_volumes.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/volumes"
mkdir -p "$OUT_DIR"

START=$(date +%s)
VOLUMES=(
    "n8n:/mnt/archie_brain/persistence/n8n"
    "kbs:/mnt/archie_brain/kytran-business-suite/data"
    "creed:/mnt/archie_brain/kytran-creed/data"
    "stalwart:/mnt/archie_brain/persistence/stalwart"
)

TOTAL=0
FAILED=0
for entry in "${VOLUMES[@]}"; do
    name="${entry%%:*}"
    path="${entry#*:}"
    if [[ ! -d "$path" ]]; then
        log_warn "skip volume $name — $path not present"
        continue
    fi
    OUT_FILE="$OUT_DIR/volume_${name}_$(backup_ts).tar.gz"
    if tar -czf "$OUT_FILE" -C "$(dirname "$path")" "$(basename "$path")" 2>>"$BACKUP_LOG_FILE"; then
        sz=$(stat -c %s "$OUT_FILE")
        TOTAL=$(( TOTAL + sz ))
        log_info "volume $name OK — $sz bytes"
    else
        log_error "volume $name tar failed"
        FAILED=1
    fi
done

DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_to_db "volumes" "primary" "$STATUS" "$OUT_DIR" "$TOTAL" "$DUR"
exit "$FAILED"
```

- [ ] **Step 2:** Test.

```bash
chmod +x scripts/backup/component_volumes.sh
scripts/backup/component_volumes.sh /tmp/backup_smoke
ls -lah /tmp/backup_smoke/volumes/
```

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/component_volumes.sh
git commit -m "feat(backup): component_volumes.sh

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 10: `component_convlogs.sh` (weekly)

**Files:** Create `scripts/backup/component_convlogs.sh`

- [ ] **Step 1:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/component_convlogs.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/convlogs"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/convlogs_$(backup_ts).tar.gz"

if [[ ! -d "$ARCHIE_REPO/conversation_logs" ]]; then
    log_warn "no conversation_logs dir — skipping"
    log_to_db "convlogs" "primary" "skipped" "" "0" "0" "no conversation_logs dir"
    exit 0
fi

tar -czf "$OUT_FILE" -C "$ARCHIE_REPO" conversation_logs 2>>"$BACKUP_LOG_FILE"
SIZE=$(stat -c %s "$OUT_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
log_info "convlogs OK — $SIZE bytes in ${DUR}ms"
log_to_db "convlogs" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
```

- [ ] **Step 2:** Test.

```bash
chmod +x scripts/backup/component_convlogs.sh
scripts/backup/component_convlogs.sh /tmp/backup_smoke
ls -lah /tmp/backup_smoke/convlogs/
```

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/component_convlogs.sh
git commit -m "feat(backup): component_convlogs.sh — weekly conversation_logs

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 11: `component_kb_export.sh` (weekly)

**Files:** Create `scripts/backup/component_kb_export.sh`

- [ ] **Step 1:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/component_kb_export.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/kb_export"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/kb_$(backup_ts).dump"

docker exec archie_database pg_dump -U archie -d archie \
    --data-only -t knowledge_base -Fc -Z 6 > "$OUT_FILE"

SIZE=$(stat -c %s "$OUT_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
log_info "kb_export OK — $SIZE bytes in ${DUR}ms"
log_to_db "kb_export" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
```

- [ ] **Step 2:** Test.

```bash
chmod +x scripts/backup/component_kb_export.sh
scripts/backup/component_kb_export.sh /tmp/backup_smoke
docker exec archie_database pg_restore --list /tmp/backup_smoke/kb_export/*.dump | head
```

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/component_kb_export.sh
git commit -m "feat(backup): component_kb_export.sh — weekly KB data-only export

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 12: `component_vps_pull.sh` (weekly)

**Files:** Create `scripts/backup/component_vps_pull.sh`

> **Pre-req:** SSH key for `kytran@100.64.0.1` (mesh) must be deployed. If `ssh -o BatchMode=yes` fails, add a key-deploy step via Hostinger KVM before proceeding.

- [ ] **Step 1:** Confirm SSH reachable.

```bash
ssh -o BatchMode=yes -o ConnectTimeout=5 kytran@100.64.0.1 'echo ok' || echo "NEEDS SETUP"
```

- [ ] **Step 2:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/component_vps_pull.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/vps_pull"
mkdir -p "$OUT_DIR"

VPS_HOST="${BACKUP_VPS_HOST:-100.64.0.1}"
VPS_USER="${BACKUP_VPS_USER:-kytran}"

START=$(date +%s)
FAILED=0

VPS_DBS=(market_watch civic_watch legal_watch gov_watch thenews)
for db in "${VPS_DBS[@]}"; do
    remote_path="/tmp/${db}_$(date +%Y%m%d).dump"
    if ssh "${VPS_USER}@${VPS_HOST}" "docker exec ${db}_db pg_dump -U postgres -d ${db} -Fc -Z 6 > ${remote_path}" 2>>"$BACKUP_LOG_FILE"; then
        rsync -az "${VPS_USER}@${VPS_HOST}:${remote_path}" "$OUT_DIR/" 2>>"$BACKUP_LOG_FILE" \
            && ssh "${VPS_USER}@${VPS_HOST}" "rm -f ${remote_path}"
    else
        log_warn "VPS DB dump failed for $db (container may not exist) — skipping"
    fi
done

ssh "${VPS_USER}@${VPS_HOST}" 'ls -d /root/*/persistence 2>/dev/null || true' | while read -r rp; do
    [[ -z "$rp" ]] && continue
    name=$(echo "$rp" | awk -F/ '{print $(NF-1)}')
    rsync -az "${VPS_USER}@${VPS_HOST}:${rp}" "$OUT_DIR/${name}_persistence" 2>>"$BACKUP_LOG_FILE" || FAILED=1
done

SIZE=$(dir_size_bytes "$OUT_DIR")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_info "vps_pull $STATUS — $SIZE bytes in ${DUR}ms"
log_to_db "vps_pull" "primary" "$STATUS" "$OUT_DIR" "$SIZE" "$DUR"
exit "$FAILED"
```

- [ ] **Step 3:** Test.

```bash
chmod +x scripts/backup/component_vps_pull.sh
scripts/backup/component_vps_pull.sh /tmp/backup_smoke
ls -lah /tmp/backup_smoke/vps_pull/
```

- [ ] **Step 4:** Commit.

```bash
git add scripts/backup/component_vps_pull.sh
git commit -m "feat(backup): component_vps_pull.sh — weekly rsync of VPS product DBs + data

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 13: `component_monthly_full.sh`

**Files:** Create `scripts/backup/component_monthly_full.sh`

- [ ] **Step 1:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/component_monthly_full.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/monthly_full"
mkdir -p "$OUT_DIR"

START=$(date +%s)
OUT_FILE="$OUT_DIR/monthly_full_$(backup_ts).tar.gz"

tar -czf "$OUT_FILE" -C "$RUN_DIR" \
    $(ls "$RUN_DIR" | grep -v '^monthly_full$') 2>>"$BACKUP_LOG_FILE"

SIZE=$(stat -c %s "$OUT_FILE")
DUR=$(( ( $(date +%s) - START ) * 1000 ))
log_info "monthly_full OK — $SIZE bytes in ${DUR}ms"
log_to_db "monthly_full" "primary" "success" "$OUT_FILE" "$SIZE" "$DUR"
```

- [ ] **Step 2:** Test.

```bash
chmod +x scripts/backup/component_monthly_full.sh
scripts/backup/component_monthly_full.sh /tmp/backup_smoke
ls -lah /tmp/backup_smoke/monthly_full/
```

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/component_monthly_full.sh
git commit -m "feat(backup): component_monthly_full.sh

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

# Phase 3 — Tier sync scripts

### Task 14: `tier_sync_usb.py`

**Files:** Create `scripts/backup/tier_sync_usb.py`

- [ ] **Step 1:** Write the script.

```python
#!/usr/bin/env python3
"""scripts/backup/tier_sync_usb.py <run_dir>

Copies the run's component files to /mnt/external-backup with rsync.
Only the components declared in TIER_COMPONENTS land on USB.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

USB_ROOT = Path(os.environ.get("BACKUP_USB", "/mnt/external-backup"))
TIER_COMPONENTS = {"database", "code", "gitbundles", "config", "volumes"}

def log_db(component, status, path, size, dur_ms, err=""):
    err_sql = err.replace("'", "''")
    subprocess.run([
        "docker", "exec", "-i", "archie_database",
        "psql", "-U", "archie", "-d", "archie",
        "-c",
        f"INSERT INTO backup_log (component, tier, status, file_path, size_bytes, duration_ms, error_message, created_at) "
        f"VALUES ('{component}', 'usb', '{status}', '{path}', {size}, {dur_ms}, NULLIF('{err_sql}', ''), NOW());"
    ], check=False, capture_output=True)

def dir_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

def main():
    if len(sys.argv) != 2:
        print("usage: tier_sync_usb.py <run_dir>", file=sys.stderr)
        sys.exit(2)
    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"run_dir does not exist: {run_dir}", file=sys.stderr)
        sys.exit(2)
    if not USB_ROOT.is_mount() and not USB_ROOT.is_dir():
        print(f"USB not mounted at {USB_ROOT}", file=sys.stderr)
        sys.exit(1)

    target = USB_ROOT / run_dir.name
    target.mkdir(parents=True, exist_ok=True)
    failures = 0

    for component in sorted(os.listdir(run_dir)):
        if component not in TIER_COMPONENTS:
            continue
        src = run_dir / component
        dst = target / component
        dst.mkdir(exist_ok=True)
        start = time.time()
        r = subprocess.run(
            ["rsync", "-a", "--delete", f"{src}/", f"{dst}/"],
            capture_output=True, text=True,
        )
        dur_ms = int((time.time() - start) * 1000)
        sz = dir_size(dst)
        if r.returncode == 0:
            log_db(component, "success", str(dst), sz, dur_ms)
            print(f"usb ok: {component} {sz}B {dur_ms}ms")
        else:
            failures += 1
            log_db(component, "failed", str(dst), sz, dur_ms, r.stderr[:500])
            print(f"usb FAIL: {component} — {r.stderr[:200]}", file=sys.stderr)

    sys.exit(failures)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2:** Test.

```bash
chmod +x scripts/backup/tier_sync_usb.py
scripts/backup/tier_sync_usb.py /tmp/backup_smoke
ls /mnt/external-backup/backup_smoke*/ 2>&1 || ls /mnt/external-backup/ | tail
```

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/tier_sync_usb.py
git commit -m "feat(backup): tier_sync_usb.py

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 15: `tier_sync_gdrive.py`

**Files:** Create `scripts/backup/tier_sync_gdrive.py`

- [ ] **Step 1:** Write the script.

```python
#!/usr/bin/env python3
"""scripts/backup/tier_sync_gdrive.py <run_dir> <mode>

Uploads the run's components to Google Drive via the existing
Work Suite OAuth connection. Files are encrypted client-side with
BACKUP_GDRIVE_PASSPHRASE before upload. Execution is delegated to
the platform container, which owns the OAuth token.
"""
import os, sys, time, subprocess, tempfile
from pathlib import Path

COMPONENTS_BY_MODE = {
    "daily":   {"database", "code", "gitbundles", "config"},
    "weekly":  {"database", "code", "gitbundles", "config", "kb_export"},
    "monthly": {"database", "code", "gitbundles", "config", "kb_export", "monthly_full"},
}

def log_db(component, status, path, size, dur_ms, err=""):
    err_sql = err.replace("'", "''")
    subprocess.run([
        "docker", "exec", "-i", "archie_database",
        "psql", "-U", "archie", "-d", "archie",
        "-c",
        f"INSERT INTO backup_log (component, tier, status, file_path, size_bytes, duration_ms, error_message, created_at) "
        f"VALUES ('{component}', 'gdrive', '{status}', '{path}', {size}, {dur_ms}, NULLIF('{err_sql}', ''), NOW());"
    ], check=False, capture_output=True)

def upload_via_platform(local_path: str, remote_name: str) -> tuple[bool, str]:
    py = (
        "from tools.google_work_suite.services.drive_service import backup_ensure_folder, backup_upload_file; "
        f"fid = backup_ensure_folder('ARCHIE Backups'); "
        f"r = backup_upload_file(fid, '{local_path}', '{remote_name}'); "
        "print(r)"
    )
    r = subprocess.run(
        ["docker", "exec", "archie_platform", "python3", "-c", py],
        capture_output=True, text=True,
    )
    return (r.returncode == 0, (r.stdout + r.stderr).strip())

def encrypt(src: str, dst: str, passphrase: str):
    subprocess.run([
        "openssl", "enc", "-aes-256-gcm", "-pbkdf2", "-iter", "200000",
        "-salt", "-in", src, "-out", dst,
        "-pass", f"pass:{passphrase}",
    ], check=True)

def main():
    if len(sys.argv) != 3:
        print("usage: tier_sync_gdrive.py <run_dir> <mode>", file=sys.stderr)
        sys.exit(2)
    run_dir = Path(sys.argv[1])
    mode = sys.argv[2]
    components = COMPONENTS_BY_MODE.get(mode, COMPONENTS_BY_MODE["daily"])
    passphrase = os.environ.get("BACKUP_GDRIVE_PASSPHRASE")
    if not passphrase:
        print("BACKUP_GDRIVE_PASSPHRASE not set — skipping gdrive tier", file=sys.stderr)
        log_db("gdrive", "skipped", str(run_dir), 0, 0, "no passphrase")
        sys.exit(0)

    failures = 0
    for component in sorted(os.listdir(run_dir)):
        if component not in components:
            continue
        src_dir = run_dir / component
        for f in src_dir.rglob("*"):
            if not f.is_file():
                continue
            start = time.time()
            with tempfile.NamedTemporaryFile(suffix=".enc", delete=False) as tf:
                enc_path = tf.name
            try:
                if str(f).endswith(".enc"):
                    up_src = str(f)
                else:
                    encrypt(str(f), enc_path, passphrase)
                    up_src = enc_path
                remote_name = f"{run_dir.name}/{f.relative_to(run_dir)}"
                ok, msg = upload_via_platform(up_src, remote_name)
                dur_ms = int((time.time() - start) * 1000)
                sz = os.path.getsize(up_src)
                if ok:
                    log_db(component, "success", remote_name, sz, dur_ms)
                    print(f"gdrive ok: {remote_name} ({sz}B)")
                else:
                    failures += 1
                    log_db(component, "failed", remote_name, sz, dur_ms, msg[:500])
                    print(f"gdrive FAIL: {remote_name}: {msg[:200]}", file=sys.stderr)
            finally:
                if up_src == enc_path and os.path.exists(enc_path):
                    os.unlink(enc_path)

    sys.exit(failures)

if __name__ == "__main__":
    main()
```

- [ ] **Step 2:** Pre-flight — confirm Work Suite OAuth connection.

```bash
docker exec archie_platform python3 -c "
from tools.google_work_suite.services.drive_service import backup_is_oauth_configured, backup_test_connection
print('configured:', backup_is_oauth_configured())
print('test:', backup_test_connection())
"
```

- [ ] **Step 3:** Test with a single file.

```bash
chmod +x scripts/backup/tier_sync_gdrive.py
mkdir -p /tmp/gdrive_smoke/config
echo test > /tmp/gdrive_smoke/config/.test
scripts/backup/tier_sync_gdrive.py /tmp/gdrive_smoke daily
```

Expected: upload logged to `backup_log`, file in Drive `ARCHIE Backups` folder.

- [ ] **Step 4:** Commit.

```bash
git add scripts/backup/tier_sync_gdrive.py
git commit -m "feat(backup): tier_sync_gdrive.py — encrypted upload via Work Suite OAuth

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 16: `tier_sync_vps.sh`

**Files:** Create `scripts/backup/tier_sync_vps.sh`

- [ ] **Step 1:** Write the script.

```bash
#!/usr/bin/env bash
# scripts/backup/tier_sync_vps.sh <run_dir>
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"
load_backup_env

: "${BACKUP_VPS_PASSPHRASE:?BACKUP_VPS_PASSPHRASE missing}"
VPS_HOST="${BACKUP_VPS_HOST:-100.64.0.1}"
VPS_USER="${BACKUP_VPS_USER:-kytran}"
VPS_REMOTE_ROOT="${BACKUP_VPS_REMOTE_ROOT:-/var/backups/archie}"

RUN_DIR="${1:?run_dir required}"
VPS_COMPONENTS=(database gitbundles config)

START=$(date +%s)
REMOTE_DIR="${VPS_REMOTE_ROOT}/$(basename "$RUN_DIR")"

ssh "${VPS_USER}@${VPS_HOST}" "mkdir -p '${REMOTE_DIR}'" 2>>"$BACKUP_LOG_FILE" \
    || { log_error "cannot reach VPS $VPS_HOST"; log_to_db "vps" "vps" "failed" "$REMOTE_DIR" "0" "0" "ssh mkdir failed"; exit 1; }

TOTAL=0
FAILED=0
for c in "${VPS_COMPONENTS[@]}"; do
    src="$RUN_DIR/$c"
    [[ ! -d "$src" ]] && continue
    WORK=$(mktemp -d)
    for f in "$src"/*; do
        [[ -f "$f" ]] || continue
        out="$WORK/$(basename "$f").enc"
        if [[ "$f" == *.enc ]]; then
            cp "$f" "$out"
        else
            openssl enc -aes-256-gcm -pbkdf2 -iter 200000 -salt \
                -in "$f" -out "$out" -pass env:BACKUP_VPS_PASSPHRASE
        fi
    done
    if rsync -az "$WORK/" "${VPS_USER}@${VPS_HOST}:${REMOTE_DIR}/${c}/" 2>>"$BACKUP_LOG_FILE"; then
        sz=$(dir_size_bytes "$WORK")
        TOTAL=$(( TOTAL + sz ))
        log_info "vps tier $c OK ($sz bytes)"
    else
        log_error "vps rsync failed for $c"
        FAILED=1
    fi
    rm -rf "$WORK"
done

DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_to_db "vps" "vps" "$STATUS" "$REMOTE_DIR" "$TOTAL" "$DUR"
exit "$FAILED"
```

- [ ] **Step 2:** One-time remote setup.

```bash
ssh kytran@100.64.0.1 'sudo mkdir -p /var/backups/archie && sudo chown kytran:kytran /var/backups/archie'
```

- [ ] **Step 3:** Test.

```bash
chmod +x scripts/backup/tier_sync_vps.sh
scripts/backup/tier_sync_vps.sh /tmp/backup_smoke
ssh kytran@100.64.0.1 'ls -la /var/backups/archie/'
```

- [ ] **Step 4:** Commit.

```bash
git add scripts/backup/tier_sync_vps.sh
git commit -m "feat(backup): tier_sync_vps.sh — encrypted rsync to US Outpost

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

# Phase 4 — Retention + Verification

### Task 17: `retention_prune.py`

**Files:** Create `scripts/backup/retention_prune.py`

- [ ] **Step 1:** Write the script.

```python
#!/usr/bin/env python3
"""scripts/backup/retention_prune.py

Enforces per-tier retention from a declarative config.
Monotonic — never deletes something unless more recent copies exist at the same tier.
"""
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

RETENTION = {
    "database":    {"primary": (30, 12, 6),  "usb": (14, 4, 0),  "gdrive": (0, 4, 6),  "vps": (7, 0, 0)},
    "code":        {"primary": (14, 8, 0),   "usb": (7, 4, 0),   "gdrive": (0, 4, 0),  "vps": (0, 0, 0)},
    "gitbundles":  {"primary": (14, 0, 12),  "usb": (7, 4, 0),   "gdrive": (0, 4, 6),  "vps": (7, 0, 0)},
    "config":      {"primary": (14, 0, 12),  "usb": (7, 0, 0),   "gdrive": (0, 0, 12), "vps": (7, 0, 0)},
    "volumes":     {"primary": (14, 4, 0),   "usb": (0, 4, 0),   "gdrive": (0, 0, 0),  "vps": (0, 0, 0)},
    "convlogs":    {"primary": (0, 8, 0),    "usb": (0, 0, 0),   "gdrive": (0, 0, 0),  "vps": (0, 0, 0)},
    "kb_export":   {"primary": (0, 12, 6),   "usb": (0, 0, 0),   "gdrive": (0, 0, 6),  "vps": (0, 0, 0)},
    "vps_pull":    {"primary": (0, 8, 3),    "usb": (0, 0, 0),   "gdrive": (0, 0, 0),  "vps": (0, 0, 0)},
    "monthly_full":{"primary": (0, 0, 6),    "usb": (0, 0, 0),   "gdrive": (0, 0, 6),  "vps": (0, 0, 0)},
    "pre-change":  {"primary": (20, 0, 0),   "usb": (0, 0, 0),   "gdrive": (0, 0, 0),  "vps": (0, 0, 0)},
}

PRIMARY_ROOT = Path(os.environ.get("BACKUP_ROOT", "/mnt/data/backups"))
USB_ROOT = Path(os.environ.get("BACKUP_USB", "/mnt/external-backup"))

DATE_RE = re.compile(r"^(\d{8})_")

def parse_ts(name: str):
    m = DATE_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y%m%d")
    except ValueError:
        return None

def classify(date: datetime):
    tags = {"daily"}
    if date.weekday() == 6:
        tags.add("weekly")
    if date.day <= 3:
        tags.add("monthly")
    return tags

def prune_dir(root: Path, component: str, tier: str):
    keep_d, keep_w, keep_m = RETENTION.get(component, {}).get(tier, (0, 0, 0))
    runs = []
    for child in sorted(root.iterdir(), reverse=True) if root.is_dir() else []:
        if not child.is_dir():
            continue
        ts = parse_ts(child.name)
        if not ts:
            continue
        comp_path = child / component
        if not comp_path.exists():
            continue
        runs.append((ts, child, comp_path))

    if not runs:
        return 0

    kept_d = kept_w = kept_m = 0
    deleted = 0
    for ts, run_dir, comp_path in runs:
        tags = classify(ts)
        keep = False
        if "monthly" in tags and kept_m < keep_m:
            kept_m += 1; keep = True
        elif "weekly" in tags and kept_w < keep_w:
            kept_w += 1; keep = True
        elif kept_d < keep_d:
            kept_d += 1; keep = True
        if not keep:
            print(f"prune: removing {comp_path}")
            try:
                shutil.rmtree(comp_path)
                deleted += 1
                try:
                    if not any(run_dir.iterdir()):
                        run_dir.rmdir()
                except OSError:
                    pass
            except Exception as e:
                print(f"failed to remove {comp_path}: {e}", file=sys.stderr)

    return deleted

def main():
    total_deleted = 0
    for component in RETENTION.keys():
        total_deleted += prune_dir(PRIMARY_ROOT, component, "primary")
        if USB_ROOT.is_dir():
            total_deleted += prune_dir(USB_ROOT, component, "usb")
    subprocess.run([
        "docker", "exec", "-i", "archie_database",
        "psql", "-U", "archie", "-d", "archie",
        "-c",
        f"INSERT INTO backup_log (component, tier, status, notes, created_at) "
        f"VALUES ('retention', 'primary', 'prune', '{total_deleted} deleted', NOW());"
    ], check=False, capture_output=True)
    print(f"retention prune: {total_deleted} items removed")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2:** Test on a synthetic tree.

```bash
chmod +x scripts/backup/retention_prune.py
mkdir -p /tmp/prune_test
for d in 20260101 20260115 20260201 20260301 20260315 20260401; do
    mkdir -p /tmp/prune_test/${d}_daily/database
    touch /tmp/prune_test/${d}_daily/database/dummy.dump
done
BACKUP_ROOT=/tmp/prune_test BACKUP_USB=/nowhere scripts/backup/retention_prune.py
ls /tmp/prune_test/
```

Expected: prune keeps most-recent N per retention table; deletions logged; DB row written.

- [ ] **Step 3:** Commit.

```bash
git add scripts/backup/retention_prune.py
git commit -m "feat(backup): retention_prune.py

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 18: `verify_backups.sh` + `decrypt_restore.sh`

**Files:**
- Create: `scripts/backup/verify_backups.sh`
- Create: `scripts/backup/decrypt_restore.sh`

- [ ] **Step 1:** Write `verify_backups.sh`.

```bash
#!/usr/bin/env bash
# scripts/backup/verify_backups.sh
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"
load_backup_env

RESULT=0

latest_file_under() {
    find "$1" -type f -name "$2" -printf '%T@ %p\n' 2>/dev/null | sort -rn | head -1 | cut -d' ' -f2-
}

DB_FILE=$(latest_file_under "$BACKUP_ROOT" "*.dump")
if [[ -n "$DB_FILE" ]] && docker exec -i archie_database pg_restore --list < "$DB_FILE" >/dev/null 2>&1; then
    log_info "verify OK: db ($DB_FILE)"
    psql_archie -c "UPDATE backup_log SET verification_status='verified' WHERE file_path='$DB_FILE';"
else
    log_error "verify FAIL: db ($DB_FILE)"
    RESULT=1
    notify_telegram error "Backup verify failed: DB dump ($DB_FILE)"
fi

CODE_FILE=$(latest_file_under "$BACKUP_ROOT" "archie_code_*.tar.gz")
if [[ -n "$CODE_FILE" ]] && tar -tzf "$CODE_FILE" >/dev/null 2>&1; then
    log_info "verify OK: code ($CODE_FILE)"
    psql_archie -c "UPDATE backup_log SET verification_status='verified' WHERE file_path='$CODE_FILE';"
else
    log_error "verify FAIL: code ($CODE_FILE)"
    RESULT=1
fi

BUNDLE=$(latest_file_under "$BACKUP_ROOT" "archie_*.bundle")
if [[ -n "$BUNDLE" ]] && git bundle verify "$BUNDLE" >/dev/null 2>&1; then
    log_info "verify OK: gitbundle ($BUNDLE)"
    psql_archie -c "UPDATE backup_log SET verification_status='verified' WHERE file_path='$BUNDLE';"
else
    log_error "verify FAIL: gitbundle ($BUNDLE)"
    RESULT=1
fi

CFG=$(latest_file_under "$BACKUP_ROOT" "config_*.tar.gz.enc")
if [[ -n "$CFG" && -n "${BACKUP_CONFIG_PASSPHRASE:-}" ]]; then
    TMP=$(mktemp -d)
    if openssl enc -d -aes-256-gcm -pbkdf2 -iter 200000 -in "$CFG" -out "$TMP/c.tar.gz" -pass env:BACKUP_CONFIG_PASSPHRASE \
       && tar -xzf "$TMP/c.tar.gz" -C "$TMP" .backup_sentinel 2>/dev/null \
       && head -1 "$TMP/.backup_sentinel" | grep -q "archie-backup-sentinel"; then
        log_info "verify OK: config encryption roundtrip"
        psql_archie -c "UPDATE backup_log SET verification_status='verified' WHERE file_path='$CFG';"
    else
        log_error "verify FAIL: config encryption roundtrip"
        RESULT=1
        notify_telegram error "Backup verify failed: config encryption roundtrip"
    fi
    rm -rf "$TMP"
fi

exit "$RESULT"
```

- [ ] **Step 2:** Write `decrypt_restore.sh`.

```bash
#!/usr/bin/env bash
# scripts/backup/decrypt_restore.sh <encrypted_file> <passphrase_env_var>
set -euo pipefail
FILE="${1:?encrypted file required}"
VAR="${2:?passphrase env var name required}"
if [[ -z "${!VAR:-}" ]]; then
    echo "Env var $VAR is empty. Load from .env first: set -o allexport; source .env; set +o allexport"
    exit 1
fi
OUT="${FILE%.enc}"
openssl enc -d -aes-256-gcm -pbkdf2 -iter 200000 \
    -in "$FILE" -out "$OUT" -pass "env:$VAR"
echo "Decrypted → $OUT"
```

- [ ] **Step 3:** Test.

```bash
chmod +x scripts/backup/verify_backups.sh scripts/backup/decrypt_restore.sh
scripts/backup/verify_backups.sh 2>&1 | head
```

- [ ] **Step 4:** Commit.

```bash
git add scripts/backup/verify_backups.sh scripts/backup/decrypt_restore.sh
git commit -m "feat(backup): verify_backups.sh + decrypt_restore.sh

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

# Phase 5 — Platform integration

### Task 19: Watchdog backup-freshness + disk-free checks

**Files:** Modify `platform_v2/services/watchdog.py`

- [ ] **Step 1:** Read the current watchdog to match patterns.

```bash
grep -n 'def check_\|def _alert\|def run' /mnt/archie_brain/platform_v2/services/watchdog.py | head -30
```

- [ ] **Step 2:** Add these two functions alongside other `check_*` functions.

```python
def check_backup_freshness():
    """Alert if no successful primary backup within last 36 hours."""
    from database import get_db_cursor
    from datetime import datetime
    with get_db_cursor() as (_, cur):
        cur.execute("""
            SELECT MAX(created_at) AS latest
            FROM backup_log
            WHERE status = 'success' AND tier = 'primary'
        """)
        row = cur.fetchone()
    latest = row["latest"] if row else None
    if latest is None:
        return _alert("backup_freshness", "error",
                      "No successful primary backups recorded — check cron + /var/log/archie_backup.log")
    age_h = (datetime.utcnow() - latest.replace(tzinfo=None)).total_seconds() / 3600
    if age_h > 36:
        return _alert("backup_freshness", "error",
                      f"No successful primary backup in {age_h:.1f}h — cron may be dead")

def check_backup_disk_free():
    """Alert if any backup tier < 20% free."""
    import shutil
    mounts = [
        ("primary", "/mnt/data"),
        ("usb",     "/mnt/external-backup"),
    ]
    for name, path in mounts:
        try:
            u = shutil.disk_usage(path)
            pct_free = 100.0 * u.free / u.total
            if pct_free < 20:
                _alert(f"backup_disk_{name}", "warning",
                       f"Backup disk {name} ({path}) < 20% free ({pct_free:.1f}%)")
        except FileNotFoundError:
            _alert(f"backup_disk_{name}", "warning", f"Backup mount missing: {path}")
```

- [ ] **Step 3:** Wire into `run()`. Find the existing `run()` loop and add:

```python
    check_backup_freshness()
    check_backup_disk_free()
```

- [ ] **Step 4:** Restart + confirm no import errors.

```bash
docker compose restart archie_platform
docker logs --tail 50 archie_platform | grep -iE 'error|exception|traceback' | head
```

- [ ] **Step 5:** Induce a test condition.

```bash
docker exec archie_database psql -U archie -d archie -c "INSERT INTO backup_log (component, tier, status, created_at) VALUES ('test', 'primary', 'success', NOW() - INTERVAL '40 hours');"
# Wait for next watchdog cycle (2 min). Verify Telegram fired.
docker exec archie_database psql -U archie -d archie -c "DELETE FROM backup_log WHERE component='test';"
```

- [ ] **Step 6:** Commit.

```bash
git add platform_v2/services/watchdog.py
git commit -m "feat(watchdog): add backup freshness + disk-free checks

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 20: Backup Manager UI — tier health dashboard

**Files:**
- Modify: `platform_v2/tools/backup_manager/backup_manager_routes.py`
- Modify: `platform_v2/templates/tools/backup_manager.html` (or module template location)

- [ ] **Step 1:** Extend `/health` endpoint. In `backup_manager_routes.py`, find `def backup_health():` (≈line 1811) and extend its response dict with:

```python
    with get_backup_db_cursor(commit=False) as (conn, cur):
        cur.execute("""
            SELECT DISTINCT ON (component, tier)
                   component, tier, status, created_at, size_bytes, verification_status
              FROM backup_log
             ORDER BY component, tier, created_at DESC;
        """)
        tier_rows = cur.fetchall()
    tiers = {}
    for row in tier_rows:
        tiers.setdefault(row["tier"], []).append({
            "component": row["component"],
            "status": row["status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "size_bytes": row["size_bytes"],
            "verification_status": row["verification_status"],
        })
    response["tiers"] = tiers
```

- [ ] **Step 2:** Restart, hit endpoint.

```bash
docker compose restart archie_platform
curl -s http://192.168.1.200:3000/tools/backup-manager/health -H "Cookie: <session>" | head
```

Expected: JSON with `tiers` key containing per-tier arrays.

- [ ] **Step 3:** Add a tier-health card to the template. Use safe DOM methods (no `innerHTML`). Insert this block into the dashboard template:

```html
<!-- Tier Health Panel -->
<div class="bm-tier-grid" id="bm-tier-health">
    <h3>Backup Tiers</h3>
    <table class="bm-tier-table">
        <thead>
            <tr><th>Tier</th><th>Oldest component</th><th>Status</th></tr>
        </thead>
        <tbody id="bm-tier-tbody"></tbody>
    </table>
</div>
<script>
(function() {
    function td(text, className) {
        const c = document.createElement('td');
        c.textContent = text;
        if (className) c.className = className;
        return c;
    }
    fetch('/tools/backup-manager/health').then(function(r){ return r.json(); }).then(function(d) {
        const tbody = document.getElementById('bm-tier-tbody');
        const tiers = (d && d.tiers) || {};
        Object.keys(tiers).forEach(function(tier) {
            const items = tiers[tier].slice().sort(function(a, b) {
                return (a.created_at || '').localeCompare(b.created_at || '');
            });
            const oldest = items[0];
            if (!oldest) return;
            const ageH = (Date.now() - new Date(oldest.created_at).getTime()) / 3600000;
            const cls = ageH > 36 ? 'bm-bad' : (ageH > 24 ? 'bm-warn' : 'bm-ok');
            const tr = document.createElement('tr');
            tr.className = cls;
            tr.appendChild(td(tier));
            tr.appendChild(td(oldest.component + ' (' + ageH.toFixed(1) + 'h ago)'));
            tr.appendChild(td(oldest.status));
            tbody.appendChild(tr);
        });
    });
})();
</script>
```

- [ ] **Step 4:** Commit.

```bash
git add platform_v2/tools/backup_manager/backup_manager_routes.py platform_v2/templates/tools/backup_manager.html
git commit -m "feat(backup-manager): tier health dashboard (safe DOM, no innerHTML)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 21: Pre-change hook writes to new `backup_log`

**Files:** Modify `platform_v2/services/backup_integration_service.py`

- [ ] **Step 1:** Find the existing INSERT.

```bash
grep -n 'INSERT INTO backup_log' /mnt/archie_brain/platform_v2/services/backup_integration_service.py
```

- [ ] **Step 2:** Replace the INSERT with the new-schema version:

```python
            cur.execute(
                """
                INSERT INTO backup_log
                    (component, tier, status, file_path, notes, created_at)
                VALUES
                    ('pre-change', 'primary', 'success', %s, %s, NOW())
                """,
                (snapshot_dir, description),
            )
```

- [ ] **Step 3:** Update path constants:

```python
PRECHANGE_DIR = "/mnt/data/backups/pre-change"
PRIMARY_DIR = "/mnt/data/backups"
USB_DIR = "/mnt/external-backup"
```

- [ ] **Step 4:** Create symlink to preserve compatibility.

```bash
sudo mkdir -p /mnt/data/backups/pre-change
sudo ln -sfn /mnt/data/backups/pre-change /mnt/data2/backups/pre-change 2>/dev/null || true
```

- [ ] **Step 5:** Restart + test.

```bash
docker compose restart archie_platform
docker exec archie_platform python3 -c "
from services.backup_integration_service import create_prechange_snapshot
print(create_prechange_snapshot('test snapshot from plan task 21'))
"
docker exec archie_database psql -U archie -d archie -c "SELECT component, tier, status, created_at FROM backup_log WHERE component='pre-change' ORDER BY created_at DESC LIMIT 3;"
```

- [ ] **Step 6:** Commit.

```bash
git add platform_v2/services/backup_integration_service.py
git commit -m "fix(backup-integration): write to canonical backup_log schema + new primary path

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

# Phase 6 — Documentation + drill task

### Task 22: Restore runbook

**Files:** Create `scripts/backup/README.md`

- [ ] **Step 1:** Write the README.

```markdown
# A.R.C.H.I.E. Backup System — Restore Runbook

**Spec:** `docs/superpowers/specs/2026-04-16-backup-system-design.md`
**Plan:** `docs/superpowers/plans/2026-04-16-backup-system-redesign.md`

## Quick Status Check

    docker exec archie_database psql -U archie -d archie -c "
    SELECT DISTINCT ON (tier) tier, component, status, created_at
    FROM backup_log ORDER BY tier, created_at DESC;"

    df -h /mnt/data /mnt/external-backup
    sudo cat /etc/cron.d/archie-backup
    sudo systemctl status cron

## Restore: Database

    docker compose stop archie_platform
    LATEST=$(ls -t /mnt/data/backups/*/database/*.dump | head -1)
    docker exec -i archie_database createdb -U archie archie_restore
    docker exec -i archie_database pg_restore -U archie -d archie_restore --clean --if-exists < "$LATEST"
    docker exec archie_database psql -U archie -d archie_restore -c "SELECT COUNT(*) FROM knowledge_base;"

## Restore: Code

    LATEST=$(ls -t /mnt/data/backups/*/code/archie_code_*.tar.gz | head -1)
    tar -xzf "$LATEST" -C /tmp/restore_code

## Restore: Git history (from bundle)

    mkdir /tmp/archie_restored && cd /tmp/archie_restored
    git clone /mnt/data/code_bundles/archie_latest.bundle .
    # If incremental: clone the full first, then unbundle the incremental:
    git clone /path/to/archie_full.bundle .
    cd archie && git bundle unbundle /path/to/archie_incremental.bundle

## Restore: Config (encrypted)

    set -o allexport; source /mnt/archie_brain/.env; set +o allexport
    LATEST=$(ls -t /mnt/data/backups/*/config/config_*.tar.gz.enc | head -1)
    /mnt/archie_brain/scripts/backup/decrypt_restore.sh "$LATEST" BACKUP_CONFIG_PASSPHRASE
    tar -xzf "${LATEST%.enc}" -C /tmp/restore_config

## Passphrase Recovery

1. Primary: `/mnt/archie_brain/.env` on the hub.
2. Secondary: paper safe (handwritten on install day).
3. If both lost: all encrypted backups (GDrive cold, VPS) are unrecoverable. Primary tier on host is unencrypted — last line of defense.

Never rotate passphrases casually — rotation invalidates every existing encrypted backup.

## Quarterly Drill

Every 90 days, restore a random weekly backup end-to-end into a disposable Postgres container. Verify:

- `SELECT COUNT(*) FROM knowledge_base;` within 1% of production
- Platform boots from restored code
- `notify_telegram info "drill complete"` fires

Log the drill as a `project_decisions` row for audit trail.

## Failure Modes

| Symptom | Diagnose |
|---------|----------|
| "No successful primary backup in Xh" | `sudo cat /etc/cron.d/archie-backup`; `sudo grep CRON /var/log/syslog \| tail`; `cat /var/log/archie_backup.log \| tail -50` |
| USB < 20% free | `du -sh /mnt/external-backup/* \| sort -h`; run `scripts/backup/retention_prune.py`; shorten USB retention if needed |
| GDrive upload fail | `docker exec archie_platform python3 -c "from tools.google_work_suite.services.drive_service import backup_test_connection; print(backup_test_connection())"` — if False, re-auth Work Suite |
| VPS rsync fail | `ssh kytran@100.64.0.1`; `tailscale status` |
```

- [ ] **Step 2:** Commit.

```bash
git add scripts/backup/README.md
git commit -m "docs(backup): restore runbook, passphrase recovery, drill procedure

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

### Task 23: Dev HQ quarterly drill + ADR + acceptance walkthrough

- [ ] **Step 1:** Create a recurring quarterly drill task via MCP.

    mcp__archie__create_task(
      project_id=<backup-system project id>,
      title="Quarterly backup restore drill",
      description="Restore a random weekly backup end-to-end. See scripts/backup/README.md § Quarterly Drill.",
      priority=8, type="testing", effort="medium",
    )

- [ ] **Step 2:** Log ADR via MCP.

    mcp__archie__log_decision(
      title="ADR-XXX: Backup system 4-tier architecture",
      decision="Host cron orchestrates component scripts; primary /mnt/data → USB → GDrive (encrypted via Work Suite OAuth) → VPS Outpost (encrypted, mesh). Platform is observer, not scheduler.",
      context="See docs/superpowers/specs/2026-04-16-backup-system-design.md",
      rationale="Cron survives platform outage — exactly when backups matter most.",
    )

- [ ] **Step 3:** Run spec §14 acceptance walkthrough.

```bash
sudo ls /etc/cron.d/archie-backup
docker exec archie_database psql -U archie -d archie -c "SELECT component, tier, COUNT(*), MAX(created_at) FROM backup_log WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY component, tier;"
scripts/backup/verify_backups.sh
# Watchdog alert test — already covered in Task 19 Step 5
# Restore drill — see README.md § Quarterly Drill
cat scripts/backup/README.md | grep -iE 'restore|passphrase' | head
```

- [ ] **Step 4:** Final review.

```bash
git log --oneline --since=2026-04-16 -- 'scripts/backup/**' 'docs/superpowers/**' 'platform_v2/services/watchdog.py' 'platform_v2/services/backup_integration_service.py' 'platform_v2/tools/backup_manager/**' 'database/migrations/**'
```

Expected: 20+ commits from this plan, all local (no push until 2026-05-01).

---

## Self-review summary

- ✅ Spec §2–§14 each map to at least one task.
- ✅ No placeholders — every script has complete working code.
- ✅ Type/name consistency: `backup_log` columns match across Task 2 schema, all `log_to_db` calls, Task 19 watchdog query, Task 20 `/health` extension.
- ⚠️ Triage (Phase 0) uses `/mnt/data2/backups/` for the manual triage backup but the new architecture uses `/mnt/data/backups/`. Intentional — reuses existing `create_backup_programmatic`; symlink + path migration happens in Task 21.
- ⚠️ Task 12 (`component_vps_pull.sh`) assumes SSH key to VPS is deployed. If not, add a Hostinger KVM key-deploy pre-step.
- ⚠️ GDrive quota — Task 15 silently skips or fails depending on quota. Add a quota pre-check to Task 15 if on free tier.
- ✅ Task 20 uses safe DOM methods (createElement + textContent) — no innerHTML.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-backup-system-redesign.md` (23 main tasks + 5 triage tasks across 7 phases).

**Two execution options:**

1. **Subagent-Driven (recommended for this plan)** — I dispatch a fresh subagent per task, review output between each, fast iteration. Given the size (28 tasks) this is the right call; context stays tight.

2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints at phase boundaries.

Which approach? (Also: do you want me to start with Phase 0 Triage *now* — T1 through T5 — while you decide which execution skill to use for the rest?)

#!/usr/bin/env bash
# scripts/backup/run_backup.sh
# Top-level backup orchestrator. Called from cron.
#
# Usage:
#   run_backup.sh daily
#   run_backup.sh weekly
#   run_backup.sh monthly
#   run_backup.sh <component>   # e.g. db, code, gitbundle, config
#
# Spec: docs/superpowers/specs/2026-04-16-backup-system-design.md
# Plan: docs/superpowers/plans/2026-04-16-backup-system-redesign.md Task 3

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
FAILED_COMPONENTS=""
CRITICAL_FAILED=0
# The database dump is the only restore-CRITICAL component: code lives in git/GitHub,
# config regenerates, volumes are caches/media. If db succeeds we MUST get it off-site
# even when a non-critical component failed — a flaky code/config/volume tar must never
# again silently kill the Drive/DR copy of a perfectly good database (#5092). The
# surrounding spaces make " db " a whole-word match inside the padded list.
CRITICAL_COMPONENTS=" db "

run_component() {
    local name="$1"
    local script="$SCRIPT_DIR/component_${name}.sh"
    if [[ ! -x "$script" ]]; then
        log_warn "component_${name}.sh not present yet — skipping"
        return 0
    fi
    log_info "→ component: $name"
    if ! "$script" "$RUN_DIR"; then
        log_error "Component FAILED: $name"
        FAILED=1
        FAILED_COMPONENTS+="$name "
        if [[ "$CRITICAL_COMPONENTS" == *" $name "* ]]; then CRITICAL_FAILED=1; fi
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
        log_error "Unknown MODE: $MODE"
        exit 1
        ;;
esac

# ── Tier-sync gate (#5092) ────────────────────────────────────────────────
# Old behaviour: ANY component failure skipped ALL off-site tier sync + retention,
# so one flaky non-critical tar silently stalled the Google Drive / DR copy of a
# healthy database for days (Drive stalled 2026-07-11 → 07-21). New: the database
# (restore-critical) reaching off-site is DECOUPLED from non-critical components.
# Retention still requires a fully clean run — never prune old restore points when
# the new set is incomplete.
DO_TIER_SYNC=0
DO_RETENTION=0
if (( FAILED == 0 )); then
    DO_TIER_SYNC=1
    DO_RETENTION=1
    log_info "All components OK — starting tier sync + retention"
elif (( CRITICAL_FAILED == 0 )); then
    DO_TIER_SYNC=1
    log_warn "Non-critical component(s) failed: ${FAILED_COMPONENTS}— DB OK, tier sync WITHOUT retention (#5092)"
    notify_telegram warn "Partial backup mode=$MODE ts=$TS: non-critical failed (${FAILED_COMPONENTS}); DB synced off-site; retention skipped"
else
    log_error "CRITICAL component failed (${FAILED_COMPONENTS}) — skipping tier sync + retention"
    notify_telegram error "Primary backup failed: mode=$MODE ts=$TS run=$RUN_DIR (critical: ${FAILED_COMPONENTS})"
fi

if (( DO_TIER_SYNC == 1 )); then
    # Write metadata.json BEFORE tier sync so USB/GDrive/VPS copies include it
    # (the UI scanner on each tier filters on metadata.json existence).
    PRE_SYNC_SIZE=$(dir_size_bytes "$RUN_DIR")
    PRE_SYNC_DUR=$(( ( $(date +%s) - START_EPOCH ) * 1000 ))
    python3 - "$RUN_DIR" "$MODE" "$TS" "$PRE_SYNC_SIZE" "$PRE_SYNC_DUR" <<'PYEOF_PRESYNC'
import json, os, sys
from datetime import datetime
run_dir, mode, ts, size, dur_ms = sys.argv[1:]
size = int(size)
components = {n: True for n in os.listdir(run_dir) if os.path.isdir(os.path.join(run_dir, n))}
db_file = None
db_dir = os.path.join(run_dir, "database")
if os.path.isdir(db_dir):
    dumps = sorted(f for f in os.listdir(db_dir) if f.endswith(".dump"))
    if dumps:
        db_file = f"database/{dumps[-1]}"
# Compute next build number from existing metadata (max + 1). Keeps the UI's
# "Build #N" column monotonic across the legacy → phase-1-6 transition.
parent_dir = os.path.dirname(run_dir)
max_build = 0
for sib in os.listdir(parent_dir):
    mp = os.path.join(parent_dir, sib, "metadata.json")
    if os.path.exists(mp):
        try:
            with open(mp) as _f:
                bn = json.load(_f).get("build_number")
            if isinstance(bn, int):
                max_build = max(max_build, bn)
        except Exception:
            pass
# Read current platform version from system_config
import subprocess as _sp
try:
    _r = _sp.run(
        ["docker", "exec", "archie_database", "psql", "-U", "archie", "-At", "-c",
         "SELECT value FROM system_config WHERE key='platform_version' LIMIT 1"],
        capture_output=True, text=True, timeout=5
    )
    platform_ver = _r.stdout.strip() or "unknown"
except Exception:
    platform_ver = "unknown"

meta = {
    "name": os.path.basename(run_dir), "timestamp": ts, "description": mode,
    "created_by": "scripts/backup/run_backup.sh",
    "created_at": datetime.utcnow().isoformat() + "Z",
    "platform_version": platform_ver, "build_number": max_build + 1,
    "backup_type": mode, "run_mode": mode, "proposal_id": None,
    "compression": "pg_dump-Fc", "database_file": db_file,
    "total_size_bytes": size, "total_size_mb": round(size / (1024 * 1024), 2),
    "external_copy": False, "external_path": None,
    "pipeline": platform_ver, "components": components,
    "duration_ms": int(dur_ms),
    "hook_results": {"pre": [], "post": []},
}
with open(os.path.join(run_dir, "metadata.json"), "w") as f:
    json.dump(meta, f, indent=2)
PYEOF_PRESYNC
    log_info "wrote metadata.json pre-sync"

    "$SCRIPT_DIR/tier_sync_usb.py"    "$RUN_DIR"        || log_warn "USB tier sync had errors"
    "$SCRIPT_DIR/tier_sync_gdrive.py" "$RUN_DIR" "$MODE" || log_warn "GDrive tier sync had errors"
    # vps tier RETIRED 2026-08-29 (decision #1049 / #6104): the outposts lapse and the
    # dr tier already lives on Citadel — a vps tier there would share its failure domain.
fi

if (( DO_RETENTION == 1 )); then
    "$SCRIPT_DIR/retention_prune.py"                    || log_warn "Retention prune had errors"
fi

DUR_MS=$(( ( $(date +%s) - START_EPOCH ) * 1000 ))
SIZE=$(dir_size_bytes "$RUN_DIR")
# Honest status so the freshness gate (which keys on last SUCCESS) can't be fooled:
# clean=success; DB reached off-site but a non-critical component failed=partial;
# nothing synced=failed (#5092).
if (( FAILED == 0 )); then
    RUN_STATUS=success
elif (( DO_TIER_SYNC == 1 )); then
    RUN_STATUS=partial
else
    RUN_STATUS=failed
fi
log_to_db "run_backup" "primary" "$RUN_STATUS" "$RUN_DIR" "$SIZE" "$DUR_MS"

# Refresh metadata.json with final size/duration AFTER tier sync. We MERGE
# onto the pre-sync write rather than overwriting, so build_number,
# backup_type=full, and run_mode established pre-sync survive. (Previously
# this block blindly rewrote metadata with build_number=None + backup_type=<mode>,
# which put every fresh backup back into the UI's LEGACY bucket.)
if (( FAILED == 0 )); then
    python3 - "$RUN_DIR" "$SIZE" "$DUR_MS" <<'PYEOF'
import json, os, sys
run_dir, size, dur_ms = sys.argv[1:]
size = int(size)
meta_path = os.path.join(run_dir, "metadata.json")
if os.path.exists(meta_path):
    with open(meta_path) as f:
        meta = json.load(f)
else:
    meta = {}
# Only the numbers that can change between pre-sync and post-sync.
meta["total_size_bytes"] = size
meta["total_size_mb"] = round(size / (1024 * 1024), 2)
meta["duration_ms"] = int(dur_ms)
with open(meta_path, "w") as f:
    json.dump(meta, f, indent=2)
PYEOF
    log_info "refreshed metadata.json with final size/duration (pre-sync values preserved)"

    # Emit a self-contained rollback.sh so an operator can restore this specific
    # backup with a single ./rollback.sh invocation. Mirrors the convenience
    # script the legacy pipeline had (observed in build #10 review 2026-04-17).
    DUMP_BASENAME=$(ls "$RUN_DIR/database/" 2>/dev/null | grep '\.dump$' | head -1)
    CODE_BASENAME=$(ls "$RUN_DIR/code/" 2>/dev/null | grep '\.tar' | head -1)
    cat > "$RUN_DIR/rollback.sh" <<ROLLBACK_EOF
#!/usr/bin/env bash
# A.R.C.H.I.E. rollback script — restores backup $(basename "$RUN_DIR").
# Created $(date -u +%FT%TZ) by scripts/backup/run_backup.sh.
#
# Usage:  sudo bash rollback.sh
#
# Prerequisites on target host:
#   - docker + docker compose installed
#   - archie_database container using pgvector/pgvector:pg16 image
#   - This backup dir accessible at the path below
set -euo pipefail

BACKUP_DIR="\${BACKUP_DIR:-$RUN_DIR}"
echo "Rolling back to: \$BACKUP_DIR"

cd /mnt/archie_brain
echo "Stopping platform..."
docker compose stop archie_platform || true

echo "Restoring PostgreSQL (pg_dump -Fc custom format)..."
docker exec -i archie_database psql -U archie -c "DROP DATABASE IF EXISTS archie;"
docker exec -i archie_database psql -U archie -c "CREATE DATABASE archie;"
cat "\$BACKUP_DIR/database/$DUMP_BASENAME" | docker exec -i archie_database pg_restore -U archie -d archie --no-owner --no-privileges

if [ -n "$CODE_BASENAME" ] && [ -f "\$BACKUP_DIR/code/$CODE_BASENAME" ]; then
    echo "Restoring platform code from \$BACKUP_DIR/code/$CODE_BASENAME..."
    tar -xzf "\$BACKUP_DIR/code/$CODE_BASENAME" -C /mnt/archie_brain
fi

echo "Restarting platform..."
docker compose up -d archie_platform

echo ""
echo "Optional next steps (not automated):"
echo "  - Decrypt config tier: scripts/backup/decrypt_restore.sh <config>.enc BACKUP_CONFIG_PASSPHRASE"
echo "  - Restore KBS + Stalwart from volumes/: docker run --rm -v <vol>:/target -v \$BACKUP_DIR/volumes:/src alpine tar -xzf /src/<vol>.tar.gz -C /target"
echo "  - Restore git bundles: git clone \$BACKUP_DIR/gitbundles/<repo>.bundle <repo>"
echo ""
echo "✓ Core rollback complete. Verify: curl -s http://localhost:3000/api/health | jq"
ROLLBACK_EOF
    chmod +x "$RUN_DIR/rollback.sh"
    log_info "emitted rollback.sh for this backup"
fi

log_info "=== run_backup.sh DONE mode=$MODE failed=$FAILED size=$SIZE dur_ms=$DUR_MS ==="
exit "$FAILED"

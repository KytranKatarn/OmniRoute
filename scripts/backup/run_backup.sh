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

if (( FAILED == 0 )); then
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
meta = {
    "name": os.path.basename(run_dir), "timestamp": ts, "description": mode,
    "created_by": "scripts/backup/run_backup.sh",
    "created_at": datetime.utcnow().isoformat() + "Z",
    "platform_version": "phase-1-6", "build_number": max_build + 1,
    "backup_type": "full", "run_mode": mode, "proposal_id": None,
    "compression": "pg_dump-Fc", "database_file": db_file,
    "total_size_bytes": size, "total_size_mb": round(size / (1024 * 1024), 2),
    "external_copy": False, "external_path": None,
    "pipeline": "phase-1-6", "components": components,
    "duration_ms": int(dur_ms),
    "hook_results": {"pre": [], "post": []},
}
with open(os.path.join(run_dir, "metadata.json"), "w") as f:
    json.dump(meta, f, indent=2)
PYEOF_PRESYNC
    log_info "wrote metadata.json pre-sync"

    log_info "All components OK — starting tier sync"
    "$SCRIPT_DIR/tier_sync_usb.py"    "$RUN_DIR"        || log_warn "USB tier sync had errors"
    "$SCRIPT_DIR/tier_sync_gdrive.py" "$RUN_DIR" "$MODE" || log_warn "GDrive tier sync had errors"
    "$SCRIPT_DIR/tier_sync_vps.sh"    "$RUN_DIR"        || log_warn "VPS tier sync had errors"
    "$SCRIPT_DIR/retention_prune.py"                    || log_warn "Retention prune had errors"
else
    log_error "Component failures — skipping tier sync + retention"
    notify_telegram error "Primary backup failed: mode=$MODE ts=$TS run=$RUN_DIR"
fi

DUR_MS=$(( ( $(date +%s) - START_EPOCH ) * 1000 ))
SIZE=$(dir_size_bytes "$RUN_DIR")
log_to_db "run_backup" "primary" \
    "$([[ $FAILED -eq 0 ]] && echo success || echo failed)" \
    "$RUN_DIR" "$SIZE" "$DUR_MS"

# Refresh metadata.json with final size/duration numbers (post tier-sync).
# First write happened pre-sync so USB got it; this just updates the primary copy.
if (( FAILED == 0 )); then
    python3 - "$RUN_DIR" "$MODE" "$TS" "$SIZE" "$DUR_MS" <<'PYEOF'
import json, os, sys
from datetime import datetime
run_dir, mode, ts, size, dur_ms = sys.argv[1:]
size = int(size)
components = {
    name: True
    for name in os.listdir(run_dir)
    if os.path.isdir(os.path.join(run_dir, name))
}
# Find the DB dump (varies: archie_<ts>.dump)
db_file = None
db_dir = os.path.join(run_dir, "database")
if os.path.isdir(db_dir):
    dumps = sorted(f for f in os.listdir(db_dir) if f.endswith(".dump"))
    if dumps:
        db_file = f"database/{dumps[-1]}"
meta = {
    "name": os.path.basename(run_dir),
    "timestamp": ts,
    "description": mode,
    "created_by": "scripts/backup/run_backup.sh",
    "created_at": datetime.utcnow().isoformat() + "Z",
    "platform_version": "phase-1-6",
    "build_number": None,
    "backup_type": mode,
    "proposal_id": None,
    "compression": "pg_dump-Fc",
    "database_file": db_file,
    "total_size_bytes": size,
    "total_size_mb": round(size / (1024 * 1024), 2),
    "external_copy": False,
    "external_path": None,
    "pipeline": "phase-1-6",
    "components": components,
    "duration_ms": int(dur_ms),
    "hook_results": {"pre": [], "post": []},
}
with open(os.path.join(run_dir, "metadata.json"), "w") as f:
    json.dump(meta, f, indent=2)
PYEOF
    log_info "wrote metadata.json for UI visibility"
fi

log_info "=== run_backup.sh DONE mode=$MODE failed=$FAILED size=$SIZE dur_ms=$DUR_MS ==="
exit "$FAILED"

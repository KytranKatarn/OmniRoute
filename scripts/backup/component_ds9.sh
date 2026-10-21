#!/usr/bin/env bash
# scripts/backup/component_ds9.sh <run_dir>
# Captures the Deep Space 9 (DS9) gateway's own state.
#
# WHY THIS EXISTS
# The DS9 is the platform's self-owned AI gateway (host-native systemd service,
# deep-space-9.service, DATA_DIR=/home/kytran/.omniroute). Its store holds
# state that exists NOWHERE ELSE:
#
#   * api_keys — the gateway's live API keys. The PLATFORM's own key also
#     lives in .env (and is backed up by component_config.sh), but the CODEX
#     LANE's key ('Host Codex DS9 gate7', Dev HQ #7380) exists ONLY here. A
#     restore without this file leaves the codex lane unable to reach DS9.
#   * provider_connections — the codex-app-server connection that the DHQ DS9
#     tab renders (Dev HQ #7395).
#   * key_value — 86 rows of DS9 settings: routing mode, provider limits, the
#     synced model catalogues, the last-known-good provider map.
#   * combos — the operator-created combos.
#
# A tar of the live store is NOT safe: DS9 writes continuously, so the .sqlite
# plus its -wal/-shm sidecars can be captured mid-write. This uses SQLite's
# ONLINE BACKUP API, which produces a consistent snapshot while the database
# stays live - the same reason component_db.sh excludes the Postgres data files
# ("Postgres data files aren't safely tarrable on a live server").
#
# The encrypted columns stay decryptable after a restore: the DS9's
# STORAGE_ENCRYPTION_KEY is in .env (OMNIROUTE_STORAGE_ENCRYPTION_KEY), which
# component_config.sh already backs up.
#
# NOT captured, and why:
#   * db_backups/ - the DS9's own rolling backups; we are the backup now.
#   * logs/, cache/ - regenerable.
#   * storage.sqlite.probe-failed-* - leftovers from a failed probe.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/ds9"
mkdir -p "$OUT_DIR"

DS9_DATA_DIR="${DS9_DATA_DIR:-/home/kytran/.omniroute}"
DS9_DB="$DS9_DATA_DIR/storage.sqlite"

START=$(date +%s)
STATUS="success"
ERR=""
TOTAL=0

if [[ ! -d "$DS9_DATA_DIR" ]]; then
    log_warn "DS9 data dir not present at $DS9_DATA_DIR — nothing to capture"
    log_to_db "ds9" "secondary" "skipped" "$OUT_DIR" 0 0 "DS9 data dir absent"
    exit 0
fi

# --- 1. A consistent snapshot of the live store -----------------------------
SNAPSHOT="$OUT_DIR/storage_$(backup_ts).sqlite"
if [[ -f "$DS9_DB" ]]; then
    if python3 - "$DS9_DB" "$SNAPSHOT" <<'PY'
import sqlite3, sys

src, dst = sys.argv[1], sys.argv[2]
# Read-only source, online-backup destination. The backup API takes a
# transaction-consistent snapshot even while the database is being written.
source = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
target = sqlite3.connect(dst)
with target:
    source.backup(target)
target.close()
source.close()
PY
    then
        # The sentinel is what verify_backups.sh roundtrips, so a snapshot that
        # cannot be read back is a failed backup, not a successful one.
        SENTINEL_STAGE_DIR=$(mktemp -d)
        echo "archie-backup-sentinel $(date -u +%FT%TZ)" > "$SENTINEL_STAGE_DIR/.backup_sentinel"
        if python3 - "$SNAPSHOT" "$SENTINEL_STAGE_DIR/.backup_sentinel" <<'PY'
import sqlite3, sys

db, sentinel = sys.argv[1], sys.argv[2]
con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
cur = con.cursor()
cur.execute("SELECT COUNT(*) FROM provider_connections")
conns = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM api_keys")
keys = cur.fetchone()[0]
con.close()
assert "archie-backup-sentinel" in open(sentinel, encoding="utf-8").read()
# A snapshot with no provider_connections and no api_keys is a snapshot of the
# WRONG database (or an empty one). Fail loudly rather than archiving a file
# that looks fine and restores nothing.
assert conns > 0 or keys > 0, "snapshot has no provider_connections and no api_keys"
print(f"verify OK: ds9 snapshot (provider_connections={conns}, api_keys={keys})")
PY
        then
            SZ=$(stat -c %s "$SNAPSHOT")
            TOTAL=$(( TOTAL + SZ ))
            log_info "DS9 store snapshot OK — $SZ bytes"
        else
            STATUS="failed"
            ERR="snapshot failed its readback verification"
            log_error "DS9 store snapshot failed verification — not archiving it"
            rm -f "$SNAPSHOT"
        fi
        rm -rf "$SENTINEL_STAGE_DIR"
        # The readback connection creates empty -shm/-wal sidecars next to the
        # snapshot. They are not part of the backup; leave the archive clean.
        rm -f "$SNAPSHOT-shm" "$SNAPSHOT-wal"
    else
        STATUS="failed"
        ERR="sqlite online backup failed"
        log_error "DS9 store snapshot failed"
    fi
else
    log_warn "DS9 store not found at $DS9_DB — skipping the snapshot"
fi

# --- 2. The per-call audit trail (raw request/response logs) ---------------
if [[ -d "$DS9_DATA_DIR/call_logs" ]]; then
    CALLS_OUT="$OUT_DIR/call_logs_$(backup_ts).tar.gz"
    if tar --ignore-failed-read -czf "$CALLS_OUT" \
           -C "$DS9_DATA_DIR" call_logs 2>>"$BACKUP_LOG_FILE"; then
        SZ=$(stat -c %s "$CALLS_OUT")
        TOTAL=$(( TOTAL + SZ ))
        log_info "DS9 call_logs OK — $SZ bytes"
    else
        STATUS="failed"
        ERR="${ERR:+$ERR; }call_logs tar failed"
        log_error "DS9 call_logs tar failed"
    fi
fi

# --- 3. The DS9's own env (port, data dir, and its encryption key ref) ------
if [[ -f "$DS9_DATA_DIR/.env" ]]; then
    if cp "$DS9_DATA_DIR/.env" "$OUT_DIR/ds9.env" 2>>"$BACKUP_LOG_FILE"; then
        log_info "DS9 env OK"
    else
        STATUS="failed"
        ERR="${ERR:+$ERR; }ds9 .env copy failed"
    fi
fi

DUR=$(( $(date +%s) - START ))
log_to_db "ds9" "secondary" "$STATUS" "$OUT_DIR" "$TOTAL" "$(( DUR * 1000 ))" "$ERR"
log_info "DS9 capture done — status=$STATUS total=$TOTAL bytes in ${DUR}s"
[[ "$STATUS" == "success" ]]

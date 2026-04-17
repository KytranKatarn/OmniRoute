#!/usr/bin/env bash
# scripts/backup/component_volumes.sh <run_dir>
# Captures stateful service data.
#
# Two sources:
#  1. Bind-mount paths under /mnt/archie_brain/persistence and per-product /data dirs
#     (n8n, creed — legacy pattern).
#  2. Named Docker volumes — where KBS, Stalwart Mail, Headscale, Tailscale, and
#     KBS Redis actually persist their state. These were invisible to the original
#     bind-mount-only scanner, so today's 8-bug round of UI QA exposed that
#     business-critical data wasn't being backed up (task series #2073-#2077).
#
# archie_database is intentionally EXCLUDED here — it's backed up via pg_dump -Fc
# in component_db.sh (Postgres data files aren't safely tarrable on a live server).
# archie_comfyui_output is EXCLUDED because it's regeneratable.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/lib_common.sh"

RUN_DIR="${1:?run_dir required}"
OUT_DIR="$RUN_DIR/volumes"
mkdir -p "$OUT_DIR"

START=$(date +%s)
TOTAL=0
FAILED=0

# ----------------------------------------------------------------------------
# (1) Bind-mount paths — legacy pattern, kept for n8n + per-product data dirs.
# ----------------------------------------------------------------------------
BIND_MOUNTS=(
    "n8n:/mnt/archie_brain/persistence/n8n"
    "kbs_data:/mnt/archie_brain/kytran-business-suite/data"
    "creed_data:/mnt/archie_brain/kytran-creed/data"
    "stalwart_persistence:/mnt/archie_brain/persistence/stalwart"
)

for entry in "${BIND_MOUNTS[@]}"; do
    name="${entry%%:*}"
    path="${entry#*:}"
    if [[ ! -d "$path" ]]; then
        log_warn "skip bind-mount $name — $path not present"
        continue
    fi
    OUT_FILE="$OUT_DIR/volume_${name}_$(backup_ts).tar.gz"
    # Exclude postgres subdirs owned by other UIDs — those live in named volumes now.
    if tar --ignore-failed-read \
           --exclude='*/postgres' \
           --exclude='*/postgres-data' \
           -czf "$OUT_FILE" -C "$(dirname "$path")" "$(basename "$path")" 2>>"$BACKUP_LOG_FILE"; then
        sz=$(stat -c %s "$OUT_FILE")
        TOTAL=$(( TOTAL + sz ))
        log_info "bind-mount $name OK — $sz bytes"
    else
        log_error "bind-mount $name tar failed"
        FAILED=1
    fi
done

# ----------------------------------------------------------------------------
# (2) Named Docker volumes — KBS postgres, Stalwart mail, etc.
# ----------------------------------------------------------------------------
# List every named volume that holds STATE. Add new ones here when products
# come online. Exclusions: archie_database (pg_dump handles it),
# archie_comfyui_output (regeneratable), container-runtime hash-named volumes.
NAMED_VOLUMES=(
    "kbs_pg:kytran-business-suite_pg-data"
    "kbs_redis:kytran-business-suite_redis-data"
    "stalwart_mail:stalwart-mail_stalwart-data"
    "archie_kbs_redis:archie_brain_kbs-redis-data"
    "headscale:archie_headscale_data"
    "tailscale:archie_tailscale_hub"
)

# Confirm docker is reachable (cron may run before docker if ordering slips).
if ! docker info >/dev/null 2>&1; then
    log_error "docker unreachable — skipping named-volume backup"
else
    for entry in "${NAMED_VOLUMES[@]}"; do
        short="${entry%%:*}"
        vol="${entry#*:}"
        if ! docker volume inspect "$vol" >/dev/null 2>&1; then
            log_warn "skip named-volume $short ($vol) — not present"
            continue
        fi
        OUT_FILE="$OUT_DIR/dockervol_${short}_$(backup_ts).tar.gz"
        # Run alpine with the volume mounted read-only, tar straight to host file
        # via stdout. Avoids needing write perms on the volume and avoids a
        # two-copy approach.
        if docker run --rm \
                -v "$vol:/source:ro" \
                alpine sh -c "tar -C /source -czf - ." > "$OUT_FILE" 2>>"$BACKUP_LOG_FILE"; then
            sz=$(stat -c %s "$OUT_FILE")
            TOTAL=$(( TOTAL + sz ))
            log_info "named-volume $short ($vol) OK — $sz bytes"
        else
            log_error "named-volume $short ($vol) tar failed"
            FAILED=1
        fi
    done
fi

DUR=$(( ( $(date +%s) - START ) * 1000 ))
STATUS=$([[ $FAILED -eq 0 ]] && echo success || echo failed)
log_to_db "volumes" "primary" "$STATUS" "$OUT_DIR" "$TOTAL" "$DUR"
exit "$FAILED"

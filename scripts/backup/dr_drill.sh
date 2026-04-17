#!/usr/bin/env bash
# Quarterly disaster-recovery drill.
# Restores the latest daily DB dump into a throwaway Postgres container
# and confirms row counts match production within 1%.
# Writes a report to scripts/backup/dr_reports/.
set -euo pipefail

REPO="/mnt/archie_brain"
SRC_DIR="${BACKUP_ROOT:-/mnt/data2/backups}"
REPORT_DIR="$REPO/scripts/backup/dr_reports"
mkdir -p "$REPORT_DIR"
TS=$(date -u +%Y-%m-%d)
REPORT="$REPORT_DIR/$TS.md"
CONTAINER="archie_dr_drill_$$"

latest_dump=$(ls -td "$SRC_DIR"/*/database/*.dump 2>/dev/null | head -1 || true)
[[ -n "${latest_dump:-}" ]] || { echo "No dump found in $SRC_DIR/*/database/"; exit 1; }

echo "DR Drill $TS — using $latest_dump"

# Clean up drill container on ANY exit (success, failure, interrupt).
cleanup() { docker rm -f "$CONTAINER" >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM

# Row counts from production.
prod_rows=$(docker exec archie_database psql -U archie -d archie -At -c \
    "SELECT COUNT(*) FROM knowledge_base;")

# Spin up throwaway container. Mount dump read-only so we can pg_restore from inside.
docker run -d --rm --name "$CONTAINER" \
    -e POSTGRES_PASSWORD=drilldrill \
    -v "$latest_dump:/tmp/dump.dump:ro" \
    postgres:16-alpine > /dev/null

# Wait for the drill postgres to accept connections (psql lives inside the container).
for _ in $(seq 1 30); do
    if docker exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1; then
        break
    fi
    sleep 1
done

# Create DB and restore — all inside the drill container (no host psql needed).
docker exec "$CONTAINER" psql -U postgres -c "CREATE DATABASE archie;" >/dev/null

# pg_restore emits warnings on role/extension mismatches but must succeed overall.
# Capture its real exit code via PIPESTATUS (tail would otherwise mask failures).
set +e
docker exec "$CONTAINER" pg_restore -U postgres -d archie --no-owner --no-privileges \
    /tmp/dump.dump 2>&1 | tail -10
restore_rc=${PIPESTATUS[0]}
set -e

# pg_restore returns non-zero for minor warnings too, so don't fail hard on rc alone.
# Real test: can we query knowledge_base?
drill_rows=$(docker exec "$CONTAINER" psql -U postgres -d archie -At -c \
    "SELECT COUNT(*) FROM knowledge_base;" 2>/dev/null || echo "RESTORE_FAILED")

if [[ "$drill_rows" == "RESTORE_FAILED" ]]; then
    echo "FAIL: knowledge_base not present after restore (pg_restore rc=$restore_rc)" >&2
    cat >"$REPORT" <<EOF
# DR Drill — $TS

- Dump: \`$latest_dump\`
- Production rows: $prod_rows
- Status: **FAIL**
- Reason: pg_restore did not produce a queryable knowledge_base table (rc=$restore_rc)
EOF
    echo "Report: $REPORT"
    exit 1
fi

# Compute delta percentage.
pct_diff=$(awk "BEGIN{printf \"%.4f\", ($prod_rows - $drill_rows) / $prod_rows * 100}")
within_1pct=$(awk "BEGIN{print (($prod_rows - $drill_rows) / $prod_rows < 0.01 && ($drill_rows - $prod_rows) / $prod_rows < 0.01) ? 1 : 0}")

if [[ "$within_1pct" == "1" ]]; then
    status="PASS"
else
    status="FAIL"
fi

cat >"$REPORT" <<EOF
# DR Drill — $TS

- Dump: \`$latest_dump\`
- Production rows (knowledge_base): $prod_rows
- Drill restore rows: $drill_rows
- Delta: $pct_diff%
- Status: **$status**

Acceptance: delta < 1%.
EOF

echo "Report: $REPORT"
echo "Status: $status"
[[ "$status" == "PASS" ]] || exit 1

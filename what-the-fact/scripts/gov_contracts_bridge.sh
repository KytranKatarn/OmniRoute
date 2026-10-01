#!/usr/bin/env bash
# Gov Watch → WTF bridge: federal contracts signed, by department and year.
#
# WHY A HOST SCRIPT: gov-watch's database (gov_watch_db) lives on Citadel's `gov-watch_default`
# docker network; the WTF containers sit on `what-the-fact_default` and cannot reach it. Both
# databases are containers on the SAME host, so this pipes one aggregate between them with
# `docker exec` — no network hop, no credentials leave the box, nothing is exposed.
#
# Runs ON CITADEL as root. Install (needs Kytran's OK — it is production host config):
#   30 6 * * *  /opt/archie-products/what-the-fact/scripts/gov_contracts_bridge.sh >> /var/log/gov_contracts_bridge.log 2>&1
# gov-watch's own proactive ingest finishes ≈05:40 UTC, so 06:30 UTC reads a settled table.
#
# SAFETY: the replace is ONE transaction (psql --single-transaction + ON_ERROR_STOP). A short or
# failed read can never leave the page half-empty, and a result that is implausibly small refuses
# to replace the table at all. A heartbeat row lands in parliament.ingest_log on BOTH outcomes so
# drift_guard can see a dead bridge (monitor RUNS, not rows — gov-watch.md).
set -euo pipefail

GOV_DB_CONTAINER="${GOV_DB_CONTAINER:-gov_watch_db}"
WTF_DB_CONTAINER="${WTF_DB_CONTAINER:-what-the-fact-wtf-postgres-1}"
SQL_FILE="${SQL_FILE:-$(dirname "$0")/gov_contracts_by_dept.sql}"
MIN_ROWS="${MIN_ROWS:-300}"          # ~100 departments x ~20 years today; far below that = a bad read
TASK="gov_contracts_bridge"

wtf_psql() { docker exec -i "$WTF_DB_CONTAINER" psql -U wtfuser -d wtf -v ON_ERROR_STOP=1 "$@"; }

heartbeat_error() {
  local msg="${1//\'/}"
  wtf_psql -q -c "INSERT INTO parliament.ingest_log (task, error) VALUES ('$TASK', left('$msg', 500))" || true
}
trap 'heartbeat_error "bridge failed at line $LINENO"' ERR

exec 9>/tmp/gov_contracts_bridge.lock
flock -n 9 || { echo "another run is in progress"; exit 0; }

CSV="$(mktemp)"; trap 'rm -f "$CSV"' EXIT
docker exec -i "$GOV_DB_CONTAINER" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -q' < "$SQL_FILE" > "$CSV"
ROWS=$(wc -l < "$CSV")
echo "$(date -u +%FT%TZ) aggregate rows: $ROWS"

{
cat <<SQL
CREATE SCHEMA IF NOT EXISTS gov_watch;
CREATE TABLE IF NOT EXISTS gov_watch.contracts_signed_by_dept_year (
    owner_org     TEXT    NOT NULL,
    title_en      TEXT    NOT NULL,
    year          INTEGER NOT NULL,
    n_contracts   INTEGER NOT NULL,
    signed_value  NUMERIC(18,2) NOT NULL,
    largest_value NUMERIC(18,2) NOT NULL,
    refreshed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_org, year)
);
CREATE TEMP TABLE stage (LIKE gov_watch.contracts_signed_by_dept_year INCLUDING DEFAULTS) ON COMMIT DROP;
COPY stage (owner_org, title_en, year, n_contracts, signed_value, largest_value) FROM STDIN WITH CSV;
SQL
cat "$CSV"
echo '\.'
cat <<SQL
DO \$\$ BEGIN
  IF (SELECT count(*) FROM stage) < $MIN_ROWS THEN
    RAISE EXCEPTION 'refusing to replace: only % rows staged (min $MIN_ROWS)', (SELECT count(*) FROM stage);
  END IF;
END \$\$;
DELETE FROM gov_watch.contracts_signed_by_dept_year;
INSERT INTO gov_watch.contracts_signed_by_dept_year SELECT * FROM stage;
INSERT INTO parliament.ingest_log (task, records_fetched, records_upserted)
VALUES ('$TASK', (SELECT count(*) FROM stage), (SELECT count(*) FROM stage));
SQL
} | wtf_psql --single-transaction -q

trap - ERR
echo "$(date -u +%FT%TZ) ok"

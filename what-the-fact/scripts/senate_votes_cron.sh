#!/usr/bin/env bash
# Weekly parliament HUB scrapes — everything that cannot run in wtf-ingest
# (#5725 Senate, #5727 lobbying).
#
# sencanada.ca's roster + votes pages are JS-rendered (Playwright + system
# Chrome, which the ingest container deliberately does not carry — its weekly
# senators run is enrichment-only and scrapes 0, proven 2026-08-18).
# lobbycanada.gc.ca sits behind an interactive Cloudflare turnstile that only
# HEADED Chrome clears (xvfb-run below; headless never passes — 2026-08-18).
#
# Install (hub, one-time):
#   sudo tee /etc/cron.d/wtf-senate-votes >/dev/null <<'CRON'
#   15 4 * * 0 kytran /mnt/archie_brain/what-the-fact/scripts/senate_votes_cron.sh
#   CRON
#
# Each step heartbeats to parliament.ingest_log ('senators_roster' /
# 'senate_votes'); the container-side drift_guard alarms if either goes
# stale — the "monitor RUNS, not ROWS" rule.
set -eo pipefail
# Log EVERYTHING from here — a pre-python failure must land in the log,
# not vanish into cron mail.
exec >> /tmp/wtf_senate_votes.log 2>&1
echo "=== senate cron run $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
cd /mnt/archie_brain/what-the-fact

# NEVER `source` the root .env — it is a docker env_file, not bash: values
# hold literal $1 (silently mangled by expansion, fatal under -u) and shell
# metacharacters bash tries to EXECUTE (leaked a credential fragment to
# this log on 2026-08-18, and set -e aborted the run). Quoting the file
# would break docker's env_file semantics, so extract the ONE key we need
# without any shell evaluation:
set -u
DB_PASSWORD="$(grep -m1 '^DB_PASSWORD=' /mnt/archie_brain/.env | cut -d= -f2-)"
if [ -z "${DB_PASSWORD}" ]; then
    echo "FATAL: DB_PASSWORD not found in /mnt/archie_brain/.env"
    exit 1
fi
export WTF_DATABASE_URL="postgresql://archie:${DB_PASSWORD}@192.168.1.200:5432/wtf"

echo "--- senators roster sync ---"
python3 -m ingest.parliament.senators || echo "senators roster sync FAILED (error heartbeat written by python)"

echo "--- senate votes sync ---"
python3 -m ingest.parliament.senate_votes || echo "senate votes sync FAILED (error heartbeat written by python)"

echo "--- lobbying registry sync (headed Chrome under Xvfb — turnstile) ---"
xvfb-run -a python3 -m ingest.parliament.lobbying || echo "lobbying sync FAILED (error heartbeat written by python)"

echo "=== senate cron run done $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

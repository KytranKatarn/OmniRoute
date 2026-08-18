#!/usr/bin/env bash
# Weekly Senate votes scrape — runs on the HUB, not in wtf-ingest (#5725).
#
# sencanada.ca's votes pages are JS-rendered, so the scraper needs
# Playwright + Chrome, which the ingest container deliberately does not
# carry (requirements-ingest.txt keeps the image small). The hub already
# has both (senators.py committee scraper precedent).
#
# Install (hub, one-time):
#   sudo tee /etc/cron.d/wtf-senate-votes >/dev/null <<'CRON'
#   15 4 * * 0 kytran /mnt/archie_brain/what-the-fact/scripts/senate_votes_cron.sh
#   CRON
#
# The run heartbeats to parliament.ingest_log (task='senate_votes') via
# run_senate_votes_sync, so the container-side drift_guard alarms if this
# cron ever stops working — the "monitor RUNS, not ROWS" rule.
set -euo pipefail
# Log EVERYTHING from here — a pre-exec failure (env sourcing, unbound
# DB_PASSWORD) must land in the log, not vanish into cron mail.
exec >> /tmp/wtf_senate_votes.log 2>&1
cd /mnt/archie_brain/what-the-fact

# DB creds come from the platform root .env (hub-local postgres, wtf DB).
set -a; source /mnt/archie_brain/.env 2>/dev/null || true; set +a
export WTF_DATABASE_URL="${WTF_DATABASE_URL:-postgresql://archie:${DB_PASSWORD}@192.168.1.200:5432/wtf}"

exec python3 -m ingest.parliament.senate_votes

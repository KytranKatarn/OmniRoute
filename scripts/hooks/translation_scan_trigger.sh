#!/usr/bin/env bash
# Trigger A.R.C.H.I.E. translation_coverage_scan when website/i18n files
# change in git. Called by post-commit and post-merge hooks.
#
# Carry-over from project #290 task #2365 — Translation Automation Pipeline.
# Pipeline: scan finds gaps → delegate_task to R.O.S.E.T.T.A. → bundle write
# → Hostinger deploy. The git trigger fires the scan whenever website HTML or
# i18n bundle JSON changes — without waiting for the daily 02:00 UTC cron.
#
# Args:
#   $1 — optional "previous" git SHA. Defaults to HEAD~1.
#
# The script is silent on no-op (no website changes), prints one short line
# on trigger, never blocks git, and tolerates docker/platform being down.

set -uo pipefail

PREV="${1:-HEAD~1}"
CUR="HEAD"

# Files changed since PREV. Quiet on error (e.g., shallow clone, first commit).
CHANGED=$(git diff --name-only "${PREV}" "${CUR}" 2>/dev/null) || exit 0
[ -z "$CHANGED" ] && exit 0

# Match repo-relative paths that map onto EXTERNAL_SCAN_SOURCES entries
# living *inside* this git repo. Out-of-repo sources (e.g.
# /mnt/standalone/...) are ignored — those have their own commit cadence.
#
# Watched (relative to repo root):
#   website/**                  — kytranempowerment.com, creed-ai.org
#   kytran-server-manager/**    — KSO templates
#   what-the-fact/**            — WTF brand i18n
#
# File-type filter: HTML templates + i18n bundle JSON only.
TRIGGERED=$(printf '%s\n' "$CHANGED" \
    | grep -E '^(website|kytran-server-manager|what-the-fact)/.*\.(html|json|js)$' \
    || true)

[ -z "$TRIGGERED" ] && exit 0

COUNT=$(printf '%s\n' "$TRIGGERED" | wc -l | tr -d ' ')
SAMPLE=$(printf '%s\n' "$TRIGGERED" | head -3 | tr '\n' ',' | sed 's/,$//')

# JSON-encode the changed repo-relative paths. Passed to the delegate via an
# env var (NOT interpolated into Python source) so a maliciously-named file
# cannot inject code. The handler maps these onto EXTERNAL_SCAN_SOURCES and runs
# a SCOPED scan (changed source only, no global generation/domain-audit/deploy)
# instead of the full ~73-min nightly sweep that false-blocked at the 360s timeout.
CHANGED_PATHS_JSON=$(printf '%s\n' "$TRIGGERED" \
    | python3 -c 'import json,sys; print(json.dumps([l for l in sys.stdin.read().splitlines() if l]))')

REASON="git $(basename "$0" .sh) — ${COUNT} website/i18n file(s) changed: ${SAMPLE}"

# Dry-run mode: print what would happen without firing the docker exec call.
# Used by smoke tests and by developers debugging the hook.
if [ "${ARCHIE_TRIGGER_DRYRUN:-0}" = "1" ]; then
    echo "[translation-scan] DRY RUN — ${COUNT} file(s) would queue scan"
    echo "[translation-scan] reason: ${REASON}"
    exit 0
fi

# Fire the delegate_task call inside the platform container so DB env is set
# up. Fully detached: never blocks git; failures are silently swallowed.
# delegate_task is the canonical external→archie path (ADR-001) and the
# capability translation_coverage_scan resolves to a known-tool handler.
# Reason + paths are passed as ENV VARS (read via os.environ / json.loads), never
# templated into the Python source — keeps attacker-controlled filenames out of
# the code context. The python -c body below is fully static.
(
    docker exec -d \
        -e ARCHIE_SCAN_REASON="$REASON" \
        -e ARCHIE_SCAN_PATHS="$CHANGED_PATHS_JSON" \
        archie_platform python -c "
import os, json
from services.delegation_service import delegate_task
paths = json.loads(os.environ.get('ARCHIE_SCAN_PATHS', '[]'))
delegate_task(
    capability='translation_coverage_scan',
    reason=os.environ.get('ARCHIE_SCAN_REASON', ''),
    args={'trigger': 'git_hook', 'changed_count': len(paths), 'changed_paths': paths},
    delegation_source='automation',
    requested_by='git_hook',
    priority=5,
)
" 2>/dev/null || true
) &

echo "[translation-scan] queued — ${COUNT} website/i18n file(s) changed"
exit 0

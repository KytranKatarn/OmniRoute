#!/usr/bin/env bash
# Run the platform test suite in a DEDICATED, EPHEMERAL container (#5998).
#
# WHY NOT `docker exec archie_platform pytest`:
#   archie_platform has mem_limit 8g (docker-compose.yml:79), sized for the SERVING
#   workload — 4 gunicorn workers at ~1.5 GB RSS is ~6 GB. Running the whole suite in
#   there adds a fifth heavy process beside four live workers, and it OOM-dies around
#   45-55% with exit 137. It completed exactly once, in 7m11s; whether it survives
#   depends on what production happens to be doing. Measured 2026-08-24:
#   /sys/fs/cgroup/memory.events -> oom_kill 2.
#
# WHY NOT archie_staging:
#   It mounts /mnt/archie_sandbox/platform_v2 — the SANDBOX copy, not this repo — so it
#   would test a different, stale tree. Its limit is also 4g, HALF of archie_platform's.
#   (The task that filed this originally recommended archie_staging; checking it first
#   is what caught that.)
#
#
# ⚠️ MEASURED 2026-08-24 — THIS SCRIPT DOES NOT FIX THE OOM, AND WAS NOT WRITTEN TO.
#   Run at --memory 16g (double the platform's 8g) the suite STILL died:
#   OOMKilled=true, exit 137, at the SAME file (tests/test_internal_approvals.py, ~57%).
#   So the wall is NOT the container cap — something in or near that file allocates
#   >16 GiB. Raising --memory only moves the wall; the leak is the actual bug (#5998).
#   What this script DOES buy: an ephemeral, isolated runner that cannot OOM the live
#   platform, with the PYTHONPATH and scripts/ mount the production container gets from
#   compose (their absence caused 13 collection errors, all now gone). Use it to BISECT
#   the leak — not as evidence the suite passes.
# THIS runs the same image against THIS repo's tree, with its own memory ceiling, on the
# same docker network so archie_database is reachable. Nothing competes with production,
# and a runaway test cannot OOM the live platform.
#
# Usage:   scripts/run_tests.sh [pytest args...]
#          scripts/run_tests.sh tests/test_lane_classifier.py -v
#          TEST_MEM=24g scripts/run_tests.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${TEST_IMAGE:-archie_brain-archie_platform}"
MEM="${TEST_MEM:-16g}"
NET="${TEST_NET:-archie_network}"

# The suite never touches production data: tests/conftest.py HARD-OVERRIDES DB_NAME to
# TEST_DB_NAME (default archie_test) — not a setdefault, because inside the platform
# container DB_NAME=archie is already set and a setdefault would be a silent no-op.
: "${TEST_DB_NAME:=archie_test}"

echo "[run_tests] image=$IMAGE mem=$MEM net=$NET db=$TEST_DB_NAME"
echo "[run_tests] tree=$REPO/platform_v2 (this repo, NOT the sandbox copy)"

# ai_bridge is imported as a PACKAGE (`import ai_bridge.x`), so its PARENT must be on the
# path — mounting ai_bridge alone is not enough. PYTHONPATH mirrors what docker-compose
# sets for archie_platform; it lives in `environment:`, NOT in .env, so --env-file does
# not carry it. Without it: 10 collection errors, all ModuleNotFoundError: ai_bridge.
# scripts/ is mounted too — three tests locate repo scripts under /mnt/archie_brain/scripts.
exec docker run --rm \
  --name "archie_tests_$$" \
  --network "$NET" \
  --memory "$MEM" \
  -v "$REPO/platform_v2:/app" \
  -v "$REPO/ai_bridge:/mnt/archie_brain/ai_bridge:ro" \
  -v "$REPO/scripts:/mnt/archie_brain/scripts:ro" \
  --env-file "$REPO/.env" \
  -e "TEST_DB_NAME=$TEST_DB_NAME" \
  -e "PYTHONPATH=/mnt/archie_brain" \
  -w /app \
  "$IMAGE" \
  python3 -m pytest "$@"

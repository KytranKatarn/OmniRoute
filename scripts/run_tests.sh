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

# Withhold the docker socket with TEST_DOCKER_SOCK=0 (see the mounts note below).
DOCKER_SOCK_ARG=""
if [ "${TEST_DOCKER_SOCK:-1}" != "0" ] && [ -S /var/run/docker.sock ]; then
  DOCKER_SOCK_ARG="-v /var/run/docker.sock:/var/run/docker.sock"
fi

echo "[run_tests] image=$IMAGE mem=$MEM net=$NET db=$TEST_DB_NAME"
echo "[run_tests] tree=$REPO/platform_v2 (this repo, NOT the sandbox copy)"

# ---------------------------------------------------------------------------
# MOUNTS (#6014). Several tests read repo directories. Without them they fail in a way that
# is INDISTINGUISHABLE from a real defect — 15 of the 152 failures triaged on 2026-08-24
# were nothing but missing mounts here (measured: 14 failed -> 25 passed as they were added).
#
# Rule: MIRROR archie_platform, which is what the tests were written against
#   docker inspect archie_platform --format '{{range .Mounts}}{{.Source}}|{{.Destination}}|{{.RW}}{{"\n"}}{{end}}'
# but mirror it NARROWLY. That container has 43 mounts, including /backups, .git and
# website/ as READ-WRITE. A test is arbitrary code: nothing here gets write access it does
# not need, and nothing is mounted that no failing test asked for.
#
#   .claude/{skills,commands,rules} -> tests/test_platform_registry_changes.py       (7)
#   database/migrations             -> tests/migrations/*, test_secnet_followups.py  (4)
#   /var/run/docker.sock            -> tests/test_platform_registry_services.py      (4)
#   standalone/                     -> tests/test_media_hub_probe_honesty.py           (1)
#   kytran-auth/                    -> tests/test_oauth_refresh.py                     (1)
#   .git                            -> tests/test_hub_deploy_provenance.py             (1)
#     ^ .git is READ-ONLY here. archie_platform mounts it READ-WRITE; a test is arbitrary
#       code and has no business writing to the repo's history.
#     ^ read-only. That test skipped with "not mounted in this container" — TRUE, but the
#       path it probed was "/standalone/..." (the #5994 root bug), so the message named the
#       wrong cause. Fixing the path alone still skips; the tree has to be here too.
#
# ⚠️ ON THE DOCKER SOCKET: it grants root-equivalent control of the host, so it earns a
# pause — but it is NOT a new exposure. archie_platform ALREADY mounts it read-write, and
# this runner uses THAT SAME IMAGE on THAT SAME HOST. The only delta is that test code runs
# there instead of app code. TEST_DOCKER_SOCK=0 withholds it; those 4 tests then fail,
# which is honest rather than hidden.
# ---------------------------------------------------------------------------

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
  -v "$REPO/.claude/skills:/mnt/archie_brain/.claude/skills:ro" \
  -v "$REPO/.claude/commands:/mnt/archie_brain/.claude/commands:ro" \
  -v "$REPO/.claude/rules:/mnt/archie_brain/.claude/rules:ro" \
  -v "$REPO/database/migrations:/mnt/archie_brain/database/migrations:ro" \
  -v "$REPO/standalone:/mnt/archie_brain/standalone:ro" \
  -v "$REPO/kytran-auth:/mnt/archie_brain/kytran-auth:ro" \
  -v "$REPO/.git:/mnt/archie_brain/.git:ro" \
  $DOCKER_SOCK_ARG \
  --env-file "$REPO/.env" \
  -e "TEST_DB_NAME=$TEST_DB_NAME" \
  -e "PYTHONPATH=/mnt/archie_brain" \
  -w /app \
  "$IMAGE" \
  python3 -m pytest "$@"

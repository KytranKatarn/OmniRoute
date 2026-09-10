#!/usr/bin/env bash
# archie-comms unit tests run on the HOST: the image excludes tests/ (.dockerignore) and
# ships no pytest, so `docker exec archie_comms pytest` cannot work (#6653 Phase 4).
# Usage: bash archie-comms/scripts/run_tests.sh [pytest args]   (default: -q tests/)
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${COMMS_VENV:-$HOME/.cache/archie-comms-venv}"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q "flask==3.1.*" "flask-login==0.6.*" "requests>=2.33.0" "pyjwt>=2.12.0" "psycopg2-binary==2.9.*" pytest
fi
cd "$HERE"
if [ "$#" -eq 0 ]; then
  exec "$VENV/bin/python" -m pytest -q tests/
fi
exec "$VENV/bin/python" -m pytest "$@"

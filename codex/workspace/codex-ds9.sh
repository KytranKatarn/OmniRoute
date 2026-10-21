#!/bin/sh
set -eu
if [ ! -s /run/secrets/ds9_codex_gateway_api_key ]; then
  echo "DS9 credential is unavailable; refusing to use another provider." >&2
  exit 1
fi
DS9_CODEX_API_KEY="$(cat /run/secrets/ds9_codex_gateway_api_key)"
export DS9_CODEX_API_KEY
# docker exec does not inherit variables exported by the container entrypoint.
# Load the existing MCP bearer here too; keep unreadable mounts an explicit error.
if [ -e /run/secrets/codex_kb_bearer ]; then
  if [ ! -r /run/secrets/codex_kb_bearer ]; then
    echo "Mounted Archie KB credential is unreadable; check its owner and mode." >&2
    exit 1
  fi
  ARCHIE_KB_BEARER="$(cat /run/secrets/codex_kb_bearer)"
  export ARCHIE_KB_BEARER
fi
exec codex --profile ds9 -a on-request --sandbox workspace-write "$@"

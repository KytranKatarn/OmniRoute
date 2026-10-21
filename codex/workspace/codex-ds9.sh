#!/bin/sh
set -eu
if [ ! -s /run/secrets/ds9_codex_gateway_api_key ]; then
  echo "DS9 credential is unavailable; refusing to use another provider." >&2
  exit 1
fi
DS9_CODEX_API_KEY="$(cat /run/secrets/ds9_codex_gateway_api_key)"
export DS9_CODEX_API_KEY
exec codex --profile ds9 -a on-request --sandbox workspace-write "$@"

#!/usr/bin/env bash
#
# Provision full-access (read+write, NO admin) MCP bearers for the two coder lanes.
#
# WHY THIS EXISTS AS A SCRIPT YOU RUN:
#   secrets/ is root-owned, so the assistant cannot write credential files. Everything
#   else in this change is automatable; this step is not, by design.
#
# WHAT IT DOES
#   1. mints a fresh token per lane, stores only its SHA-256 in mcp_api_keys
#   2. writes the token to that lane's Docker-secret file, mode 600
#   3. deactivates the old shared read-only key (id 4, `codex-kb-readonly`)
#
# The tokens are NEVER printed, never logged, and never leave this host. The only
# copies are the two secret files.
#
# SAFE TO RE-RUN: each lane's row is replaced by name, and existing secret files are
# backed up with a timestamp before being overwritten.
#
# AFTER RUNNING, the lanes still present their OLD bearer until they restart:
#   docker compose up -d --build archie_mcp_gateway
#   docker compose restart archie_codex_terminal archie_opencode_terminal
#
# Usage:  sudo bash scripts/provision_coder_lane_keys.sh
#
set -euo pipefail
umask 077

cd /mnt/archie_brain

if ! docker ps --format '{{.Names}}' | grep -qx archie_database; then
  echo "ERROR: archie_database is not running — start it first." >&2
  exit 1
fi

mkdir -p secrets/codex secrets/opencode

# mint <key-name> <dest-file> [read-gid]
#
# read-gid is NOT optional bookkeeping — it is what makes a lane able to open its own
# bearer. A compose file-secret is BIND-MOUNTED, so the container sees this file's
# owner and mode; the opencode lane runs as uid 1000 and cannot read a root:root 0600
# file. Passing a gid writes root:<gid> 0640 instead: root still owns it, that one
# group may READ it, nobody may write it. Omit the arg for a lane that runs as root
# (codex), which needs no grant.
mint() {
  local name="$1" dest="$2" read_gid="${3:-}" tok hash prefix
  tok="archie-mcp-$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
  hash="$(printf '%s' "$tok" | sha256sum | cut -d' ' -f1)"
  prefix="${tok:0:16}"   # mcp_api_keys.key_prefix is varchar(16) — longer WILL error

  # Replace by name so a re-run cannot leave two live rows for one lane.
  docker exec -i archie_database psql -U archie -d archie -v ON_ERROR_STOP=1 -q <<SQL
DELETE FROM mcp_api_keys WHERE name = '${name}';
INSERT INTO mcp_api_keys (key_hash, key_prefix, name, description, permissions, is_active)
VALUES ('${hash}', '${prefix}', '${name}',
        'Coder lane full-access bearer (read+write, NO admin) - provisioned $(date -Iseconds)',
        '["read","write"]'::jsonb, TRUE);
SQL

  # Back up an existing secret before clobbering it — losing the CURRENT bearer with no
  # copy is how a working lane becomes unauthenticated with nothing to roll back to.
  if [ -s "$dest" ]; then
    cp -p "$dest" "${dest}.bak-$(date +%Y%m%d-%H%M%S)"
  fi
  printf '%s\n' "$tok" > "$dest"
  if [ -n "$read_gid" ]; then
    chown "root:${read_gid}" "$dest"
    chmod 640 "$dest"
    echo "  ${name}: wrote ${dest} (root:${read_gid} 640 — readable by that lane's uid, $(wc -c < "$dest") bytes)"
  else
    chmod 600 "$dest"
    echo "  ${name}: wrote ${dest} (mode 600, $(wc -c < "$dest") bytes)"
  fi
}

echo "Minting coder-lane bearers (read+write, no admin)..."
mint codex-full    secrets/codex/mcp_bearer.txt
mint opencode-full secrets/opencode/mcp_bearer.txt 1000   # lane runs as uid/gid 1000

# The old shared key is read-only AND its plaintext leaked into a session transcript.
# Deactivate rather than delete, so it can be re-enabled if a lane is missed.
docker exec -i archie_database psql -U archie -d archie -v ON_ERROR_STOP=1 -q <<'SQL'
UPDATE mcp_api_keys SET is_active = FALSE WHERE name = 'codex-kb-readonly';
SQL
echo "  deactivated old shared key: codex-kb-readonly"

echo
echo "Key table now:"
docker exec archie_database psql -U archie -d archie -c \
  "SELECT id, name, permissions, is_active FROM mcp_api_keys ORDER BY id;"

echo
echo "Tokens were written to the two secret files ONLY — not printed, not logged."
echo "Next: docker compose up -d --build archie_mcp_gateway"
echo "      docker compose restart archie_codex_terminal archie_opencode_terminal"

#!/bin/bash
# /opt/archie-node/repoint.sh <hub_mesh_ip>
# Repoint this node's sync container to a hub, DURABLY and idempotently.
#
# WHY recreate (not restart): the hub URL is a BAKED container env var. A
# `docker restart` does NOT re-read --env-file, so editing config + restart is a
# no-op. We must rm + run. (DR Phase 5b, KB #270232.)
#
# Self-bootstrapping: if /opt/archie-node/sync.env does not exist yet, we extract
# the running container's env into it first — so this works on a node that was
# enrolled with baked -e flags, converting it to the env-file pattern on first run.
set -euo pipefail
NEW_IP="${1:?usage: repoint.sh <hub_mesh_ip e.g. 100.64.0.10 (DR) or 100.64.0.4 (hub)>}"
ENVF=/opt/archie-node/sync.env
C=archie_outpost_sync

if ! docker inspect "$C" >/dev/null 2>&1; then
  echo "ERROR: container $C not found on this node" >&2; exit 1
fi

# Bootstrap sync.env from the running container if missing
if [[ ! -f "$ENVF" ]]; then
  docker inspect "$C" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -E '^(NODE_ID|HUB_URL|HUB_API_KEY|NODE_TYPE|HEARTBEAT_INTERVAL|SYNC_POLL_INTERVAL|OLLAMA_HOST)=' \
    > "$ENVF"
  chmod 600 "$ENVF"
  echo "bootstrapped $ENVF from running container"
fi

# Point HUB_URL at the requested hub
if grep -qE '^HUB_URL=' "$ENVF"; then
  sed -i -E "s#^HUB_URL=http://[0-9.]+:3000#HUB_URL=http://${NEW_IP}:3000#" "$ENVF"
else
  echo "HUB_URL=http://${NEW_IP}:3000" >> "$ENVF"
fi

# Capture run params from the existing container so the recreate is faithful
IMG=$(docker inspect "$C" --format '{{.Config.Image}}')
NET=$(docker inspect "$C" --format '{{.HostConfig.NetworkMode}}')

docker rm -f "$C" >/dev/null 2>&1 || true
docker run -d --name "$C" --network "$NET" --restart unless-stopped \
  -w /app --add-host host.docker.internal:host-gateway --env-file "$ENVF" \
  -v /opt/archie-node/node_sync.py:/app/node_sync.py:ro "$IMG" \
  sh -c "pip install --no-cache-dir requests psycopg2-binary --quiet && python3 -u node_sync.py" >/dev/null

echo "repointed -> http://${NEW_IP}:3000  (container $C recreated; img=$IMG net=$NET)"
grep '^HUB_URL=' "$ENVF"

"""Fleet Command — Node routes (merged from Starbase + Starship)

Admin node management (from Starbase) + user-facing node management (from Starship).
"""

import base64
import hashlib
from hmac import compare_digest
import json
import os
import subprocess
import time
import logging
from flask import jsonify, request, Response, send_file
from flask_login import current_user
from rbac import require_permission, Permission
import psycopg2
from database import get_db_cursor
import requests

import ipaddress

from .fleet_helpers import (
    DEFAULT_NODE_PORT,
    DEFAULT_CLIENT_VERSION,
    LATEST_CLIENT_VERSION,
)

from .fleet_helpers import (
    _get_node_for_user,
    _get_node_for_user_by_int_id,
    _compute_node_status,
    LATEST_NODE_VERSION,
    validate_mesh_ip,
    node_inter_cluster_host,
)

logger = logging.getLogger(__name__)


def _valid_inter_cluster_host(v):
    """Validate a node-reported host/IP before it is written to remote_nodes.hostname.

    Rejects values that are NEVER valid inter-cluster addresses so they can't
    poison the row. `mesh_ip` is the canonical dispatch address (ADR-008);
    `hostname` is metadata + the gdnsd glue-record source. Returns the value if
    usable, else None (callers COALESCE None -> keep the existing hostname).

    Rejects: docker container short IDs (12-char hex, historically poisoned
    hostname via X-Forwarded-For), docker-bridge gateways (172.16.0.0/12),
    loopback, link-local, and 0.0.0.0. Allows hostnames (e.g.
    host.docker.internal), public IPs, mesh 100.64.x, and LAN 192.168.x
    (Starships legitimately report their LAN IP). Task #4552.
    """
    import re as _re

    if not isinstance(v, str) or not v:
        return None
    if _re.fullmatch(r"[0-9a-f]{12}", v):
        return None
    try:
        ip = ipaddress.ip_address(v)
    except ValueError:
        return v  # a hostname, not an IP — allow
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return None
    if isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("172.16.0.0/12"):
        return None
    return v


# Path to node client distribution package.
# Inside Docker: /mnt/archie_brain/node_client (bind-mounted from host).
# On host: /mnt/archie_brain/node_client
NODE_CLIENT_DIR = os.environ.get(
    "NODE_CLIENT_DIR",
    "/mnt/archie_brain/node_client",
)


# ============================================================================
# Post-approval orchestration + installer-script generators — STUBS
#
# These 5 functions were referenced inside route handlers but the real
# implementations were never landed in this module (lint baseline flagged
# them all as F821 undefined). Stubbing with placeholder bodies so the
# callers raise a clear RuntimeError instead of NameError. Real bodies
# tracked as a follow-up in Project #243.
# ============================================================================


def _on_node_approved(node_id):
    """Post-approval orchestration for a newly approved fleet node.

    Called from the node approval flow (fleet_node_routes.py line ~1628).
    Wrapped in try/except at the call site so any failure here is logged
    but does not roll back the approval itself.

    Steps:
    1. Load the node row from DB.
    2. Auto-assign agents for each model listed on the node.
    3. Insert a system_notifications entry.
    4. Send a Telegram notification.
    """
    try:
        from database import get_db_cursor
        from services.telegram_service import send_info

        # 1. Load node
        node_name = node_id
        models = []
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT node_name, extra_capabilities FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                row = cur.fetchone()
                if row:
                    node_name = row["node_name"] or node_id
                    caps = row["extra_capabilities"] or {}
                    models = caps.get("ollama_models", [])
        except Exception:
            logger.warning("_on_node_approved: could not load node %s", node_id, exc_info=True)

        # 1b. Copy geo coords from extra_capabilities → latitude/longitude columns
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT extra_capabilities FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                row = cur.fetchone()
                if row:
                    caps = row["extra_capabilities"] or {}
                    geo_lat = caps.get("geo_lat")
                    geo_lon = caps.get("geo_lon")
                    if geo_lat is not None and geo_lon is not None:
                        with get_db_cursor(commit=True) as (conn2, cur2):
                            cur2.execute(
                                """
                                UPDATE remote_nodes
                                   SET latitude = %s, longitude = %s
                                 WHERE node_id = %s
                                   AND (latitude IS NULL OR longitude IS NULL)
                                """,
                                (float(geo_lat), float(geo_lon), node_id),
                            )
        except Exception:
            logger.warning(
                "_on_node_approved: geo-coord sync failed for node=%s",
                node_id,
                exc_info=True,
            )

        # 2. Auto-assign agents for each model (best-effort)
        assigned = 0
        for model_name in models:
            try:
                from services.agent_service import auto_assign_agents_for_model

                auto_assign_agents_for_model(node_id, model_name)
                assigned += 1
            except Exception:
                logger.warning(
                    "_on_node_approved: auto_assign failed for node=%s model=%s",
                    node_id,
                    model_name,
                    exc_info=True,
                )

        # 3. System notification
        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO system_notifications
                        (title, message, notification_type, is_read, created_at)
                    VALUES (%s, %s, 'info', false, NOW())
                    """,
                    (
                        f"Node approved: {node_name}",
                        f"Fleet node {node_name} ({node_id}) approved. "
                        f"{assigned} model(s) processed for agent assignment.",
                    ),
                )
        except Exception:
            logger.warning("_on_node_approved: system_notifications insert failed", exc_info=True)

        # 4. Telegram
        try:
            send_info(f"✅ *Node approved:* `{node_name}`\n" f"ID: `{node_id}`\n" f"Models processed: {assigned}")
        except Exception:
            logger.warning("_on_node_approved: Telegram notify failed", exc_info=True)

        logger.info("_on_node_approved(%s) complete — %d model(s) processed", node_id, assigned)

    except Exception:
        logger.exception("_on_node_approved(%s) unexpected error", node_id)


def _generate_powershell_installer(hub_url: str, node_id: str, token: str) -> str:
    """Return a PowerShell installer script for Windows node onboarding."""
    return _generate_setup_ps1(hub_url, node_id, token, node_name=node_id)


def _generate_bash_installer(hub_url: str, node_id: str, token: str) -> str:
    """Return a Bash installer script for Linux/macOS node onboarding."""
    return _generate_setup_sh(hub_url, node_id, token, node_name=node_id)


def _generate_setup_ps1(hub_url: str, node_id: str, token: str, node_name: str) -> str:
    """Return a self-contained PowerShell node setup script.

    Reads deploy-node.ps1 from NODE_CLIENT_DIR and embeds it as base64 so the
    generated script needs no hub connectivity to fetch the deployment logic.
    Falls back to a runtime Invoke-WebRequest if the file is not on disk.
    """
    _node_client_dir = os.environ.get("NODE_CLIENT_DIR", "/mnt/archie_brain/node_client")
    _ps1_path = os.path.join(_node_client_dir, "deploy-node.ps1")
    try:
        with open(_ps1_path, "rb") as _f:
            _encoded = base64.b64encode(_f.read()).decode("ascii")
        _embed_block = (
            'Write-Host "Extracting embedded deploy script..." -ForegroundColor Cyan\n'
            f'$EncodedScript = "{_encoded}"\n'
            "[System.Text.Encoding]::UTF8.GetString("
            "[System.Convert]::FromBase64String($EncodedScript)"
            ') | Out-File -FilePath "deploy-node.ps1" -Encoding UTF8'
        )
    except (FileNotFoundError, IOError) as _err:
        logging.warning(
            "deploy-node.ps1 not found at %s (%s) — falling back to hub download in generated script",
            _ps1_path,
            _err,
        )
        _embed_block = (
            'Write-Host "WARNING: Embedded script unavailable — downloading from hub..." -ForegroundColor Yellow\n'
            'Invoke-WebRequest -Uri "$HubUrl/tools/department-hq/api/nodes/deploy-node.ps1" '
            '-OutFile "deploy-node.ps1" -UseBasicParsing'
        )
    return f"""# A.R.C.H.I.E. Starship Node — Auto Setup
# Generated for: {node_name} ({node_id})
$ErrorActionPreference = "Stop"
$HubUrl = "{hub_url}"
$NodeId = "{node_id}"
$HubApiKey = "{token}"
$InstallDir = "C:\\archie-node"

Write-Host "" ; Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  A.R.C.H.I.E. Starship Node Setup" -ForegroundColor Cyan
Write-Host "  Node: $NodeId" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan ; Write-Host ""

if (-not (Test-Path $InstallDir)) {{ New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null }}
Set-Location $InstallDir

{_embed_block}

Write-Host "Running deployment..." -ForegroundColor Cyan
Set-ExecutionPolicy Bypass -Scope Process -Force
& ".\\deploy-node.ps1" -Fresh -NodeId $NodeId -HubUrl $HubUrl -HubApiKey $HubApiKey

Write-Host "" ; Write-Host "Setup complete! Node $NodeId is pending admin approval." -ForegroundColor Green
"""


def _generate_setup_sh(
    hub_url: str,
    node_id: str,
    token: str,
    node_name: str,
    headscale_authkey: str = "",
    mesh_ip: str = "",
    hub_mesh_url: str = "http://100.64.0.4:3000",
    deployment_mode: str = "starship",
) -> str:
    """Return a self-contained Bash node setup script.

    Two-phase URL architecture (user-mandated, 2026-05-25):
    - hub_url:       Public URL used only for the banner comment.
                     The one-liner curl that downloads THIS script must use
                     the public URL so unenrolled VPS can reach it.
    - hub_mesh_url:  Headscale mesh URL (http://100.64.0.4:3000) used for
                     ALL hub API calls inside the script.  Steps 5-9 run
                     AFTER Headscale enrollment so mesh is reachable.
                     Per DHQ mesh-routing mandate (KB #263641).

    Script steps:
    1. Install Docker (get.docker.com convenience script).
    2. Install Tailscale.
    3. Join Headscale mesh via https://mesh.kytranempowerment.com.
    4. Auto-discover mesh IP via `tailscale ip -4` (3 retries, 5s sleep).
       Falls back to admin-provided mesh_ip env var if discovery fails.
    5. Register mesh IP with hub via POST /mesh-ip (mesh URL).
    6. Write /opt/archie-node/.env (HUB_URL + BRIDGE_URL = mesh URL).
    7. Apply UFW firewall rules (22/80/443 open, Ollama 11434 mesh-only).
    8. Create shared archie-outpost_archie_net Docker network for Caddy.
    9. Download docker-compose.node.yml from hub (mesh URL) and start stack.
    """
    headscale_login_server = "https://mesh.kytranempowerment.com"
    safe_name = node_name.replace('"', "").replace("'", "")
    _is_satellite = deployment_mode == "satellite"
    _is_outpost = deployment_mode in ("starbase_outpost", "outpost")

    # Satellite: minimal enrollment — Tailscale only, no Docker, no Ollama.
    if _is_satellite:
        authkey_line = f"  --authkey={headscale_authkey} \\\n" if headscale_authkey else ""
        return f"""#!/usr/bin/env bash
# ARCHIE Satellite Enrollment — {safe_name}
# Node: {node_id}
# Lightweight: Headscale mesh join + hub registration. No Docker or Ollama required.
set -e
echo "==> [1/4] Install Tailscale"
curl -fsSL https://tailscale.com/install.sh | sudo sh
echo "==> [2/4] Join Headscale mesh"
sudo tailscale up \\
  --login-server={headscale_login_server} \\
{authkey_line}  --accept-routes \\
  --hostname={node_id}
echo "==> [3/4] Discover mesh IP"
MESH_IP=""
for i in 1 2 3; do
  MESH_IP=$(tailscale ip -4 2>/dev/null || true)
  [ -n "$MESH_IP" ] && break
  sleep 5
done
[ -z "$MESH_IP" ] && MESH_IP="${{MESH_IP_OVERRIDE:-}}"
echo "==> [4/4] Register with hub"
curl -s -X POST {hub_mesh_url}/tools/department-hq/api/nodes/{node_id}/mesh-ip \\
  -H "Content-Type: application/json" \\
  -d '{{"mesh_ip": "'"$MESH_IP"'", "token": "{token}"}}'
echo ""
echo "Satellite '{safe_name}' enrolled. Mesh IP: $MESH_IP"
echo "Approve in Fleet tab: {hub_url}/tools/department-hq#fleet"
"""

    # For starship nodes: pre-load docker-compose.node.yml from disk and embed
    # it as a bash heredoc in step 9 so the compose file is bundled in the
    # setup script — no post-enrollment OTA fetch required (Fix T2930).
    _compose_content = None
    if not _is_outpost:
        _node_client_dir = os.environ.get("NODE_CLIENT_DIR", "/mnt/archie_brain/node_client")
        _compose_path = os.path.join(_node_client_dir, "docker-compose.node.yml")
        try:
            with open(_compose_path, "r") as _cf:
                _compose_content = _cf.read().rstrip("\n")
        except (FileNotFoundError, IOError) as _err:
            logging.warning(
                "docker-compose.node.yml not found at %s (%s) — starship step 9 will OTA download",
                _compose_path,
                _err,
            )

    # Pre-compute step 9 bash block — outpost (VPS/CPU) vs starship (LAN/GPU).
    # Inference on these outpost nodes routes through department_dispatcher →
    # ensure_model_ready → node Ollama service; the bash commands below install
    # the Ollama *daemon* on the remote VPS (not a platform-level inference call).
    if _is_outpost:
        _step9 = r"""# ── 9. archie-node agent stack (VPS/outpost mode) ──────────────────────────
info "Step 9/9 — Installing archie-node agent stack (CPU/outpost mode)..."
# Inference later routes through department_dispatcher + ensure_model_ready.
# These steps only install the Ollama service and pull base models on the VPS.
NODE_OLLAMA_PORT=11434

# 9a. Install Ollama natively on VPS host (CPU inference, no GPU)
OLLAMA_BIN="$(command -v ollama 2>/dev/null || echo /usr/local/bin/ollama)"
if "$OLLAMA_BIN" --version &>/dev/null 2>&1; then
  ok "Ollama already present ($($OLLAMA_BIN --version 2>/dev/null | head -1))"
else
  info "Installing Ollama (native, CPU-only)..."
  OLLAMA_INSTALL_URL="https://ollama.ai/install.sh"
  curl -fsSL "$OLLAMA_INSTALL_URL" | sh
  OLLAMA_BIN="$(command -v ollama)"
  systemctl enable ollama
fi
# Always bind to all interfaces — required whether Ollama was just installed
# or was already present. Docker sync agent reaches it via host.docker.internal:11434.
mkdir -p /etc/systemd/system/ollama.service.d
printf '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0"\n' \
  > /etc/systemd/system/ollama.service.d/override.conf
systemctl daemon-reload
systemctl restart ollama 2>/dev/null || systemctl start ollama
sleep 3
ok "Ollama configured and running (bound to 0.0.0.0:${NODE_OLLAMA_PORT})"

# 9b. Pull CPU-compatible models for outpost agents
# department_dispatcher uses ensure_model_ready which references these models.
info "Pulling qwen2.5:1.5b (primary model ~1.3 GB, may take 3-5 min)..."
"$OLLAMA_BIN" pull qwen2.5:1.5b \
  && ok "Pulled qwen2.5:1.5b" \
  || warn "Pull failed — retried on first dispatch via ensure_model_ready"
info "Pulling nomic-embed-text (~274 MB)..."
"$OLLAMA_BIN" pull nomic-embed-text \
  && ok "Pulled nomic-embed-text" \
  || warn "nomic-embed-text pull failed (non-fatal)"

# 9c. Download archie-node VPS stack files from hub (Headscale mesh)
info "Downloading archie-node VPS stack files from hub..."
for FILE in docker-compose.vps.yml Dockerfile.node node_api.py node_sync.py requirements.txt; do
  HUB_FILE_URL="$HUB_URL/tools/department-hq/api/nodes/vps/$FILE"
  curl -fsSL "$HUB_FILE_URL" -o "$INSTALL_DIR/$FILE" --max-time 60 \
    && ok "  $FILE" \
    || warn "  $FILE — download failed (check mesh reachability)"
done

# 9d. Start node_api container (handles skill dispatch + OTA from hub)
info "Building and starting archie_node_api..."
cd "$INSTALL_DIR"
docker compose -f docker-compose.vps.yml up -d --build \
  && ok "archie_node_api started on port 3001" \
  || warn "node_api start failed — check: docker logs archie_node_api"
cd -

# 9e. Start heartbeat/sync agent (python:3.11-slim, no custom Dockerfile needed)
info "Starting archie_outpost_sync heartbeat agent..."
docker stop archie_outpost_sync 2>/dev/null || true
docker rm   archie_outpost_sync 2>/dev/null || true
docker run -d --name archie_outpost_sync \
  --restart unless-stopped \
  -e NODE_ID="$NODE_ID" \
  -e HUB_URL="$HUB_URL" \
  -e DR_HUB_URL="http://100.64.0.10:3000" \
  -e HUB_API_KEY="$HUB_API_KEY" \
  -e NODE_TYPE=outpost \
  -e HEARTBEAT_INTERVAL=60 \
  -e SYNC_POLL_INTERVAL=60 \
  -e OLLAMA_HOST="http://host.docker.internal:${NODE_OLLAMA_PORT}" \
  --add-host host.docker.internal:host-gateway \
  --memory 128m --cpus 0.25 \
  -v "$INSTALL_DIR/node_sync.py":/app/node_sync.py:ro \
  --network archie-outpost_archie_net \
  -w /app \
  python:3.11-slim sh -c "pip install --no-cache-dir requests psycopg2-binary --quiet && python3 -u node_sync.py" \
  && ok "archie_outpost_sync started (heartbeats every 60 s)" \
  || warn "sync agent failed — check: docker logs archie_outpost_sync"

# 9f. Mesh-only firewall for node_api :3001 (KB #278720). A UFW allow does NOT
# protect Docker-published ports — Docker bypasses UFW — so :3001 would stay
# reachable (unauthenticated) from the public internet. Install the boot-persistent
# DOCKER-USER rule (allows mesh/loopback/bridge, drops public). Fail-soft: a
# firewall hiccup never aborts enrollment.
if command -v ufw &>/dev/null; then
  ufw allow from 100.64.0.0/10 to any port 3001 comment 'Mesh->NodeAPI' 2>/dev/null || true
fi
info "Installing node_api :3001 mesh-only firewall (DOCKER-USER)..."
for FW in nodeapi-mesh-firewall.sh archie-nodeapi-firewall.service; do
  curl -fsSL "$HUB_URL/tools/department-hq/api/nodes/vps/$FW" -o "$INSTALL_DIR/$FW" --max-time 30 \
    && ok "  $FW" \
    || warn "  $FW — download failed (firewall NOT applied — install manually)"
done
if [ -f "$INSTALL_DIR/nodeapi-mesh-firewall.sh" ]; then
  chmod +x "$INSTALL_DIR/nodeapi-mesh-firewall.sh"
  cp "$INSTALL_DIR/archie-nodeapi-firewall.service" /etc/systemd/system/archie-nodeapi-firewall.service 2>/dev/null || true
  systemctl daemon-reload 2>/dev/null || true
  systemctl enable --now archie-nodeapi-firewall 2>/dev/null \
    && ok "node_api :3001 mesh-firewalled (public internet blocked)" \
    || warn "firewall enable failed — run: $INSTALL_DIR/nodeapi-mesh-firewall.sh"
fi"""
        _next_steps = """\
  1. Approve at https://platform.kytranempowerment.com
     → Department HQ → Fleet tab → approve this node
  2. Node sends heartbeats every 60 s — status flips online automatically
  3. DHQ dispatcher will delegate agent work to this node"""
    else:
        if _compose_content is not None:
            # Embed docker-compose.node.yml as a quoted bash heredoc so the
            # compose file is bundled in the script — no OTA curl needed.
            # Quoted 'COMPOSE_EOF' preserves all ${VAR} refs for docker-compose.
            _step9 = (
                "# ── 9. Write and start archie-node stack"
                " ────────────────────────────────\n"
                'info "Step 9/9 — Writing archie-node stack files (compose embedded)..."\n'
                "for FILE in Dockerfile.node node_api.py node_sync.py requirements.txt; do\n"
                '  curl -fsSL "$HUB_URL/tools/department-hq/api/nodes/vps/$FILE" \\\n'
                '    -o "$INSTALL_DIR/$FILE" --max-time 60 \\\n'
                '    && ok "  $FILE" \\\n'
                '    || warn "  $FILE — download failed (non-fatal, check mesh reachability)"\n'
                "done\n"
                "\n"
                "# Write embedded docker-compose.yml (no OTA download required)\n"
                "cat > \"$INSTALL_DIR/docker-compose.yml\" << 'COMPOSE_EOF'\n"
                + _compose_content
                + "\nCOMPOSE_EOF\n"
                + 'ok "  docker-compose.yml (embedded)"\n'
                + "\n"
                + 'info "Starting archie-node stack..."\n'
                + 'cd "$INSTALL_DIR"\n'
                + "docker compose up -d --build \\\n"
                + '  && ok "archie-node stack started" \\\n'
                + '  || warn "Stack start failed — check: docker compose logs in $INSTALL_DIR"\n'
                + "cd -"
            )
        else:
            # Fallback: OTA download (original behaviour, used if compose file
            # is not present in NODE_CLIENT_DIR on the hub at generation time).
            _step9 = r"""# ── 9. Download and start archie-node stack ────────────────────────────────
info "Step 9/9 — Downloading archie-node stack files from hub..."
for FILE in Dockerfile.node node_api.py node_sync.py requirements.txt; do
  curl -fsSL "$HUB_URL/tools/department-hq/api/nodes/vps/$FILE" \
    -o "$INSTALL_DIR/$FILE" --max-time 60 \
    && ok "  $FILE" \
    || warn "  $FILE — download failed (non-fatal, check mesh reachability)"
done
curl -fsSL "$HUB_URL/tools/department-hq/api/nodes/docker-compose.node.yml" \
  -o "$INSTALL_DIR/docker-compose.yml" \
  --max-time 30 && ok "  docker-compose.yml" \
  || warn "  docker-compose.yml — download failed"

info "Starting archie-node stack..."
cd "$INSTALL_DIR"
docker compose up -d --build \
  && ok "archie-node stack started" \
  || warn "Stack start failed — check: docker compose logs in $INSTALL_DIR"
cd -"""
        _next_steps = """\
  1. Approve at https://platform.kytranempowerment.com
     → Department HQ → Fleet tab → approve this node
  2. Node sends heartbeats every 60s — status flips online automatically
  3. DHQ dispatcher will delegate agent work to this node"""

    return f"""#!/bin/bash
# A.R.C.H.I.E. Outpost Node Setup — {safe_name} ({node_id})
# Downloaded from: {hub_url}
# All hub API calls use Headscale mesh IP (100.64.0.4:3000) per DHQ mandate.
set -euo pipefail

RED='\\033[0;31m'; GREEN='\\033[0;32m'; CYAN='\\033[0;36m'; YELLOW='\\033[0;33m'; NC='\\033[0m'
info()  {{ echo -e "${{CYAN}}[ARCHIE]${{NC}} $*"; }}
ok()    {{ echo -e "${{GREEN}}[  OK  ]${{NC}} $*"; }}
warn()  {{ echo -e "${{YELLOW}}[ WARN ]${{NC}} $*"; }}
err()   {{ echo -e "${{RED}}[ERROR ]${{NC}} $*" >&2; exit 1; }}

# ── Variables ────────────────────────────────────────────────────────────────
# HUB_URL always points to the Headscale mesh IP — reachable after step 3.
HUB_URL="{hub_mesh_url}"
NODE_ID="{node_id}"
HUB_API_KEY="{token}"
NODE_NAME="{safe_name}"
HEADSCALE_AUTHKEY="{headscale_authkey}"
HEADSCALE_LOGIN_SERVER="{headscale_login_server}"
PROVIDED_MESH_IP="{mesh_ip}"
INSTALL_DIR="/opt/archie-node"

echo ""
echo "============================================"
echo "  A.R.C.H.I.E. Outpost Node Setup"
echo "  Node : $NODE_NAME"
echo "  ID   : $NODE_ID"
echo "  Hub  : $HUB_URL (mesh)"
echo "============================================"
echo ""

# ── 0. Wait for dpkg lock (Ubuntu 24.04 fresh VPS runs unattended-upgrades) ──
info "Step 0 — Waiting for dpkg lock to clear..."
for _i in $(seq 1 20); do
  if ! fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then break; fi
  info "dpkg locked by another process — waiting 10s (${{_i}}/20)..."
  sleep 10
done
# If still locked after 200s, force-clear (common on Hostinger Ubuntu 24.04)
if fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; then
  warn "dpkg lock still held — stopping unattended-upgrades and clearing lock..."
  systemctl stop unattended-upgrades apt-daily.service apt-daily-upgrade.service 2>/dev/null || true
  rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock
  dpkg --configure -a 2>/dev/null || true
fi
ok "dpkg ready"

# ── 1. Docker ───────────────────────────────────────────────────────────────
info "Step 1/9 — Docker..."
if ! command -v docker &>/dev/null; then
  info "Installing Docker via get.docker.com..."
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
  ok "Docker installed"
else
  ok "Docker already present ($(docker --version | cut -d' ' -f3 | tr -d ','))"
fi

# ── 2. Tailscale ────────────────────────────────────────────────────────────
info "Step 2/9 — Tailscale..."
if ! command -v tailscale &>/dev/null; then
  info "Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
  ok "Tailscale installed"
else
  ok "Tailscale already present"
fi

# ── 3. Join Headscale mesh ─────────────────────────────────────────────────
info "Step 3/9 — Headscale mesh join..."
if [ -n "$HEADSCALE_AUTHKEY" ]; then
  info "Joining mesh at $HEADSCALE_LOGIN_SERVER..."
  tailscale up \\
    --login-server="$HEADSCALE_LOGIN_SERVER" \\
    --auth-key="$HEADSCALE_AUTHKEY" \\
    --hostname="$NODE_NAME" \\
    --accept-routes \\
    --reset || true
  ok "Joined Headscale mesh"
else
  warn "No Headscale auth key provided — skipping mesh join (manual enroll required)"
fi

# ── 4. Discover mesh IP ─────────────────────────────────────────────────────
info "Step 4/9 — Discovering mesh IP..."
MESH_IP=""
for i in $(seq 1 12); do
  MESH_IP=$(tailscale ip -4 2>/dev/null | head -1 || true)
  [ -n "$MESH_IP" ] && break
  info "Retry $i/12 — waiting 5s for mesh IP..."
  sleep 5
done
if [ -z "$MESH_IP" ] && [ -n "$PROVIDED_MESH_IP" ]; then
  warn "tailscale ip -4 empty — using admin-provided IP: $PROVIDED_MESH_IP"
  MESH_IP="$PROVIDED_MESH_IP"
fi
if [ -z "$MESH_IP" ]; then
  err "Could not determine mesh IP. Ensure Headscale enrollment succeeded or provide mesh_ip at enrollment."
fi
ok "Mesh IP: $MESH_IP"

# ── 5. Register mesh IP with hub ────────────────────────────────────────────
info "Step 5/9 — Registering mesh IP with hub (via mesh)..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{{http_code}}" \\
  -X POST "$HUB_URL/tools/department-hq/api/nodes/$NODE_ID/mesh-ip" \\
  -H "Content-Type: application/json" \\
  -H "X-Node-API-Key: $HUB_API_KEY" \\
  -d "{{\\"mesh_ip\\": \\"$MESH_IP\\"}}" \\
  --max-time 15)
if [ "$HTTP_STATUS" = "200" ] || [ "$HTTP_STATUS" = "204" ]; then
  ok "Mesh IP registered with hub"
else
  warn "mesh-ip registration returned HTTP $HTTP_STATUS — hub will discover on first heartbeat"
fi

# ── 6. Write node .env ──────────────────────────────────────────────────────
info "Step 6/9 — Writing $INSTALL_DIR/.env..."
mkdir -p "$INSTALL_DIR"
cat > "$INSTALL_DIR/.env" <<ENV
# A.R.C.H.I.E. Outpost Node — generated by fleet enrollment $(date -u +%Y-%m-%dT%H:%M:%SZ)
# DO NOT EDIT manually — managed by hub fleet enrollment
HUB_URL=$HUB_URL
BRIDGE_URL=$HUB_URL
NODE_ID=$NODE_ID
HUB_API_KEY=$HUB_API_KEY
MESH_IP=$MESH_IP
NODE_NAME=$NODE_NAME
ENV
ok ".env written"

# ── 7. UFW firewall rules ────────────────────────────────────────────────────
info "Step 7/9 — Configuring UFW firewall..."
if command -v ufw &>/dev/null; then
  ufw allow 22    comment 'SSH'  2>/dev/null || true
  ufw allow 80    comment 'HTTP/Caddy'  2>/dev/null || true
  ufw allow 443   comment 'HTTPS/Caddy' 2>/dev/null || true
  # Ollama: restrict to Docker bridge + Headscale mesh only (KB #265604)
  ufw allow from 172.0.0.0/8   to any port 11434 comment 'Docker→Ollama' 2>/dev/null || true
  ufw allow from 100.64.0.0/10 to any port 11434 comment 'Mesh→Ollama'   2>/dev/null || true
  ufw --force enable 2>/dev/null || true
  ok "UFW rules applied"
else
  warn "UFW not installed — skipping firewall setup"
fi

# ── 8. Docker network for Caddy ─────────────────────────────────────────────
info "Step 8/9 — Creating shared Caddy Docker network..."
if docker network inspect archie-outpost_archie_net &>/dev/null; then
  ok "Network archie-outpost_archie_net already exists"
else
  docker network create archie-outpost_archie_net
  ok "Network archie-outpost_archie_net created"
fi

{_step9}

echo ""
echo "============================================"
echo "  ✓  Enrollment complete!"
echo ""
echo "  Node   : $NODE_NAME"
echo "  ID     : $NODE_ID"
echo "  Mesh   : $MESH_IP"
echo "  Status : Pending admin approval"
echo ""
echo "  Next steps:"
echo "{_next_steps}"
echo "============================================"
echo ""
"""


def register_node_routes(bp, login_required, admin_required):  # noqa: F811
    """Register node-related routes on the fleet blueprint."""

    # ============================================================================
    # REMOTE NODES API - Phase 29
    # ============================================================================

    import secrets  # noqa: E402 (hashlib already imported at top)

    def generate_node_id():
        """Generate a unique node ID"""
        return f"node_{secrets.token_hex(8)}"

    def hash_api_key(api_key):
        """Hash an API key for storage"""
        return hashlib.sha256(api_key.encode()).hexdigest()

    def verify_api_key(api_key, stored_hash):
        """Verify an API key against stored hash (constant-time comparison)"""
        return compare_digest(hash_api_key(api_key), stored_hash)

    def detect_network_type(hostname_or_ip):
        """Detect if a node is local (LAN) or external based on its IP/hostname."""
        if not hostname_or_ip:
            return "local"
        try:
            addr = ipaddress.ip_address(hostname_or_ip)
            return "local" if addr.is_private else "external"
        except ValueError:
            # Not a bare IP — could be a hostname
            # Treat common LAN patterns as local
            lower = hostname_or_ip.lower()
            if lower in ("localhost", "127.0.0.1", "::1"):
                return "local"
            if lower.endswith(".local") or lower.endswith(".lan"):
                return "local"
            return "external"

    # NOTE: served at /api/nodes/all — the bare /api/nodes is owned by
    # fleet_dashboard_routes.api_list_nodes (user-scoped, account-center). This is
    # the ALL-nodes admin/fleet view (with summary). Previously both claimed
    # /api/nodes and this one was shadowed/dead (route collision). Distinct path
    # de-collides them; the Fleet/ARMADA tab uses /api/fleet-map, not this.
    @bp.route("/api/nodes/all")
    @login_required
    @admin_required
    def get_all_nodes():
        """Get all registered remote nodes (admin/fleet, unscoped). Admin-only —
        unscoped cluster listing; non-admins use the user-scoped /api/nodes."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                status_filter = request.args.get("status", "all")
                approval_filter = request.args.get("approval", "all")
                active_only = request.args.get("active", "true").lower() == "true"

                query = """
                    SELECT rn.id, rn.node_id, rn.node_name, rn.description, rn.vpn_ip, rn.hostname, rn.port,
                           rn.status, rn.last_heartbeat, rn.last_error, rn.error_count,
                           rn.client_version, rn.gpu_available, rn.gpu_model, rn.gpu_vram_gb,
                           rn.cpu_cores, rn.cpu_model, rn.ram_gb, rn.disk_gb, rn.os_info, rn.ollama_available,
                           rn.priority, rn.weight, rn.max_concurrent, rn.current_load,
                           rn.total_requests, rn.successful_requests, rn.failed_requests, rn.avg_latency_ms,
                           rn.tags, rn.is_active, rn.created_at, rn.updated_at,
                           rn.approval_status, rn.approved_by, rn.approved_at,
                           rn.bridge_enabled, rn.bridge_priority, rn.last_model_sync,
                           rn.network_type, rn.ssh_enabled, rn.ssh_enabled_at,
                           rn.mesh_ip, rn.mesh_status, rn.mesh_connection_type,
                           rn.mesh_latency_ms, rn.mesh_last_seen,
                           o.name AS org_name, o.id AS org_id,
                           u.username AS approved_by_name
                    FROM remote_nodes rn
                    LEFT JOIN organizations o ON o.node_id = rn.node_id
                    LEFT JOIN users u ON u.id = rn.approved_by
                    WHERE 1=1
                """
                params = []

                if active_only:
                    query += " AND rn.is_active = TRUE"

                if status_filter != "all":
                    query += " AND rn.status = %s"
                    params.append(status_filter)

                if approval_filter != "all":
                    query += " AND rn.approval_status = %s"
                    params.append(approval_filter)

                query += " ORDER BY CASE rn.approval_status WHEN 'pending' THEN 0 ELSE 1 END, rn.priority, rn.node_name"

                cur.execute(query, params)
                nodes = cur.fetchall()

                # Get summary stats including approval counts
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'online' AND approval_status = 'approved') as online,
                        COUNT(*) FILTER (WHERE status = 'offline' AND approval_status = 'approved') as offline,
                        COUNT(*) FILTER (WHERE status = 'degraded' AND approval_status = 'approved') as degraded,
                        COUNT(*) FILTER (WHERE approval_status = 'pending') as pending,
                        COUNT(*) FILTER (WHERE approval_status = 'approved') as approved,
                        COUNT(*) FILTER (WHERE approval_status = 'rejected') as rejected,
                        SUM(current_load) FILTER (WHERE approval_status = 'approved') as total_load,
                        SUM(max_concurrent) FILTER (WHERE approval_status = 'approved') as total_capacity
                    FROM remote_nodes
                    WHERE is_active = TRUE
                """
                )
                summary = cur.fetchone()

                # Convert datetime
                for node in nodes:
                    for key in [
                        "last_heartbeat",
                        "created_at",
                        "updated_at",
                        "approved_at",
                        "mesh_last_seen",
                    ]:
                        if node.get(key):
                            node[key] = node[key].isoformat()

                return jsonify({"success": True, "nodes": nodes, "summary": summary})

        except Exception as e:
            logger.error(f"Error getting nodes: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/model-recommendation")
    @login_required
    def get_node_model_recommendation(node_id):
        """Hardware-aware model plan for an EXISTING node (#3731).

        Reads the node's heartbeat-reported hardware from remote_nodes and
        returns what Ollama + ComfyUI models it can/can't run + a warm set to
        pull. Powers the +Add Node wizard and the node detail panel.
        """
        try:
            from services.node_provisioning import recommend_from_node_row

            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    "SELECT node_id, node_name, cpu_cores, ram_gb, gpu_available, "
                    "gpu_vram_gb, gpu_model FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                row = cur.fetchone()
            if not row:
                return jsonify({"success": False, "error": "Node not found"}), 404
            rec = recommend_from_node_row(row)
            return jsonify(
                {
                    "success": True,
                    "node_id": row["node_id"],
                    "node_name": row.get("node_name"),
                    "hardware": {
                        "cpu_cores": row.get("cpu_cores"),
                        "ram_gb": row.get("ram_gb"),
                        "gpu_available": row.get("gpu_available"),
                        "gpu_vram_gb": row.get("gpu_vram_gb"),
                        "gpu_model": row.get("gpu_model"),
                    },
                    "recommendation": rec.to_dict(),
                }
            )
        except Exception as e:
            logger.error(f"Error computing node recommendation for {node_id}: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/model-recommendation", methods=["POST"])
    @login_required
    def post_model_recommendation():
        """Hardware-aware model plan for a node that does NOT exist yet (#3731).

        Pre-enrollment preview: the wizard POSTs a hardware profile (or the
        installer auto-detects and posts it) and gets back the can/can't-run
        plan before the node is registered. Body:
          {cpu_cores, ram_gb, gpu_available, gpu_vram_gb, gpu_model}
        """
        try:
            from services.node_provisioning import recommend

            data = request.get_json(silent=True) or {}
            rec = recommend(
                cpu_cores=int(data.get("cpu_cores") or 0),
                ram_gb=float(data.get("ram_gb") or 0.0),
                gpu_available=bool(data.get("gpu_available")),
                gpu_vram_gb=float(data.get("gpu_vram_gb") or 0.0),
                gpu_model=str(data.get("gpu_model") or ""),
            )
            return jsonify({"success": True, "recommendation": rec.to_dict()})
        except (TypeError, ValueError) as e:
            return (
                jsonify({"success": False, "error": f"Invalid hardware payload: {e}"}),
                400,
            )
        except Exception as e:
            logger.error(f"Error computing model recommendation: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/install.sh", methods=["GET"])
    def get_node_install_script():
        """Serve the node installation script"""
        import os

        script_path = "/mnt/archie_brain/node_client/install.sh"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            # Replace placeholder URL with actual server URL
            server_url = request.host_url.rstrip("/")
            script_content = script_content.replace("http://192.168.1.200:3000", server_url)

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="install.sh"',
                },
            )
        else:
            return "Install script not found", 404

    @bp.route("/api/nodes/install.ps1", methods=["GET"])
    def get_node_install_script_windows():
        """Serve the Windows PowerShell installation script"""
        import os

        script_path = "/mnt/archie_brain/node_client/install.ps1"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            # Replace placeholder URL with actual server URL
            server_url = request.host_url.rstrip("/")
            script_content = script_content.replace("http://192.168.1.200:3000", server_url)

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="install.ps1"',
                },
            )
        else:
            return "Install script not found", 404

    @bp.route("/api/nodes/setup-node.ps1", methods=["GET"])
    def get_node_full_setup_script():
        """Serve the full Windows node setup script (WSL2 + Docker + GPU + bootstrap)"""
        script_path = "/mnt/archie_brain/node_client/setup-node.ps1"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()
            server_url = request.host_url.rstrip("/")
            script_content = script_content.replace("http://192.168.1.200:3000", server_url)
            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="setup-node.ps1"',
                },
            )
        return "Setup script not found", 404

    @bp.route("/api/nodes/heartbeat.ps1", methods=["GET"])
    def get_node_heartbeat_script_windows():
        """Serve the Windows PowerShell heartbeat script"""
        import os

        script_path = "/mnt/archie_brain/node_client/heartbeat.ps1"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="heartbeat.ps1"',
                },
            )
        else:
            return "Heartbeat script not found", 404

    @bp.route("/api/nodes/update.ps1", methods=["GET"])
    def get_node_update_script_windows():
        """Serve the Windows PowerShell update script"""
        import os

        script_path = "/mnt/archie_brain/node_client/update.ps1"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            # Replace placeholder URL with actual server URL
            server_url = request.host_url.rstrip("/")
            script_content = script_content.replace("http://192.168.1.200:3000", server_url)

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="update.ps1"',
                },
            )
        else:
            return "Update script not found", 404

    @bp.route("/api/nodes/heartbeat.sh", methods=["GET"])
    def get_node_heartbeat_script_linux():
        """Serve the Linux heartbeat script"""
        import os

        script_path = "/mnt/archie_brain/node_client/heartbeat.sh"

        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()

            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="heartbeat.sh"',
                },
            )
        else:
            return "Heartbeat script not found", 404

    @bp.route("/api/nodes/docker-compose.node.yml", methods=["GET"])
    def get_node_docker_compose():
        """Serve the node Docker Compose template"""
        script_path = "/mnt/archie_brain/node_client/docker-compose.node.yml"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/yaml",
                headers={"Content-Disposition": "attachment; filename=docker-compose.node.yml"},
            )
        return (
            jsonify({"success": False, "error": "Docker Compose template not found"}),
            404,
        )

    @bp.route("/api/nodes/vps/<filename>", methods=["GET"])
    def get_vps_node_file(filename):
        """Serve VPS-specific archie-node stack files for outpost enrollment.

        Called by the generated bash installer script (step 9c) running on the
        outpost VPS after Headscale mesh join. Files are served from node_client/
        on the hub and downloaded via the Headscale mesh URL (100.64.0.4:3000).

        Allowed files mirror what outpost-us runs in /opt/archie-node/:
          docker-compose.vps.yml, Dockerfile.node, node_api.py,
          node_sync.py, requirements.txt
        """
        import mimetypes

        allowed = {
            "docker-compose.vps.yml",
            "Dockerfile.node",
            "node_api.py",
            "node_sync.py",
            "requirements.txt",
            # Mesh-only firewall for node_api :3001 (KB #278720) — served so the
            # outpost enrollment script (step 9f) can install the DOCKER-USER rule.
            "nodeapi-mesh-firewall.sh",
            "archie-nodeapi-firewall.service",
        }
        if filename not in allowed:
            return jsonify({"error": "File not found or not allowed"}), 404

        file_path = os.path.join(NODE_CLIENT_DIR, filename)
        if not os.path.exists(file_path):
            return jsonify({"error": f"{filename} not found on hub"}), 404

        mime = mimetypes.guess_type(filename)[0] or "text/plain"
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()
        return Response(content, mimetype=mime)

    @bp.route("/api/nodes/deploy-node.ps1", methods=["GET"])
    def get_node_deploy_script():
        """Serve the Windows deploy script (no auth needed)"""
        script_path = "/mnt/archie_brain/node_client/deploy-node.ps1"
        if os.path.exists(script_path):
            with open(script_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Replace placeholder URL with actual server URL
            server_url = request.host_url.rstrip("/")
            content = content.replace("http://192.168.1.200:3000", server_url)

            # PowerShell 5.1 on Windows requires CRLF line endings for here-strings.
            # Source file has LF (Linux); normalize to CRLF before serving.
            content = content.replace("\r\n", "\n").replace("\n", "\r\n")

            from flask import Response

            return Response(
                content,
                mimetype="text/plain",
                headers={"Content-Disposition": "attachment; filename=deploy-node.ps1"},
            )
        return jsonify({"success": False, "error": "Deploy script not found"}), 404

    @bp.route("/api/nodes/node_sync.py", methods=["GET"])
    def get_node_sync_service():
        """Serve the node sync service script"""
        script_path = "/mnt/archie_brain/node_client/node_sync.py"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/x-python",
                headers={"Content-Disposition": "attachment; filename=node_sync.py"},
            )
        return (
            jsonify({"success": False, "error": "Sync service script not found"}),
            404,
        )

    @bp.route("/api/nodes/Dockerfile.node", methods=["GET"])
    def get_node_dockerfile():
        """Serve the node Dockerfile"""
        script_path = "/mnt/archie_brain/node_client/Dockerfile.node"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/plain",
                headers={"Content-Disposition": "attachment; filename=Dockerfile.node"},
            )
        return jsonify({"success": False, "error": "Dockerfile.node not found"}), 404

    @bp.route("/api/nodes/node_api.py", methods=["GET"])
    def get_node_api_service():
        """Serve the node API service script"""
        script_path = "/mnt/archie_brain/node_client/node_api.py"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/x-python",
                headers={"Content-Disposition": "attachment; filename=node_api.py"},
            )
        return jsonify({"success": False, "error": "node_api.py not found"}), 404

    @bp.route("/api/nodes/node_triage.py", methods=["GET"])
    def get_node_triage_service():
        """Serve the node triage/diagnostics script"""
        script_path = "/mnt/archie_brain/node_client/node_triage.py"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/x-python",
                headers={"Content-Disposition": "attachment; filename=node_triage.py"},
            )
        return jsonify({"success": False, "error": "node_triage.py not found"}), 404

    @bp.route("/api/nodes/bootstrap-wsl2.sh", methods=["GET"])
    def get_node_bootstrap_wsl2():
        """Serve the WSL2 bootstrap script for Windows GPU nodes"""
        script_path = "/mnt/archie_brain/node_client/bootstrap-wsl2.sh"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                script_content = f.read()
            server_url = request.host_url.rstrip("/")
            script_content = script_content.replace("http://192.168.1.200:3000", server_url)
            return (
                script_content,
                200,
                {
                    "Content-Type": "text/plain; charset=utf-8",
                    "Content-Disposition": 'inline; filename="bootstrap-wsl2.sh"',
                },
            )
        return jsonify({"success": False, "error": "bootstrap-wsl2.sh not found"}), 404

    @bp.route("/api/nodes/installer.py", methods=["GET"])
    def get_gui_installer():
        """Serve the LCARS GUI installer (tkinter, PyInstaller-compatible)"""
        script_path = "/mnt/archie_brain/node_client/installer/archie_node_installer.py"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/x-python",
                headers={"Content-Disposition": "attachment; filename=archie_node_installer.py"},
            )
        return (
            jsonify({"success": False, "error": "GUI installer not found"}),
            404,
        )

    @bp.route("/api/nodes/docker-compose", methods=["GET"])
    def get_docker_compose():
        """Serve the node docker-compose.yml"""
        script_path = "/mnt/archie_brain/node_client/docker-compose.node.yml"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="text/x-yaml",
                headers={"Content-Disposition": "attachment; filename=docker-compose.yml"},
            )
        return (
            jsonify({"success": False, "error": "docker-compose not found"}),
            404,
        )

    @bp.route("/api/nodes/migrations/<filename>", methods=["GET"])
    def get_node_migration(filename):
        """Serve node migration SQL files"""
        import re

        # Sanitize filename — only allow typical migration filenames
        if not re.match(r"^[0-9a-zA-Z_\-]+\.sql$", filename):
            return jsonify({"success": False, "error": "Invalid filename"}), 400
        script_path = f"/mnt/archie_brain/node_client/migrations/{filename}"
        if os.path.exists(script_path):
            with open(script_path, "r") as f:
                content = f.read()
            from flask import Response

            return Response(
                content,
                mimetype="application/sql",
                headers={"Content-Disposition": f"attachment; filename={filename}"},
            )
        return (
            jsonify({"success": False, "error": f"Migration {filename} not found"}),
            404,
        )

    @bp.route("/api/nodes/archie-node-latest.tar.gz", methods=["GET"])
    def serve_node_image():
        """Serve the pre-built node Docker image tarball (legacy fallback)"""
        from flask import send_file

        # Check multiple locations: node_client dir (mounted in container) and /tmp (host builds)
        tarball_paths = [
            "/mnt/archie_brain/node_client/archie-node-latest.tar.gz",
            "/tmp/archie-node-latest.tar.gz",
        ]
        tarball_path = None
        for path in tarball_paths:
            if os.path.isfile(path):
                tarball_path = path
                break
        if tarball_path is None:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Node image not built yet. Nodes now build locally from Dockerfile.node.",
                    }
                ),
                404,
            )
        return send_file(
            tarball_path,
            mimetype="application/gzip",
            as_attachment=True,
            download_name="archie-node-latest.tar.gz",
        )

    @bp.route("/api/nodes/deploy-node.ps1", methods=["GET"])
    def serve_deploy_node_ps1():
        """Serve the deploy-node.ps1 Windows setup script from node_client/."""
        script_path = os.path.join(NODE_CLIENT_DIR, "deploy-node.ps1")
        if not os.path.isfile(script_path):
            return jsonify({"error": "deploy-node.ps1 not found"}), 404
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        # PowerShell 5.1 on Windows requires CRLF line endings for here-strings (@"..."@).
        # The source file has LF endings (Linux); normalize to CRLF before serving.
        content = content.replace("\r\n", "\n").replace("\n", "\r\n")
        return Response(
            content,
            mimetype="text/plain",
            headers={"Content-Disposition": 'inline; filename="deploy-node.ps1"'},
        )

    @bp.route("/api/nodes/install-node.sh", methods=["GET"])
    def serve_install_node_sh():
        """Serve the Linux terminal installer."""
        script_path = "/mnt/archie_brain/node_client/install-node.sh"
        if not os.path.exists(script_path):
            return jsonify({"error": "Installer not found"}), 404
        return send_file(script_path, mimetype="text/x-shellscript")

    @bp.route("/api/nodes/installer.exe", methods=["GET"])
    def serve_installer_exe():
        """Serve the Windows GUI installer."""
        exe_path = "/mnt/archie_brain/node_client/installer/dist/ARCHIE-Node-Setup.exe"
        if not os.path.exists(exe_path):
            return jsonify({"error": "Windows installer not built yet"}), 404
        return send_file(
            exe_path,
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name="ARCHIE-Node-Setup.exe",
        )

    @bp.route("/api/nodes/client-package", methods=["GET"])
    def get_node_client_package():
        """Serve the node client package as a tarball"""
        import os
        import tarfile
        import io

        node_client_dir = "/mnt/archie_brain/node_client"

        if not os.path.exists(node_client_dir):
            return (
                jsonify({"success": False, "error": "Node client package not found"}),
                404,
            )

        try:
            # Create tarball in memory
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tar:
                for filename in os.listdir(node_client_dir):
                    # Skip certain files
                    if filename.startswith(".") and filename not in [".env.example"]:
                        continue
                    if filename == "__pycache__":
                        continue

                    filepath = os.path.join(node_client_dir, filename)
                    if os.path.isfile(filepath):
                        tar.add(filepath, arcname=filename)

            tar_buffer.seek(0)

            return (
                tar_buffer.read(),
                200,
                {
                    "Content-Type": "application/gzip",
                    "Content-Disposition": 'attachment; filename="archie-node-client.tar.gz"',
                },
            )

        except Exception as e:
            logger.error(f"Error creating client package: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    def calculate_max_concurrent(ram_gb: float, cpu_cores: int, gpu_vram_gb: float = 0) -> int:
        """
        Calculate recommended max_concurrent tasks based on hardware.
        Formula:
        - Base: 1 task per 4GB RAM (LLMs need memory)
        - CPU bonus: +1 per 8 cores (parallel processing)
        - GPU bonus: +2 if VRAM >= 8GB, +4 if VRAM >= 16GB (GPU acceleration)
        - Minimum: 2, Maximum: 20
        """
        base = int((ram_gb or 8) / 4)  # 1 per 4GB RAM
        cpu_bonus = int((cpu_cores or 4) / 8)  # +1 per 8 cores
        gpu_bonus = 0
        if gpu_vram_gb:
            if gpu_vram_gb >= 16:
                gpu_bonus = 4
            elif gpu_vram_gb >= 8:
                gpu_bonus = 2

        total = base + cpu_bonus + gpu_bonus
        return max(2, min(20, total))  # Clamp between 2 and 20

    @bp.route("/api/nodes/register", methods=["POST"])
    def register_node():
        """Register a new remote node"""
        data = request.get_json() or {}

        required = ["node_name"]
        for field in required:
            if not data.get(field):
                return jsonify({"success": False, "error": f"{field} is required"}), 400

        # Validate hardware fields if provided
        if "ram_gb" in data and data["ram_gb"] is not None:
            try:
                ram = float(data["ram_gb"])
            except (TypeError, ValueError):
                return (
                    jsonify({"success": False, "error": "ram_gb must be a number"}),
                    400,
                )
            if ram <= 0:
                return (
                    jsonify({"success": False, "error": "ram_gb must be positive"}),
                    400,
                )

        if "cpu_cores" in data and data["cpu_cores"] is not None:
            try:
                cores = int(data["cpu_cores"])
            except (TypeError, ValueError):
                return (
                    jsonify({"success": False, "error": "cpu_cores must be an integer"}),
                    400,
                )
            if cores <= 0:
                return (
                    jsonify({"success": False, "error": "cpu_cores must be positive"}),
                    400,
                )

        try:
            with get_db_cursor() as (conn, cur):

                # Generate node ID and API key
                node_id = generate_node_id()
                api_key = secrets.token_urlsafe(32)
                api_key_hash = hash_api_key(api_key)

                # Auto-detect network type from hostname/IP or request origin.
                # Reject values that are never valid inter-cluster addresses
                # (docker container short IDs, docker-bridge gateways like 172.x,
                # loopback, link-local) from either source — they have
                # historically poisoned remote_nodes.hostname via X-Forwarded-For
                # injection. mesh_ip is the canonical inter-cluster address
                # (ADR-008). Shared guard with the heartbeat handler, #4552.
                node_hostname = _valid_inter_cluster_host(data.get("hostname")) or _valid_inter_cluster_host(
                    request.remote_addr
                )
                network_type = detect_network_type(node_hostname)

                # --- FIX1 (DR identity preservation): reclaim, don't recreate ---
                # A re-registration from hardware the hub already knows MUST refresh the
                # existing row and return its original identity — never mint a new pending
                # node_id. Minting-on-re-register orphaned the entire fleet during the
                # 2026-06-04 DR window (postmortem: .claude/dr-postmortem-and-remediation.md).
                # Reclaim is gated on a VERIFYING api-key (authoritative). A node_id alone is
                # NOT sufficient — it would let an unauthenticated caller refresh node state
                # and probe approval/tier. A known node_id presented without a valid key is
                # rejected below; genuinely-new hardware falls through to enrollment.
                node_id_in = (data.get("node_id") or "").strip()
                incoming_key = request.headers.get("X-Node-API-Key")
                incoming_hash = hash_api_key(incoming_key) if incoming_key else None

                existing = None
                if incoming_hash:
                    cur.execute(
                        """SELECT id, node_id, approval_status, deployment_mode
                           FROM remote_nodes WHERE api_key_hash = %s
                           ORDER BY (approval_status = 'approved') DESC, id ASC
                           LIMIT 1""",
                        (incoming_hash,),
                    )
                    existing = cur.fetchone()

                if existing is not None:
                    cur.execute(
                        """UPDATE remote_nodes
                           SET last_heartbeat = NOW(),
                               is_active = TRUE,
                               hostname = COALESCE(%s, hostname),
                               client_version = COALESCE(%s, client_version)
                           WHERE id = %s
                           RETURNING node_id, approval_status, deployment_mode""",
                        (node_hostname, data.get("client_version"), existing["id"]),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    logger.info(
                        "Re-registration RECLAIM: node %s kept identity " "(status=%s, mode=%s) — no new row minted",
                        row["node_id"],
                        row["approval_status"],
                        row["deployment_mode"],
                    )
                    return (
                        jsonify(
                            {
                                "success": True,
                                "node_id": row["node_id"],
                                # api_key intentionally OMITTED — the node keeps its current
                                # credential. We never rotate on reclaim, which avoids the
                                # persist-race the old path used to lose identity to.
                                "approval_status": row["approval_status"],
                                "reclaimed": True,
                                "config": {
                                    "heartbeat_interval": 30,
                                    "capability_interval": 300,
                                    "log_level": "INFO",
                                },
                                "message": "Existing node identity reclaimed — keep current credentials.",
                            }
                        ),
                        200,
                    )
                # A known node_id presented WITHOUT a verifying api-key must not reclaim,
                # mutate state, or leak approval/tier — reject it. Genuinely-new hardware
                # (no matching node_id) falls through to enrollment below.
                if node_id_in:
                    cur.execute(
                        "SELECT 1 FROM remote_nodes WHERE node_id = %s LIMIT 1",
                        (node_id_in,),
                    )
                    if cur.fetchone():
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "valid api key required to reclaim an existing node",
                                }
                            ),
                            401,
                        )
                # --- end FIX1 reclaim; brand-new hardware falls through to enrollment ---

                # Clean up stale duplicate registrations for this hostname
                if node_hostname:
                    cur.execute(
                        """
                        DELETE FROM remote_nodes
                        WHERE hostname = %s
                          AND approval_status <> 'approved'
                          AND (last_heartbeat IS NULL OR last_heartbeat < NOW() - INTERVAL '24 hours')
                        """,
                        (node_hostname,),
                    )
                    stale_count = cur.rowcount
                    if stale_count:
                        logger.info(
                            "Cleaned up %d stale duplicate(s) for hostname %s",
                            stale_count,
                            node_hostname,
                        )

                cur.execute(
                    """
                    INSERT INTO remote_nodes (
                        node_id, node_name, description, vpn_ip, hostname, port,
                        api_key_hash, client_version, gpu_available, gpu_model,
                        gpu_vram_gb, cpu_cores, cpu_model, ram_gb, disk_gb, os_info,
                        ollama_available, foocus_available, comfyui_available, auto1111_available,
                        docker_available, docker_version, nvidia_docker, wsl_available,
                        foocus_port, comfyui_port, auto1111_port,
                        iaae_compliant, priority, weight, max_concurrent, tags,
                        approval_status, network_type, deployment_mode
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    RETURNING id, node_id, node_name, approval_status
                """,
                    (
                        node_id,
                        data.get("node_name"),
                        data.get("description"),
                        data.get("vpn_ip"),
                        node_hostname,
                        data.get("port", DEFAULT_NODE_PORT),
                        api_key_hash,
                        data.get("client_version", DEFAULT_CLIENT_VERSION),
                        data.get("gpu_available", False),
                        data.get("gpu_model"),
                        data.get("gpu_vram_gb"),
                        data.get("cpu_cores"),
                        data.get("cpu_model"),
                        data.get("ram_gb"),
                        data.get("disk_gb"),
                        data.get("os_info"),
                        data.get("ollama_available", False),
                        data.get("foocus_available", False),
                        data.get("comfyui_available", False),
                        data.get("auto1111_available", False),
                        data.get("docker_available", False),
                        data.get("docker_version"),
                        data.get("nvidia_docker", False),
                        data.get("wsl_available", False),
                        # AI Service ports for dynamic routing (Phase 72)
                        data.get("foocus_port", 7865),
                        data.get("comfyui_port", 8188),
                        data.get("auto1111_port", 7860),
                        data.get("iaae_compliant", True),
                        data.get("priority", 10),
                        data.get("weight", 100),
                        # Smart max_concurrent based on hardware (or use provided value)
                        data.get("max_concurrent")
                        or calculate_max_concurrent(
                            data.get("ram_gb", 8),
                            data.get("cpu_cores", 4),
                            data.get("gpu_vram_gb", 0),
                        ),
                        data.get("tags", []),
                        "pending",  # New nodes start as pending
                        network_type,
                        # FIX1/RC5: set deployment_mode explicitly so a re-enrolling
                        # outpost/starship keeps its tier instead of silently becoming
                        # 'standard' (the DB column default).
                        data.get("deployment_mode") or "standard",
                    ),
                )

                node = cur.fetchone()

                # Alert admin — new node pending approval
                try:
                    node_name = node["node_name"] or node["node_id"]
                    hostname = data.get("hostname", "unknown")
                    cur.execute(
                        """INSERT INTO system_notifications
                           (type, title, message, source, related_action, visibility, created_at)
                           VALUES ('alert', %s, %s, 'starbase', '/tools/starbase#network', 'admin', NOW())""",
                        (
                            f"New Node Pending: {node_name}",
                            f"Node '{node_name}' ({hostname}) registered and awaiting approval. Review in Starbase Network tab.",
                        ),
                    )
                    conn.commit()
                except Exception as e:
                    logger.warning("Failed to create node registration alert: %s", e)

                # Telegram notification for node approval
                try:
                    from ai_bridge.telegram_gateway import get_gateway

                    gw = get_gateway()
                    if gw and gw.is_running:
                        import asyncio

                        msg = f"🛸 *New Node Pending Approval*\n\n*Name:* {node_name}\n*Host:* {hostname}\n*ID:* {node['node_id']}"
                        buttons = [
                            [
                                {
                                    "text": "✅ Approve",
                                    "callback_data": f"node_approve_{node['id']}",
                                },
                                {
                                    "text": "❌ Deny",
                                    "callback_data": f"node_deny_{node['id']}",
                                },
                            ]
                        ]
                        asyncio.run_coroutine_threadsafe(
                            gw.send_admin_message(msg, reply_markup={"inline_keyboard": buttons}),
                            gw.loop,
                        )
                except Exception as e:
                    logger.warning("Failed to send Telegram node alert: %s", e)

                # Calculate the actual max_concurrent that was stored
                calculated_max = data.get("max_concurrent") or calculate_max_concurrent(
                    data.get("ram_gb", 8),
                    data.get("cpu_cores", 4),
                    data.get("gpu_vram_gb", 0),
                )

                # Generate Headscale mesh auth key for the node
                headscale_authkey = None
                headscale_url = None
                try:
                    import subprocess

                    result = subprocess.run(
                        [
                            "docker",
                            "exec",
                            "archie_headscale",
                            "headscale",
                            "preauthkeys",
                            "create",
                            "--user",
                            "archie-fleet",
                            "--ephemeral",
                            "--expiration",
                            "1h",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        # Key is the last non-empty line (skip WRN lines)
                        lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip() and "WRN" not in l]
                        if lines:
                            headscale_authkey = lines[-1]
                            # WAN nodes use public domain, LAN nodes use direct IP
                            headscale_url = os.environ.get(
                                "HEADSCALE_PUBLIC_URL",
                                "https://mesh.kytranempowerment.com",
                            )
                            logger.info(
                                "Generated Headscale auth key for node %s",
                                node_id,
                            )
                    else:
                        logger.warning("Headscale key generation failed: %s", result.stderr)
                except Exception as hs_err:
                    logger.warning("Headscale key generation skipped: %s", hs_err)

                # Return config settings for the node client
                response = {
                    "success": True,
                    "node_id": node["node_id"],
                    "api_key": api_key,  # Only returned once at registration!
                    "approval_status": node["approval_status"],
                    "network_type": network_type,
                    "config": {
                        "heartbeat_interval": 30,
                        "capability_interval": 300,
                        "max_concurrent": calculated_max,
                        "log_level": "INFO",
                    },
                    "message": (
                        "Node registered. Awaiting admin approval."
                        if node["approval_status"] == "pending"
                        else "Node registered successfully."
                    ),
                    "hardware_recommendation": (
                        f'Based on {data.get("ram_gb", 8)}GB RAM, '
                        f'{data.get("cpu_cores", 4)} cores, '
                        f"recommended max_concurrent: {calculated_max}"
                    ),
                }

                # Include mesh VPN credentials if available
                if headscale_authkey:
                    response["headscale_authkey"] = headscale_authkey
                    response["headscale_url"] = headscale_url

                # Note: BEACON per-node dashboard subdomain auto-creation
                # (*.fleet.kytranempowerment.com + AdGuard rewrite + org_domains)
                # removed 2026-04-18 — project #173 cancelled, DNS cleaned 2026-04-13,
                # fleet_proxy.py deleted. See task #2144.

                return jsonify(response)

        except Exception as e:
            logger.error(f"Error registering node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/mesh-ip", methods=["POST"])
    def update_mesh_ip(node_id):
        """Update a node's mesh VPN IP address (called by installer after Tailscale joins)."""
        data = request.get_json() or {}
        api_key = request.headers.get("X-Node-API-Key")
        mesh_ip = data.get("mesh_ip")

        if not api_key:
            return jsonify({"success": False, "error": "API key required"}), 401
        if not mesh_ip:
            return jsonify({"success": False, "error": "mesh_ip is required"}), 400

        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET mesh_ip = %s,
                        mesh_status = 'connected',
                        mesh_last_seen = NOW()
                    WHERE node_id = %s
                      AND api_key_hash = %s
                    RETURNING id, node_name
                    """,
                    (mesh_ip, node_id, hash_api_key(api_key)),
                )
                row = cur.fetchone()
                if not row:
                    return (
                        jsonify({"success": False, "error": "Invalid node or API key"}),
                        403,
                    )
                conn.commit()
                logger.info(
                    "Node %s (%s) mesh IP updated to %s",
                    row["node_name"],
                    node_id,
                    mesh_ip,
                )
                return jsonify({"success": True, "mesh_ip": mesh_ip})
        except Exception as e:
            logger.error("Error updating mesh IP for %s: %s", node_id, e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/headscale-key", methods=["POST"])
    def node_headscale_key(node_id):
        """Generate a Headscale pre-auth key for a node joining the mesh.

        Called during Fresh install by deploy-node.ps1 with X-API-Key header.
        Runs: docker exec archie_headscale headscale preauthkeys create
              --user archie-fleet --expiration 24h --reusable
        Returns: {auth_key, login_server, hostname}
        """
        api_key = request.headers.get("X-API-Key") or request.headers.get("X-Node-API-Key")
        if not api_key:
            return jsonify({"success": False, "error": "API key required"}), 401

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, node_id, node_name, api_key_hash FROM remote_nodes WHERE node_id = %s",
                (node_id,),
            )
            node = cur.fetchone()
        if not node or not verify_api_key(api_key, node["api_key_hash"]):
            return jsonify({"success": False, "error": "Invalid node or API key"}), 403

        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "archie_headscale",
                    "headscale",
                    "preauthkeys",
                    "create",
                    "--user",
                    "archie-fleet",
                    "--expiration",
                    "24h",
                    "--reusable",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                logger.error("Headscale key gen failed for %s: %s", node_id, result.stderr)
                return (
                    jsonify({"success": False, "error": "Headscale key generation failed"}),
                    500,
                )

            auth_key = result.stdout.strip()
            login_server = os.environ.get("HEADSCALE_URL", "https://mesh.kytranempowerment.com")
            return jsonify(
                {
                    "success": True,
                    "auth_key": auth_key,
                    "login_server": login_server,
                    "hostname": node["node_name"],
                }
            )
        except subprocess.TimeoutExpired:
            return jsonify({"success": False, "error": "Headscale timeout"}), 500
        except Exception:
            logger.exception("Error generating headscale key for %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/repair-command", methods=["POST"])
    @login_required
    def node_repair_command(node_id):
        """Generate a repair script for a broken/offline node.

        Produces a copy-paste command that fixes HUB_URL, generates a fresh
        Headscale pre-auth key, and restarts the node containers — without
        touching docker-compose.yml (ADR-007 safe).
        """
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, node_id, node_name, api_key_hash, deployment_mode, hostname
                   FROM remote_nodes WHERE node_id = %s AND is_active = TRUE""",
                (node_id,),
            )
            node = cur.fetchone()
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        hub_url = os.environ.get("STARSHIP_HUB_URL", "http://192.168.1.200:3000")
        headscale_url = os.environ.get("HEADSCALE_URL", "https://mesh.kytranempowerment.com")

        # Generate fresh Headscale pre-auth key
        headscale_key = ""
        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "archie_headscale",
                    "headscale",
                    "preauthkeys",
                    "create",
                    "--user",
                    "archie-fleet",
                    "--expiration",
                    "24h",
                    "--reusable",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                headscale_key = result.stdout.strip()
        except Exception:
            logger.warning("Could not generate Headscale key for repair of %s", node_id)

        mode = node.get("deployment_mode", "starship")
        # deploy-node.ps1 always creates docker-compose.yml (not .starship.yml)
        compose_file = "docker-compose.yml" if mode == "starship" else "docker-compose.vps.yml"
        install_dir_linux = "/opt/archie-node"
        install_dir_win = "C:\\archie-node"
        node_hostname = node.get("node_name", "archie-node").lower().replace(" ", "-")

        # Linux tailscale command
        tailscale_linux = (
            f"tailscale up --login-server={headscale_url} --auth-key={headscale_key} --force-reauth"
            if headscale_key
            else f"tailscale up --login-server={headscale_url} --force-reauth"
        )
        # Windows tailscale requires --hostname and --unattended (confirmed 2026-05-15 on .246)
        tailscale_win = (
            f"tailscale up --auth-key={headscale_key} --force-reauth"
            f" --login-server={headscale_url} --hostname={node_hostname} --unattended"
            if headscale_key
            else f"tailscale up --force-reauth --login-server={headscale_url}"
            f" --hostname={node_hostname} --unattended"
        )

        cmd_linux = (
            f"cd {install_dir_linux} && "
            f"sed -i 's|HUB_URL=.*|HUB_URL={hub_url}|' .env 2>/dev/null || "
            f"echo 'HUB_URL={hub_url}' >> .env && "
            f"{tailscale_linux} && "
            f"docker compose -f {compose_file} up -d --force-recreate && "
            f"echo 'Node repair complete — heartbeat will appear in Fleet tab within 30s'"
        )

        cmd_windows = (
            f"cd {install_dir_win}; "
            f"(Get-Content .env) -replace 'HUB_URL=.*', 'HUB_URL={hub_url}' | Set-Content .env; "
            f"{tailscale_win}; "
            f"docker compose -f {compose_file} up -d --force-recreate; "
            f"Write-Host 'Node repair complete — check Fleet tab in 30s'"
        )

        return jsonify(
            {
                "success": True,
                "node_id": node_id,
                "node_name": node["node_name"],
                "hub_url": hub_url,
                "headscale_url": headscale_url,
                "headscale_key_generated": bool(headscale_key),
                "command_linux": cmd_linux,
                "command_windows": cmd_windows,
            }
        )

    @bp.route("/api/nodes/<node_id>/heartbeat", methods=["POST"])
    def node_heartbeat(node_id):
        """Receive heartbeat from a remote node"""
        data = request.get_json() or {}
        # Drop host values that are never valid inter-cluster addresses (docker
        # container short IDs, docker-bridge gateways like 172.x, loopback,
        # link-local) so they can't poison remote_nodes.hostname. mesh_ip is the
        # canonical inter-cluster address (ADR-008). Shared guard, #4552.
        data["hostname"] = _valid_inter_cluster_host(data.get("hostname"))
        api_key = request.headers.get("X-Node-API-Key")

        if not api_key:
            return jsonify({"success": False, "error": "API key required"}), 401

        try:
            with get_db_cursor() as (conn, cur):

                # FIX2 (DR self-heal): fetch by node_id WITHOUT the approval filter, then
                # verify the api-key, THEN branch on approval. The old query gated on
                # approval_status='approved' and 404'd a non-approved node before checking
                # its credentials — turning a transient blip into a permanent orphan with
                # no recovery path (RC3). Now a credential-valid node that the hub has seen
                # before (ever heartbeated, or has approved_at) auto-re-approves; a
                # genuinely-new node gets a distinct 409 'pending' so the client backs off
                # instead of re-registering into a fresh pending duplicate.
                cur.execute(
                    """
                    SELECT id, api_key_hash, min_required_version,
                           approval_status, approved_at, last_heartbeat
                    FROM remote_nodes WHERE node_id = %s AND is_active = TRUE
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                if not verify_api_key(api_key, node["api_key_hash"]):
                    # DEBUG: log incoming key hash to reconcile node credentials
                    incoming_hash = hash_api_key(api_key)
                    logger.warning(
                        "Heartbeat auth FAILED for node %s — " "incoming_hash=%s stored_hash=%s (first 12 chars)",
                        node_id,
                        incoming_hash[:12],
                        node["api_key_hash"][:12],
                    )
                    return jsonify({"success": False, "error": "Invalid API key"}), 401

                # Credentials are valid. If the node is not approved but is ESTABLISHED
                # hardware (it has heartbeated before, or carries an approved_at), self-heal
                # by re-approving it — this is the path that recovers a node orphaned into
                # 'pending' by the DR re-registration storm. A node that has NEVER heartbeated
                # and has no approved_at is genuinely new → 409 (distinct from 404) so the
                # client knows to wait for admin approval, not to re-register.
                if node["approval_status"] != "approved":
                    # Self-heal is ONLY for a node orphaned into 'pending' by the DR
                    # re-registration storm. It must NEVER auto-promote a 'rejected' (admin-
                    # denied) node — that would be an authorization bypass; admin denials
                    # must stick. The recoverable signal is: status == 'pending' AND the node
                    # was genuinely approved before (approved_at set; migration 418 backfilled
                    # it for every real node). approved_at is used INSTEAD of last_heartbeat
                    # because FIX1's reclaim can set last_heartbeat on a junk pending row,
                    # which would otherwise let a junk identity auto-approve as 'standard'
                    # (observed on node_7e518… / USS-246 during recovery).
                    recoverable = node["approval_status"] == "pending" and node["approved_at"] is not None
                    if recoverable:
                        cur.execute(
                            "UPDATE remote_nodes SET approval_status = 'approved', "
                            "approved_at = COALESCE(approved_at, NOW()) WHERE id = %s",
                            (node["id"],),
                        )
                        conn.commit()
                        logger.warning(
                            "Heartbeat SELF-HEAL: re-approved storm-orphaned node %s "
                            "on valid credentials (was pending, approved_at preserved)",
                            node_id,
                        )
                    else:
                        # 'rejected' (denied) or a never-approved 'pending' node: stay
                        # blocked. 409 (not 404) so the client backs off, never re-registers.
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "node not approved",
                                    "approval_status": node["approval_status"],
                                }
                            ),
                            409,
                        )

                # Version check
                client_version = data.get("client_version", DEFAULT_CLIENT_VERSION)
                # Simple version comparison (could be more sophisticated)

                # Determine status
                status = "online"
                if data.get("error"):
                    status = "degraded"

                # Update node status including AI service availability
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET status = %s,
                        last_heartbeat = NOW(),
                        -- current_load is HUB-DERIVED, not node-reported (V6): the
                        -- node's self-reported counter leaked (decrement skipped on
                        -- error) and inflated unbounded, mis-routing + corrupting the
                        -- ARMADA gauge. Derive a bounded, self-decaying value from the
                        -- hub's own recent dispatch activity, capped at max_concurrent.
                        current_load = LEAST(
                            GREATEST(0, (
                                SELECT COUNT(*) FROM task_execution_log t
                                WHERE t.node_used_id = remote_nodes.id
                                  AND t.created_at > NOW() - INTERVAL '2 minutes'
                            )),
                            COALESCE(max_concurrent, 5)
                        ),
                        client_version = %s,
                        hostname = COALESCE(%s, hostname),
                        cpu_cores = COALESCE(%s, cpu_cores),
                        cpu_model = COALESCE(%s, cpu_model),
                        ram_gb = COALESCE(%s, ram_gb),
                        -- True if heartbeat confirms GPU, or if gpu_model already set
                        -- (sync container has no GPU device access → nvidia-smi fails there,
                        --  but ollama container proves GPU exists via gpu_model being populated)
                        gpu_available = CASE WHEN %s IS TRUE THEN TRUE
                                             WHEN gpu_model IS NOT NULL THEN TRUE
                                             ELSE FALSE END,
                        gpu_model = COALESCE(%s, gpu_model),
                        gpu_vram_gb = COALESCE(%s, gpu_vram_gb),
                        -- AI Service availability (Phase 72)
                        -- Heartbeat may only turn ollama_available ON. The false
                        -- decision is owned by the hub-side live /api/tags probe in
                        -- model_dispatch_service.reconcile_fleet_models() — some nodes
                        -- (Windows Docker Desktop starships) wrongly self-report
                        -- ollama_available=false while Ollama is up with models, which
                        -- excluded them from the warm-node dispatch path (2026-05-29).
                        ollama_available = CASE WHEN %s IS TRUE THEN TRUE
                                                ELSE ollama_available END,
                        foocus_available = COALESCE(%s, foocus_available),
                        comfyui_available = COALESCE(%s, comfyui_available),
                        auto1111_available = COALESCE(%s, auto1111_available),
                        foocus_port = COALESCE(%s, foocus_port),
                        comfyui_port = COALESCE(%s, comfyui_port),
                        auto1111_port = COALESCE(%s, auto1111_port),
                        ssh_enabled = COALESCE(%s, ssh_enabled),
                        mesh_ip = COALESCE(%s, mesh_ip),
                        last_error = %s,
                        error_count = CASE WHEN %s IS NOT NULL THEN error_count + 1 ELSE 0 END
                    WHERE id = %s
                """,
                    (
                        status,
                        client_version,
                        data.get("hostname"),
                        data.get("cpu_cores"),
                        data.get("cpu_model"),
                        data.get("ram_gb"),
                        # Convert False→None so COALESCE preserves existing TRUE
                        # when nvidia-smi fails inside sync container (no GPU device access).
                        data.get("gpu_available") or None,
                        data.get("gpu_model"),
                        data.get("gpu_vram_gb"),
                        # AI Services
                        data.get("ollama_online"),
                        data.get("foocus_available"),
                        data.get("comfyui_available"),
                        data.get("auto1111_available"),
                        data.get("foocus_port"),
                        data.get("comfyui_port"),
                        data.get("auto1111_port"),
                        data.get("ssh_enabled"),
                        data.get("mesh_ip"),
                        data.get("error"),
                        data.get("error"),
                        node["id"],
                    ),
                )

                # Persist egress_metadata when heartbeat advertises it (#2884)
                egress_meta = data.get("egress_metadata")
                if egress_meta and isinstance(egress_meta, dict):
                    import json as _ejson

                    cur.execute(
                        "UPDATE remote_nodes SET egress_metadata = %s::jsonb WHERE id = %s",
                        (_ejson.dumps(egress_meta), node["id"]),
                    )

                # Persist OS info into extra_capabilities when provided
                os_type = data.get("os_type", "")
                os_name = data.get("os_name", "")
                if os_type:
                    import json as _json

                    cur.execute(
                        """
                        UPDATE remote_nodes
                        SET extra_capabilities = COALESCE(extra_capabilities, '{}'::jsonb)
                            || %s::jsonb
                        WHERE id = %s
                        """,
                        (
                            _json.dumps({"os": os_type, "os_name": os_name}),
                            node["id"],
                        ),
                    )

                # Log heartbeat
                cur.execute(
                    """
                    INSERT INTO node_heartbeats (
                        node_id, status, latency_ms, cpu_usage, memory_usage,
                        gpu_usage, current_load, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        node["id"],
                        status,
                        data.get("latency_ms"),
                        data.get("cpu_usage"),
                        data.get("memory_usage"),
                        data.get("gpu_usage"),
                        data.get("current_load", 0),
                        psycopg2.extras.Json(data.get("details", {})),
                    ),
                )

                # Sync Ollama models if provided (Phase 70: Node Model Discovery)
                models_synced = 0
                ollama_models_payload = None

                # Support both flat (ollama_models) and nested (ollama.available_models) formats
                if data.get("ollama_models") and (data.get("ollama_online") or data.get("ollama_available")):
                    ollama_models_payload = data["ollama_models"]
                elif "ollama" in data:
                    ollama_data = data["ollama"]
                    available = ollama_data.get("available_models", [])
                    if available:
                        ollama_models_payload = available

                if ollama_models_payload:
                    try:
                        cur.execute("SAVEPOINT model_sync")
                        cur.execute(
                            """
                            SELECT sync_node_models(%s, %s::jsonb)
                        """,
                            (node_id, psycopg2.extras.Json(ollama_models_payload)),
                        )
                        result = cur.fetchone()
                        # get_db_cursor returns RealDictRow — result[0] raises KeyError(0)
                        # which str()'s to literal "0" and silently aborts every model sync.
                        models_synced = result["sync_node_models"] if result else 0
                        logger.debug(f"Synced {models_synced} models for node {node_id}")

                        # Mark models no longer available
                        if ollama_models_payload:
                            available_names = [
                                m.get("name", m.get("model", "")) for m in ollama_models_payload if isinstance(m, dict)
                            ]
                            if available_names:
                                cur.execute(
                                    """
                                    UPDATE node_ollama_models SET is_available = false
                                    WHERE node_id = %s AND model_name != ALL(%s::text[])
                                """,
                                    (node_id, available_names),
                                )
                        cur.execute("RELEASE SAVEPOINT model_sync")
                    except Exception as e:
                        logger.warning(f"Model sync error for {node_id}: {e}")
                        cur.execute("ROLLBACK TO SAVEPOINT model_sync")

                # Store idle agents in node metadata (for mesh dispatcher)
                idle_agents = data.get("idle_agents")
                if idle_agents is not None:
                    try:
                        cur.execute(
                            """
                            UPDATE remote_nodes
                            SET metadata = COALESCE(metadata, '{}'::jsonb)
                                || jsonb_build_object('idle_agents', %s::jsonb)
                            WHERE node_id = %s
                            """,
                            (json.dumps(idle_agents), node_id),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store idle_agents for {node_id}: {e}")

                # Process completed jobs from node (Fleet Coordination)
                completed_jobs = data.get("completed_jobs", [])
                for job in completed_jobs:
                    try:
                        cur.execute(
                            """
                            INSERT INTO task_execution_log
                                (agent_id, agent_name, station_code, capability,
                                 module_source, success, duration_ms, created_at)
                            VALUES ((SELECT id FROM agents WHERE name = %s LIMIT 1),
                                    %s, %s, %s, 'remote', %s, %s, NOW())
                        """,
                            (
                                job.get("agent_name"),
                                job.get("agent_name"),
                                job.get("station_code", "UNKNOWN"),
                                job.get("capability"),
                                job.get("success", False),
                                job.get("duration_ms", 0),
                            ),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to log completed job: {e}")

                # Update fleet agent cache with node welfare data
                agent_welfare = data.get("agent_welfare", {})
                if agent_welfare:
                    try:
                        from tools.department_hq.services.bridge_dispatcher import (
                            get_dispatcher,
                        )

                        dispatcher = get_dispatcher()
                        for agent_name, welfare in agent_welfare.items():
                            cache_key = f"fleet:{node_id}:{agent_name}"
                            if cache_key in dispatcher._agent_cache:
                                dispatcher._agent_cache[cache_key].update(
                                    {
                                        "stress": welfare.get("stress", 0.0),
                                        "energy": welfare.get("energy", 1.0),
                                        "shift_state": welfare.get("shift_state", "active"),
                                        "task_count": welfare.get("task_count", 0),
                                        "model_loaded": welfare.get("model_loaded", False),
                                    }
                                )
                    except Exception as e:
                        logger.warning(f"Failed to update fleet welfare cache: {e}")

                # Store apps_running and device_info from fleet nodes
                apps_running = data.get("apps_running")
                if apps_running is not None:
                    try:
                        cur.execute(
                            "UPDATE remote_nodes SET apps_running = %s WHERE node_id = %s",
                            (psycopg2.extras.Json(apps_running), node_id),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store apps_running for {node_id}: {e}")

                device_info = data.get("device_info")
                if device_info is not None:
                    try:
                        cur.execute(
                            "UPDATE remote_nodes SET device_info = %s WHERE node_id = %s",
                            (psycopg2.extras.Json(device_info), node_id),
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store device_info for {node_id}: {e}")

                # Check if update was requested for this node
                cur.execute(
                    "SELECT update_requested FROM remote_nodes WHERE id = %s",
                    (node["id"],),
                )
                update_row = cur.fetchone()
                update_requested = update_row["update_requested"] if update_row else False

                response = {
                    "success": True,
                    "status": status,
                    "message": "Heartbeat received",
                    "models_synced": models_synced,
                }

                if update_requested:
                    response["update_available"] = True
                    response["update_url"] = "/tools/fleet/api/nodes/client-package"
                    response["latest_version"] = LATEST_CLIENT_VERSION
                    # Clear the flag so we only signal once
                    cur.execute(
                        "UPDATE remote_nodes SET update_requested = false WHERE id = %s",
                        (node["id"],),
                    )

                return jsonify(response)

        except Exception as e:
            logger.error(f"Heartbeat error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>")
    @login_required
    def get_node_detail(node_id):
        """Get detailed info about a specific node"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT * FROM remote_nodes WHERE node_id = %s
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get capabilities
                cur.execute(
                    """
                    SELECT provider, model_name, is_available, avg_tokens_per_sec,
                           max_context_length, priority
                    FROM node_capabilities
                    WHERE node_id = %s
                    ORDER BY provider, model_name
                """,
                    (node["id"],),
                )
                capabilities = cur.fetchall()

                # Get recent heartbeats
                cur.execute(
                    """
                    SELECT status, latency_ms, cpu_usage, memory_usage, gpu_usage,
                           current_load, created_at
                    FROM node_heartbeats
                    WHERE node_id = %s
                    ORDER BY created_at DESC
                    LIMIT 50
                """,
                    (node["id"],),
                )
                heartbeats = cur.fetchall()

                # Convert datetime
                for key in ["last_heartbeat", "created_at", "updated_at"]:
                    if node.get(key):
                        node[key] = node[key].isoformat()

                for hb in heartbeats:
                    if hb.get("created_at"):
                        hb["created_at"] = hb["created_at"].isoformat()

                # Remove sensitive data
                node.pop("api_key_hash", None)

                return jsonify(
                    {
                        "success": True,
                        "node": node,
                        "capabilities": capabilities,
                        "heartbeats": heartbeats,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>", methods=["PUT"])
    @login_required
    def update_node(node_id):
        """Update a remote node configuration"""
        data = request.get_json() or {}

        allowed_fields = [
            "node_name",
            "description",
            "vpn_ip",
            "hostname",
            "port",
            "priority",
            "weight",
            "max_concurrent",
            "tags",
            "is_active",
            "min_required_version",
        ]
        updates = {k: v for k, v in data.items() if k in allowed_fields}

        if not updates:
            return (
                jsonify({"success": False, "error": "No valid fields to update"}),
                400,
            )

        try:
            with get_db_cursor() as (conn, cur):

                set_clauses = [f"{k} = %s" for k in updates.keys()]
                values = list(updates.values())
                values.append(node_id)

                cur.execute(
                    f"""
                    UPDATE remote_nodes
                    SET {', '.join(set_clauses)}
                    WHERE node_id = %s
                    RETURNING id, node_id, node_name
                """,
                    values,
                )

                updated = cur.fetchone()

                if not updated:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                return jsonify({"success": True, "node": updated})

        except Exception as e:
            logger.error(f"Error updating node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>", methods=["DELETE"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def delete_node(node_id):
        """Delete a remote node"""
        try:
            with get_db_cursor(cursor_factory=None) as (conn, cur):

                cur.execute(
                    """
                    DELETE FROM remote_nodes WHERE node_id = %s RETURNING id
                """,
                    (node_id,),
                )

                deleted = cur.fetchone()

                if not deleted:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                return jsonify({"success": True, "message": f"Node {node_id} deleted"})

        except Exception as e:
            logger.error(f"Error deleting node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/capabilities", methods=["POST"])
    def update_node_capabilities(node_id):
        """Update capabilities for a node (called by node client)"""
        data = request.get_json() or {}
        api_key = request.headers.get("X-Node-API-Key")
        capabilities = data.get("capabilities", [])

        if not api_key:
            return jsonify({"success": False, "error": "API key required"}), 401

        try:
            with get_db_cursor() as (conn, cur):

                # Verify node
                cur.execute(
                    """
                    SELECT id, api_key_hash FROM remote_nodes
                    WHERE node_id = %s AND is_active = TRUE
                """,
                    (node_id,),
                )
                node = cur.fetchone()

                if not node or not verify_api_key(api_key, node["api_key_hash"]):
                    return jsonify({"success": False, "error": "Unauthorized"}), 401

                # Clear old capabilities and insert new
                cur.execute("DELETE FROM node_capabilities WHERE node_id = %s", (node["id"],))

                for cap in capabilities:
                    cur.execute(
                        """
                        INSERT INTO node_capabilities (
                            node_id, provider, model_name, is_available,
                            avg_tokens_per_sec, max_context_length, priority
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                        (
                            node["id"],
                            cap.get("provider", "ollama"),
                            cap.get("model_name"),
                            cap.get("is_available", True),
                            cap.get("avg_tokens_per_sec"),
                            cap.get("max_context_length"),
                            cap.get("priority", 10),
                        ),
                    )

                return jsonify(
                    {
                        "success": True,
                        "message": f"Updated {len(capabilities)} capabilities",
                    }
                )

        except Exception as e:
            logger.error(f"Error updating capabilities: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/select", methods=["POST"])
    @login_required
    def select_node_for_request():
        """Select the best node for a request (load balancing)"""
        data = request.get_json() or {}
        model_name = data.get("model")
        provider = data.get("provider", "ollama")

        try:
            with get_db_cursor() as (conn, cur):

                # Find available nodes with the requested capability
                cur.execute(
                    """
                    SELECT
                        rn.id, rn.node_id, rn.node_name, rn.mesh_ip, rn.vpn_ip, rn.hostname, rn.port,
                        rn.priority, rn.weight, rn.current_load, rn.max_concurrent,
                        nc.avg_tokens_per_sec
                    FROM remote_nodes rn
                    JOIN node_capabilities nc ON rn.id = nc.node_id
                    WHERE rn.status = 'online'
                      AND rn.is_active = TRUE
                      AND rn.current_load < rn.max_concurrent
                      AND nc.provider = %s
                      AND nc.model_name = %s
                      AND nc.is_available = TRUE
                    ORDER BY
                        rn.priority ASC,
                        (rn.current_load::float / NULLIF(rn.max_concurrent, 0)) ASC,
                        rn.weight DESC
                    LIMIT 1
                """,
                    (provider, model_name),
                )

                node = cur.fetchone()

                if not node:
                    # Fallback: return local if no remote nodes available
                    return jsonify(
                        {
                            "success": True,
                            "node": None,
                            "use_local": True,
                            "message": "No remote nodes available, use local",
                        }
                    )

                # current_load is now hub-derived in the heartbeat (V6) — no manual
                # increment here (the old counter leaked and inflated unbounded).

                return jsonify(
                    {
                        "success": True,
                        "node": {
                            "node_id": node["node_id"],
                            "name": node["node_name"],
                            "host": node_inter_cluster_host(node),
                            "port": node["port"],
                        },
                        "use_local": False,
                    }
                )

        except Exception as e:
            logger.error(f"Error selecting node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/request-complete", methods=["POST"])
    def node_request_complete(node_id):
        """Mark a request as complete (decrement load)"""
        data = request.get_json() or {}

        try:
            with get_db_cursor() as (conn, cur):

                # Get node
                cur.execute("SELECT id FROM remote_nodes WHERE node_id = %s", (node_id,))
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Decrement load and update stats
                success = data.get("success", True)
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET current_load = GREATEST(0, current_load - 1),
                        total_requests = total_requests + 1,
                        successful_requests = successful_requests + %s,
                        failed_requests = failed_requests + %s
                    WHERE id = %s
                """,
                    (1 if success else 0, 0 if success else 1, node["id"]),
                )

                # Log request
                cur.execute(
                    """
                    INSERT INTO node_requests (
                        node_id, request_type, model_name, tokens_in, tokens_out,
                        latency_ms, status, error_message
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        node["id"],
                        data.get("request_type", "completion"),
                        data.get("model"),
                        data.get("tokens_in"),
                        data.get("tokens_out"),
                        data.get("latency_ms"),
                        "success" if success else "failed",
                        data.get("error"),
                    ),
                )

                return jsonify({"success": True})

        except Exception as e:
            logger.error(f"Error completing request: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/stats")
    @login_required
    def get_node_stats():
        """Get aggregate stats across all nodes"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Overall stats
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total_nodes,
                        COUNT(*) FILTER (WHERE status = 'online') as online_nodes,
                        SUM(current_load) as total_current_load,
                        SUM(max_concurrent) as total_capacity,
                        SUM(total_requests) as total_requests,
                        SUM(successful_requests) as successful_requests,
                        AVG(avg_latency_ms) as avg_latency
                    FROM remote_nodes
                    WHERE is_active = TRUE
                """
                )
                overall = cur.fetchone()

                # By provider
                cur.execute(
                    """
                    SELECT
                        nc.provider,
                        COUNT(DISTINCT nc.node_id) as node_count,
                        COUNT(*) as model_count,
                        COUNT(*) FILTER (WHERE nc.is_available) as available_models
                    FROM node_capabilities nc
                    JOIN remote_nodes rn ON nc.node_id = rn.id
                    WHERE rn.is_active = TRUE
                    GROUP BY nc.provider
                """
                )
                by_provider = cur.fetchall()

                # Recent requests (last hour)
                cur.execute(
                    """
                    SELECT
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE status = 'success') as successful,
                        AVG(latency_ms) as avg_latency
                    FROM node_requests
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                """
                )
                recent = cur.fetchone()

                return jsonify(
                    {
                        "success": True,
                        "overall": overall,
                        "by_provider": by_provider,
                        "recent_hour": recent,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # NODE APPROVAL & MANAGEMENT - Phase 29+ Enhancement
    # ============================================================================
    @bp.route("/api/nodes/<node_id>/approve", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def approve_node(node_id):
        """Approve a pending node registration"""
        try:
            # Phase 1: approve the node (own cursor, commits and closes)
            with get_db_cursor(commit=True) as (conn, cur):
                user_id = current_user.id if current_user.is_authenticated else None
                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET approval_status = 'approved',
                        approved_by = %s,
                        approved_at = NOW()
                    WHERE node_id = %s AND approval_status = 'pending'
                    RETURNING node_id, node_name, approval_status
                """,
                    (user_id, node_id),
                )
                node = cur.fetchone()
                if not node:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Node not found or already processed",
                            }
                        ),
                        404,
                    )
                result = {
                    "success": True,
                    "node_id": node["node_id"],
                    "node_name": node["node_name"],
                    "approval_status": node["approval_status"],
                    "message": f"Node '{node['node_name']}' approved successfully",
                }

            # Phase 2: post-approval orchestration (separate connection, no deadlock)
            try:
                _on_node_approved(node_id)
            except Exception as e:
                logger.error("Post-approval orchestration failed for %s: %s", node_id, e)

            return jsonify(result)

        except Exception as e:
            logger.error(f"Error approving node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/reject", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def reject_node(node_id):
        """Reject a pending node registration"""
        data = request.get_json() or {}
        reason = data.get("reason", "No reason provided")

        try:
            with get_db_cursor(commit=True) as (conn, cur):

                # Get current user ID from Flask-Login session
                user_id = current_user.id if current_user.is_authenticated else None

                cur.execute(
                    """
                    UPDATE remote_nodes
                    SET approval_status = 'rejected',
                        approved_by = %s,
                        approved_at = NOW(),
                        last_error = %s,
                        is_active = FALSE
                    WHERE node_id = %s AND approval_status = 'pending'
                    RETURNING node_id, node_name, approval_status
                """,
                    (user_id, f"Rejected: {reason}", node_id),
                )

                node = cur.fetchone()

                if not node:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Node not found or already processed",
                            }
                        ),
                        404,
                    )

                return jsonify(
                    {
                        "success": True,
                        "node_id": node["node_id"],
                        "node_name": node["node_name"],
                        "approval_status": node["approval_status"],
                        "message": f"Node '{node['node_name']}' rejected",
                    }
                )

        except Exception as e:
            logger.error(f"Error rejecting node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/ssh-toggle", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def ssh_toggle_node(node_id):
        """Toggle SSH access on a remote node via mesh sync."""
        data = request.get_json() or {}
        enabled = data.get("enabled", True)
        timeout_minutes = int(data.get("timeout_minutes", 60))

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                # Verify node exists
                cur.execute(
                    "SELECT id, node_name FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                node = cur.fetchone()
                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Update SSH state
                if enabled:
                    cur.execute(
                        """UPDATE remote_nodes
                           SET ssh_enabled = TRUE,
                               ssh_enabled_at = NOW(),
                               ssh_auto_disable_at = NOW() + INTERVAL '%s minutes'
                           WHERE node_id = %s""",
                        (timeout_minutes, node_id),
                    )
                else:
                    cur.execute(
                        """UPDATE remote_nodes
                           SET ssh_enabled = FALSE,
                               ssh_enabled_at = NULL,
                               ssh_auto_disable_at = NULL
                           WHERE node_id = %s""",
                        (node_id,),
                    )

                # Push sync command to node
                hub_public_key = ""
                try:
                    import pathlib

                    key_path = pathlib.Path.home() / ".ssh" / "id_rsa.pub"
                    if key_path.is_file():
                        hub_public_key = key_path.read_text().strip()
                except Exception:
                    pass

                cur.execute(
                    """INSERT INTO mesh_sync_log
                       (node_id, sync_type, payload, status)
                       VALUES (%s, 'ssh_toggle', %s::jsonb, 'pending')""",
                    (
                        node_id,
                        json.dumps(
                            {
                                "enabled": enabled,
                                "hub_public_key": hub_public_key,
                                "timeout_minutes": timeout_minutes,
                            }
                        ),
                    ),
                )

            action = "enabled" if enabled else "disabled"
            return jsonify(
                {
                    "success": True,
                    "ssh_enabled": enabled,
                    "timeout_minutes": timeout_minutes if enabled else 0,
                    "message": f"SSH {action} on {node['node_name']}",
                }
            )

        except Exception as e:
            logger.error("SSH toggle failed for node %s: %s", node_id, e)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/test", methods=["POST"])
    @login_required
    def test_node_connection(node_id):
        """Test connectivity to a remote node's Ollama instance"""

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT node_id, node_name, mesh_ip, vpn_ip, hostname, port
                    FROM remote_nodes
                    WHERE node_id = %s AND is_active = TRUE
                """,
                    (node_id,),
                )

                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Build endpoint URL

                host = node_inter_cluster_host(node)
                port = node["port"] or DEFAULT_NODE_PORT
                url = f"http://{host}:{port}/api/tags"

                # Test connection with timing
                start_time = time.time()
                try:
                    import requests as req

                    resp = req.get(url, timeout=10)
                    latency_ms = int((time.time() - start_time) * 1000)

                    if resp.status_code == 200:
                        models = resp.json().get("models", [])
                        return jsonify(
                            {
                                "success": True,
                                "node_id": node_id,
                                "node_name": node["node_name"],
                                "reachable": True,
                                "latency_ms": latency_ms,
                                "ollama_status": "online",
                                "models_count": len(models),
                                "models": [m.get("name") for m in models[:10]],  # First 10 models
                            }
                        )
                    else:
                        return jsonify(
                            {
                                "success": True,
                                "node_id": node_id,
                                "reachable": True,
                                "latency_ms": latency_ms,
                                "ollama_status": "error",
                                "error": f"Ollama returned status {resp.status_code}",
                            }
                        )
                except req.exceptions.Timeout:
                    return jsonify(
                        {
                            "success": True,
                            "node_id": node_id,
                            "reachable": False,
                            "latency_ms": 10000,
                            "error": "Connection timed out",
                        }
                    )
                except req.exceptions.ConnectionError as e:
                    logger.error(f"Node connection failed: {e}")
                    return jsonify(
                        {
                            "success": True,
                            "node_id": node_id,
                            "reachable": False,
                            "latency_ms": None,
                            "error": "Connection failed",
                        }
                    )

        except Exception as e:
            logger.error(f"Error testing node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/health-history", methods=["GET"])
    @login_required
    def get_node_health_history(node_id):
        """Get health history for a node (for charts)"""
        hours = request.args.get("hours", 24, type=int)

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get node internal ID
                cur.execute("SELECT id FROM remote_nodes WHERE node_id = %s", (node_id,))
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get heartbeat history
                cur.execute(
                    """
                    SELECT
                        DATE_TRUNC('hour', created_at) as hour,
                        AVG(cpu_usage) as avg_cpu,
                        AVG(memory_usage) as avg_memory,
                        AVG(gpu_usage) as avg_gpu,
                        AVG(latency_ms) as avg_latency,
                        COUNT(*) as heartbeat_count,
                        COUNT(*) FILTER (WHERE status = 'online') as online_count
                    FROM node_heartbeats
                    WHERE node_id = %s
                      AND created_at > NOW() - (%s * INTERVAL '1 hour')
                    GROUP BY DATE_TRUNC('hour', created_at)
                    ORDER BY hour
                """,
                    (node["id"], int(hours)),
                )

                history = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "node_id": node_id,
                        "hours": hours,
                        "data_points": len(history),
                        "history": history,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting health history: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/health")
    @login_required
    def get_node_health(node_id):
        """Get latest heartbeat health data for a specific node."""
        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT rn.status, rn.last_heartbeat, rn.current_load, rn.max_concurrent,
                           rn.cpu_cores, rn.ram_gb, rn.gpu_model, rn.gpu_vram_gb,
                           rn.deployment_mode, rn.bridge_priority
                    FROM remote_nodes rn
                    WHERE rn.node_id = %s
                """,
                    (node_id,),
                )
                node = cur.fetchone()

            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404

            # Convert datetime for JSON serialization
            health = dict(node)
            if health.get("last_heartbeat"):
                health["last_heartbeat"] = health["last_heartbeat"].isoformat()

            return jsonify({"success": True, "node_id": node_id, "health": health})

        except Exception as e:
            logger.error(f"Error getting node health: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/dispatch-test", methods=["POST"])
    @login_required
    def dispatch_test_to_node(node_id):
        """Send a connectivity test to a specific node's Ollama."""
        import time as _time

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT mesh_ip, vpn_ip, hostname, port FROM remote_nodes
                    WHERE node_id = %s AND is_active = true
                """,
                    (node_id,),
                )
                node = cur.fetchone()

            if not node:
                return (
                    jsonify({"success": False, "error": "Node not found or inactive"}),
                    404,
                )

            host = node_inter_cluster_host(node)
            port = node["port"] or DEFAULT_NODE_PORT
            ollama_url = f"http://{host}:{port}"
            start = _time.time()
            resp = requests.get(f"{ollama_url}/api/tags", timeout=10)
            latency_ms = round((_time.time() - start) * 1000)
            data = resp.json()
            model_count = len(data.get("models", []))

            return jsonify(
                {
                    "success": True,
                    "node_id": node_id,
                    "latency_ms": latency_ms,
                    "model_count": model_count,
                    "ollama_url": ollama_url,
                }
            )

        except requests.exceptions.Timeout:
            return jsonify({"success": False, "error": "Connection timed out"}), 504
        except requests.exceptions.ConnectionError:
            return jsonify({"success": False, "error": "Connection refused"}), 502
        except Exception as e:
            logger.error(f"Error dispatch-testing node: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # NODE STATION ASSIGNMENTS - Phase 31
    # ============================================================================

    @bp.route("/api/nodes/<node_id>/stations", methods=["GET"])
    @login_required
    def get_node_stations(node_id):
        """Get all station assignments for a node"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Get node internal ID
                cur.execute(
                    "SELECT id, node_name FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get station assignments — bridge_stations deprecated, use it only for name lookup
                # (node_station_assignments still references station_id FK)
                cur.execute(
                    """
                    SELECT
                        nsa.id AS assignment_id,
                        nsa.station_id,
                        COALESCE(bs.station_code, 'UNKNOWN') as station_code,
                        COALESCE(bs.station_name, 'Unknown') as station_name,
                        COALESCE(bs.color, '#666') AS station_color,
                        nsa.role,
                        nsa.priority,
                        nsa.shift_preference,
                        nsa.max_concurrent,
                        nsa.is_active,
                        nsa.assigned_at,
                        nsa.notes
                    FROM node_station_assignments nsa
                    LEFT JOIN bridge_stations bs ON nsa.station_id = bs.id
                    WHERE nsa.node_id = %s
                    ORDER BY nsa.priority ASC
                """,
                    (node["id"],),
                )

                assignments = cur.fetchall()

                return jsonify(
                    {
                        "success": True,
                        "node_id": node_id,
                        "node_name": node["node_name"],
                        "assignment_count": len(assignments),
                        "assignments": assignments,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting node stations: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/stations", methods=["POST"])
    @login_required
    def assign_node_to_station(node_id):
        """Assign a node to a station"""
        data = request.get_json() or {}

        if not data.get("station_id"):
            return jsonify({"success": False, "error": "station_id is required"}), 400

        try:
            with get_db_cursor() as (conn, cur):

                # Get node internal ID
                cur.execute(
                    "SELECT id, node_name FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Verify station exists (bridge_stations still holds node-station mappings)
                cur.execute(
                    "SELECT id, station_name FROM bridge_stations WHERE id = %s",
                    (data["station_id"],),
                )
                station = cur.fetchone()

                if not station:
                    return (
                        jsonify({"success": False, "error": "Station not found"}),
                        404,
                    )

                # Check if assignment already exists
                cur.execute(
                    """
                    SELECT id FROM node_station_assignments
                    WHERE node_id = %s AND station_id = %s
                """,
                    (node["id"], data["station_id"]),
                )

                if cur.fetchone():
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "Node is already assigned to this station",
                            }
                        ),
                        400,
                    )

                # Create assignment
                cur.execute(
                    """
                    INSERT INTO node_station_assignments (
                        node_id, station_id, role, priority, shift_preference,
                        max_concurrent, notes, assigned_by
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, role, priority, assigned_at
                """,
                    (
                        node["id"],
                        data["station_id"],
                        data.get("role", "worker"),
                        data.get("priority", 10),
                        data.get("shift_preference", "any"),
                        data.get("max_concurrent", 5),
                        data.get("notes"),
                        current_user.id if current_user.is_authenticated else None,
                    ),
                )

                assignment = cur.fetchone()

                return jsonify(
                    {
                        "success": True,
                        "message": f"Node '{node['node_name']}' assigned to station '{station['station_name']}'",
                        "assignment": {
                            "id": assignment["id"],
                            "node_id": node_id,
                            "node_name": node["node_name"],
                            "station_id": data["station_id"],
                            "station_name": station["station_name"],
                            "role": assignment["role"],
                            "priority": assignment["priority"],
                            "assigned_at": (
                                assignment["assigned_at"].isoformat() if assignment["assigned_at"] else None
                            ),
                        },
                    }
                )

        except Exception as e:
            logger.error(f"Error assigning node to station: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/stations/<int:station_id>", methods=["PUT"])
    @login_required
    def update_node_station_assignment(node_id, station_id):
        """Update a node's station assignment (role, priority, etc.)"""
        data = request.get_json() or {}

        try:
            with get_db_cursor() as (conn, cur):

                # Get node internal ID
                cur.execute(
                    "SELECT id, node_name FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Check if assignment exists
                cur.execute(
                    """
                    SELECT nsa.id, COALESCE(bs.station_name, 'Unknown') as station_name
                    FROM node_station_assignments nsa
                    LEFT JOIN bridge_stations bs ON nsa.station_id = bs.id
                    WHERE nsa.node_id = %s AND nsa.station_id = %s
                """,
                    (node["id"], station_id),
                )
                assignment = cur.fetchone()

                if not assignment:
                    return (
                        jsonify({"success": False, "error": "Assignment not found"}),
                        404,
                    )

                # Build update query dynamically
                update_fields = []
                update_values = []

                if "role" in data:
                    if data["role"] not in ["primary", "backup", "relief", "worker"]:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "Invalid role. Must be: primary, backup, relief, or worker",
                                }
                            ),
                            400,
                        )
                    update_fields.append("role = %s")
                    update_values.append(data["role"])

                if "priority" in data:
                    update_fields.append("priority = %s")
                    update_values.append(data["priority"])

                if "shift_preference" in data:
                    if data["shift_preference"] not in [
                        "alpha",
                        "beta",
                        "gamma",
                        "any",
                    ]:
                        return (
                            jsonify(
                                {
                                    "success": False,
                                    "error": "Invalid shift_preference. Must be: alpha, beta, gamma, or any",
                                }
                            ),
                            400,
                        )
                    update_fields.append("shift_preference = %s")
                    update_values.append(data["shift_preference"])

                if "max_concurrent" in data:
                    update_fields.append("max_concurrent = %s")
                    update_values.append(data["max_concurrent"])

                if "is_active" in data:
                    update_fields.append("is_active = %s")
                    update_values.append(data["is_active"])

                if "notes" in data:
                    update_fields.append("notes = %s")
                    update_values.append(data["notes"])

                if not update_fields:
                    return (
                        jsonify({"success": False, "error": "No fields to update"}),
                        400,
                    )

                # Execute update
                update_values.append(assignment["id"])
                cur.execute(
                    f"""
                    UPDATE node_station_assignments
                    SET {', '.join(update_fields)}
                    WHERE id = %s
                    RETURNING id, role, priority, shift_preference, max_concurrent, is_active
                """,
                    tuple(update_values),
                )

                updated = cur.fetchone()

                return jsonify(
                    {
                        "success": True,
                        "message": (
                            f"Assignment updated for node '{node['node_name']}' "
                            f"at station '{assignment['station_name']}'"
                        ),
                        "assignment": {
                            "node_id": node_id,
                            "station_id": station_id,
                            "station_name": assignment["station_name"],
                            **updated,
                        },
                    }
                )

        except Exception as e:
            logger.error(f"Error updating station assignment: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/stations/<int:station_id>", methods=["DELETE"])
    @login_required
    def remove_node_from_station(node_id, station_id):
        """Remove a node from a station"""
        try:
            with get_db_cursor() as (conn, cur):

                # Get node internal ID
                cur.execute(
                    "SELECT id, node_name FROM remote_nodes WHERE node_id = %s",
                    (node_id,),
                )
                node = cur.fetchone()

                if not node:
                    return jsonify({"success": False, "error": "Node not found"}), 404

                # Get station name for response (bridge_stations deprecated but still exists)
                cur.execute(
                    "SELECT station_name FROM bridge_stations WHERE id = %s",
                    (station_id,),
                )
                station = cur.fetchone() or {"station_name": "Unknown"}

                # Delete assignment
                cur.execute(
                    """
                    DELETE FROM node_station_assignments
                    WHERE node_id = %s AND station_id = %s
                    RETURNING id
                """,
                    (node["id"], station_id),
                )

                deleted = cur.fetchone()

                if not deleted:
                    return (
                        jsonify({"success": False, "error": "Assignment not found"}),
                        404,
                    )

                return jsonify(
                    {
                        "success": True,
                        "message": (
                            f"Node '{node['node_name']}' removed from station "
                            f"'{station['station_name'] if station else station_id}'"
                        ),
                    }
                )

        except Exception as e:
            logger.error(f"Error removing node from station: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/<int:station_id>/nodes", methods=["GET"])
    @login_required
    def get_station_nodes(station_id):
        """Get all nodes assigned to a station"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                # Verify station exists (bridge_stations deprecated but still holds node-station FK data)
                cur.execute(
                    "SELECT id, station_code, station_name, color FROM bridge_stations WHERE id = %s",
                    (station_id,),
                )
                station = cur.fetchone()

                if not station:
                    return (
                        jsonify({"success": False, "error": "Station not found"}),
                        404,
                    )

                # Get assigned nodes with details
                cur.execute(
                    """
                    SELECT
                        rn.node_id,
                        rn.node_name,
                        rn.status,
                        rn.hostname,
                        rn.cpu_cores,
                        rn.ram_gb,
                        rn.gpu_model,
                        rn.ollama_available,
                        rn.docker_available,
                        rn.current_load,
                        rn.max_concurrent,
                        nsa.role,
                        nsa.priority,
                        nsa.shift_preference,
                        nsa.is_active AS assignment_active,
                        nsa.assigned_at
                    FROM node_station_assignments nsa
                    JOIN remote_nodes rn ON nsa.node_id = rn.id
                    WHERE nsa.station_id = %s
                    ORDER BY
                        CASE nsa.role
                            WHEN 'primary' THEN 1
                            WHEN 'backup' THEN 2
                            WHEN 'relief' THEN 3
                            ELSE 4
                        END,
                        nsa.priority ASC
                """,
                    (station_id,),
                )

                nodes = cur.fetchall()

                # Categorize by role
                by_role = {
                    "primary": [n for n in nodes if n["role"] == "primary"],
                    "backup": [n for n in nodes if n["role"] == "backup"],
                    "relief": [n for n in nodes if n["role"] == "relief"],
                    "worker": [n for n in nodes if n["role"] == "worker"],
                }

                return jsonify(
                    {
                        "success": True,
                        "station": station,
                        "node_count": len(nodes),
                        "by_role": {
                            "primary": len(by_role["primary"]),
                            "backup": len(by_role["backup"]),
                            "relief": len(by_role["relief"]),
                            "worker": len(by_role["worker"]),
                        },
                        "nodes": nodes,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting station nodes: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/batch-nodes", methods=["POST"])
    @login_required
    def get_batch_station_nodes():
        """Get nodes for multiple stations in one query"""
        data = request.get_json() or {}
        station_ids = data.get("station_ids", [])
        if not station_ids:
            return jsonify({"success": True, "stations": {}})

        try:
            with get_db_cursor(commit=False) as (conn, cur):
                cur.execute(
                    """
                    SELECT
                        nsa.station_id,
                        rn.node_id, rn.node_name, rn.status, rn.hostname,
                        rn.cpu_cores, rn.ram_gb, rn.gpu_model,
                        rn.ollama_available, rn.docker_available,
                        rn.current_load, rn.max_concurrent,
                        nsa.role, nsa.priority, nsa.shift_preference,
                        nsa.is_active AS assignment_active, nsa.assigned_at
                    FROM node_station_assignments nsa
                    JOIN remote_nodes rn ON nsa.node_id = rn.id
                    WHERE nsa.station_id = ANY(%s)
                    ORDER BY nsa.station_id,
                        CASE nsa.role
                            WHEN 'primary' THEN 1 WHEN 'backup' THEN 2
                            WHEN 'relief' THEN 3 ELSE 4
                        END, nsa.priority ASC
                """,
                    (station_ids,),
                )

                nodes = cur.fetchall()

                # Group by station_id
                by_station = {}
                for n in nodes:
                    sid = str(n["station_id"])
                    if sid not in by_station:
                        by_station[sid] = []
                    by_station[sid].append(n)

                return jsonify({"success": True, "stations": by_station})
        except Exception as e:
            logger.error(f"Error batch fetching nodes: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/stations/coverage", methods=["GET"])
    @login_required
    def get_all_station_coverage():
        """Get node coverage summary for all stations"""
        try:
            with get_db_cursor(commit=False) as (conn, cur):

                cur.execute(
                    """
                    SELECT * FROM v_station_node_coverage
                """
                )

                coverage = cur.fetchall()

                # Calculate summary
                total_assignments = sum(c["total_nodes"] for c in coverage)
                stations_with_nodes = len([c for c in coverage if c["total_nodes"] > 0])
                stations_without_primary = len([c for c in coverage if c["primary_nodes"] == 0])

                return jsonify(
                    {
                        "success": True,
                        "summary": {
                            "total_stations": len(coverage),
                            "stations_with_nodes": stations_with_nodes,
                            "stations_without_primary": stations_without_primary,
                            "total_assignments": total_assignments,
                        },
                        "coverage": coverage,
                    }
                )

        except Exception as e:
            logger.error(f"Error getting station coverage: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/select-for-station", methods=["POST"])
    @login_required
    def select_node_for_station_api():
        """Select the best available node for a station task"""
        data = request.get_json() or {}

        if not data.get("station_id"):
            return jsonify({"success": False, "error": "station_id is required"}), 400

        try:
            with get_db_cursor(commit=False) as (conn, cur):

                urgency = data.get("urgency", "normal")

                cur.execute(
                    """
                    SELECT * FROM select_node_for_station(%s, %s)
                """,
                    (data["station_id"], urgency),
                )

                nodes = cur.fetchall()

                if not nodes:
                    return (
                        jsonify(
                            {
                                "success": False,
                                "error": "No available nodes for this station",
                                "suggestion": "Assign nodes to this station or ensure assigned nodes are online",
                            }
                        ),
                        404,
                    )

                # Return best node (first in sorted list)
                best_node = nodes[0]

                return jsonify(
                    {
                        "success": True,
                        "selected_node": best_node,
                        "alternatives": nodes[1:] if len(nodes) > 1 else [],
                        "selection_criteria": {
                            "urgency": urgency,
                            "station_id": data["station_id"],
                        },
                    }
                )

        except Exception as e:
            logger.error(f"Error selecting node for station: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ============================================================================
    # USER-FACING NODE MANAGEMENT (from Starship)
    # ============================================================================

    @bp.route("/api/nodes/<int:node_id>/diagnostics")
    @login_required
    def api_node_diagnostics(node_id):
        """Proxy diagnostics request to a node's local API."""
        import requests as _req

        node = _get_node_for_user_by_int_id(node_id, current_user.id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        hostname = node_inter_cluster_host(node)
        api_port = 3001  # node_api default port
        try:
            resp = _req.get(f"http://{hostname}:{api_port}/diagnostics", timeout=8)
            if resp.ok:
                return jsonify({"success": True, "diagnostics": resp.json()})
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Node returned HTTP {resp.status_code}",
                    }
                ),
                502,
            )
        except _req.exceptions.Timeout:
            return jsonify({"success": False, "error": "Node API timed out"}), 504
        except _req.exceptions.ConnectionError:
            return jsonify({"success": False, "error": "Node API unreachable"}), 502
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/nodes/<node_id>/status")
    @login_required
    def api_node_status(node_id):
        """Get detailed status for a specific node including version, stations, agents."""
        user_id = current_user.id
        try:
            node = _get_node_for_user(node_id, user_id)
            if not node:
                return jsonify({"success": False, "error": "Node not found"}), 404

            with get_db_cursor() as (conn, cur):
                # Models with full metadata
                cur.execute(
                    """
                    SELECT model_name, model_size_gb, is_available,
                           context_length, quantization, model_family,
                           parameter_size, capabilities,
                           total_requests, avg_response_ms
                    FROM node_ollama_models
                    WHERE node_id = %s
                    ORDER BY is_available DESC, model_name
                    """,
                    (node["node_id"],),
                )
                models = cur.fetchall()

                # Job stats (bridge_jobs doesn't track per-node yet)
                stats = {"total_jobs": 0, "completed_jobs": 0, "failed_jobs": 0}

                # Latest heartbeat metrics
                cur.execute(
                    """
                    SELECT cpu_usage, memory_usage, gpu_usage, current_load
                    FROM node_heartbeats
                    WHERE node_id = %s
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (node.get("id") or 0,),
                )
                latest_hb = cur.fetchone()

                # Station color lookup — from Python map (bridge_stations deprecated)
                _STATION_COLORS = {
                    "COMMAND": "#00e5ff",
                    "ANALYTICS": "#8b5cf6",
                    "CREATIVE": "#f472b6",
                    "ENGINEERING": "#fbbf24",
                    "COMMUNICATIONS": "#22d3ee",
                    "RESEARCH": "#10b981",
                    "SECURITY": "#ef4444",
                    "LOGISTICS": "#f97316",
                    "DIPLOMATIC": "#818cf8",
                    "OPERATIONS": "#a3e635",
                }
                # Build stations from the legacy map with agent counts from node_agents
                cur.execute(
                    """
                    SELECT unnest(na.station_codes) as station_code, COUNT(*) as agent_count
                    FROM node_agents na
                    WHERE na.node_id = %s AND na.status = 'active'
                    GROUP BY unnest(na.station_codes)
                    """,
                    (node.get("id") or 0,),
                )
                code_counts = {r["station_code"]: r["agent_count"] for r in cur.fetchall()}
                stations = [
                    {
                        "id": idx,
                        "station_code": code,
                        "station_name": code.title(),
                        "color": color,
                        "icon": None,
                        "default_llm": None,
                        "assigned": code in code_counts,
                        "station_active": True,
                        "agent_count": code_counts.get(code, 0),
                    }
                    for idx, (code, color) in enumerate(_STATION_COLORS.items())
                ]
                station_color_map = _STATION_COLORS

                # Node-specific agents from node_agents table
                cur.execute(
                    """
                    SELECT na.id, na.name, na.display_name, na.first_name,
                           na.last_name, na.model, na.status, na.title,
                           na.station_codes, na.is_allowed
                    FROM node_agents na
                    WHERE na.node_id = %s AND na.status = 'active'
                    ORDER BY na.display_name
                    """,
                    (node.get("id") or 0,),
                )
                agents_raw = cur.fetchall()

                # Attach station colors from the lookup
                agents = []
                for a in agents_raw:
                    codes = a["station_codes"] or []
                    colors = [station_color_map.get(c, "#666") for c in codes]
                    agents.append(
                        {
                            "id": a["id"],
                            "name": a["name"],
                            "display_name": a["display_name"],
                            "model": a["model"],
                            "status": a["status"],
                            "title": a["title"],
                            "station_codes": codes,
                            "station_colors": colors,
                            "allowed": a["is_allowed"],
                        }
                    )

            # Version check
            client_ver = node.get("client_version", "1.0.0") or "1.0.0"
            update_available = client_ver < LATEST_NODE_VERSION

            # If node is offline, zero out live metrics
            computed_status = _compute_node_status(node)
            if computed_status == "offline":
                latest_hb = None

            # Compute model totals
            total_model_size = sum(float(m["model_size_gb"]) for m in models if m["model_size_gb"])
            available_count = sum(1 for m in models if m["is_available"])
            assigned_stations = sum(1 for s in stations if s["assigned"])
            active_stations = sum(1 for s in stations if s["assigned"] and s["station_active"])

            return jsonify(
                {
                    "success": True,
                    "agent_count": len(agents),
                    "node": {
                        "db_id": node.get("id") or 0,
                        "node_id": node["node_id"],
                        "node_name": node["node_name"],
                        "status": _compute_node_status(node),
                        "deployment_mode": node["deployment_mode"],
                        "bridge_priority": node["bridge_priority"],
                        "last_heartbeat": (node["last_heartbeat"].isoformat() if node["last_heartbeat"] else None),
                        "privacy_settings": node.get("privacy_settings", {}),
                        "client_version": client_ver,
                        "mesh_ip": node.get("mesh_ip"),
                        "mesh_status": node.get("mesh_status", "disconnected"),
                        "mesh_connection_type": node.get("mesh_connection_type"),
                        "mesh_latency_ms": node.get("mesh_latency_ms"),
                        "hostname": node.get("hostname"),
                        "vpn_ip": node.get("vpn_ip"),
                    },
                    "version": {
                        "current": client_ver,
                        "latest": LATEST_NODE_VERSION,
                        "update_available": update_available,
                    },
                    "hardware": {
                        "cpu_model": node["cpu_model"],
                        "cpu_cores": node["cpu_cores"],
                        "ram_gb": float(node["ram_gb"]) if node["ram_gb"] else None,
                        "gpu_model": node["gpu_model"],
                        "gpu_vram_gb": (float(node["gpu_vram_gb"]) if node["gpu_vram_gb"] else None),
                        "disk_gb": float(node["disk_gb"]) if node["disk_gb"] else None,
                    },
                    "live_metrics": {
                        "cpu_usage": (float(latest_hb["cpu_usage"]) if latest_hb and latest_hb["cpu_usage"] else 0),
                        "memory_usage": (
                            float(latest_hb["memory_usage"]) if latest_hb and latest_hb["memory_usage"] else 0
                        ),
                        "gpu_usage": (float(latest_hb["gpu_usage"]) if latest_hb and latest_hb["gpu_usage"] else 0),
                        "current_load": (
                            float(latest_hb["current_load"]) if latest_hb and latest_hb["current_load"] else 0
                        ),
                    },
                    "models": [
                        {
                            "model_name": m["model_name"],
                            "model_size_gb": (float(m["model_size_gb"]) if m["model_size_gb"] else None),
                            "is_available": m["is_available"],
                            "context_length": m["context_length"],
                            "quantization": m["quantization"],
                            "model_family": m["model_family"],
                            "parameter_size": m["parameter_size"],
                            "capabilities": m["capabilities"] or [],
                            "total_requests": m["total_requests"] or 0,
                            "avg_response_ms": m["avg_response_ms"],
                        }
                        for m in models
                    ],
                    "model_summary": {
                        "total": len(models),
                        "available": available_count,
                        "total_size_gb": round(total_model_size, 1),
                    },
                    "stations": [
                        {
                            "id": s["id"],
                            "station_code": s["station_code"],
                            "station_name": s["station_name"],
                            "color": s["color"],
                            "icon": s["icon"],
                            "default_llm": s["default_llm"],
                            "assigned": s["assigned"],
                            "active": (s["station_active"] if s["station_active"] is not None else False),
                            "agent_count": s["agent_count"],
                        }
                        for s in stations
                    ],
                    "station_summary": {
                        "total": assigned_stations,
                        "active": active_stations,
                    },
                    "agents": agents,
                    "stats": {
                        "total_jobs": stats["total_jobs"],
                        "completed_jobs": stats["completed_jobs"],
                        "failed_jobs": stats["failed_jobs"],
                    },
                }
            )
        except Exception:
            logger.exception("Failed to get node status for node %s", node_id)
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/settings", methods=["PUT"])
    @login_required
    def api_update_node_settings(node_id):
        """Update node name, deployment mode, and priority (inline edit from STATUS tab)."""
        user_id = current_user.id
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        data = request.get_json() or {}

        updates = []
        params = []
        if "node_name" in data:
            name = data["node_name"].strip()
            if not name or len(name) > 100:
                return jsonify({"success": False, "error": "Invalid name"}), 400
            updates.append("node_name = %s")
            params.append(name)
        if "deployment_mode" in data:
            mode = data["deployment_mode"]
            if mode not in ("starship", "satellite", "outpost"):
                return jsonify({"success": False, "error": "Invalid mode"}), 400
            updates.append("deployment_mode = %s")
            params.append(mode)
        if "bridge_priority" in data:
            try:
                prio = int(data["bridge_priority"])
                prio = max(0, min(100, prio))
            except (ValueError, TypeError):
                return jsonify({"success": False, "error": "Invalid priority"}), 400
            updates.append("bridge_priority = %s")
            params.append(prio)

        if not updates:
            return jsonify({"success": False, "error": "No fields to update"}), 400

        params.append(node_id)
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE remote_nodes SET " + ", ".join(updates) + " WHERE node_id = %s",
                params,
            )
        return jsonify({"success": True})

    @bp.route("/api/model-catalog")
    @login_required
    def fleet_api_model_catalog():
        """Return the curated model catalog for browsing and selection."""
        category = request.args.get("category")
        with get_db_cursor() as (conn, cur):
            if category:
                cur.execute(
                    "SELECT id, name, COALESCE(description, '') as description, category, size_gb, quantization, is_active FROM model_catalog WHERE is_active = true AND category = %s ORDER BY size_gb",
                    (category,),
                )
            else:
                cur.execute(
                    "SELECT id, name, COALESCE(description, '') as description, category, size_gb, quantization, is_active FROM model_catalog WHERE is_active = true ORDER BY category, size_gb"
                )
            models = cur.fetchall()
            return jsonify({"success": True, "models": [dict(m) for m in models]})

    # ========================================================================
    # NODE SETUP / ONBOARDING
    # ========================================================================

    @bp.route("/api/request-node", methods=["POST"])
    @login_required
    def api_request_node():
        """Generate a setup token and pre-register a pending node for this user."""

        user_id = current_user.id
        data = request.get_json() or {}
        node_name = data.get("node_name", "").strip() or f"Starship-{secrets.token_hex(3).upper()}"

        # Generate unique node ID and setup token
        node_id = f"starship_{secrets.token_hex(8)}"
        setup_token = secrets.token_urlsafe(32)

        # Get starbase hostname for the config
        starbase_host = os.getenv("STARBASE_HOST", request.host.split(":")[0])
        starbase_port = os.getenv("STARBASE_PORT", "3000")

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO remote_nodes (
                        node_id, node_name, deployment_mode, status,
                        is_active, bridge_enabled, bridge_priority,
                        approval_status, user_id, setup_token,
                        privacy_settings
                    ) VALUES (
                        %s, %s, 'starship', 'pending',
                        false, false, 50,
                        'pending', %s, %s,
                        '{}'::jsonb
                    )
                    RETURNING id, node_id, node_name
                    """,
                    (node_id, node_name, user_id, setup_token),
                )
                row = cur.fetchone()

            # Build config for the node
            hub_url = os.getenv(
                "STARSHIP_HUB_URL",
                "https://platform.kytranempowerment.com",
            )
            config = {
                "node_id": node_id,
                "node_name": node_name,
                "setup_token": setup_token,
                "starbase_url": f"http://{starbase_host}:{starbase_port}",
                "deployment_mode": "starship",
                "heartbeat_interval": 30,
                "hub_url": hub_url,
            }

            return jsonify(
                {
                    "success": True,
                    "node_id": row["node_id"],
                    "node_name": row["node_name"],
                    "db_id": row["id"],
                    "setup_token": setup_token,
                    "config": config,
                }
            )
        except Exception:
            logger.exception("Failed to request new node")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/setup-instructions/<node_id>")
    @login_required
    def api_setup_instructions(node_id):
        """Get setup instructions and config for a pending node."""
        user_id = current_user.id
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        starbase_host = os.getenv("STARBASE_HOST", request.host.split(":")[0])
        starbase_port = os.getenv("STARBASE_PORT", "3000")

        config = {
            "node_id": node["node_id"],
            "node_name": node["node_name"],
            "setup_token": node.get("setup_token", ""),
            "starbase_url": f"http://{starbase_host}:{starbase_port}",
            "deployment_mode": "starship",
            "heartbeat_interval": 30,
        }

        return jsonify({"success": True, "config": config})

    @bp.route("/install")
    def starship_install_script():
        """Serve OS-appropriate install script authenticated by setup token.

        This is the endpoint that the one-liner curl command calls:
          curl -fsSL 'https://platform.kytranempowerment.com/tools/department-hq/install?token=...' | sudo bash

        The script body uses hub_mesh_url (100.64.0.4:3000) for all API calls
        — those only run AFTER Headscale enrollment, so the mesh is reachable.
        A fresh Headscale pre-auth key is generated on each script fetch so the
        VPS can join automatically without any manual console steps.
        """
        token = request.args.get("token", "").strip()
        if not token:
            return Response(
                "Error: missing token parameter\n",
                mimetype="text/plain",
                status=400,
            )

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT node_id, node_name, setup_token, mesh_ip, deployment_mode FROM remote_nodes WHERE setup_token = %s",
                (token,),
            )
            node = cur.fetchone()
            if not node:
                return Response(
                    "Error: invalid or expired token\n",
                    mimetype="text/plain",
                    status=403,
                )

        # Two-phase URLs: public for banner, mesh for in-script API calls
        hub_public_url = os.environ.get("HUB_PUBLIC_URL", "https://platform.kytranempowerment.com")
        hub_mesh_url = os.environ.get("HUB_MESH_URL", "http://100.64.0.4:3000")
        node_id = node["node_id"]
        node_name = node.get("node_name") or node_id
        provided_mesh_ip = node.get("mesh_ip") or ""
        node_deployment_mode = node.get("deployment_mode", "starship") or "starship"

        # Generate a fresh Headscale pre-auth key so VPS joins mesh automatically
        headscale_authkey = ""
        try:
            import subprocess as _sp

            hs = _sp.run(
                [
                    "docker",
                    "exec",
                    "archie_headscale",
                    "headscale",
                    "preauthkeys",
                    "create",
                    "--user",
                    "archie-fleet",
                    "--expiration",
                    "24h",
                    "--reusable",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if hs.returncode == 0:
                hs_lines = [l.strip() for l in hs.stdout.strip().splitlines() if l.strip()]
                headscale_authkey = hs_lines[-1] if hs_lines else ""
        except Exception:
            logger.warning(
                "Could not generate Headscale auth key for /install endpoint",
                exc_info=True,
            )

        ua = (request.headers.get("User-Agent") or "").lower()
        is_powershell = "powershell" in ua or "windowspowershell" in ua

        if is_powershell:
            script = _generate_setup_ps1(hub_public_url, node_id, token, node_name)
            return Response(script, mimetype="text/plain", status=200)
        else:
            script = _generate_setup_sh(
                hub_public_url,
                node_id,
                token,
                node_name,
                headscale_authkey=headscale_authkey,
                mesh_ip=provided_mesh_ip,
                hub_mesh_url=hub_mesh_url,
                deployment_mode=node_deployment_mode,
            )
            return Response(script, mimetype="text/plain", status=200)

    @bp.route("/api/nodes/<node_id>/request-update", methods=["POST"])
    @login_required
    def api_request_update(node_id):
        """Request a node to self-update on its next heartbeat."""
        user_id = current_user.id
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                UPDATE remote_nodes
                SET update_requested = true, update_requested_at = NOW()
                WHERE node_id = %s
                """,
                (node_id,),
            )
        return jsonify({"success": True, "message": "Update will be pushed on next heartbeat"})

    @bp.route("/download/node-package")
    @login_required
    def download_node_package():
        """Download the starship node package (tar.gz)."""
        package_path = os.path.join(NODE_CLIENT_DIR, "archie-node-latest.tar.gz")
        if os.path.exists(package_path):
            return send_file(
                package_path,
                as_attachment=True,
                download_name="archie-starship-node.tar.gz",
            )
        return jsonify({"success": False, "error": "Package not found"}), 404

    @bp.route("/api/nodes/<node_id>/download-zip")
    @login_required
    def api_download_node_zip(node_id):
        """Generate and serve a ZIP with everything needed to run a node.

        Contains: docker-compose.yml, .env (pre-filled), start/stop/update
        scripts for Windows and Mac. Zero build steps required.
        """
        import io
        import zipfile

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT node_id, node_name, setup_token FROM remote_nodes WHERE node_id = %s",
                (node_id,),
            )
            node = cur.fetchone()
            if not node:
                return jsonify({"error": "Node not found"}), 404

            api_key = node.get("setup_token", "")
            node_name = node.get("node_name", "archie-node")

        hub_url = request.host_url.rstrip("/")
        external_url = os.environ.get("EXTERNAL_URL", hub_url)

        compose_path = os.path.join(NODE_CLIENT_DIR, "docker-compose.node.yml")
        if not os.path.exists(compose_path):
            return jsonify({"error": "Compose template not found"}), 500
        with open(compose_path) as f:
            compose_content = f.read()

        env_content = (
            f"NODE_ID={node_id}\n"
            f"NODE_NAME={node_name}\n"
            f"HUB_URL={external_url}\n"
            f"HUB_API_KEY={api_key}\n"
            f"DB_PASSWORD=archie_node_default\n"
            f"OLLAMA_PORT=11434\n"
            f"NODE_API_PORT=3001\n"
            f"COMFYUI_PORT=8188\n"
        )

        scripts = {}
        for script_name in [
            "start.bat",
            "stop.bat",
            "update.bat",
            "cleanup.bat",
            "start.command",
            "stop.command",
            "update.command",
            "cleanup.command",
        ]:
            script_path = os.path.join(NODE_CLIENT_DIR, script_name)
            if os.path.exists(script_path):
                with open(script_path) as f:
                    scripts[script_name] = f.read()

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("docker-compose.yml", compose_content)
            zf.writestr(".env", env_content)
            for name, content in scripts.items():
                zf.writestr(name, content)
            zf.writestr(
                "README.txt",
                "A.R.C.H.I.E. Node — by Kytran Empowerment\n"
                "==========================================\n\n"
                "Prerequisites:\n"
                "  1. Install Docker Desktop from https://docker.com/products/docker-desktop\n"
                "  2. Start Docker Desktop\n\n"
                "Setup:\n"
                "  1. Extract this folder anywhere on your computer\n"
                "  2. Double-click start.bat (Windows) or start.command (Mac)\n"
                "  3. Wait ~2 minutes for containers to download and start\n"
                "  4. Your node will appear in the fleet automatically\n\n"
                "Commands:\n"
                "  start.bat / start.command     - Start the node\n"
                "  stop.bat / stop.command       - Stop the node\n"
                "  update.bat / update.command   - Update to latest version\n"
                "  cleanup.bat / cleanup.command - Remove old install + free disk space\n\n"
                f"Node ID: {node_id}\n"
                f"Hub: {external_url}\n",
            )
        buf.seek(0)

        safe_name = node_name.replace(" ", "-").lower()
        return Response(
            buf.read(),
            mimetype="application/zip",
            headers={"Content-Disposition": f'attachment; filename="ARCHIE-Node-{safe_name}.zip"'},
        )

    # ========================================================================
    # STATION COMMANDS
    # ========================================================================

    @bp.route("/api/station-commands", methods=["GET"])
    @login_required
    def api_get_station_commands():
        """Get all station commands, optionally filtered by station."""
        station_code = request.args.get("station_code")

        with get_db_cursor() as (conn, cur):
            if station_code:
                cur.execute(
                    """
                    SELECT sc.*, COALESCE(bs.station_code, 'UNKNOWN') as station_code
                    FROM station_commands sc
                    LEFT JOIN bridge_stations bs ON bs.id = sc.station_id
                    WHERE COALESCE(bs.station_code, '') = %s AND sc.is_active = true
                    ORDER BY sc.command_name
                    """,
                    (station_code,),
                )
            else:
                cur.execute(
                    """
                    SELECT sc.*, COALESCE(bs.station_code, 'UNKNOWN') as station_code
                    FROM station_commands sc
                    LEFT JOIN bridge_stations bs ON bs.id = sc.station_id
                    WHERE sc.is_active = true
                    ORDER BY station_code, sc.command_name
                    """
                )
            commands = cur.fetchall()

        return jsonify({"commands": [dict(c) for c in commands]})

    @bp.route("/api/station-commands/execute", methods=["POST"])
    @login_required
    def api_execute_station_command():
        """Execute a station command via Smart Relay triage flow."""
        data = request.get_json()
        command_id = data.get("command_id")
        prompt = data.get("prompt", "")

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT sc.*, COALESCE(bs.station_code, 'UNKNOWN') as station_code
                FROM station_commands sc
                LEFT JOIN bridge_stations bs ON bs.id = sc.station_id
                WHERE sc.id = %s AND sc.is_active = true
                """,
                (command_id,),
            )
            command = cur.fetchone()

        if not command:
            return jsonify({"error": "Command not found"}), 404

        from tools.department_hq.services.bridge_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()

        result = dispatcher.request_work(
            capability=command["capability"],
            prompt=prompt or command["description"],
            module_id="station_command",
        )

        return jsonify(
            {
                "command": command["command_name"],
                "station": command["station_code"],
                "result": result,
            }
        )

    # ========================================================================
    # FLEET-WIDE STATS (VRAM / RAM per node)
    # ========================================================================

    @bp.route("/api/fleet-stats")
    @login_required
    def api_fleet_stats():
        """Return live VRAM/RAM usage per node for fleet overview."""
        user_id = current_user.id
        try:
            with get_db_cursor() as (conn, cur):
                # All nodes visible to this user with hardware specs
                cur.execute(
                    """
                    SELECT rn.id, rn.node_id, rn.node_name, rn.hostname, rn.port,
                           rn.status, rn.is_active, rn.last_heartbeat,
                           rn.ram_gb, rn.gpu_model, rn.gpu_vram_gb,
                           rn.cpu_model, rn.cpu_cores, rn.deployment_mode,
                           -- Latest heartbeat metrics (correlated subquery)
                           hb.cpu_usage, hb.memory_usage, hb.gpu_usage, hb.current_load,
                           hb.details AS hb_details,
                           -- Active agent count on this node
                           (SELECT COUNT(*) FROM node_agents na
                            WHERE na.node_id = rn.id AND na.status = 'active') AS agent_count,
                           -- Loaded model count from node_ollama_models
                           (SELECT COUNT(*) FROM node_ollama_models nom
                            WHERE nom.node_id = rn.node_id AND nom.is_available = true) AS models_loaded
                    FROM remote_nodes rn
                    LEFT JOIN LATERAL (
                        SELECT cpu_usage, memory_usage, gpu_usage, current_load, details
                        FROM node_heartbeats nh
                        WHERE nh.node_id = rn.id
                        ORDER BY nh.created_at DESC
                        LIMIT 1
                    ) hb ON true
                    WHERE rn.registered_by = %s OR rn.registered_by IS NULL
                    ORDER BY rn.bridge_priority DESC, rn.node_name
                    """,
                    (user_id,),
                )
                nodes_raw = cur.fetchall()

                # For VRAM used, sum model sizes from node_ollama_models
                node_vram_used = {}
                if nodes_raw:
                    node_ids = [n["node_id"] for n in nodes_raw]
                    cur.execute(
                        """
                        SELECT node_id, COALESCE(SUM(model_size_gb), 0) AS total_vram_used
                        FROM node_ollama_models
                        WHERE node_id = ANY(%s) AND is_available = true
                        GROUP BY node_id
                        """,
                        (node_ids,),
                    )
                    for row in cur.fetchall():
                        node_vram_used[row["node_id"]] = float(row["total_vram_used"])

            nodes = []
            for n in nodes_raw:
                computed_status = _compute_node_status(n)
                ram_total = float(n["ram_gb"]) if n["ram_gb"] else 0
                vram_total = float(n["gpu_vram_gb"]) if n["gpu_vram_gb"] else 0
                mem_pct = float(n["memory_usage"]) if n["memory_usage"] and computed_status != "offline" else 0
                cpu_pct = float(n["cpu_usage"]) if n["cpu_usage"] and computed_status != "offline" else 0
                gpu_pct = float(n["gpu_usage"]) if n["gpu_usage"] and computed_status != "offline" else 0

                ram_used = round(ram_total * mem_pct / 100, 1) if ram_total else 0
                vram_used = round(node_vram_used.get(n["node_id"], 0), 1)

                # Extract outpost-specific data from heartbeat details
                hb_details = n.get("hb_details") or {}
                uptime_secs = hb_details.get("uptime", 0) if computed_status != "offline" else 0
                services_count = sum(1 for v in hb_details.values() if v is True) if hb_details else 0

                nodes.append(
                    {
                        "node_id": n["node_id"],
                        "node_name": n["node_name"],
                        "hostname": n["hostname"],
                        "status": computed_status,
                        "deployment_mode": n["deployment_mode"],
                        "ram_total": ram_total,
                        "ram_used": ram_used,
                        "vram_total": vram_total,
                        "vram_used": vram_used,
                        "agent_count": n["agent_count"] or 0,
                        "models_loaded": n["models_loaded"] or 0,
                        "cpu_usage": round(cpu_pct, 1),
                        "gpu_usage": round(gpu_pct, 1),
                        "gpu_model": n["gpu_model"],
                        "cpu_model": n["cpu_model"],
                        "cpu_cores": n["cpu_cores"],
                        "mem_usage": round(mem_pct, 1),
                        "uptime_secs": uptime_secs,
                        "services_count": services_count,
                    }
                )

            # Fleet totals
            total_ram = sum(nd["ram_total"] for nd in nodes)
            total_ram_used = sum(nd["ram_used"] for nd in nodes)
            total_vram = sum(nd["vram_total"] for nd in nodes)
            total_vram_used = sum(nd["vram_used"] for nd in nodes)
            total_agents = sum(nd["agent_count"] for nd in nodes)
            total_models = sum(nd["models_loaded"] for nd in nodes)

            return jsonify(
                {
                    "success": True,
                    "fleet_totals": {
                        "node_count": len(nodes),
                        "online_count": sum(1 for nd in nodes if nd["status"] != "offline"),
                        "ram_total": round(total_ram, 1),
                        "ram_used": round(total_ram_used, 1),
                        "vram_total": round(total_vram, 1),
                        "vram_used": round(total_vram_used, 1),
                        "agent_count": total_agents,
                        "models_loaded": total_models,
                    },
                    "nodes": nodes,
                }
            )
        except Exception as e:
            logger.error(f"Fleet stats error: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # ONE-CLICK SETUP SCRIPT DOWNLOADS
    # ========================================================================

    @bp.route("/api/nodes/<node_id>/setup-script")
    @login_required
    def api_node_setup_script(node_id):
        """Download a customized setup/update script for an existing node."""
        user_id = current_user.id
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        os_type = request.args.get("os", "linux").lower()
        hub_url = os.environ.get("STARSHIP_HUB_URL", "https://platform.kytranempowerment.com")
        token = node.get("setup_token", "")
        node_name = node.get("node_name", "Starship Node")

        if os_type == "windows":
            script = _generate_setup_ps1(hub_url, node_id, token, node_name)
            return Response(
                script,
                mimetype="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="archie-setup-{node_id}.ps1"'},
            )
        else:
            script = _generate_setup_sh(hub_url, node_id, token, node_name)
            return Response(
                script,
                mimetype="application/octet-stream",
                headers={"Content-Disposition": f'attachment; filename="archie-setup-{node_id}.sh"'},
            )

    @bp.route("/api/nodes/new-setup-script")
    @login_required
    def api_new_node_setup_script():
        """Auto-register a NEW node and return a downloadable setup script.

        For the one-line curl/powershell flow: registers a pending node,
        then returns the install script with credentials baked in.

        Query params:
          os          — linux (default) | windows
          name        — human-readable node name (optional)
          mesh_ip     — Headscale mesh IP (100.64.x.x) if known ahead of time (optional)
          format      — json → return {command_linux, command_windows} for the UI modal
          deployment_mode — starship (default) | starbase_outpost
        """

        user_id = current_user.id
        os_type = request.args.get("os", "linux").lower()
        node_name = request.args.get("name", "").strip()
        mesh_ip_param = (request.args.get("mesh_ip") or "").strip()
        deployment_mode = request.args.get("deployment_mode", "starship").strip()
        if deployment_mode not in ("starship", "starbase_outpost", "satellite"):
            deployment_mode = "starship"

        # Validate mesh IP if provided
        if mesh_ip_param and not validate_mesh_ip(mesh_ip_param):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Invalid mesh IP: {mesh_ip_param!r}. Must be in 100.64.0.0/10.",
                    }
                ),
                400,
            )

        # Generate unique node ID and setup token
        # Prefix reflects deployment tier: outpost for VPS nodes, starship for LAN GPU nodes
        _id_prefix = (
            "outpost"
            if deployment_mode == "starbase_outpost"
            else ("satellite" if deployment_mode == "satellite" else "starship")
        )
        node_id = f"{_id_prefix}_{secrets.token_hex(8)}"
        setup_token = secrets.token_urlsafe(32)
        if not node_name:
            _name_prefix = (
                "Outpost"
                if deployment_mode == "starbase_outpost"
                else ("Satellite" if deployment_mode == "satellite" else "Starship")
            )
            node_name = f"{_name_prefix}-{secrets.token_hex(3).upper()}"

        # Two-phase URLs (2026-05-25 user mandate):
        # hub_url      = mesh IP — used for ALL in-script API calls (post-Headscale enrollment)
        # hub_public_url = public HTTPS URL — used only for the one-liner curl download command
        #                  (VPS cannot reach 100.64.0.4 before joining Headscale)
        hub_url = os.environ.get(
            "HUB_MESH_URL",
            os.environ.get("STARSHIP_HUB_URL", "http://100.64.0.4:3000"),
        )
        hub_public_url = os.environ.get("HUB_PUBLIC_URL", "https://platform.kytranempowerment.com")

        # Generate Headscale pre-auth key so the setup script can join the mesh
        # automatically without any manual console steps.
        headscale_authkey = ""
        try:
            import subprocess

            hs_result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "archie_headscale",
                    "headscale",
                    "preauthkeys",
                    "create",
                    "--user",
                    "archie-fleet",
                    "--expiration",
                    "24h",
                    "--reusable",
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if hs_result.returncode == 0:
                lines = [l.strip() for l in hs_result.stdout.strip().splitlines() if l.strip()]
                headscale_authkey = lines[-1] if lines else ""
                logger.info("Generated Headscale auth key for node %s", node_id)
            else:
                logger.warning("headscale preauthkeys create failed: %s", hs_result.stderr[:200])
        except Exception:
            logger.warning(
                "Could not generate Headscale auth key (docker exec unavailable?)",
                exc_info=True,
            )

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO remote_nodes (
                        node_id, node_name, deployment_mode, status,
                        is_active, bridge_enabled, bridge_priority,
                        approval_status, user_id, setup_token,
                        api_key_hash, privacy_settings,
                        mesh_ip, hostname
                    ) VALUES (
                        %s, %s, %s, 'pending',
                        false, false, 50,
                        'pending', %s, %s,
                        %s, '{}'::jsonb,
                        %s, %s
                    )
                    RETURNING id, node_id, node_name
                    """,
                    (
                        node_id,
                        node_name,
                        deployment_mode,
                        user_id,
                        setup_token,
                        hash_api_key(setup_token),
                        mesh_ip_param or None,
                        mesh_ip_param or None,  # hostname = mesh_ip when provided
                    ),
                )
                cur.fetchone()

            # JSON mode — return credentials + copy-paste commands for the UI modal
            if request.args.get("format") == "json":
                cmd_linux = _generate_setup_sh(
                    hub_public_url,  # shown in script banner only
                    node_id,
                    setup_token,
                    node_name,
                    headscale_authkey=headscale_authkey,
                    mesh_ip=mesh_ip_param,
                    hub_mesh_url=hub_url,  # ALL in-script API calls use mesh IP
                    deployment_mode=deployment_mode,
                )
                # One-liner uses PUBLIC URL — VPS cannot reach 100.64.0.4 before Headscale join.
                # The /install endpoint serves the script; inside it HUB_URL = mesh IP.
                cmd_linux_oneliner = (
                    f"curl -fsSL '{hub_public_url}/tools/department-hq/install?token={setup_token}' | sudo bash"
                )
                _generate_setup_ps1(hub_public_url, node_id, setup_token, node_name)
                cmd_win_oneliner = f"iex (iwr '{hub_public_url}/tools/department-hq/install?token={setup_token}' -UseBasicParsing).Content"
                # Satellite: the "command" is the full bash script (no one-liner curl wrapper needed
                # since the script itself is minimal and can be pasted directly into any terminal).
                cmd_satellite = cmd_linux if deployment_mode == "satellite" else None
                mobile_enroll_url = (
                    f"{hub_public_url}/tools/department-hq/fleet/satellite/enroll?token={setup_token}"
                    if deployment_mode == "satellite"
                    else None
                )
                resp = {
                    "success": True,
                    "node_id": node_id,
                    "node_name": node_name,
                    "setup_token": setup_token,
                    "command_linux": cmd_linux_oneliner,
                    "command_windows": cmd_win_oneliner,
                }
                if cmd_satellite:
                    resp["command_satellite"] = cmd_satellite
                if mobile_enroll_url:
                    resp["mobile_enroll_url"] = mobile_enroll_url
                if headscale_authkey:
                    resp["headscale_authkey"] = headscale_authkey
                return jsonify(resp)

            if os_type == "windows":
                # Prefer the pre-built GUI installer .exe — check static/downloads first, then installer/dist
                exe_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    "static",
                    "downloads",
                    "ARCHIE-Node-Setup.exe",
                )
                if not os.path.isfile(exe_path):
                    exe_path = os.path.join(NODE_CLIENT_DIR, "installer", "dist", "ARCHIE-Node-Setup.exe")
                if os.path.isfile(exe_path):
                    logger.info("Serving pre-built ARCHIE-Node-Setup.exe installer")
                    return send_file(
                        exe_path,
                        mimetype="application/octet-stream",
                        as_attachment=True,
                        download_name="ARCHIE-Node-Setup.exe",
                    )

                # Fallback: generate a .bat wrapper with embedded PowerShell
                ps1_script = _generate_setup_ps1(hub_url, node_id, setup_token, node_name)
                safe_name = node_name.replace(" ", "-")
                ps1_path = f"%TEMP%\\archie-node-{safe_name}.ps1"
                bat = "@echo off\r\n"
                bat += "title A.R.C.H.I.E. Starship Node Setup\r\n"
                bat += "echo.\r\n"
                bat += "echo   ========================================\r\n"
                bat += "echo   A.R.C.H.I.E. STARSHIP NODE SETUP\r\n"
                bat += f"echo   Node: {node_name}\r\n"
                bat += "echo   ========================================\r\n"
                bat += "echo.\r\n"
                bat += "echo   Writing setup script...\r\n"
                import base64

                ps1_bytes = ps1_script.encode("utf-16-le")
                ps1_b64 = base64.b64encode(ps1_bytes).decode("ascii")
                bat += f"powershell -ExecutionPolicy Bypass -EncodedCommand {ps1_b64}\r\n"
                bat += "echo.\r\n"
                bat += "pause\r\n"
                return Response(
                    bat,
                    mimetype="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="ARCHIE-Node-Setup-{safe_name}.bat"'},
                )
            else:
                script = _generate_setup_sh(
                    hub_url,
                    node_id,
                    setup_token,
                    node_name,
                    deployment_mode=deployment_mode,
                )
                return Response(
                    script,
                    mimetype="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="archie-setup-{node_id}.sh"'},
                )
        except Exception:
            logger.exception("Failed to create new node setup script")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    @bp.route("/api/nodes/<node_id>/disconnect", methods=["DELETE"])
    @login_required
    def api_disconnect_node(node_id):
        """Disconnect a node from the fleet. Returns deployed agents to barracks."""
        user_id = current_user.id
        node = _get_node_for_user(node_id, user_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        if node["deployment_mode"] == "starbase":
            return (
                jsonify({"success": False, "error": "Cannot disconnect the Starbase"}),
                400,
            )

        try:
            node_db_id = node["id"]

            # Fetch the deployed hub agents linked to this node so we can
            # return them to barracks via agent_service (Project #241
            # Track C.3 straggler — this site was missed by the original
            # Track A audit).
            with get_db_cursor(commit=False) as (_conn, _cur):
                _cur.execute(
                    """SELECT hub_agent_id FROM node_agents
                       WHERE node_id = %s AND hub_agent_id IS NOT NULL""",
                    (node_db_id,),
                )
                _hub_ids = [r["hub_agent_id"] if isinstance(r, dict) else r[0] for r in _cur.fetchall()]

            from services import agent_service as _svc

            returned = 0
            for _aid in _hub_ids:
                _existing = _svc.get_agent(_aid)
                if _existing and _existing.get("shift_state") == "deployed":
                    _svc.barracks(_aid)
                    returned += 1

            with get_db_cursor(commit=True) as (conn, cur):
                # Delete node agents
                cur.execute("DELETE FROM node_agents WHERE node_id = %s", (node_db_id,))

                # Delete station assignments
                cur.execute(
                    "DELETE FROM node_station_assignments WHERE node_id = %s",
                    (node_db_id,),
                )

                # Delete heartbeat history
                cur.execute("DELETE FROM node_heartbeats WHERE node_id = %s", (node_db_id,))

                # Delete the node itself
                cur.execute("DELETE FROM remote_nodes WHERE id = %s", (node_db_id,))

                # Log notification
                cur.execute(
                    """INSERT INTO system_notifications (type, title, message, created_at)
                       VALUES ('warning', 'Node Disconnected',
                               %s, NOW())""",
                    (f"Node {node['node_name']} disconnected from fleet. {returned} agents returned to barracks.",),
                )

            logger.info(f"Node {node['node_name']} disconnected — {returned} agents returned to barracks")
            return jsonify(
                {
                    "success": True,
                    "message": f"Node disconnected. {returned} agents returned to barracks.",
                    "agents_returned": returned,
                }
            )
        except Exception as e:
            logger.error(f"Failed to disconnect node {node_id}: {e}")
            return jsonify({"success": False, "error": "Internal server error"}), 500

    # ========================================================================
    # SSH TOGGLE
    # ========================================================================

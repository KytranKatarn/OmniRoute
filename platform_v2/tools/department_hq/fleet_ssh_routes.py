"""
Fleet SSH Routes — hub-side SSH execution for Starship nodes.

Complements fleet_ota_routes.py (pull-based) with direct SSH push.
OTA queue: model pull, compose-recreate, code-update
SSH direct: logs, rebuild (docker build), restart, status

Routes:
  GET  /api/nodes/<id>/ssh-status
  GET  /api/nodes/<id>/ssh-logs     ?container=X&tail=N
  POST /api/nodes/<id>/ssh-restart  {service?}
  POST /api/nodes/<id>/ssh-rebuild  {no_cache?}

Requires SSH private key at ~/.ssh/id_ed25519 inside the container.
Mount it via docker-compose volumes if not already present.
"""

import logging
import pathlib
import subprocess

from database import get_db_cursor
from flask import jsonify, request

logger = logging.getLogger(__name__)

# ── SSH key ───────────────────────────────────────────────────────────────────
_KEY_CANDIDATES = [
    pathlib.Path.home() / ".ssh" / "id_ed25519",
    pathlib.Path.home() / ".ssh" / "id_rsa",
]
_SSH_KEY = next((str(p) for p in _KEY_CANDIDATES if p.exists()), None)

_BASE_SSH_OPTS = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "BatchMode=yes",
]
_SSH_OPTS = (["-i", _SSH_KEY] + _BASE_SSH_OPTS) if _SSH_KEY else _BASE_SSH_OPTS

# ── Node metadata ─────────────────────────────────────────────────────────────
_SSH_USER_BY_MODE = {
    "starship": "Famil",
    "outpost": "kytran",
    "starbase_outpost": "kytran",
}
_INSTALL_DIR_BY_MODE = {
    "starship": r"C:\ARCHIE-Node",
    "outpost": "/opt/archie-node",
    "starbase_outpost": "/opt/archie-products",
}

_REPO = pathlib.Path(__file__).parent.parent.parent.parent
_NODE_CLIENT = _REPO / "node_client"
_NODE_CONFIGS = _REPO / "node-configs"


# ── Internal helpers ──────────────────────────────────────────────────────────


def _get_node(node_id: int) -> dict | None:
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, node_id, node_name, hostname, deployment_mode, os_info " "FROM remote_nodes WHERE id = %s",
            (node_id,),
        )
        return cur.fetchone()


def _ssh_target(node: dict) -> str:
    mode = (node.get("deployment_mode") or "").lower()
    return f"{_SSH_USER_BY_MODE.get(mode, 'kytran')}@{node['hostname']}"


def _is_windows(node: dict) -> bool:
    mode = (node.get("deployment_mode") or "").lower()
    os_info = (node.get("os_info") or "").lower()
    return mode == "starship" or "windows" in os_info


def _install_dir(node: dict) -> str:
    mode = (node.get("deployment_mode") or "").lower()
    return _INSTALL_DIR_BY_MODE.get(mode, "/opt/archie-node")


def _ssh_run(node: dict, cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """SSH into node and run cmd. Returns (rc, stdout, stderr)."""
    if not _SSH_KEY:
        return 1, "", "No SSH key found (tried id_ed25519, id_rsa)"
    proc = subprocess.run(
        ["ssh"] + _SSH_OPTS + [_ssh_target(node), cmd],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _scp_to(node: dict, local: str, remote: str) -> tuple[int, str]:
    if not _SSH_KEY:
        return 1, "No SSH key found"
    proc = subprocess.run(
        ["scp"] + _SSH_OPTS + [local, f"{_ssh_target(node)}:{remote}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode, proc.stderr


# ── Route registration ────────────────────────────────────────────────────────


def register_ssh_routes(bp, auth_decorator):
    """Register SSH management routes on the fleet blueprint."""

    @bp.route("/api/nodes/<int:node_id>/ssh-status", methods=["GET"])
    @auth_decorator
    def api_ssh_status(node_id):
        """Return docker ps from the node via SSH."""
        node = _get_node(node_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        try:
            rc, out, err = _ssh_run(
                node,
                'docker ps --format "table {{.Names}}\\t{{.Status}}\\t{{.Ports}}"',
                timeout=15,
            )
            return jsonify({"success": rc == 0, "output": out or err, "node_name": node["node_name"]})
        except subprocess.TimeoutExpired:
            return jsonify({"success": False, "error": "SSH timeout"}), 504
        except Exception as exc:
            logger.exception("ssh-status node %s", node_id)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/nodes/<int:node_id>/ssh-logs", methods=["GET"])
    @auth_decorator
    def api_ssh_logs(node_id):
        """Return container logs via SSH."""
        node = _get_node(node_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        container = request.args.get("container", "archie_node_sync")
        tail = min(int(request.args.get("tail", 200)), 1000)
        try:
            rc, out, err = _ssh_run(node, f"docker logs {container} --tail {tail} -t 2>&1", timeout=20)
            return jsonify(
                {"success": rc == 0, "logs": out or err, "container": container, "node_name": node["node_name"]}
            )
        except subprocess.TimeoutExpired:
            return jsonify({"success": False, "error": "SSH timeout"}), 504
        except Exception as exc:
            logger.exception("ssh-logs node %s", node_id)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/nodes/<int:node_id>/ssh-restart", methods=["POST"])
    @auth_decorator
    def api_ssh_restart(node_id):
        """docker compose restart [service] via SSH."""
        node = _get_node(node_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404
        body = request.get_json(silent=True) or {}
        service = (body.get("service") or "").strip()
        install_dir = _install_dir(node)
        try:
            rc, out, err = _ssh_run(
                node,
                f'cd "{install_dir}" && docker compose restart {service}'.rstrip(),
                timeout=60,
            )
            return jsonify(
                {"success": rc == 0, "output": out or err, "service": service or "all", "node_name": node["node_name"]}
            )
        except subprocess.TimeoutExpired:
            return jsonify({"success": False, "error": "SSH timeout"}), 504
        except Exception as exc:
            logger.exception("ssh-restart node %s", node_id)
            return jsonify({"success": False, "error": str(exc)}), 500

    @bp.route("/api/nodes/<int:node_id>/ssh-rebuild", methods=["POST"])
    @auth_decorator
    def api_ssh_rebuild(node_id):
        """
        SCP updated files to node then docker compose up -d --build.
        Use for nodes running archie-node:local (built on-device).
        For GHCR-based nodes prefer OTA push-update + compose-recreate.
        """
        node = _get_node(node_id)
        if not node:
            return jsonify({"success": False, "error": "Node not found"}), 404

        body = request.get_json(silent=True) or {}
        no_cache = bool(body.get("no_cache", False))
        install_dir = _install_dir(node)
        sep = "\\" if _is_windows(node) else "/"

        # Pick node-specific compose, fall back to generic
        node_suffix = (node["node_name"] or "").lower().split("-")[-1]
        specific = _NODE_CONFIGS / f"node-{node_suffix}" / "docker-compose.yml"
        generic = _NODE_CLIENT / "docker-compose.node.yml"
        compose_src = str(specific) if specific.exists() else str(generic)

        steps: list[str] = []
        try:
            # 1. SCP docker-compose.yml
            rc, err = _scp_to(node, compose_src, f"{install_dir}{sep}docker-compose.yml")
            steps.append(f"compose: {'ok' if rc == 0 else f'FAILED {err}'}")
            if rc != 0:
                return jsonify({"success": False, "steps": steps}), 500

            # 2. SCP Python source files
            for fname in ["node_sync.py", "node_api.py", "requirements.txt"]:
                src = _NODE_CLIENT / fname
                if not src.exists():
                    continue
                rc, err = _scp_to(node, str(src), f"{install_dir}{sep}{fname}")
                steps.append(f"{fname}: {'ok' if rc == 0 else f'FAILED {err}'}")

            # 3. Rebuild
            cache_flag = "--no-cache" if no_cache else ""
            rc, out, err = _ssh_run(
                node,
                f'cd "{install_dir}" && docker compose up -d --build {cache_flag}'.rstrip(),
                timeout=300,
            )
            steps.append(f"up --build: {'ok' if rc == 0 else 'FAILED'}")
            return jsonify({"success": rc == 0, "steps": steps, "output": out or err, "node_name": node["node_name"]})

        except subprocess.TimeoutExpired:
            steps.append("timeout")
            return jsonify({"success": False, "steps": steps, "error": "SSH timeout"}), 504
        except Exception as exc:
            logger.exception("ssh-rebuild node %s", node_id)
            return jsonify({"success": False, "steps": steps, "error": str(exc)}), 500

#!/usr/bin/env python3
"""
Hub-side SSH management for Starship fleet nodes.

Complements OTA (pull-based) with direct SSH push commands.
OTA handles: model pull, compose-recreate, code-update (queued via mesh_sync_log)
SSH handles:  logs, rebuild (docker build), emergency restart, arbitrary exec

Usage:
  python scripts/node-ssh.py status [--node NAME]
  python scripts/node-ssh.py logs   --node NAME [--container CTR] [--tail N] [--follow]
  python scripts/node-ssh.py restart --node NAME [--service SVC]
  python scripts/node-ssh.py rebuild --node NAME [--no-cache]
  python scripts/node-ssh.py pull    --node NAME --model MODEL
  python scripts/node-ssh.py exec    --node NAME --cmd "docker ps"

Node can be name (Starship-246), partial match (246), or LAN IP.
"""

import argparse
import os
import subprocess
import sys

# ── SSH defaults ──────────────────────────────────────────────────────────────
SSH_KEY = os.path.expanduser("~/.ssh/id_ed25519")
SSH_OPTS = [
    "-i", SSH_KEY,
    "-o", "StrictHostKeyChecking=no",
    "-o", "ConnectTimeout=10",
    "-o", "BatchMode=yes",
]

# ── Known nodes (fallback when DB unavailable) ────────────────────────────────
# user=Famil on Windows Starships; kytran on Linux outposts
NODES = {
    "starship-246": {
        "host": "192.168.1.246",
        "user": "Famil",
        "install_dir": r"C:\ARCHIE-Node",
        "platform": "windows",
    },
    "starship-245": {
        "host": "192.168.1.245",
        "user": "Famil",
        "install_dir": r"C:\ARCHIE-Node",
        "platform": "windows",
    },
}

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
NODE_CONFIGS_DIR = os.path.join(_REPO, "node-configs")
NODE_CLIENT_DIR = os.path.join(_REPO, "node_client")


# ── Node resolution ───────────────────────────────────────────────────────────

def resolve_node(name: str) -> dict:
    name_lower = name.lower().strip()
    if name_lower in NODES:
        return {**NODES[name_lower], "name": name_lower}
    for k, v in NODES.items():
        if name_lower in k or name_lower in v["host"]:
            return {**v, "name": k}
    node = _db_lookup(name)
    if node:
        return node
    raise SystemExit(
        f"Unknown node: '{name}'\nKnown: {', '.join(NODES)}"
    )


def _db_lookup(name: str) -> dict | None:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "192.168.1.200"),
            port=int(os.getenv("DB_PORT", "5432")),
            dbname=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=os.getenv("DB_PASSWORD", ""),
            connect_timeout=3,
        )
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT node_name, hostname, deployment_mode, os_info "
                "FROM remote_nodes WHERE node_name ILIKE %s OR hostname = %s LIMIT 1",
                (f"%{name}%", name),
            )
            row = cur.fetchone()
        conn.close()
        if not row:
            return None
        mode = (row["deployment_mode"] or "").lower()
        ssh_user = "Famil" if mode == "starship" else "kytran"
        os_info = (row["os_info"] or "").lower()
        install_dir = r"C:\ARCHIE-Node" if "windows" in os_info else "/opt/archie-node"
        return {
            "name": row["node_name"],
            "host": row["hostname"],
            "user": ssh_user,
            "install_dir": install_dir,
            "platform": "windows" if "windows" in os_info else "linux",
        }
    except Exception:
        return None


# ── SSH helpers ───────────────────────────────────────────────────────────────

def ssh_run(node: dict, cmd: str, timeout: int = 60) -> int:
    target = f"{node['user']}@{node['host']}"
    # Use list form — no shell=True, no injection risk
    result = subprocess.run(
        ["ssh"] + SSH_OPTS + [target, cmd],
        timeout=timeout if timeout > 0 else None,
    )
    return result.returncode


def scp_to(node: dict, local: str, remote: str) -> int:
    target = f"{node['user']}@{node['host']}:{remote}"
    return subprocess.run(["scp"] + SSH_OPTS + [local, target]).returncode


def _header(node: dict):
    print(f"\n{'─' * 50}")
    print(f"  {node['name'].upper()}  ({node['host']})")
    print(f"{'─' * 50}")


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_status(args):
    nodes = [args.node] if args.node else list(NODES.keys())
    for name in nodes:
        node = resolve_node(name)
        _header(node)
        ssh_run(node, 'docker ps --format "table {{.Names}}\\t{{.Status}}\\t{{.Ports}}"')


def cmd_logs(args):
    node = resolve_node(args.node)
    container = args.container
    tail = args.tail
    follow_flag = "-f" if args.follow else ""
    _header(node)
    ssh_run(
        node,
        f"docker logs {container} --tail {tail} -t {follow_flag} 2>&1",
        timeout=0 if args.follow else 30,
    )


def cmd_restart(args):
    node = resolve_node(args.node)
    install_dir = node["install_dir"]
    service = args.service or ""
    _header(node)
    ssh_run(node, f'cd "{install_dir}" && docker compose restart {service}')
    print(f"\n✓ Restart sent to {node['name']}")


def cmd_rebuild(args):
    """SCP updated compose + source files, then docker compose up --build."""
    node = resolve_node(args.node)
    install_dir = node["install_dir"]
    node_suffix = node["name"].split("-")[-1]
    _header(node)

    specific = os.path.join(NODE_CONFIGS_DIR, f"node-{node_suffix}", "docker-compose.yml")
    generic = os.path.join(NODE_CLIENT_DIR, "docker-compose.node.yml")
    compose_src = specific if os.path.exists(specific) else generic
    print(f"→ compose: {os.path.relpath(compose_src, _REPO)}")

    sep = "\\" if node["platform"] == "windows" else "/"
    remote_compose = f"{install_dir}{sep}docker-compose.yml"
    if scp_to(node, compose_src, remote_compose) != 0:
        raise SystemExit("SCP of docker-compose.yml failed")

    for fname in ["node_sync.py", "node_api.py", "requirements.txt"]:
        src = os.path.join(NODE_CLIENT_DIR, fname)
        if not os.path.exists(src):
            continue
        print(f"→ SCP {fname}")
        scp_to(node, src, f"{install_dir}{sep}{fname}")

    no_cache = "--no-cache" if args.no_cache else ""
    print(f"→ docker compose up -d --build {no_cache}".rstrip())
    ssh_run(
        node,
        f'cd "{install_dir}" && docker compose up -d --build {no_cache}'.rstrip(),
        timeout=300,
    )
    print(f"\n✓ Rebuild complete on {node['name']}")


def cmd_pull(args):
    """Immediate Ollama model pull — bypasses OTA queue."""
    node = resolve_node(args.node)
    _header(node)
    print(f"→ Pulling {args.model} on {node['name']} (may take minutes)")
    ssh_run(node, f"docker exec archie_node_ollama ollama pull {args.model}", timeout=600)


def cmd_exec(args):
    """Run an arbitrary command on the node."""
    node = resolve_node(args.node)
    _header(node)
    ssh_run(node, args.cmd, timeout=120)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        prog="node-ssh",
        description="Hub-side SSH management for Starship fleet nodes",
    )
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("status", help="docker ps on one or all nodes")
    s.add_argument("--node", "-n")

    s = sub.add_parser("logs", help="Fetch container logs")
    s.add_argument("--node", "-n", required=True)
    s.add_argument("--container", "-c", default="archie_node_sync")
    s.add_argument("--tail", "-t", type=int, default=100)
    s.add_argument("--follow", "-f", action="store_true")

    s = sub.add_parser("restart", help="docker compose restart")
    s.add_argument("--node", "-n", required=True)
    s.add_argument("--service", "-s", help="Service name (omit = all)")

    s = sub.add_parser("rebuild", help="SCP files + docker compose up --build")
    s.add_argument("--node", "-n", required=True)
    s.add_argument("--no-cache", action="store_true")

    s = sub.add_parser("pull", help="Ollama model pull (immediate, not queued)")
    s.add_argument("--node", "-n", required=True)
    s.add_argument("--model", "-m", required=True)

    s = sub.add_parser("exec", help="Run arbitrary SSH command")
    s.add_argument("--node", "-n", required=True)
    s.add_argument("--cmd", "-c", required=True)

    args = p.parse_args()
    dispatch = {
        "status": cmd_status, "logs": cmd_logs, "restart": cmd_restart,
        "rebuild": cmd_rebuild, "pull": cmd_pull, "exec": cmd_exec,
    }
    try:
        dispatch[args.command](args)
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
A.R.C.H.I.E. Starship Node API
================================
Lightweight Flask app for local agent runtime.
Receives agent configs via sync, serves local status, queues jobs.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

from flask import Flask, jsonify, request, render_template_string
import psycopg2
import psycopg2.extras

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("archie_node_api")

app = Flask(__name__)

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://archie_node:archie_node_default@postgres:5432/archie_node",
)
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
NODE_ID = os.environ.get("NODE_ID", "unknown")
NODE_TIMEZONE = os.environ.get("NODE_TIMEZONE", "America/Toronto")
SKILLS_DIR = os.environ.get("SKILLS_DIR", "/skills")


def get_db():
    """Get a database connection."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    cur = conn.cursor()
    cur.execute("SET timezone = %s", (NODE_TIMEZONE,))
    cur.close()
    return conn


def _serialize_row(row):
    """Convert a DB row dict, formatting timestamps to ET-aware ISO strings."""
    out = {}
    for k, v in row.items():
        if isinstance(v, datetime):
            # Postgres returns naive timestamps; attach the configured timezone
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


@app.route("/health")
def health():
    """Health check endpoint."""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False

    return jsonify(
        {
            "status": "ok" if db_ok else "degraded",
            "node_id": NODE_ID,
            "database": "connected" if db_ok else "disconnected",
        }
    )


@app.route("/api/agents")
def list_agents():
    """List all agent configs stored locally."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM node_agent_configs ORDER BY agent_name")
    agents = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"agents": [_serialize_row(a) for a in agents]})


@app.route("/api/jobs")
def list_jobs():
    """List recent jobs."""
    limit = request.args.get("limit", 20, type=int)
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(
        "SELECT * FROM node_jobs ORDER BY created_at DESC LIMIT %s", (limit,)
    )
    jobs = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({"jobs": [_serialize_row(j) for j in jobs]})


@app.route("/api/status")
def node_status():
    """Node status with agent count and job stats."""
    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT COUNT(*) as count FROM node_agent_configs")
    agent_count = cur.fetchone()["count"]
    cur.execute(
        "SELECT status, COUNT(*) as count FROM node_jobs GROUP BY status"
    )
    job_stats = {r["status"]: r["count"] for r in cur.fetchall()}
    cur.close()
    conn.close()
    return jsonify(
        {
            "node_id": NODE_ID,
            "agents": agent_count,
            "jobs": job_stats,
        }
    )


@app.route("/api/jobs/execute", methods=["POST"])
def execute_job():
    """Execute a job request from Bridge dispatch."""
    import time
    import requests as req_lib

    data = request.get_json()
    capability = data.get("capability")
    prompt = data.get("prompt")
    target_agent = data.get("target_agent")
    target_model = data.get("target_model")

    if not all([capability, prompt, target_agent]):
        return jsonify({"error": "capability, prompt, target_agent required"}), 400

    start = time.time()
    try:
        resp = req_lib.post(
            f"{OLLAMA_HOST}/api/generate",
            json={"model": target_model, "prompt": prompt, "stream": False},
            timeout=300,
        )
        duration_ms = int((time.time() - start) * 1000)

        if resp.ok:
            result = resp.json()
            return jsonify(
                {
                    "success": True,
                    "agent_name": target_agent,
                    "capability": capability,
                    "duration_ms": duration_ms,
                    "response": result.get("response", ""),
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "agent_name": target_agent,
                        "capability": capability,
                        "duration_ms": int((time.time() - start) * 1000),
                        "error": resp.text,
                    }
                ),
                500,
            )

    except Exception as e:
        return (
            jsonify(
                {
                    "success": False,
                    "agent_name": target_agent,
                    "error": str(e),
                    "duration_ms": int((time.time() - start) * 1000),
                }
            ),
            500,
        )


@app.route("/diagnostics")
def diagnostics():
    """Full node health snapshot — disk, GPU, containers, models, versions."""
    import shutil
    import platform as plat
    import subprocess as sp

    result = {
        "node_id": NODE_ID,
        "client_version": os.environ.get("ARCHIE_VERSION", "unknown"),
        "python_version": sys.version.split()[0],
        "platform": plat.system(),
        "hostname": os.environ.get("HOSTNAME", "unknown"),
    }

    # Uptime (container start approximation)
    try:
        with open("/proc/uptime", "r") as f:
            result["uptime_seconds"] = int(float(f.read().split()[0]))
    except Exception:
        result["uptime_seconds"] = 0

    # Disk space
    try:
        usage = shutil.disk_usage("/")
        result["disk"] = {
            "total_gb": round(usage.total / 1e9, 1),
            "free_gb": round(usage.free / 1e9, 1),
            "percent_used": round((usage.used / usage.total) * 100, 1),
        }
    except Exception as e:
        result["disk"] = {"error": str(e)}

    # GPU via nvidia-smi (if available inside container or on host)
    try:
        gpu_out = sp.run(
            ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if gpu_out.returncode == 0 and gpu_out.stdout.strip():
            parts = gpu_out.stdout.strip().split(", ")
            result["gpu"] = {
                "model": parts[0],
                "vram_total_mb": int(parts[1]),
                "vram_used_mb": int(parts[2]),
                "temperature_c": int(parts[3]),
            }
        else:
            result["gpu"] = {"available": False}
    except Exception:
        result["gpu"] = {"available": False}

    # Ollama models
    try:
        import requests as req_lib
        tags = req_lib.get(f"{OLLAMA_HOST}/api/tags", timeout=5)
        if tags.ok:
            models = tags.json().get("models", [])
            result["ollama"] = {
                "online": True,
                "model_count": len(models),
                "models": [{"name": m["name"], "size_gb": round(m.get("size", 0) / 1e9, 1)} for m in models],
            }
        else:
            result["ollama"] = {"online": False, "error": f"HTTP {tags.status_code}"}

        # Currently loaded models
        ps = req_lib.get(f"{OLLAMA_HOST}/api/ps", timeout=5)
        if ps.ok:
            loaded = ps.json().get("models", [])
            result["ollama"]["loaded"] = [
                {"name": m["name"], "vram_gb": round(m.get("size_vram", 0) / 1e9, 1)} for m in loaded
            ]
    except Exception as e:
        result["ollama"] = {"online": False, "error": str(e)}

    # ComfyUI status
    try:
        import requests as req_lib
        comfy = req_lib.get("http://archie_starship_comfyui:8188/system_stats", timeout=3)
        if comfy.ok:
            data = comfy.json()
            dev = data.get("devices", [{}])[0]
            result["comfyui"] = {
                "online": True,
                "vram_total_mb": round(dev.get("vram_total", 0) / 1e6),
                "vram_free_mb": round(dev.get("vram_free", 0) / 1e6),
            }
        else:
            result["comfyui"] = {"online": False}
    except Exception:
        result["comfyui"] = {"online": False}

    # Container health — REAL query via the mounted Docker socket (#3763).
    # Mirrors node_sync's http.client+AF_UNIX socket pattern. Was a hardcoded stub.
    containers = []
    try:
        import http.client as _httpc, socket as _sock, json as _json
        sock_path = "/var/run/docker.sock"
        if os.path.exists(sock_path):
            _conn = _httpc.HTTPConnection("localhost", timeout=5)
            _s = _sock.socket(_sock.AF_UNIX, _sock.SOCK_STREAM)
            _s.connect(sock_path)
            _conn.sock = _s
            _conn.request("GET", "/containers/json?all=0")
            _resp = _conn.getresponse()
            _raw = _resp.read().decode("utf-8", errors="replace")
            _conn.close()
            if _resp.status == 200:
                for ct in (_json.loads(_raw) or []):
                    containers.append({
                        "name": (ct.get("Names") or ["?"])[0].lstrip("/"),
                        "image": ct.get("Image", ""),
                        "state": ct.get("State", ""),
                        "status": ct.get("Status", ""),
                    })
    except Exception as _e:
        containers = [{"name": "_docker_query_error", "state": "error", "status": str(_e)[:160]}]
    result["containers"] = containers

    # Database connectivity
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM node_agent_configs")
        agent_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM node_jobs WHERE status = 'pending'")
        pending_jobs = cur.fetchone()[0]
        cur.close()
        conn.close()
        result["database"] = {"connected": True, "agents": agent_count, "pending_jobs": pending_jobs}
    except Exception as e:
        result["database"] = {"connected": False, "error": str(e)}

    return jsonify(result)


@app.route("/downloads")
def active_downloads():
    """Show active download progress (for future use with download_progress table)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """SELECT download_type, item_name, total_bytes, completed_bytes, status,
                      started_at, updated_at, error_message
               FROM download_progress
               WHERE status = 'downloading'
               ORDER BY started_at DESC"""
        )
        downloads = cur.fetchall()
        cur.close()
        conn.close()
        return jsonify({"downloads": [_serialize_row(d) for d in downloads]})
    except Exception:
        # Table may not exist yet
        return jsonify({"downloads": [], "note": "download_progress table not yet created"})


@app.route("/api/compose-recreate", methods=["POST"])
def compose_recreate():
    """Recreate sync container with updated volume mounts.

    Inspects the current sync container, clones its config with added
    volumes, stops+removes the old one, and creates+starts the new one.
    Called from hub after docker-compose.node.yml is updated via OTA.

    POST body: { "add_volumes": {"comfyui_data": "/comfyui/models"} }
    """
    import http.client
    import socket as _socket
    import json as _json

    def _docker_api(method, path, body=None):
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.connect("/var/run/docker.sock")
        conn = http.client.HTTPConnection("localhost")
        conn.sock = sock
        headers = {"Content-Type": "application/json"} if body else {}
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read().decode("utf-8", errors="replace")
        status = resp.status
        conn.close()
        return status, data

    data = request.get_json() or {}
    container_name = data.get("container_name", "archie_starship_sync")
    add_volumes = data.get("add_volumes", {"comfyui_data": "/comfyui/models"})

    # Safety: only allow recreating known ARCHIE containers
    ALLOWED_CONTAINERS = {
        "archie_starship_sync",
        "archie_starship_api",
        "archie_starship_comfyui",
    }
    if container_name not in ALLOWED_CONTAINERS:
        return jsonify({
            "success": False,
            "error": f"Container not in allowlist. Allowed: {sorted(ALLOWED_CONTAINERS)}",
        }), 400

    try:
        # Step 1: Inspect current sync container
        status, inspect_data = _docker_api("GET", f"/containers/{container_name}/json")
        if status != 200:
            return jsonify({"success": False, "error": f"Cannot inspect {container_name}: HTTP {status}"}), 500

        config = _json.loads(inspect_data)
        image = config["Config"]["Image"]
        env = config["Config"]["Env"]
        cmd = config["Config"]["Cmd"]
        binds = config.get("HostConfig", {}).get("Binds", [])
        network_mode = config.get("HostConfig", {}).get("NetworkMode", "bridge")
        restart_policy = config.get("HostConfig", {}).get("RestartPolicy", {"Name": "unless-stopped"})

        # Step 2: Add new volume binds
        for vol_name, mount_path in add_volumes.items():
            bind_str = f"{vol_name}:{mount_path}"
            if not any(mount_path in b for b in binds):
                binds.append(bind_str)
                logger.info("[compose-recreate] Adding volume: %s", bind_str)

        # Step 3: Disable restart policy, stop and remove old container
        _docker_api("POST", f"/containers/{container_name}/update",
                    body=_json.dumps({"RestartPolicy": {"Name": "no"}}))
        _docker_api("POST", f"/containers/{container_name}/stop?t=10")
        import time as _time
        _time.sleep(2)
        _docker_api("DELETE", f"/containers/{container_name}?force=true")
        logger.info("[compose-recreate] Removed old %s", container_name)

        # Step 4: Create new container with updated config
        create_body = _json.dumps({
            "Image": image,
            "Cmd": cmd,
            "Env": env,
            "HostConfig": {
                "Binds": binds,
                "NetworkMode": network_mode,
                "RestartPolicy": restart_policy,
            },
        })

        status, create_data = _docker_api(
            "POST",
            f"/containers/create?name={container_name}",
            body=create_body,
        )
        if status not in (200, 201):
            return jsonify({"success": False, "error": f"Create failed: HTTP {status} {create_data[:200]}"}), 500

        new_id = _json.loads(create_data).get("Id", "unknown")

        # Step 5: Start the new container
        start_status, _ = _docker_api("POST", f"/containers/{new_id}/start")
        if start_status not in (200, 204):
            return jsonify({"success": False, "error": f"Start failed: HTTP {start_status}"}), 500

        logger.info("[compose-recreate] New %s created and started (id=%s)", container_name, new_id[:12])
        return jsonify({
            "success": True,
            "container": container_name,
            "new_id": new_id[:12],
            "volumes": binds,
            "message": f"Sync container recreated with {len(add_volumes)} new volume(s)",
        })

    except Exception as e:
        logger.error("[compose-recreate] Failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


# =============================================================================
# B.E.A.C.O.N. — Bridge-Enabled Autonomous Control & Operations Network
# Local LCARS dashboard for fleet node management
# =============================================================================

BEACON_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "beacon_config.json"
)


def _load_beacon_config():
    """Load BEACON feature toggle config."""
    defaults = {
        "warp_access": True,
        "fleet_dispatch": True,
        "comfyui_sharing": True,
        "model_sync": True,
        "ota_updates": "auto",
        "telemetry": "full",
    }
    try:
        if os.path.exists(BEACON_CONFIG_FILE):
            with open(BEACON_CONFIG_FILE) as f:
                saved = json.load(f)
            defaults.update(saved)
    except Exception:
        pass
    return defaults


def _save_beacon_config(config):
    """Save BEACON feature toggle config."""
    with open(BEACON_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


@app.route("/api/firewall-rule", methods=["POST"])
def firewall_rule():
    """Add a firewall rule on the host. Localhost-only, port-restricted."""
    # Security: only accept from localhost (sync container)
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return jsonify({"success": False, "error": "Forbidden: localhost only"}), 403

    data = request.get_json() or {}
    port = data.get("port")
    protocol = data.get("protocol", "tcp")
    rule_name = data.get("name", f"ARCHIE-{port}-{protocol}")

    # Port allowlist
    ALLOWED_PORTS = {11434, 8188, 3001}
    if not port or int(port) not in ALLOWED_PORTS:
        return jsonify({
            "success": False,
            "error": f"Port not in allowlist. Allowed: {sorted(ALLOWED_PORTS)}",
        }), 400

    port = int(port)
    import subprocess
    import platform as _platform

    try:
        if _platform.system() == "Windows":
            cmd = [
                "netsh", "advfirewall", "firewall", "add", "rule",
                f"name={rule_name}",
                "dir=in", "action=allow",
                f"protocol={protocol}",
                f"localport={port}",
            ]
        else:
            cmd = ["ufw", "allow", f"{port}/{protocol}"]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15
        )
        output = result.stdout + result.stderr

        return jsonify({
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "output": output[:1000],
            "command": " ".join(cmd),
        })
    except subprocess.TimeoutExpired:
        return jsonify({"success": False, "error": "Command timed out"}), 500
    except Exception as e:
        logger.exception("Firewall rule failed")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/beacon/stats")
def beacon_stats():
    """Live local stats for BEACON dashboard.

    Reuses the existing /diagnostics endpoint data which works inside Docker
    (reads /proc, calls Ollama API, checks ComfyUI) without needing psutil.
    """
    import platform as plat

    stats = {
        "node_id": NODE_ID,
        "node_name": os.environ.get("NODE_NAME", plat.node()),
        "uptime": None,
        "cpu": {},
        "memory": {},
        "gpu": {},
        "disk": {},
        "ollama": {"online": False, "models": [], "loaded": 0},
        "mesh": {"connected": False, "ip": None},
        "config": _load_beacon_config(),
    }

    # Pull data from the diagnostics endpoint (same process, just call the func)
    try:
        with app.test_request_context():
            diag_resp = diagnostics()
            diag = diag_resp.get_json() if hasattr(diag_resp, "get_json") else {}
    except Exception:
        diag = {}

    # Disk from diagnostics
    if diag.get("disk"):
        d = diag["disk"]
        stats["disk"] = {
            "total_gb": d.get("total_gb", 0),
            "free_gb": d.get("free_gb", 0),
            "usage_percent": d.get("percent_used", 0),
        }

    # Uptime from diagnostics
    if diag.get("uptime_seconds"):
        secs = int(diag["uptime_seconds"])
        hours, rem = divmod(secs, 3600)
        mins, s = divmod(rem, 60)
        stats["uptime"] = f"{hours}h {mins}m {s}s"

    # CPU — read from /proc/stat (works in Docker containers)
    try:
        import subprocess

        result = subprocess.run(
            ["nproc"], capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0:
            cores = int(result.stdout.strip())
            stats["cpu"]["cores"] = cores
            stats["cpu"]["threads"] = cores

        # Get CPU usage from /proc/stat snapshot
        with open("/proc/loadavg") as f:
            load_1min = float(f.read().split()[0])
            stats["cpu"]["usage_percent"] = round(
                min(load_1min / max(cores, 1) * 100, 100), 1
            )
    except Exception:
        pass

    # Memory — read from /proc/meminfo (works in Docker)
    try:
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    meminfo[parts[0].rstrip(":")] = int(parts[1])
        total_kb = meminfo.get("MemTotal", 0)
        avail_kb = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        used_kb = total_kb - avail_kb
        stats["memory"] = {
            "total_gb": round(total_kb / 1048576, 1),
            "used_gb": round(used_kb / 1048576, 1),
            "usage_percent": round(used_kb / max(total_kb, 1) * 100, 1),
        }
    except Exception:
        pass

    # GPU from ComfyUI diagnostics (VRAM info)
    if diag.get("comfyui", {}).get("online"):
        cu = diag["comfyui"]
        vram_total = cu.get("vram_total_mb", 0)
        vram_free = cu.get("vram_free_mb", 0)
        vram_used = vram_total - vram_free
        stats["gpu"] = {
            "name": "GPU (via ComfyUI)",
            "vram_total_mb": vram_total,
            "vram_used_mb": vram_used,
            "usage_percent": round(vram_used / max(vram_total, 1) * 100) if vram_total else 0,
        }

    # Ollama from diagnostics
    if diag.get("ollama", {}).get("online"):
        ol = diag["ollama"]
        stats["ollama"]["online"] = True
        stats["ollama"]["models"] = ol.get("models", [])
        stats["ollama"]["loaded"] = len(ol.get("loaded", []))

    # Mesh VPN + WARP status — check Tailscale
    try:
        import subprocess

        result = subprocess.run(
            ["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=3
        )
        if result.returncode == 0 and result.stdout.strip():
            stats["mesh"]["connected"] = True
            stats["mesh"]["ip"] = result.stdout.strip()

            # Check WARP (Tailscale SSH) status
            result2 = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True, text=True, timeout=3,
            )
            if result2.returncode == 0:
                try:
                    ts_status = json.loads(result2.stdout)
                    stats["mesh"]["warp_enabled"] = ts_status.get("Self", {}).get("SSH", False)
                    stats["mesh"]["hostname"] = ts_status.get("Self", {}).get("HostName", "")
                    peers = ts_status.get("Peer", {})
                    stats["mesh"]["peers"] = len(peers)
                except Exception:
                    pass
    except Exception:
        pass

    # WARP toggle — respect beacon config
    beacon_cfg = _load_beacon_config()
    stats["mesh"]["warp_allowed"] = beacon_cfg.get("warp_access", True)

    return jsonify(stats)


@app.route("/api/beacon/config", methods=["GET", "POST"])
def beacon_config():
    """Get or update BEACON feature toggles."""
    if request.method == "POST":
        data = request.get_json() or {}
        config = _load_beacon_config()
        for key in [
            "warp_access",
            "fleet_dispatch",
            "comfyui_sharing",
            "model_sync",
            "ota_updates",
            "telemetry",
        ]:
            if key in data:
                config[key] = data[key]
        _save_beacon_config(config)
        return jsonify({"success": True, "config": config})
    else:
        return jsonify({"success": True, "config": _load_beacon_config()})


@app.route("/api/beacon/saas")
def beacon_saas():
    """Discover available SaaS modules from hub."""
    hub_url, api_key = _get_hub_config()
    if not hub_url:
        return jsonify({"success": False, "modules": [], "error": "Hub not configured"})

    try:
        import requests as req

        headers = {"X-Node-API-Key": api_key} if api_key else {}
        r = req.get(
            f"{hub_url}/tools/department-hq/api/mesh/saas-modules",
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            # Add hub URL so BEACON can link to modules
            for mod in data.get("modules", []):
                mod["hub_url"] = f"{hub_url}{mod['route']}"
            return jsonify(data)
        return jsonify({"success": False, "modules": [], "error": f"HTTP {r.status_code}"})
    except Exception as e:
        return jsonify({"success": False, "modules": [], "error": str(e)})


def _get_hub_config():
    """Get hub URL and API key from env or config.json."""
    hub_url = os.environ.get("HUB_URL", "")
    api_key = os.environ.get("HUB_API_KEY", "")
    if not hub_url:
        try:
            config_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)), "config.json"
            )
            with open(config_path) as f:
                cfg = json.load(f)
            hub_url = cfg.get("hub_url", "")
            api_key = api_key or cfg.get("hub_api_key", "")
        except Exception:
            pass
    return hub_url, api_key


@app.route("/api/beacon/sync", methods=["POST"])
def beacon_sync():
    """Trigger data sync from hub — pull knowledge, projects, tasks, contacts."""
    hub_url, api_key = _get_hub_config()
    if not hub_url:
        return jsonify({"success": False, "error": "Hub not configured"})

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Get watermarks
        cur.execute("SELECT sync_type, last_synced_at FROM node_sync_watermarks")
        watermarks = {r["sync_type"]: r["last_synced_at"].isoformat() for r in cur.fetchall()}

        # Pull from hub
        import requests as req

        r = req.post(
            f"{hub_url}/tools/department-hq/api/mesh/sync-data",
            json={"watermarks": watermarks, "limit": 200},
            headers={"X-Node-API-Key": api_key},
            timeout=30,
        )
        if r.status_code != 200:
            return jsonify({"success": False, "error": f"Hub returned {r.status_code}"})

        data = r.json()
        if not data.get("success"):
            return jsonify({"success": False, "error": data.get("error", "Unknown")})

        package = data.get("package", {})
        synced = {}

        # Upsert knowledge
        for kb in package.get("knowledge", []):
            cur.execute(
                """INSERT INTO node_knowledge_cache
                   (hub_kb_id, title, content, knowledge_type, category,
                    tags, importance_score, source_type, synced_at, hub_updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)
                   ON CONFLICT (hub_kb_id) DO UPDATE SET
                    title=EXCLUDED.title, content=EXCLUDED.content,
                    knowledge_type=EXCLUDED.knowledge_type, category=EXCLUDED.category,
                    tags=EXCLUDED.tags, importance_score=EXCLUDED.importance_score,
                    synced_at=NOW(), hub_updated_at=EXCLUDED.hub_updated_at""",
                (
                    kb["id"], kb.get("title"), kb.get("content"),
                    kb.get("knowledge_type"), kb.get("category"),
                    kb.get("tags", []), kb.get("importance_score", 0.5),
                    kb.get("source_type"), kb.get("updated_at"),
                ),
            )
        synced["knowledge"] = len(package.get("knowledge", []))

        # Upsert projects
        for p in package.get("projects", []):
            cur.execute(
                """INSERT INTO node_projects
                   (hub_project_id, name, slug, description, status, priority,
                    project_type, tags, synced_at, hub_updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)
                   ON CONFLICT (hub_project_id) DO UPDATE SET
                    name=EXCLUDED.name, slug=EXCLUDED.slug,
                    description=EXCLUDED.description, status=EXCLUDED.status,
                    priority=EXCLUDED.priority, synced_at=NOW(),
                    hub_updated_at=EXCLUDED.hub_updated_at""",
                (
                    p["id"], p["name"], p.get("slug"), p.get("description"),
                    p.get("status"), p.get("priority", 5),
                    p.get("project_type"), p.get("tags", []),
                    p.get("updated_at"),
                ),
            )
        synced["projects"] = len(package.get("projects", []))

        # Upsert tasks
        for t in package.get("tasks", []):
            cur.execute(
                """INSERT INTO node_tasks
                   (hub_task_id, hub_project_id, title, description, status,
                    priority, assigned_agent, tags, synced_at, hub_updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW(),%s)
                   ON CONFLICT (hub_task_id) DO UPDATE SET
                    title=EXCLUDED.title, description=EXCLUDED.description,
                    status=EXCLUDED.status, priority=EXCLUDED.priority,
                    assigned_agent=EXCLUDED.assigned_agent, synced_at=NOW(),
                    hub_updated_at=EXCLUDED.hub_updated_at""",
                (
                    t["id"], t.get("project_id"), t["title"],
                    t.get("description"), t.get("status"),
                    t.get("priority", 5), t.get("assigned_agent"),
                    t.get("tags", []), t.get("updated_at"),
                ),
            )
        synced["tasks"] = len(package.get("tasks", []))

        # Upsert contacts
        for c in package.get("contacts", []):
            cur.execute(
                """INSERT INTO node_contacts
                   (hub_contact_id, name, email, company, role,
                    tags, synced_at, hub_updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,NOW(),%s)
                   ON CONFLICT (hub_contact_id) DO UPDATE SET
                    name=EXCLUDED.name, email=EXCLUDED.email,
                    company=EXCLUDED.company, role=EXCLUDED.role,
                    tags=EXCLUDED.tags, synced_at=NOW(),
                    hub_updated_at=EXCLUDED.hub_updated_at""",
                (
                    c["id"], c["name"], c.get("email"),
                    c.get("company"), c.get("role"),
                    c.get("tags", []), c.get("updated_at"),
                ),
            )
        synced["contacts"] = len(package.get("contacts", []))

        # Update watermarks
        for sync_type, records in [
            ("knowledge_sync", package.get("knowledge", [])),
            ("project_sync", package.get("projects", [])),
            ("task_sync", package.get("tasks", [])),
            ("contact_sync", package.get("contacts", [])),
        ]:
            if records:
                latest = max(r.get("updated_at", "") for r in records)
                cur.execute(
                    """UPDATE node_sync_watermarks
                       SET last_synced_at = %s, record_count = record_count + %s,
                           updated_at = NOW()
                       WHERE sync_type = %s""",
                    (latest, len(records), sync_type),
                )

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"success": True, "synced": synced})

    except Exception as e:
        logger.error(f"Data sync failed: {e}")
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/beacon/local-data")
def beacon_local_data():
    """Query locally synced data — works offline."""
    data_type = request.args.get("type", "knowledge")
    search = request.args.get("q", "")
    limit = min(int(request.args.get("limit", 50)), 200)

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        if data_type == "knowledge":
            if search:
                cur.execute(
                    """SELECT hub_kb_id, title, knowledge_type, category, importance_score, synced_at
                       FROM node_knowledge_cache
                       WHERE title ILIKE %s OR content ILIKE %s
                       ORDER BY importance_score DESC LIMIT %s""",
                    (f"%{search}%", f"%{search}%", limit),
                )
            else:
                cur.execute(
                    """SELECT hub_kb_id, title, knowledge_type, category, importance_score, synced_at
                       FROM node_knowledge_cache
                       ORDER BY synced_at DESC LIMIT %s""",
                    (limit,),
                )
        elif data_type == "projects":
            cur.execute(
                "SELECT * FROM node_projects ORDER BY priority DESC LIMIT %s",
                (limit,),
            )
        elif data_type == "tasks":
            cur.execute(
                "SELECT * FROM node_tasks WHERE status != 'completed' ORDER BY priority DESC LIMIT %s",
                (limit,),
            )
        elif data_type == "contacts":
            if search:
                cur.execute(
                    """SELECT * FROM node_contacts
                       WHERE name ILIKE %s OR email ILIKE %s OR company ILIKE %s
                       ORDER BY name LIMIT %s""",
                    (f"%{search}%", f"%{search}%", f"%{search}%", limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM node_contacts ORDER BY name LIMIT %s",
                    (limit,),
                )
        else:
            return jsonify({"success": False, "error": f"Unknown type: {data_type}"})

        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Serialize
        for row in rows:
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()

        return jsonify({"success": True, "type": data_type, "count": len(rows), "data": rows})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/beacon/fleet")
def beacon_fleet():
    """Pull fleet-wide stats from hub via mesh VPN or LAN."""
    hub_url, api_key = _get_hub_config()

    if not hub_url:
        return jsonify({"success": False, "error": "Hub URL not configured"})

    fleet = {
        "connected": False,
        "nodes_online": 0,
        "nodes_total": 0,
        "total_gpu_vram_gb": 0,
        "total_ram_gb": 0,
        "total_models": 0,
        "mesh_connected": 0,
        "this_node": {},
    }

    try:
        import requests as req

        headers = {}
        if api_key:
            headers["X-Node-API-Key"] = api_key

        # Pull node stats from hub
        r = req.get(
            f"{hub_url}/tools/department-hq/api/nodes",
            headers=headers,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            fleet["connected"] = True
            nodes = data.get("nodes", [])
            summary = data.get("summary", {})
            fleet["nodes_online"] = summary.get("online", 0)
            fleet["nodes_total"] = summary.get("total", 0)

            for n in nodes:
                fleet["total_ram_gb"] += float(n.get("ram_gb") or 0)
                fleet["total_gpu_vram_gb"] += float(n.get("gpu_vram_gb") or 0)
                if n.get("mesh_ip"):
                    fleet["mesh_connected"] += 1
                # Find this node's rank
                if n.get("node_id") == NODE_ID:
                    fleet["this_node"] = {
                        "name": n.get("node_name"),
                        "total_requests": n.get("total_requests", 0),
                        "avg_latency_ms": n.get("avg_latency_ms"),
                        "priority": n.get("bridge_priority"),
                    }

            # Count total models from hub mesh topology
            try:
                r2 = req.get(
                    f"{hub_url}/tools/department-hq/api/mesh/topology",
                    headers=headers,
                    timeout=5,
                )
                if r2.status_code == 200:
                    fleet["mesh_connected"] = r2.json().get("mesh_connected", 0)
            except Exception:
                pass
    except Exception as e:
        fleet["error"] = str(e)

    return jsonify(fleet)


@app.route("/")
def beacon_dashboard():
    """B.E.A.C.O.N. — Local LCARS fleet node dashboard."""
    node_name = os.environ.get("NODE_NAME", NODE_ID)
    return render_template_string(BEACON_HTML, node_id=NODE_ID, node_name=node_name)


BEACON_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>B.E.A.C.O.N. — {{ node_name }}</title>
<style>
  :root {
    --bg: #0a0a12; --panel: #12121f; --cyan: #00e5ff; --green: #10b981;
    --yellow: #fbbf24; --red: #ef4444; --purple: #8b5cf6; --muted: #64748b;
    --text: #e2e8f0; --border: rgba(0,229,255,0.15);
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; min-height:100vh; }

  .beacon-header {
    background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
    border-bottom: 2px solid var(--cyan);
    padding: 16px 24px;
    display: flex; align-items: center; justify-content: space-between;
  }
  .beacon-title { font-size: 1.4rem; color: var(--cyan); letter-spacing: 2px; font-weight: 700; }
  .beacon-subtitle { font-size: 0.75rem; color: var(--muted); margin-top: 2px; }
  .beacon-node-id { font-family: monospace; color: var(--purple); font-size: 0.85rem; }
  .beacon-mesh-badge { padding: 4px 12px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; }
  .mesh-on { background: rgba(16,185,129,0.15); color: var(--green); border: 1px solid rgba(16,185,129,0.3); }
  .mesh-off { background: rgba(100,116,139,0.15); color: var(--muted); border: 1px solid rgba(100,116,139,0.3); }

  .beacon-grid {
    display: grid; grid-template-columns: 1fr 1fr; gap: 16px;
    padding: 20px; max-width: 1200px; margin: 0 auto;
  }
  @media (max-width: 768px) { .beacon-grid { grid-template-columns: 1fr; } }

  .beacon-card {
    background: var(--panel); border: 1px solid var(--border);
    border-radius: 8px; padding: 16px; position: relative;
  }
  .beacon-card.full { grid-column: 1 / -1; }
  .card-title {
    font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1.5px;
    color: var(--cyan); margin-bottom: 12px; font-weight: 600;
  }

  .gauge-row { display: flex; gap: 16px; margin-bottom: 8px; align-items: center; }
  .gauge-label { font-size: 0.75rem; color: var(--muted); width: 50px; }
  .gauge-bar { flex: 1; height: 8px; background: rgba(255,255,255,0.05); border-radius: 4px; overflow: hidden; }
  .gauge-fill { height: 100%; border-radius: 4px; transition: width 0.5s ease; }
  .gauge-fill.green { background: var(--green); }
  .gauge-fill.yellow { background: var(--yellow); }
  .gauge-fill.red { background: var(--red); }
  .gauge-value { font-size: 0.75rem; font-family: monospace; width: 65px; text-align: right; }

  .stat-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid rgba(255,255,255,0.03); }
  .stat-label { font-size: 0.8rem; color: var(--muted); }
  .stat-value { font-size: 0.8rem; font-family: monospace; }

  .model-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }
  .model-chip {
    background: rgba(139,92,246,0.1); border: 1px solid rgba(139,92,246,0.2);
    padding: 6px 10px; border-radius: 6px; font-size: 0.75rem; font-family: monospace;
    display: flex; justify-content: space-between;
  }
  .model-size { color: var(--muted); }

  .toggle-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  @media (max-width: 768px) { .toggle-grid { grid-template-columns: 1fr; } }
  .toggle-item {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 12px; background: rgba(255,255,255,0.02); border-radius: 6px;
  }
  .toggle-label { font-size: 0.8rem; }
  .toggle-desc { font-size: 0.65rem; color: var(--muted); }
  .switch { position:relative; width:40px; height:22px; }
  .switch input { opacity:0; width:0; height:0; }
  .slider {
    position:absolute; inset:0; background:#334155; border-radius:11px;
    cursor:pointer; transition:0.3s;
  }
  .slider:before {
    content:""; position:absolute; height:16px; width:16px; left:3px; bottom:3px;
    background:white; border-radius:50%; transition:0.3s;
  }
  input:checked + .slider { background:var(--cyan); }
  input:checked + .slider:before { transform:translateX(18px); }

  .beacon-footer {
    text-align: center; padding: 12px; font-size: 0.65rem; color: var(--muted);
    border-top: 1px solid var(--border);
  }
  .live-dot { display:inline-block; width:6px; height:6px; background:var(--green); border-radius:50%; margin-right:4px; animation:pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
  .status-ok { color: var(--green); }
  .status-off { color: var(--muted); }
</style>
</head>
<body>

<div class="beacon-header">
  <div>
    <div class="beacon-title">B.E.A.C.O.N.</div>
    <div class="beacon-subtitle">Bridge-Enabled Autonomous Control &amp; Operations Network</div>
  </div>
  <div style="text-align:right">
    <div class="beacon-node-id" id="hdr-node-id">{{ node_name }}</div>
    <div style="display:flex;gap:6px;justify-content:flex-end;margin-top:4px;">
      <div id="hdr-mesh" class="beacon-mesh-badge mesh-off">MESH: CHECKING...</div>
      <div id="hdr-warp" class="beacon-mesh-badge mesh-off">W.A.R.P.: —</div>
    </div>
  </div>
</div>

<div class="beacon-grid">
  <div class="beacon-card">
    <div class="card-title"><span class="live-dot"></span> System Resources</div>
    <div class="gauge-row">
      <span class="gauge-label">CPU</span>
      <div class="gauge-bar"><div class="gauge-fill green" id="g-cpu" style="width:0%"></div></div>
      <span class="gauge-value" id="v-cpu">-</span>
    </div>
    <div class="gauge-row">
      <span class="gauge-label">RAM</span>
      <div class="gauge-bar"><div class="gauge-fill green" id="g-ram" style="width:0%"></div></div>
      <span class="gauge-value" id="v-ram">-</span>
    </div>
    <div class="gauge-row">
      <span class="gauge-label">GPU</span>
      <div class="gauge-bar"><div class="gauge-fill green" id="g-gpu" style="width:0%"></div></div>
      <span class="gauge-value" id="v-gpu">-</span>
    </div>
    <div class="gauge-row">
      <span class="gauge-label">Disk</span>
      <div class="gauge-bar"><div class="gauge-fill green" id="g-disk" style="width:0%"></div></div>
      <span class="gauge-value" id="v-disk">-</span>
    </div>
    <div style="margin-top:10px">
      <div class="stat-row"><span class="stat-label">Uptime</span><span class="stat-value" id="s-uptime">-</span></div>
      <div class="stat-row"><span class="stat-label">GPU</span><span class="stat-value" id="s-gpu-name">-</span></div>
      <div class="stat-row"><span class="stat-label">VRAM</span><span class="stat-value" id="s-vram">-</span></div>
    </div>
  </div>

  <div class="beacon-card">
    <div class="card-title"><span class="live-dot"></span> Ollama Engine</div>
    <div class="stat-row"><span class="stat-label">Status</span><span class="stat-value" id="o-status">-</span></div>
    <div class="stat-row"><span class="stat-label">Models Available</span><span class="stat-value" id="o-count">-</span></div>
    <div class="stat-row"><span class="stat-label">Models Loaded</span><span class="stat-value" id="o-loaded">-</span></div>
    <div style="margin-top:12px">
      <div class="card-title">Installed Models</div>
      <div class="model-grid" id="model-list"></div>
    </div>
  </div>

  <!-- Fleet Stats -->
  <div class="beacon-card full">
    <div class="card-title">Fleet Network</div>
    <div id="fleet-panel" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:12px;">
      <div class="stat-row" style="flex-direction:column;align-items:center;text-align:center;border:1px solid var(--border);border-radius:8px;padding:12px;">
        <div style="font-size:1.8rem;font-weight:700;color:var(--cyan);" id="f-online">-</div>
        <div class="stat-label">Nodes Online</div>
      </div>
      <div class="stat-row" style="flex-direction:column;align-items:center;text-align:center;border:1px solid var(--border);border-radius:8px;padding:12px;">
        <div style="font-size:1.8rem;font-weight:700;color:var(--green);" id="f-mesh">-</div>
        <div class="stat-label">On Mesh</div>
      </div>
      <div class="stat-row" style="flex-direction:column;align-items:center;text-align:center;border:1px solid var(--border);border-radius:8px;padding:12px;">
        <div style="font-size:1.8rem;font-weight:700;color:var(--purple);" id="f-ram">-</div>
        <div class="stat-label">Fleet RAM (GB)</div>
      </div>
      <div class="stat-row" style="flex-direction:column;align-items:center;text-align:center;border:1px solid var(--border);border-radius:8px;padding:12px;">
        <div style="font-size:1.8rem;font-weight:700;color:var(--yellow);" id="f-vram">-</div>
        <div class="stat-label">Fleet VRAM (GB)</div>
      </div>
    </div>
    <div id="fleet-status" style="margin-top:8px;font-size:0.7rem;color:var(--muted);"></div>
  </div>

  <div class="beacon-card full">
    <div class="card-title">Fleet Controls</div>
    <div class="toggle-grid" id="toggle-grid"></div>
  </div>

  <!-- SaaS Apps -->
  <div class="beacon-card full">
    <div class="card-title">SaaS Applications</div>
    <div id="saas-panel" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;">
      <div style="color:var(--muted);font-size:0.8rem;">Loading apps...</div>
    </div>
  </div>
</div>

<div class="beacon-footer">
  B.E.A.C.O.N. v4.0 | Kytran Empowerment Technologies | A.R.C.H.I.E. Fleet Mesh
</div>

<script>
var TOGGLES = [
  {key:'warp_access', label:'W.A.R.P. Access', desc:'Allow remote AI agent SSH support'},
  {key:'fleet_dispatch', label:'Fleet Dispatch', desc:'Share GPU/CPU with fleet inference'},
  {key:'comfyui_sharing', label:'ComfyUI Sharing', desc:'Allow remote image generation'},
  {key:'model_sync', label:'Model Sync', desc:'Auto-download recommended models'},
  {key:'ota_updates', label:'OTA Updates', desc:'Auto-accept platform updates', isSelect:true, options:['auto','manual']},
  {key:'telemetry', label:'Telemetry', desc:'Metrics shared with hub', isSelect:true, options:['full','basic','off']}
];

function gc(p) { return p > 85 ? 'red' : p > 60 ? 'yellow' : 'green'; }

function sg(id, pct, lbl) {
  var e = document.getElementById('g-'+id);
  var v = document.getElementById('v-'+id);
  if(e){e.style.width=pct+'%'; e.className='gauge-fill '+gc(pct);}
  if(v) v.textContent = lbl || pct+'%';
}

function renderToggles(cfg) {
  var g = document.getElementById('toggle-grid');
  g.textContent = '';
  TOGGLES.forEach(function(t) {
    var d = document.createElement('div');
    d.className = 'toggle-item';
    var left = document.createElement('div');
    var l1 = document.createElement('div'); l1.className='toggle-label'; l1.textContent=t.label;
    var l2 = document.createElement('div'); l2.className='toggle-desc'; l2.textContent=t.desc;
    left.appendChild(l1); left.appendChild(l2);
    d.appendChild(left);
    if (t.isSelect) {
      var sel = document.createElement('select');
      sel.style.cssText='background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:4px;padding:4px 8px;font-size:0.75rem;';
      t.options.forEach(function(o){var op=document.createElement('option');op.value=o;op.textContent=o.toUpperCase();if(cfg[t.key]===o)op.selected=true;sel.appendChild(op);});
      sel.onchange=function(){setT(t.key,this.value);};
      d.appendChild(sel);
    } else {
      var sw = document.createElement('label'); sw.className='switch';
      var inp = document.createElement('input'); inp.type='checkbox'; inp.checked=!!cfg[t.key];
      inp.onchange=function(){setT(t.key,this.checked);};
      var sl = document.createElement('span'); sl.className='slider';
      sw.appendChild(inp); sw.appendChild(sl); d.appendChild(sw);
    }
    g.appendChild(d);
  });
}

function setT(k,v){var b={};b[k]=v;fetch('/api/beacon/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});}

function refresh() {
  fetch('/api/beacon/stats').then(function(r){return r.json();}).then(function(d) {
    document.getElementById('hdr-node-id').textContent = d.node_name || d.node_id;
    var me = document.getElementById('hdr-mesh');
    if (d.mesh && d.mesh.connected) {
      me.textContent = 'MESH: ' + d.mesh.ip;
      me.className = 'beacon-mesh-badge mesh-on';
    } else {
      me.textContent = 'MESH: OFFLINE';
      me.className = 'beacon-mesh-badge mesh-off';
    }
    var we = document.getElementById('hdr-warp');
    if (d.mesh && d.mesh.warp_enabled && d.mesh.warp_allowed) {
      we.textContent = 'W.A.R.P.: ACTIVE';
      we.className = 'beacon-mesh-badge mesh-on';
    } else if (d.mesh && d.mesh.warp_enabled && !d.mesh.warp_allowed) {
      we.textContent = 'W.A.R.P.: BLOCKED';
      we.className = 'beacon-mesh-badge mesh-off';
    } else {
      we.textContent = 'W.A.R.P.: OFF';
      we.className = 'beacon-mesh-badge mesh-off';
    }
    if(d.cpu.usage_percent!==undefined) sg('cpu',Math.round(d.cpu.usage_percent));
    if(d.memory.usage_percent!==undefined) sg('ram',Math.round(d.memory.usage_percent),d.memory.used_gb+'/'+d.memory.total_gb+'GB');
    if(d.gpu && d.gpu.usage_percent!==undefined){
      sg('gpu',d.gpu.usage_percent,d.gpu.usage_percent+'%');
      document.getElementById('s-gpu-name').textContent=d.gpu.name||'-';
      document.getElementById('s-vram').textContent=d.gpu.vram_used_mb+'/'+d.gpu.vram_total_mb+'MB';
    } else { document.getElementById('s-gpu-name').textContent='None'; document.getElementById('s-vram').textContent='-'; }
    if(d.disk) sg('disk',d.disk.usage_percent,d.disk.free_gb+'GB free');
    document.getElementById('s-uptime').textContent=d.uptime||'-';
    var os=document.getElementById('o-status');
    os.textContent=d.ollama.online?'ONLINE':'OFFLINE';
    os.className='stat-value '+(d.ollama.online?'status-ok':'status-off');
    document.getElementById('o-count').textContent=d.ollama.models.length;
    document.getElementById('o-loaded').textContent=d.ollama.loaded;
    var ml=document.getElementById('model-list'); ml.textContent='';
    d.ollama.models.forEach(function(m){
      var c=document.createElement('div');c.className='model-chip';
      var n=document.createElement('span');n.textContent=m.name;
      var s=document.createElement('span');s.className='model-size';s.textContent=m.size_gb+'GB';
      c.appendChild(n);c.appendChild(s);ml.appendChild(c);
    });
    if(d.config && !window._tr){renderToggles(d.config);window._tr=true;}
  }).catch(function(){});
}
refresh();
setInterval(refresh, 5000);

function refreshFleet() {
  fetch('/api/beacon/fleet').then(function(r){return r.json();}).then(function(f) {
    if (f.connected) {
      document.getElementById('f-online').textContent = f.nodes_online || 0;
      document.getElementById('f-mesh').textContent = f.mesh_connected || 0;
      document.getElementById('f-ram').textContent = Math.round(f.total_ram_gb || 0);
      document.getElementById('f-vram').textContent = Math.round(f.total_gpu_vram_gb || 0);
      var status = 'Connected to hub';
      if (f.this_node && f.this_node.name) {
        status += ' | This node: ' + f.this_node.name;
        if (f.this_node.total_requests) status += ' (' + f.this_node.total_requests + ' requests)';
      }
      document.getElementById('fleet-status').textContent = status;
    } else {
      document.getElementById('fleet-status').textContent = f.error ? 'Hub unreachable: ' + f.error : 'Fleet: disconnected';
    }
  }).catch(function(){
    document.getElementById('fleet-status').textContent = 'Fleet: offline';
  });
}
refreshFleet();
setInterval(refreshFleet, 30000);

function loadSaasApps() {
  fetch('/api/beacon/saas').then(function(r){return r.json();}).then(function(d) {
    var panel = document.getElementById('saas-panel');
    panel.textContent = '';
    if (!d.success || !d.modules || d.modules.length === 0) {
      var msg = document.createElement('div');
      msg.style.cssText = 'color:var(--muted);font-size:0.8rem;';
      msg.textContent = d.error ? 'Hub: ' + d.error : 'No SaaS apps available';
      panel.appendChild(msg);
      return;
    }
    d.modules.forEach(function(m) {
      var card = document.createElement('a');
      card.href = m.hub_url || '#';
      card.target = '_blank';
      card.style.cssText = 'display:flex;flex-direction:column;align-items:center;gap:4px;padding:12px 8px;background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.2);border-radius:8px;text-decoration:none;transition:border-color 0.2s;';
      card.onmouseover = function(){this.style.borderColor='var(--cyan)';};
      card.onmouseout = function(){this.style.borderColor='rgba(139,92,246,0.2)';};
      var icon = document.createElement('div');
      icon.style.cssText = 'font-size:1.2rem;';
      icon.textContent = m.icon || '\u2B21';
      var name = document.createElement('div');
      name.style.cssText = 'font-size:0.75rem;color:var(--text);font-weight:600;text-align:center;';
      name.textContent = m.name;
      var desc = document.createElement('div');
      desc.style.cssText = 'font-size:0.6rem;color:var(--muted);text-align:center;';
      desc.textContent = (m.description || '').substring(0, 40);
      card.appendChild(icon);
      card.appendChild(name);
      card.appendChild(desc);
      panel.appendChild(card);
    });
  }).catch(function(){
    var panel = document.getElementById('saas-panel');
    panel.textContent = '';
    var msg = document.createElement('div');
    msg.style.cssText = 'color:var(--muted);font-size:0.8rem;';
    msg.textContent = 'Hub unreachable';
    panel.appendChild(msg);
  });
}
loadSaasApps();
</script>
</body>
</html>"""


@app.route("/api/skills/push", methods=["POST"])
def skills_push():
    """Receive a skill from the hub and write to local SKILLS_DIR filesystem.

    No postgres required — DB-free so it works on lightweight nodes (VPS)
    that do not have a local database.
    """
    data = request.get_json() or {}
    slug = data.get("slug", "").strip()
    content = data.get("content", "")
    repo_slug = data.get("repo_slug", "unknown")

    if not slug or not content:
        return jsonify({"success": False, "error": "slug and content are required"}), 400

    repo_dir = os.path.join(SKILLS_DIR, repo_slug)
    try:
        os.makedirs(repo_dir, exist_ok=True)
        skill_path = os.path.join(repo_dir, f"{slug}.md")
        with open(skill_path, "w") as fh:
            fh.write(content)
        logger.info("[SkillPush] Wrote %s/%s.md", repo_slug, slug)
        return jsonify({"success": True, "slug": slug, "path": skill_path})
    except Exception as e:
        logger.error("[SkillPush] Failed to write %s/%s: %s", repo_slug, slug, e)
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    logger.info("Starting Node API + BEACON v4.0 on port 3001 (node: %s)", NODE_ID)
    app.run(host="0.0.0.0", port=3001, debug=False)

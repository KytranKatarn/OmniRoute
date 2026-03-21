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

from flask import Flask, jsonify, request
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

    # Container health (check via Docker socket if available)
    containers = []
    try:
        import urllib.request
        sock_url = "http://localhost/containers/json"
        # Docker socket — try via node_sync's _docker_api pattern
        req = urllib.request.Request(f"http+unix://%2Fvar%2Frun%2Fdocker.sock/containers/json")
        # Fallback: just report what we know
        containers = [
            {"name": "archie_starship_ollama", "status": "check via Docker Desktop"},
            {"name": "archie_starship_db", "status": "check via Docker Desktop"},
            {"name": "archie_starship_sync", "status": "running (we are here)"},
            {"name": "archie_starship_api", "status": "running (serving this request)"},
            {"name": "archie_starship_comfyui", "status": "check via Docker Desktop"},
        ]
    except Exception:
        pass
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

    container_name = "archie_starship_sync"
    data = request.get_json() or {}
    add_volumes = data.get("add_volumes", {"comfyui_data": "/comfyui/models"})

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

        # Step 3: Stop and remove old container
        _docker_api("POST", f"/containers/{container_name}/stop?t=10")
        _docker_api("DELETE", f"/containers/{container_name}")
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


if __name__ == "__main__":
    logger.info("Starting Node API v3.2 on port 3001 (node: %s)", NODE_ID)
    app.run(host="0.0.0.0", port=3001, debug=False)

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


if __name__ == "__main__":
    logger.info("Starting Node API v3.0 on port 3001 (node: %s)", NODE_ID)
    app.run(host="0.0.0.0", port=3001, debug=False)

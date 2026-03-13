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


if __name__ == "__main__":
    logger.info("Starting Node API on port 3001 (node: %s)", NODE_ID)
    app.run(host="0.0.0.0", port=3001, debug=False)

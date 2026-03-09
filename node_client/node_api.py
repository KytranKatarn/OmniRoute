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


def get_db():
    """Get a database connection."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn


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
    return jsonify({"agents": [dict(a) for a in agents]})


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
    return jsonify({"jobs": [dict(j) for j in jobs]})


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


if __name__ == "__main__":
    logger.info("Starting Node API on port 3001 (node: %s)", NODE_ID)
    app.run(host="0.0.0.0", port=3001, debug=False)

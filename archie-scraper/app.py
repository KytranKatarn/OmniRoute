import logging
import os
from urllib.parse import urlparse

from flask import Flask, jsonify, request

from browser_pool import BrowserPool
from database import get_db
from job_worker import JobWorker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
pool = BrowserPool()
worker = JobWorker(pool)


@app.route("/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "pool_size": pool.size,
            "slots_available": pool.available_count(),
        }
    )


@app.route("/jobs", methods=["POST"])
def submit_job():
    data = request.get_json(silent=True) or {}
    job_type = (data.get("job_type") or "").strip()
    target_url = (data.get("target_url") or "").strip()
    if not job_type or not target_url:
        return jsonify({"error": "job_type and target_url required"}), 400
    # SSRF guard: only allow http/https to external hosts
    try:
        parsed = urlparse(target_url)
        if parsed.scheme not in ("http", "https"):
            return jsonify({"error": f"scheme '{parsed.scheme}' not allowed — only http/https"}), 400
        if not parsed.netloc:
            return jsonify({"error": "invalid URL — no host"}), 400
    except Exception:
        return jsonify({"error": "invalid URL"}), 400
    job_id = worker.enqueue(
        job_type=job_type,
        target_url=target_url,
        params=data.get("params") or {},
        egress_tier=int(data.get("egress_tier") or 1),
        requested_by=data.get("requested_by") or "api",
    )
    return jsonify({"job_id": job_id, "status": "pending"}), 201


@app.route("/jobs/<int:job_id>")
def get_job(job_id):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM scout_jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(row))


@app.route("/jobs")
def list_jobs():
    status = request.args.get("status")
    with get_db() as conn:
        with conn.cursor() as cur:
            if status:
                cur.execute(
                    """SELECT id, job_type, target_url, status, created_at,
                              egress_tier, requested_by, findings
                       FROM scout_jobs WHERE status = %s
                       ORDER BY created_at DESC LIMIT 50""",
                    (status,),
                )
            else:
                cur.execute(
                    """SELECT id, job_type, target_url, status, created_at,
                              egress_tier, requested_by, findings
                       FROM scout_jobs ORDER BY created_at DESC LIMIT 50"""
                )
            rows = cur.fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/pool/status")
def pool_status():
    return jsonify(pool.status())


if __name__ == "__main__":
    worker.start()
    app.run(host="0.0.0.0", port=4243, debug=False)

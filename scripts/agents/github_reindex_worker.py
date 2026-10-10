#!/usr/bin/env python3
"""
GitHub Incremental Reindex Worker

Polls the github_reindex_queue table for pending items, fetches changed files
from GitHub using the compare API, and processes them for indexing/embedding.

Runs as a cron job (every 60s) similar to codex-delegation-worker.py.
"""

import re
import fcntl
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

REPO = "/mnt/archie_brain"
LOCK = "/tmp/github-reindex-worker.lock"
POLL_INTERVAL = 60  # seconds

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def psql(sql: str) -> str:
    """Run SQL in the DB container; return stripped -tA output (| separated)."""
    r = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            "archie_database",
            "psql",
            "-U",
            "archie",
            "-d",
            "archie",
            "-tA",
            "-F",
            "|",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr.strip()}")
    lines = [
        ln for ln in r.stdout.splitlines() if not re.match(r"^(UPDATE|INSERT|DELETE|SELECT|MERGE)\s+\d", ln.strip())
    ]
    return "\n".join(lines).strip()


def _json_sql(value: dict) -> str:
    """Encode JSON without interpolating arbitrary text into a SQL literal."""
    encoded = json.dumps(value).encode().hex()
    return f"convert_from(decode('{encoded}', 'hex'), 'UTF8')::jsonb"


def get_github_headers():
    """Get GitHub API headers with auth token."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return None, False
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ARCHIE-Platform",
    }, True


def claim_queue_item() -> dict | None:
    """Atomically claim the oldest pending reindex queue item."""
    out = psql(
        """
        UPDATE github_reindex_queue
        SET status = 'processing', started_at = NOW()
        WHERE id = (
            SELECT id FROM github_reindex_queue
            WHERE status = 'pending'
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING id, tracked_repo_id, trigger_type, trigger_payload, from_sha, to_sha;
        """
    )
    if not out:
        return None
    parts = out.split("|", 5)
    return {
        "id": int(parts[0]),
        "tracked_repo_id": int(parts[1]),
        "trigger_type": parts[2],
        "trigger_payload": json.loads(parts[3]) if parts[3] else {},
        "from_sha": parts[4] if parts[4] else None,
        "to_sha": parts[5] if parts[5] else None,
    }


def get_tracked_repo(repo_id: int) -> dict | None:
    """Get tracked repo details."""
    out = psql(
        f"""
        SELECT owner, repo, branch, webhook_secret, auto_ingest, max_files
        FROM github_tracked_repos
        WHERE id = {repo_id} AND status = 'active'
        """
    )
    if not out:
        return None
    parts = out.split("|", 5)
    return {
        "owner": parts[0],
        "repo": parts[1],
        "branch": parts[2],
        "webhook_secret": parts[3],
        "auto_ingest": parts[4] == "t",
        "max_files": int(parts[5]) if parts[5] else None,
    }


def get_github_headers():
    """Get GitHub API headers with auth token."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        return None, False
    return {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "ARCHIE-Platform",
    }, True


def get_changed_files(owner: str, repo: str, from_sha: str, to_sha: str) -> list:
    """Get changed files between two commits using GitHub Compare API."""
    headers, has_token = get_github_headers()
    if not has_token:
        logger.warning("No GitHub token available")
        return []

    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{from_sha}...{to_sha}"
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return [f["filename"] for f in data.get("files", [])]
    except Exception as e:
        logger.error(f"Failed to get changed files: {e}")
        return []


def process_reindex(item: dict, tracked_repo: dict, changed_files: list) -> bool:
    """Process the reindex for changed files."""
    # For now, trigger a full reindex of the repo via the existing pipeline
    # In the future, this could do incremental indexing per file
    owner = tracked_repo["owner"]
    repo = tracked_repo["repo"]
    repo_name = f"{owner}/{repo}"

    logger.info(f"Processing reindex for {repo_name} with {len(changed_files)} changed files")

    # Trigger the existing reindex pipeline via dispatcher
    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        dispatcher = get_dispatcher()
        job_id = dispatcher.create_job(
            job_type="github_index",
            module_source="consciousness",
            description=f"Incremental reindex: {repo_name} ({len(changed_files)} files)",
            total_steps=1,
            capability="code_analysis",
            metadata={"repo": repo_name, "priority": "high", "max_files": tracked_repo.get("max_files")},
        )
        if job_id:
            logger.info(f"Created incremental reindex job {job_id} for {repo_name}")
            return True
        else:
            logger.error(f"Failed to create reindex job for {repo_name}")
            return False
    except Exception as e:
        logger.error(f"Failed to dispatch reindex job: {e}")
        return False


def update_queue_status(queue_id: int, status: str, error: str = None, files_processed: int = 0, files_total: int = 0):
    """Update queue item status."""
    parts = [f"status = '{status}'"]
    if error:
        safe_error = error.replace("'", "''")
        parts.append(f"error_message = '{safe_error}'")
    if files_processed:
        parts.append(f"files_processed = {files_processed}")
    if files_total:
        parts.append(f"files_total = {files_total}")
    if status == "completed":
        parts.append("completed_at = NOW()")

    psql(
        f"""
        UPDATE github_reindex_queue
        SET {", ".join(parts)}, updated_at = NOW()
        WHERE id = {queue_id}
        """
    )


def main() -> int:
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.info("Another github-reindex-worker is running")
        return 0

    logger.info("Starting GitHub reindex worker")

    while True:
        try:
            item = claim_queue_item()
            if not item:
                logger.debug("No pending reindex items")
                time.sleep(POLL_INTERVAL)
                continue

            queue_id = item["id"]
            logger.info(f"Processing reindex queue #{queue_id} for repo {item['tracked_repo_id']}")

            # Get tracked repo details
            tracked_repo = get_tracked_repo(item["tracked_repo_id"])
            if not tracked_repo:
                logger.error(f"Tracked repo {item['tracked_repo_id']} not found or inactive")
                update_queue_status(queue_id, "failed", "Tracked repo not found or inactive")
                continue

            # Get changed files
            from_sha = item["from_sha"]
            to_sha = item["to_sha"]

            if not from_sha or from_sha == "0" * 40:
                # Full reindex - get all files
                logger.info(f"Full reindex requested for {tracked_repo['owner']}/{tracked_repo['repo']}")
                changed_files = ["*"]  # Signal full reindex
            else:
                changed_files = get_changed_files(
                    tracked_repo["owner"],
                    tracked_repo["repo"],
                    from_sha,
                    to_sha,
                )
                logger.info(f"Found {len(changed_files)} changed files")

            # Process reindex
            success = process_reindex(item, tracked_repo, changed_files)

            if success:
                update_queue_status(
                    queue_id, "completed", files_total=len(changed_files) if changed_files != ["*"] else 0
                )
                logger.info(f"Reindex queue #{queue_id} completed successfully")
            else:
                update_queue_status(queue_id, "failed", "Failed to dispatch reindex job")
                logger.error(f"Reindex queue #{queue_id} failed")

        except Exception as e:
            logger.error(f"Error processing reindex queue: {e}")
            if "queue_id" in locals():
                update_queue_status(queue_id, "failed", str(e))

        # Small delay before next poll
        time.sleep(2)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

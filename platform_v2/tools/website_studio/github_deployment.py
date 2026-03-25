"""
Website Designer GitHub Deployment
====================================
Handles GitHub Pages deployment for website projects.

Provides:
- deploy_website: commit, push, enable GitHub Pages
- auto_commit_and_push: wrapper for commit + push
- get_deployment_history: fetch deployment records
- _enable_github_pages: GitHub API Pages management
- _record_deployment: persist deployment record to DB

Author: A.R.C.H.I.E. Platform
Date: 2026-03-14
"""

import os
from database import _get_db_password
import json
import subprocess
import logging
import psycopg2
import psycopg2.extras
from datetime import datetime
from typing import Dict, List, Optional

from .chat_handler import ensure_repo_cloned, auto_commit_changes, WEBSITE_REPO_PATH

logger = logging.getLogger("archie_platform")

# DB connection config — direct psycopg2 (module pattern)
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "192.168.1.200"),
    "dbname": os.environ.get("DB_NAME", "archie"),
    "user": os.environ.get("DB_USER", "archie"),
    "password": _get_db_password(),
}


def _get_conn():
    return psycopg2.connect(**DB_CONFIG)


def deploy_website(user_id: int, project_id: Optional[int] = None) -> Dict:
    """
    Full deployment pipeline:
    1. Ensure repo is cloned
    2. Auto-commit any pending changes
    3. Push to origin/main
    4. Enable GitHub Pages
    5. Record deployment
    Returns {success, url, commit_hash, error}
    """
    try:
        # Step 1: ensure repo exists
        clone_result = ensure_repo_cloned(WEBSITE_REPO_PATH)
        if not clone_result.get("success"):
            return {"success": False, "error": clone_result.get("error", "Failed to clone repo")}

        # Step 2: commit any outstanding changes
        commit_result = auto_commit_changes("Deploy from Website Designer", WEBSITE_REPO_PATH)
        # commit_result may succeed with "nothing to commit" — that's fine

        # Step 3: get current commit hash
        hash_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=WEBSITE_REPO_PATH,
            capture_output=True,
            text=True,
            timeout=30,
        )
        commit_hash = hash_proc.stdout.strip() if hash_proc.returncode == 0 else "unknown"

        # Step 4: push to origin main
        push_proc = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=WEBSITE_REPO_PATH,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if push_proc.returncode != 0:
            err = push_proc.stderr.strip()
            logger.error("git push failed: %s", err)
            return {"success": False, "error": f"git push failed: {err}"}

        # Step 5: enable GitHub Pages
        deployment_url = _enable_github_pages(user_id)

        # Step 6: record deployment
        _record_deployment(project_id, user_id, commit_hash, deployment_url)

        return {
            "success": True,
            "url": deployment_url,
            "commit_hash": commit_hash,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Git operation timed out"}
    except Exception as e:
        logger.exception("deploy_website error")
        return {"success": False, "error": str(e)}


def auto_commit_and_push(message: str, repo_path: str = WEBSITE_REPO_PATH) -> Dict:
    """
    Wrapper: commit all changes then push to origin/main.
    Returns {success, commit_hash, pushed, error}
    """
    try:
        commit_result = auto_commit_changes(message, repo_path)
        if not commit_result.get("success"):
            return {"success": False, "error": commit_result.get("error", "Commit failed")}

        push_proc = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if push_proc.returncode != 0:
            err = push_proc.stderr.strip()
            return {"success": False, "error": f"git push failed: {err}"}

        hash_proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=15,
        )
        commit_hash = hash_proc.stdout.strip() if hash_proc.returncode == 0 else "unknown"

        return {"success": True, "commit_hash": commit_hash, "pushed": True}

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Git operation timed out"}
    except Exception as e:
        logger.exception("auto_commit_and_push error")
        return {"success": False, "error": str(e)}


def get_deployment_history(project_id: int) -> List[Dict]:
    """
    Fetch last 20 deployments for a project.
    Returns list of dicts with isoformat dates.
    """
    try:
        conn = _get_conn()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT id, website_id, deployment_type, status, commit_hash,
                   deployment_url, deployed_by, error_message, created_at
            FROM website_deployments
            WHERE website_id = %s
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (project_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()

        result = []
        for row in rows:
            d = dict(row)
            if d.get("created_at") and hasattr(d["created_at"], "isoformat"):
                d["created_at"] = d["created_at"].isoformat()
            result.append(d)
        return result

    except Exception as e:
        logger.exception("get_deployment_history error")
        return []


def _enable_github_pages(user_id: int) -> Optional[str]:
    """
    Load GitHub token, parse owner/repo from git remote, check/enable Pages.
    Returns html_url or None.
    """
    import urllib.request

    # Load token: user_integrations first, then env var
    token = None
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT credentials FROM user_integrations
            WHERE user_id = %s AND service = 'github'
            LIMIT 1
            """,
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            creds = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            token = creds.get("access_token") or creds.get("token")
    except Exception:
        logger.warning("Could not load GitHub token from user_integrations")

    if not token:
        token = os.environ.get("GITHUB_TOKEN")

    if not token:
        logger.warning("No GitHub token available — skipping Pages setup")
        return None

    # Parse owner/repo from git remote
    try:
        remote_proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=WEBSITE_REPO_PATH,
            capture_output=True,
            text=True,
            timeout=15,
        )
        remote_url = remote_proc.stdout.strip()
        # Support https://github.com/owner/repo.git and git@github.com:owner/repo.git
        if "github.com" in remote_url:
            if remote_url.startswith("git@"):
                # git@github.com:owner/repo.git
                path_part = remote_url.split(":", 1)[1]
            else:
                # https://github.com/owner/repo.git
                path_part = remote_url.split("github.com/", 1)[1]
            path_part = path_part.rstrip("/").removesuffix(".git")
            owner, repo = path_part.split("/", 1)
        else:
            logger.warning("Remote URL not GitHub: %s", remote_url)
            return None
    except Exception as e:
        logger.warning("Failed to parse git remote: %s", e)
        return None

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    api_base = f"https://api.github.com/repos/{owner}/{repo}/pages"

    def _github_request(url, method="GET", data=None):
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        if body:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, {}

    # Check if Pages already enabled
    status, body = _github_request(api_base)
    if status == 200:
        return body.get("html_url")

    # Enable Pages from main branch
    payload = {"source": {"branch": "main", "path": "/"}}
    status, body = _github_request(api_base, method="POST", data=payload)
    if status in (200, 201):
        return body.get("html_url")

    logger.warning("GitHub Pages enable returned status %s", status)
    return f"https://{owner}.github.io/{repo}/"


def _record_deployment(
    project_id: Optional[int],
    user_id: int,
    commit_hash: str,
    deployment_url: Optional[str],
) -> None:
    """
    Insert a record into website_deployments.
    """
    try:
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO website_deployments
                (website_id, deployment_type, status, commit_hash, deployment_url, deployed_by, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                project_id,
                "github_pages",
                "success",
                commit_hash,
                deployment_url,
                user_id,
                datetime.utcnow(),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.exception("_record_deployment error: %s", e)

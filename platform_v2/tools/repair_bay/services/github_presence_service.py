"""GitHub Presence Service — weekly F.O.R.G.E. audit of KytranKatarn public profile."""

from __future__ import annotations
import logging
import os
from datetime import datetime, timezone
import requests

logger = logging.getLogger(__name__)
_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
_GITHUB_ORG = os.getenv("GITHUB_ORG", "KytranKatarn")
_GITHUB_API = "https://api.github.com"


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github.v3+json"}
    if _GITHUB_TOKEN:
        h["Authorization"] = f"token {_GITHUB_TOKEN}"
    return h


def fetch_public_repos() -> list:
    """Fetch all public repos for the GitHub org/user."""
    repos = []
    page = 1
    while True:
        resp = requests.get(
            f"{_GITHUB_API}/users/{_GITHUB_ORG}/repos",
            headers=_gh_headers(),
            params={"type": "public", "per_page": 100, "page": page},
            timeout=15,
        )
        if resp.status_code != 200:
            logger.error("[GitHubPresence] Failed to fetch repos: %s", resp.status_code)
            break
        batch = resp.json()
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def run_presence_audit() -> dict:
    """Fetch public repos, dispatch to F.O.R.G.E., store in KB and inbox."""
    from tools.department_hq.services.department_dispatcher import dispatch
    from services.director_report_service import submit_via_inbox
    from database import get_db_cursor

    repos = fetch_public_repos()
    if not repos:
        logger.warning("[GitHubPresence] No public repos found for %s", _GITHUB_ORG)
        return {"repo_count": 0, "success": False}

    lines = []
    for r in repos:
        topics = ", ".join(r.get("topics", [])[:3]) or "none"
        desc = (r.get("description") or "no description")[:60]
        lines.append(
            f"- {r['name']}: {desc} | stars={r.get('stargazers_count', 0)}"
            f" | updated={r.get('updated_at', '?')[:10]} | topics={topics}"
        )

    repo_summary = "\n".join(lines)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prompt = (
        f"You are F.O.R.G.E., reviewing the public GitHub profile of {_GITHUB_ORG}.\n\n"
        f"Public repos ({len(repos)} total):\n{repo_summary}\n\n"
        f"Provide your assessment:\n\n"
        f"SUMMARY\n2-3 sentences on overall GitHub public presence quality.\n\n"
        f"ISSUES\n- [HIGH/MEDIUM/LOW] <issue> — <recommendation>\n"
        f"(If presence is strong, write: No significant issues.)\n\n"
        f"VERDICT: PROFESSIONAL | NEEDS IMPROVEMENT | URGENT ACTION NEEDED"
    )

    try:
        result = dispatch(capability="code_review", prompt=prompt, module_id="repair_bay")
        analysis = result.response.strip() if result.success and result.response else None
    except Exception as exc:
        logger.error("[GitHubPresence] F.O.R.G.E. dispatch failed: %s", exc)
        return {"repo_count": len(repos), "success": False}

    if not analysis:
        logger.warning("[GitHubPresence] F.O.R.G.E. returned empty response")
        return {"repo_count": len(repos), "success": False}

    # Store in knowledge base
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO knowledge_base
                  (title, content, knowledge_type, category, importance_score, has_embedding)
                VALUES (%s, %s, 'vault_note', 'github_presence', 0.75, FALSE)
                """,
                (
                    f"GitHub Presence Audit — {today}",
                    f"# GitHub Presence Audit — {today}\n\nRepos: {len(repos)}\n\n{analysis}",
                ),
            )
        logger.info("[GitHubPresence] Stored audit in KB")
    except Exception as exc:
        logger.warning("[GitHubPresence] Failed to store in KB: %s", exc)

    # Send to inbox
    try:
        submit_via_inbox(
            category="github_audit",
            title=f"F.O.R.G.E. GitHub Presence Audit — {today} ({len(repos)} repos)",
            message=analysis,
            source_agent="F.O.R.G.E.",
            severity="info",
            department="Engineering & Technology",
        )
    except Exception as exc:
        logger.warning("[GitHubPresence] Failed to submit to inbox: %s", exc)

    return {"repo_count": len(repos), "summary_length": len(analysis), "success": True}

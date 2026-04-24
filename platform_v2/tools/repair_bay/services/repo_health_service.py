"""Repo Health Service — daily per-repo GitHub presence check."""

from __future__ import annotations
import logging
import os
import requests

logger = logging.getLogger(__name__)
_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
_GITHUB_API = "https://api.github.com"


def _gh_headers() -> dict:
    h = {"Accept": "application/vnd.github.v3+json"}
    if _GITHUB_TOKEN:
        h["Authorization"] = f"token {_GITHUB_TOKEN}"
    return h


def check_repo_health(repo: str) -> dict:
    """Check a single repo for public presence completeness.
    Returns: {repo, issues: list[str], healthy: bool}
    """
    issues = []
    try:
        resp = requests.get(f"{_GITHUB_API}/repos/{repo}", headers=_gh_headers(), timeout=15)
        if resp.status_code != 200:
            logger.warning("[RepoHealth] Failed to fetch %s: %s", repo, resp.status_code)
            return {"repo": repo, "issues": [f"API error {resp.status_code}"], "healthy": False}
        data = resp.json()
        if not data.get("description"):
            issues.append("No description set")
        else:
            issues.append(f"Description: {data['description'][:60]}")
        topics = data.get("topics", [])
        if not topics:
            issues.append("No topics tagged")
        else:
            issues.append(f"Topics: {', '.join(topics[:5])}")
        if not data.get("license"):
            issues.append("No license file")
        else:
            issues.append(f"License: {data['license'].get('spdx_id', 'present')}")
    except Exception as exc:
        logger.error("[RepoHealth] Error checking %s: %s", repo, exc)
        return {"repo": repo, "issues": [f"Error: {exc}"], "healthy": False}

    try:
        readme_resp = requests.get(f"{_GITHUB_API}/repos/{repo}/readme", headers=_gh_headers(), timeout=10)
        if readme_resp.status_code == 200:
            issues.append("README present")
        else:
            issues.append("No README found")
    except Exception as exc:
        issues.append(f"README check failed: {exc}")

    problem_lines = [l for l in issues if any(w in l for w in ["No ", "Error", "failed"])]
    healthy = len(problem_lines) == 0
    return {"repo": repo, "issues": issues, "healthy": healthy}


def run_health_checks() -> dict:
    """Run health checks for all tracked repos. Submit inbox report for unhealthy ones."""
    from tools.repair_bay.services.pr_review_service import get_tracked_repos
    from services.director_report_service import submit_via_inbox

    repos = get_tracked_repos()
    healthy_count = unhealthy_count = 0
    for repo in repos:
        result = check_repo_health(repo)
        if result["healthy"]:
            logger.info("[RepoHealth] %s — all clear", repo)
            healthy_count += 1
        else:
            unhealthy_count += 1
            problem_lines = [l for l in result["issues"] if any(w in l for w in ["No ", "Error", "failed"])]
            message = (
                f"Repo: {repo}\n\n"
                + "\n".join(f"- {l}" for l in result["issues"])
                + f"\n\nView: https://github.com/{repo}"
            )
            try:
                submit_via_inbox(
                    category="repo_health",
                    title=f"Repo Health: {len(problem_lines)} issue(s) — {repo}",
                    message=message,
                    source_agent="F.O.R.G.E.",
                    severity="warning",
                    department="Engineering & Technology",
                )
                logger.info("[RepoHealth] %s — %d issues, reported to inbox", repo, len(problem_lines))
            except Exception as exc:
                logger.error("[RepoHealth] Failed to submit report for %s: %s", repo, exc)
    return {"checked": len(repos), "healthy": healthy_count, "unhealthy": unhealthy_count}

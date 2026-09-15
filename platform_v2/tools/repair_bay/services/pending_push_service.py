"""
Pending Push Service — scans local git for branches with unpushed commits.

No DB writes. Reads git refs on-demand via `subprocess.run(git)`. Repo lives
at /mnt/archie_brain inside the container (mounted from host).
"""

import subprocess
from datetime import datetime, timezone


REPO_PATH = "/mnt/archie_brain"


def is_freeze_active(today=None):
    """Push freeze has been lifted. Always returns False."""
    return False


def _git(*args, check=False):
    """Run a git command in REPO_PATH, return stripped stdout (empty on error).

    Passes `-c safe.directory=REPO_PATH` because the container runs as root but
    the repo is owned by the host user — git would otherwise refuse with
    "detected dubious ownership in repository".
    """
    try:
        result = subprocess.run(
            ["git", "-c", f"safe.directory={REPO_PATH}", "-C", REPO_PATH, *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=check,
        )
        if result.returncode != 0 and not check:
            return ""
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError):
        return ""


def scan_pending_pushes():
    """
    Scan all local branches; return rows where local is ahead of origin.

    Each row:
      - branch: short branch name
      - local_sha: local tip (short)
      - remote_sha: origin tip (short) or None if no remote
      - commits_ahead: count of local commits not on origin
      - commits_behind: count of origin commits not local
      - last_touched: ISO datetime of local tip
      - last_commit_subject: commit subject line
      - has_remote: bool
    """
    # List all local branches with committer date + author email
    fmt = "%(refname:short)|%(objectname:short)|%(committerdate:iso-strict)|%(contents:subject)"
    raw = _git("for-each-ref", f"--format={fmt}", "refs/heads/")
    if not raw:
        return []

    rows = []
    for line in raw.split("\n"):
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        branch, local_sha, committer_iso, subject = parts

        # Remote ref sha (empty if no tracking)
        remote_sha = _git("rev-parse", "--short", f"refs/remotes/origin/{branch}") or None

        ahead = behind = 0
        has_remote = bool(remote_sha)
        if has_remote:
            # Use rev-list to count both sides
            counts = _git(
                "rev-list",
                "--left-right",
                "--count",
                f"refs/remotes/origin/{branch}...refs/heads/{branch}",
            )
            if counts and "\t" in counts:
                b, a = counts.split("\t", 1)
                try:
                    behind = int(b)
                    ahead = int(a)
                except ValueError:
                    pass

        rows.append(
            {
                "branch": branch,
                "local_sha": local_sha,
                "remote_sha": remote_sha,
                "commits_ahead": ahead,
                "commits_behind": behind,
                "last_touched": committer_iso,
                "last_commit_subject": subject,
                "has_remote": has_remote,
            }
        )

    # Sort: pending first (ahead > 0), then by last_touched desc
    rows.sort(
        key=lambda r: (r["commits_ahead"] == 0, r["last_touched"]),
        reverse=False,
    )
    # Actually we want ahead>0 first then newest-first — reverse the sort
    rows.sort(key=lambda r: r["last_touched"], reverse=True)
    rows.sort(key=lambda r: r["commits_ahead"] == 0)  # stable: pending first

    return rows


def pending_commit_subjects(branch, limit=20):
    """One-line subjects of the commits on *branch* not on origin/*branch*.

    Used by the Create-PR route to build the PR body.  Falls back to an
    empty list when the rev-list fails (e.g. no remote).
    """
    if not branch:
        return []
    has_remote = bool(_git("rev-parse", "--short", f"refs/remotes/origin/{branch}"))
    if has_remote:
        raw = _git(
            "log",
            "--format=%s",
            f"--max-count={limit}",
            f"refs/remotes/origin/{branch}..refs/heads/{branch}",
        )
    else:
        raw = _git(
            "log",
            "--format=%s",
            f"--max-count={limit}",
            f"refs/heads/{branch}",
        )
    return [ln for ln in raw.split("\n") if ln.strip()] if raw else []


def summarize():
    """Summary for the API and boot dashboard."""
    rows = scan_pending_pushes()
    pending = [r for r in rows if r["commits_ahead"] > 0]
    return {
        "freeze_active": False,
        "scanned_at": datetime.now(timezone.utc).isoformat() + "Z",
        "pending_branches": len(pending),
        "total_branches": len(rows),
        "total_commits_queued": sum(r["commits_ahead"] for r in pending),
        "branches": rows,
    }

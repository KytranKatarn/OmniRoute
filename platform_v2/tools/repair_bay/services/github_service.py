"""F.O.R.G.E. GitHub Service — Branch, PR, and Issue management via GitHub REST API.

Full-cycle Optimization & Regenerative GitHub Engine (Project #188).
Uses GitHub REST API + git subprocess for all operations.
Runs inside Docker — no gh CLI dependency.
"""

import json
import logging
import os
import subprocess
from typing import Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

# Repository config
REPO_OWNER = "KytranKatarn"
REPO_NAME = "archie-platform"
REPO_FULL = f"{REPO_OWNER}/{REPO_NAME}"
REPO_PATH = "/mnt/archie_brain"
PIPELINE_LABEL = "archie-forge"
SCAN_LABEL = "archie-scan"
API_BASE = "https://api.github.com"


def _get_token() -> str:
    """Get GitHub token from secrets or env."""
    token_path = "/mnt/archie_brain/secrets/api/github_token.txt"
    try:
        if os.path.exists(token_path):
            with open(token_path, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return os.environ.get("GITHUB_TOKEN", "")


def _get_read_token() -> str:
    """Read-only token for cross-repo GETs (PR/diff fetches on watch-product repos).

    Prefers FORGE_REVIEW_TOKEN (a least-privilege read PAT scoped to all repos); falls
    back to the write token so archie-platform reads still work if it is unset. Writes
    (_api_post / _api_patch / merge / git push) keep using _get_token()."""
    return os.environ.get("FORGE_REVIEW_TOKEN", "") or _get_token()


def _api_read_headers() -> Dict[str, str]:
    """GitHub API headers using the read token (for GETs across all repos)."""
    token = _get_read_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api_headers() -> Dict[str, str]:
    """Build GitHub API headers with auth."""
    token = _get_token()
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api_get(path: str, params: Dict = None, timeout: int = 15) -> Tuple[bool, Dict]:
    """GitHub API GET request."""
    try:
        resp = requests.get(
            f"{API_BASE}{path}",
            headers=_api_read_headers(),
            params=params,
            timeout=timeout,
        )
        if resp.status_code < 300:
            return True, resp.json()
        return False, {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    except Exception as e:
        return False, {"error": str(e)}


def _api_post(path: str, data: Dict = None, timeout: int = 15) -> Tuple[bool, Dict]:
    """GitHub API POST request."""
    try:
        resp = requests.post(
            f"{API_BASE}{path}",
            headers=_api_headers(),
            json=data or {},
            timeout=timeout,
        )
        if resp.status_code < 300:
            return True, resp.json()
        return False, {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    except Exception as e:
        return False, {"error": str(e)}


def _api_patch(path: str, data: Dict = None, timeout: int = 15) -> Tuple[bool, Dict]:
    """GitHub API PATCH request."""
    try:
        resp = requests.patch(
            f"{API_BASE}{path}",
            headers=_api_headers(),
            json=data or {},
            timeout=timeout,
        )
        if resp.status_code < 300:
            return True, resp.json()
        return False, {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    except Exception as e:
        return False, {"error": str(e)}


def _git_env() -> Dict[str, str]:
    """Build environment for git commands with token auth."""
    env = os.environ.copy()
    token = _get_token()
    if token:
        # Use token in remote URL via credential helper
        env["GIT_ASKPASS"] = "/bin/echo"
        env["GIT_TERMINAL_PROMPT"] = "0"
        # Configure git to use token-based HTTPS URLs
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = f"url.https://x-access-token:{token}@github.com/.insteadOf"
        env["GIT_CONFIG_VALUE_0"] = "https://github.com/"
    return env


def _run_git(args: List[str], timeout: int = 60) -> Tuple[bool, str, str]:
    """Run a git command in the repo directory with token auth."""
    cmd = ["git"] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=REPO_PATH,
            env=_git_env(),
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", f"git command timed out after {timeout}s"
    except Exception as e:
        return False, "", str(e)


# ============================================================================
# CONTAINER-LOCAL CLONE — pipeline branch/push ops (task #3926)
# ============================================================================
# The platform/scheduler containers run as ROOT while REPO_PATH is owned by
# the host user (uid 1000): git refuses with dubious-ownership, and "fixing"
# that via safe.directory would root-poison the host .git on every write.
# Instead, ALL local-git writes happen in this throwaway shallow clone on the
# container's /tmp tmpfs — the shared tree is never touched. This supersedes
# the #3919 busy-deferral for these ops; _primary_tree_busy remains available
# for any future operation that genuinely must run in the primary checkout.

CLONE_PATH = "/tmp/repair_bay_clone"
CLONE_URL = f"https://github.com/{REPO_FULL}.git"


def _run_git_clone(args: List[str], timeout: int = 120) -> Tuple[bool, str, str]:
    """Run a git command inside the container-local clone (auth via _git_env)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=CLONE_PATH,
            env=_git_env(),
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", f"git command timed out after {timeout}s"
    except Exception as e:
        return False, "", str(e)


def _ensure_clone(base: str = "main") -> Optional[str]:
    """Create/refresh the shallow blob-less clone. Returns an error string or None.

    --depth 1 --filter=blob:none --no-checkout keeps it a few MB on the 512M
    /tmp tmpfs; blobs are fetched on demand by the sparse checkout. A container
    restart wipes /tmp — the clone is recreated lazily on next use.
    """
    import shutil

    if not os.path.isdir(os.path.join(CLONE_PATH, ".git")):
        try:
            shutil.rmtree(CLONE_PATH, ignore_errors=True)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "--filter=blob:none", "--no-checkout", CLONE_URL, CLONE_PATH],
                capture_output=True,
                text=True,
                timeout=300,
                env=_git_env(),
            )
            if result.returncode != 0:
                return f"clone failed: {result.stderr.strip()[:300]}"
        except Exception as e:
            return f"clone failed: {e}"
    ok, _, err = _run_git_clone(["fetch", "--depth", "1", "origin", f"+refs/heads/{base}:refs/remotes/origin/{base}"])
    if not ok:
        return f"fetch failed: {err[:300]}"
    return None


# ============================================================================
# LABELS — ensure pipeline labels exist
# ============================================================================


def ensure_labels():
    """Create pipeline labels if they don't exist."""
    labels = [
        (PIPELINE_LABEL, "F.O.R.G.E. automated pipeline PR", "8b5cf6"),
        (SCAN_LABEL, "F.O.R.G.E. scan finding", "ef4444"),
        ("forge-regression", "F.O.R.G.E. regression detected", "f97316"),
        ("forge-approved", "F.O.R.G.E. approved for merge", "22c55e"),
    ]
    for name, desc, color in labels:
        _api_post(
            f"/repos/{REPO_FULL}/labels",
            {"name": name, "description": desc, "color": color},
        )


# ============================================================================
# BRANCHES
# ============================================================================


def _primary_tree_busy() -> Optional[str]:
    """Return a reason string when the shared checkout must NOT be touched.

    REPO_PATH is the LIVE volume-mounted tree shared with interactive
    Claude/owner sessions. Branch-switching here while a session is mid-branch
    destroys their state — twice this week a session's commit was stranded on
    main / its branch reset by an async pipeline call (task #3919,
    KB #272080). Same contract as codex-prod-deploy.sh's safety guard:
    pipelines DEFER instead of clobbering; callers get success=False with
    deferred=True and retry on a later cycle.
    """
    ok, branch, _ = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if not ok:
        return "cannot determine current branch"
    if branch.strip() != "main":
        return f"checkout is on branch '{branch.strip()}'"
    ok, status, _ = _run_git(["status", "--porcelain"])
    if not ok:
        return "cannot determine tree status"
    if status.strip():
        return "working tree has uncommitted changes"
    return None


def create_branch(branch_name: str, base: str = "main") -> Dict:
    """Create a new branch from origin/<base> and push it.

    Task #3926: operates entirely in the container-local clone — server-side
    ref creation via push of the fetched base tip. No working tree, and the
    shared REPO_PATH checkout is never touched.
    """
    err = _ensure_clone(base)
    if err:
        return {"success": False, "error": err}

    ok, out, _ = _run_git_clone(["ls-remote", "--heads", "origin", branch_name])
    if ok and out.strip():
        return {"success": True, "branch": branch_name, "existed": True}

    ok, out, err2 = _run_git_clone(["push", "origin", f"origin/{base}:refs/heads/{branch_name}"])
    if not ok:
        return {"success": False, "error": f"Branch creation failed: {err2}"}
    return {"success": True, "branch": branch_name, "existed": False}


def delete_branch(branch_name: str, remote: bool = True) -> Dict:
    """Delete a branch in the local clone and optionally on remote (#3926)."""
    if os.path.isdir(os.path.join(CLONE_PATH, ".git")):
        _run_git_clone(["branch", "-D", branch_name])
    if remote:
        err = _ensure_clone()
        if err:
            return {"success": False, "error": err}
        ok, _, err2 = _run_git_clone(["push", "origin", "--delete", branch_name])
        if not ok:
            # Was silently ignored before — surfaced during #3926 E2E when the
            # test branch survived its own cleanup.
            return {"success": False, "branch": branch_name, "error": f"remote delete failed: {err2[:200]}"}
    return {"success": True, "branch": branch_name}


def push_changes(branch_name: str, files: List[str], commit_message: str) -> Dict:
    """Stage files, commit, and push to a branch — in the local clone (#3926).

    File CONTENT comes from REPO_PATH, where the pipeline wrote it (READING
    the shared tree is safe — we just never run git there): each listed path
    is copied into the clone, or staged as a deletion when missing. Sparse
    checkout of only the touched paths keeps tmpfs usage minimal.
    """
    import shutil

    # Path-traversal guard (security review on PR #1557): `files` originates
    # from pipeline proposal data — reject absolute paths and anything that
    # escapes the repo root BEFORE it reaches sparse-checkout, the copy, or
    # git add/rm. realpath also catches in-repo symlinks pointing outside.
    repo_real = os.path.realpath(REPO_PATH)
    safe_files: List[str] = []
    for f in files:
        norm = os.path.normpath(str(f))
        if os.path.isabs(norm) or norm.startswith("..") or norm.startswith("-") or norm in (".", ""):
            return {"success": False, "error": f"invalid path rejected: {f!r}"}
        src_real = os.path.realpath(os.path.join(REPO_PATH, norm))
        if os.path.commonpath([src_real, repo_real]) != repo_real:
            return {"success": False, "error": f"path escapes repo root: {f!r}"}
        safe_files.append(norm)

    err = _ensure_clone()
    if err:
        return {"success": False, "error": err}

    # Explicit refspec: a --depth 1 clone is single-branch, so a bare
    # `fetch origin <branch>` lands only in FETCH_HEAD and never creates the
    # origin/<branch> ref the checkout below needs.
    ok, _, err2 = _run_git_clone(
        ["fetch", "--depth", "1", "origin", f"+refs/heads/{branch_name}:refs/remotes/origin/{branch_name}"]
    )
    if not ok:
        return {"success": False, "error": f"Fetch of {branch_name} failed: {err2}"}
    _run_git_clone(["sparse-checkout", "set", "--no-cone", "--"] + safe_files)
    ok, _, err2 = _run_git_clone(["checkout", "-B", branch_name, f"origin/{branch_name}"])
    if not ok:
        return {"success": False, "error": f"Checkout failed: {err2}"}

    clone_real = os.path.realpath(CLONE_PATH)
    for f in safe_files:
        src = os.path.join(REPO_PATH, f)
        dst = os.path.join(CLONE_PATH, f)
        # Symlinked dirs inside the clone could redirect dst outside tmpfs.
        if os.path.commonpath([os.path.realpath(dst), clone_real]) != clone_real:
            return {"success": False, "error": f"destination escapes clone: {f!r}"}
        if os.path.exists(src):
            dst_dir = os.path.dirname(dst)
            if dst_dir:
                os.makedirs(dst_dir, exist_ok=True)
            shutil.copy2(src, dst)
            _run_git_clone(["add", "--", f])
        else:
            _run_git_clone(["rm", "--ignore-unmatch", "-q", "--", f])

    ok, _, _ = _run_git_clone(["diff", "--cached", "--quiet"])
    if ok:
        return {"success": True, "committed": False, "message": "No changes to commit"}

    ok, out, err2 = _run_git_clone(
        ["-c", "user.email=forge@kytranempowerment.com", "-c", "user.name=F.O.R.G.E.", "commit", "-m", commit_message]
    )
    if not ok:
        return {"success": False, "error": f"Commit failed: {err2}"}

    ok, out, err2 = _run_git_clone(["push", "origin", branch_name])
    if not ok:
        return {"success": False, "error": f"Push failed: {err2}"}

    ok, sha, _ = _run_git_clone(["rev-parse", "HEAD"])
    return {"success": True, "committed": True, "sha": sha, "branch": branch_name}


# ============================================================================
# PULL REQUESTS
# ============================================================================


def create_pr(
    branch_name: str,
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
    base: str = "main",
) -> Dict:
    """Create a pull request via GitHub API."""
    if labels is None:
        labels = [PIPELINE_LABEL]

    ok, data = _api_post(
        f"/repos/{REPO_FULL}/pulls",
        {
            "title": title,
            "body": body,
            "head": branch_name,
            "base": base,
        },
        timeout=30,
    )
    if not ok:
        return {"success": False, "error": data.get("error", "PR creation failed")}

    pr_number = data.get("number")
    pr_url = data.get("html_url", "")

    # Add labels
    if labels and pr_number:
        _api_post(
            f"/repos/{REPO_FULL}/issues/{pr_number}/labels",
            {"labels": labels},
        )

    return {
        "success": True,
        "pr_url": pr_url,
        "pr_number": pr_number,
        "branch": branch_name,
    }


def get_pr_status(pr_number: int) -> Dict:
    """Get PR status including checks and reviews."""
    ok, data = _api_get(f"/repos/{REPO_FULL}/pulls/{pr_number}")
    if not ok:
        return {"success": False, "error": data.get("error")}

    # Get reviews
    ok2, reviews = _api_get(f"/repos/{REPO_FULL}/pulls/{pr_number}/reviews")
    review_list = reviews if ok2 and isinstance(reviews, list) else []

    # Get review comments
    ok3, comments = _api_get(f"/repos/{REPO_FULL}/pulls/{pr_number}/comments")
    comment_list = comments if ok3 and isinstance(comments, list) else []

    # Get issue comments (general PR comments — CodeRabbit posts walkthroughs here)
    ok4, issue_comments = _api_get(f"/repos/{REPO_FULL}/issues/{pr_number}/comments")
    issue_comment_list = issue_comments if ok4 and isinstance(issue_comments, list) else []

    # Build forge_reviews: formal reviews + CodeRabbit issue comments
    forge_reviews = [
        {
            "review_status": (r.get("state") or "commented").lower(),
            "review_source": (r.get("user") or {}).get("login", "reviewer"),
            "created_at": r.get("submitted_at") or r.get("created_at"),
            "body": (r.get("body") or "")[:300],
        }
        for r in review_list
        if (r.get("user") or {}).get("login")
    ]
    # Add CodeRabbit walkthrough comments
    for c in issue_comment_list:
        login = (c.get("user") or {}).get("login", "")
        if "coderabbit" in login.lower() or "coderabbit" in (c.get("body") or "").lower()[:100]:
            forge_reviews.append(
                {
                    "review_status": "commented",
                    "review_source": login or "coderabbit-ai[bot]",
                    "created_at": c.get("created_at"),
                    "body": (c.get("body") or "")[:3000],
                }
            )

    return {
        "success": True,
        "state": data.get("state"),
        "mergeable": data.get("mergeable"),
        "title": data.get("title"),
        "labels": [l.get("name") for l in data.get("labels", [])],
        "reviews": forge_reviews,
        "forge_reviews": forge_reviews,
        "review_comments": len(comment_list),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


def merge_pr(pr_number: int, method: str = "squash") -> Dict:
    """Merge a pull request via PUT (GitHub requires PUT for merges).

    Pre-merge conflict guard (#3709 Phase 1): refuses to merge when GitHub
    reports a definitive conflict with the base branch — stops a conflicted
    branch from being squash-merged and breaking main (the "don't break each
    other's builds" guard). GitHub's ``mergeable_state`` can be: clean, dirty
    (= merge conflict), behind, blocked, unstable, draft, has_hooks, unknown
    (still computing). We HARD-block only on a definitive conflict; 'unknown'
    means GitHub has not finished computing, so we re-poll once before allowing
    (never false-block on a transient unknown). 'behind'/'blocked'/'unstable'
    are CI/branch-protection states, not conflicts — GitHub itself rejects
    those with a clear error, so we let the merge attempt surface it.
    """
    pre_ok, pre = _api_get(f"/repos/{REPO_FULL}/pulls/{pr_number}")
    if pre_ok:
        state = (pre.get("mergeable_state") or "").lower()
        mergeable = pre.get("mergeable")
        if state == "unknown" or mergeable is None:
            import time as _time

            _time.sleep(2)
            pre_ok2, pre2 = _api_get(f"/repos/{REPO_FULL}/pulls/{pr_number}")
            if pre_ok2:
                state = (pre2.get("mergeable_state") or "").lower()
                mergeable = pre2.get("mergeable")
        if mergeable is False or state == "dirty":
            return {
                "success": False,
                "merged": False,
                "conflict": True,
                "mergeable_state": state,
                "error": (
                    f"Refusing to merge PR #{pr_number}: conflicts with base "
                    f"(mergeable={mergeable}, mergeable_state={state!r}). "
                    f"Rebase the branch on main and resolve conflicts first."
                ),
            }
    try:
        resp = requests.put(
            f"{API_BASE}/repos/{REPO_FULL}/pulls/{pr_number}/merge",
            headers=_api_headers(),
            json={"merge_method": method},
            timeout=30,
        )
        if resp.status_code >= 300:
            return {
                "success": False,
                "merged": False,
                "error": f"Merge failed: HTTP {resp.status_code} - {resp.text[:200]}",
            }
        ok = True
        data = resp.json()
    except Exception as e:
        return {"success": False, "merged": False, "error": str(e)}

    # Delete the branch after merge
    if ok:
        pr_ok, pr_data = _api_get(f"/repos/{REPO_FULL}/pulls/{pr_number}")
        if pr_ok:
            branch = pr_data.get("head", {}).get("ref")
            if branch and branch != "main":
                try:
                    requests.delete(
                        f"{API_BASE}/repos/{REPO_FULL}/git/refs/heads/{branch}",
                        headers=_api_headers(),
                        timeout=10,
                    )
                except Exception:
                    pass

    return {
        "success": True,
        # GitHub's merge response carries "merged": true; default True since a
        # <300 status already confirmed the merge. Callers check .get("merged").
        "merged": bool(data.get("merged", False)),
        "pr_number": pr_number,
        "method": method,
        "sha": data.get("sha", ""),
        "message": data.get("message", ""),
    }


def list_pipeline_prs(state: str = "open") -> Dict:
    """List all F.O.R.G.E. pipeline PRs."""
    ok, data = _api_get(
        f"/repos/{REPO_FULL}/pulls",
        {"state": state, "per_page": 50},
    )
    if not ok:
        return {"success": False, "error": data.get("error")}

    # Filter by pipeline label
    prs = [
        {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "state": pr.get("state"),
            "created_at": pr.get("created_at"),
            "url": pr.get("html_url"),
            "labels": [l.get("name") for l in pr.get("labels", [])],
        }
        for pr in (data if isinstance(data, list) else [])
        if any(l.get("name") == PIPELINE_LABEL for l in pr.get("labels", []))
    ]

    return {"success": True, "prs": prs, "count": len(prs)}


def list_all_prs_enriched(state: str = "open", repo: str = None) -> Dict:
    """List ALL PRs (not label-filtered) enriched with check status + review
    decision. Used by the Repair Bay Reviews tab so admins can see every open
    PR at a glance, not just pipeline-labeled ones.

    Enrichment per PR (parallelized via ThreadPoolExecutor):
      - mergeable: MERGEABLE | CONFLICTING | UNKNOWN
      - review_decision: APPROVED | CHANGES_REQUESTED | REVIEW_REQUIRED | NONE
      - checks: {lint, test, docker_build, coderabbit: success|failure|pending}
      - coderabbit_status: success if a CodeRabbit review exists
    """
    import concurrent.futures

    # repo-aware (default = the platform repo); lets F.O.R.G.E. review PRs in
    # other repos (e.g. archie-code, the engine repo) — #4295. _enrich() below
    # closes over this local so all its API calls hit the same repo.
    repo = repo or REPO_FULL

    ok, data = _api_get(
        f"/repos/{repo}/pulls",
        {"state": state, "per_page": 50, "sort": "updated", "direction": "desc"},
    )
    if not ok:
        return {"success": False, "error": data.get("error")}

    if not isinstance(data, list):
        return {"success": True, "prs": [], "count": 0}

    base_prs = [
        {
            "number": pr.get("number"),
            "title": pr.get("title"),
            "state": pr.get("state"),
            "user": (pr.get("user") or {}).get("login"),
            "head_ref": (pr.get("head") or {}).get("ref"),
            "head_sha": (pr.get("head") or {}).get("sha"),
            "created_at": pr.get("created_at"),
            "updated_at": pr.get("updated_at"),
            "html_url": pr.get("html_url"),
            "diff_url": f"https://api.github.com/repos/{repo}/pulls/{pr.get('number')}",
            "draft": pr.get("draft", False),
            "additions": None,
            "deletions": None,
            "changed_files": None,
            "mergeable": "UNKNOWN",
            "review_decision": "NONE",
            "checks": {},
            "coderabbit_status": None,
        }
        for pr in data
    ]

    def _enrich(pr):
        num = pr["number"]
        sha = pr["head_sha"]

        # Detail call for mergeable state
        det_ok, det = _api_get(f"/repos/{repo}/pulls/{num}", timeout=8)
        if det_ok and isinstance(det, dict):
            mergeable = det.get("mergeable")
            if mergeable is True:
                pr["mergeable"] = "MERGEABLE"
            elif mergeable is False:
                pr["mergeable"] = "CONFLICTING"
            # else leave UNKNOWN (still computing)
            # Diff size — the /pulls/{num} detail call carries these; the list
            # endpoint does not. Populating them feeds the F.O.R.G.E. review
            # prompt header + PR Review tab size badges (were always NULL).
            pr["additions"] = det.get("additions")
            pr["deletions"] = det.get("deletions")
            pr["changed_files"] = det.get("changed_files")

        # Reviews → review decision
        rev_ok, reviews = _api_get(f"/repos/{repo}/pulls/{num}/reviews", timeout=8)
        if rev_ok and isinstance(reviews, list) and reviews:
            # Latest review per reviewer wins
            latest = {}
            for r in reviews:
                reviewer = (r.get("user") or {}).get("login", "")
                latest[reviewer] = r.get("state")
            states = list(latest.values())
            if any(s == "CHANGES_REQUESTED" for s in states):
                pr["review_decision"] = "CHANGES_REQUESTED"
            elif any(s == "APPROVED" for s in states):
                pr["review_decision"] = "APPROVED"
            # Detect CodeRabbit review
            for reviewer, state_ in latest.items():
                if "coderabbit" in reviewer.lower():
                    pr["coderabbit_status"] = "success" if state_ in ("APPROVED", "COMMENTED") else "pending"
                    pr["checks"]["coderabbit"] = pr["coderabbit_status"]
                    break

        # Check runs for the head SHA
        if sha:
            chk_ok, chk = _api_get(
                f"/repos/{repo}/commits/{sha}/check-runs",
                params={"per_page": 30},
                timeout=8,
            )
            if chk_ok and isinstance(chk, dict):
                for run in chk.get("check_runs", []):
                    name = (run.get("name") or "").lower()
                    status = run.get("status")  # queued | in_progress | completed
                    concl = run.get("conclusion")  # success | failure | skipped | ...
                    if status != "completed":
                        val = "pending"
                    elif concl == "success":
                        val = "success"
                    elif concl in ("failure", "cancelled", "timed_out"):
                        val = "failure"
                    else:
                        val = concl or "unknown"
                    # Bucket by canonical name
                    if "lint" in name:
                        pr["checks"]["lint"] = val
                    elif "test" in name:
                        pr["checks"]["test"] = val
                    elif "docker" in name or "build" in name:
                        pr["checks"]["docker_build"] = val
                    elif "coderabbit" in name:
                        pr["checks"]["coderabbit"] = val
                        if not pr["coderabbit_status"]:
                            pr["coderabbit_status"] = val
        return pr

    enriched = []
    # Parallelize enrichment — 11 PRs * 3 API calls each = ~33 HTTP requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_enrich, pr): pr for pr in base_prs}
        for fut in concurrent.futures.as_completed(futures, timeout=25):
            try:
                enriched.append(fut.result())
            except Exception as exc:
                logger.warning("PR enrichment failed: %s", exc)
                enriched.append(futures[fut])

    # Preserve the original order (updated_desc)
    order_map = {pr["number"]: i for i, pr in enumerate(base_prs)}
    enriched.sort(key=lambda p: order_map.get(p["number"], 999))

    return {"success": True, "prs": enriched, "count": len(enriched)}


def add_pr_comment(pr_number: int, body: str) -> Dict:
    """Add a comment to a PR."""
    ok, data = _api_post(
        f"/repos/{REPO_FULL}/issues/{pr_number}/comments",
        {"body": body},
    )
    return {"success": ok, "error": data.get("error") if not ok else None}


# ============================================================================
# ISSUES
# ============================================================================


def create_issue(
    title: str,
    body: str,
    labels: Optional[List[str]] = None,
    severity: str = "high",
) -> Dict:
    """Create a GitHub issue from a scan finding."""
    if labels is None:
        labels = [SCAN_LABEL]
    labels.append(f"severity-{severity}")

    ok, data = _api_post(
        f"/repos/{REPO_FULL}/issues",
        {"title": title, "body": body, "labels": labels},
    )
    if not ok:
        return {"success": False, "error": data.get("error")}

    return {
        "success": True,
        "issue_url": data.get("html_url", ""),
        "issue_number": data.get("number"),
    }


# ============================================================================
# DEPENDABOT + CODERABBIT
# ============================================================================


def get_dependabot_alerts(state: str = "open") -> Dict:
    """Fetch Dependabot alerts from GitHub API."""
    ok, data = _api_get(f"/repos/{REPO_FULL}/dependabot/alerts", params={"state": state, "per_page": 100})
    if not ok:
        return {"success": False, "error": data.get("error", "API request failed")}
    alerts = []
    for alert in data:
        vuln = alert.get("security_vulnerability", {})
        alerts.append(
            {
                "number": alert.get("number"),
                "severity": vuln.get("severity", "unknown"),
                "package_name": vuln.get("package", {}).get("name"),
                "ecosystem": vuln.get("package", {}).get("ecosystem"),
                "vulnerable_range": vuln.get("vulnerable_version_range"),
                "fix_version": (vuln.get("first_patched_version") or {}).get("identifier"),
                "summary": alert.get("security_advisory", {}).get("summary"),
                "advisory_id": alert.get("security_advisory", {}).get("ghsa_id"),
                "manifest_path": alert.get("dependency", {}).get("manifest_path"),
                "state": alert.get("state"),
            }
        )
    return {"success": True, "alerts": alerts, "count": len(alerts)}


def dismiss_dependabot_alert(alert_number: int, reason: str = "fix_started") -> Dict:
    """Dismiss a Dependabot alert."""
    ok, data = _api_patch(
        f"/repos/{REPO_FULL}/dependabot/alerts/{alert_number}",
        data={"state": "dismissed", "dismissed_reason": reason},
    )
    if not ok:
        return {"success": False, "error": data.get("error", "Dismiss failed")}
    return {"success": True, "alert_number": alert_number, "state": "dismissed"}


def get_coderabbit_reviews(pr_number: int) -> Dict:
    """Fetch CodeRabbit review comments from a PR."""
    ok, data = _api_get(f"/repos/{REPO_FULL}/pulls/{pr_number}/comments")
    if not ok:
        return {"success": False, "error": data.get("error", "Failed to fetch reviews")}
    reviews = [
        {"body": c.get("body", ""), "created_at": c.get("created_at"), "path": c.get("path")}
        for c in data
        if "coderabbit" in (c.get("user", {}).get("login", "")).lower()
    ]
    return {"success": True, "reviews": reviews, "count": len(reviews)}


def close_issue(issue_number: int, comment: str = None) -> Dict:
    """Close a GitHub issue, optionally with a comment."""
    if comment:
        _api_post(
            f"/repos/{REPO_FULL}/issues/{issue_number}/comments",
            {"body": comment},
        )
    ok, data = _api_patch(
        f"/repos/{REPO_FULL}/issues/{issue_number}",
        {"state": "closed"},
    )
    return {"success": ok, "error": data.get("error") if not ok else None}


def find_existing_issue(file_path: str, issue_type: str) -> Optional[int]:
    """Check if an open issue already exists for this file+type (dedup)."""
    ok, data = _api_get(
        f"/repos/{REPO_FULL}/issues",
        {
            "labels": SCAN_LABEL,
            "state": "open",
            "per_page": 100,
        },
    )
    if not ok or not isinstance(data, list):
        return None

    search_term = f"{file_path}"
    for issue in data:
        if search_term in issue.get("title", "") or search_term in issue.get("body", ""):
            return issue.get("number")
    return None


# ============================================================================
# HEALTH CHECK
# ============================================================================


def health_check() -> Dict:
    """Check GitHub connectivity and auth status."""
    ok, data = _api_get("/user")
    if not ok:
        return {"success": False, "authenticated": False, "error": data.get("error")}

    # Check repo access
    ok2, repo_data = _api_get(f"/repos/{REPO_FULL}")
    repo_access = ok2

    return {
        "success": True,
        "authenticated": True,
        "user": data.get("login"),
        "repo_access": repo_access,
        "repo": REPO_FULL,
        "repo_visibility": repo_data.get("visibility") if ok2 else None,
    }

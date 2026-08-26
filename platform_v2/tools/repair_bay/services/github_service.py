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

from services.github_rate_helper import check_before_write, observe

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


def _rate_blocked(method: str, path: str, rl: Dict) -> Tuple[bool, Dict]:
    """Uniform (False, {...}) result when the rate guard blocks a write."""
    logger.warning("GitHub %s %s blocked by rate guard: %s", method, path, rl.get("reason"))
    return False, {
        "error": f"github rate limit guard: {rl.get('reason')}",
        "rate_limited": True,
        "rate_limit": rl,
    }


def _api_get(path: str, params: Dict = None, timeout: int = 15) -> Tuple[bool, Dict]:
    """GitHub API GET request."""
    try:
        resp = requests.get(
            f"{API_BASE}{path}",
            headers=_api_read_headers(),
            params=params,
            timeout=timeout,
        )
        # Read token = different quota bucket: harvest only for secondary-limit
        # detection, never move the write-bucket counter.
        observe(resp, is_write=False)
        if resp.status_code < 300:
            return True, resp.json()
        return False, {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    except Exception as e:
        return False, {"error": str(e)}


def _api_post(path: str, data: Dict = None, timeout: int = 15) -> Tuple[bool, Dict]:
    """GitHub API POST request."""
    allowed, rl = check_before_write(token=_get_token())
    if not allowed:
        return _rate_blocked("POST", path, rl)
    try:
        resp = requests.post(
            f"{API_BASE}{path}",
            headers=_api_headers(),
            json=data or {},
            timeout=timeout,
        )
        observe(resp, is_write=True)
        if resp.status_code < 300:
            return True, resp.json()
        return False, {"error": f"HTTP {resp.status_code}", "detail": resp.text[:200]}
    except Exception as e:
        return False, {"error": str(e)}


def _api_patch(path: str, data: Dict = None, timeout: int = 15) -> Tuple[bool, Dict]:
    """GitHub API PATCH request."""
    allowed, rl = check_before_write(token=_get_token())
    if not allowed:
        return _rate_blocked("PATCH", path, rl)
    try:
        resp = requests.patch(
            f"{API_BASE}{path}",
            headers=_api_headers(),
            json=data or {},
            timeout=timeout,
        )
        observe(resp, is_write=True)
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
    allowed, rl = check_before_write(token=_get_token())
    if not allowed:
        logger.warning("push to %s blocked by rate guard: %s", branch_name, rl.get("reason"))
        return {
            "success": False,
            "error": f"github rate limit guard: {rl.get('reason')}",
            "rate_limited": True,
            "rate_limit": rl,
        }

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


def pr_merge_state(pr_number: int, repo: str = None) -> Optional[str]:
    """'merged' | 'closed' (unmerged) | 'open' | None when GitHub is unreadable.

    Spec 2026-08-26 §6.4: the proposal merge-completion scanner needs to tell a
    MERGED PR (complete the proposal) from a CLOSED-unmerged one (fix_requested).
    Same single-call, repo-aware, None-on-error contract as pr_is_open below —
    and the same asymmetry: the caller must treat None as "leave the row alone".
    """
    target = repo or REPO_FULL
    ok, data = _api_get(f"/repos/{target}/pulls/{pr_number}")
    if not ok or not isinstance(data, dict):
        return None
    if data.get("merged_at") or data.get("merged"):
        return "merged"
    state = data.get("state")
    if state == "closed":
        return "closed"
    if state == "open":
        return "open"
    return None


def pr_is_open(pr_number: int, repo: str = None) -> Optional[bool]:
    """Is this PR still open on GitHub? ``None`` when it cannot be determined.

    #5419. Deliberately ONE API call and repo-aware — ``get_pr_status`` below
    fires four and is hardcoded to ``REPO_FULL``, so it is both wasteful for a
    state check and wrong for the non-default repos F.O.R.G.E. reviews.

    Exists because ``pr_reviews.state`` is only refreshed by ``sync_closed_prs``
    on a 4-hour cycle, so a PR merged out-of-band keeps reading ``open`` to the
    tiered-merge worker for hours. The governance gate is checked BEFORE any
    GitHub call (by design — a refusal must cost no API quota), so the refusal
    path never discovers the PR is already merged.

    ⚠️ The caller must treat ``None`` as "still open". Failing to notify on a
    genuinely blocked PR reintroduces the silence bug #5413 fixed; a redundant
    notification is merely noise. Those are not symmetric.
    """
    target = repo or REPO_FULL
    ok, data = _api_get(f"/repos/{target}/pulls/{pr_number}")
    if not ok or not isinstance(data, dict):
        return None
    if data.get("merged_at") or data.get("merged"):
        return False
    state = (data.get("state") or "").lower()
    if not state:
        return None
    return state == "open"


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
        # GitHub's `state` is only open|closed — it cannot distinguish MERGED
        # from closed-without-merge. Callers deciding "is this already done?"
        # (e.g. the idempotent pr_merge approval executor) need the real answer,
        # so surface it rather than making them infer it from 'closed'.
        "merged": bool(data.get("merged")),
        "merged_at": data.get("merged_at"),
        "mergeable": data.get("mergeable"),
        "title": data.get("title"),
        "labels": [l.get("name") for l in data.get("labels", [])],
        "reviews": forge_reviews,
        "forge_reviews": forge_reviews,
        "review_comments": len(comment_list),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
    }


# Per-authority auto-merge ceilings. classify_pr_tier's own docstring reads
# "tier 1 (F.O.R.G.E.), 2 (A.R.C.H.I.E.), 3 (Kytran)" — the tier ladder is an AUTHORITY
# ladder, so the ceiling must be scoped to the ACTOR doing the merging. The first cut of
# the #5194 gate read FORGE_AUTO_MERGE_MAX_TIER for every caller, which applied a
# F.O.R.G.E.-scoped limit to A.R.C.H.I.E.'s Tier-2 COO path and silently removed the COO
# from her own loop — flattening a three-actor model into "only F.O.R.G.E.-sized changes
# ever merge". Safety properties (an approved verdict) are UNIVERSAL; authority limits
# are PER-ACTOR.
_AUTHORITY_CEILING = {
    "forge": ("FORGE_AUTO_MERGE_MAX_TIER", 1),  # Engineering director — small changes
    "coo": ("ARCHIE_COO_AUTO_MERGE_MAX_TIER", 2),  # A.R.C.H.I.E. — COO authority
    # STRICTLY NARROWER THAN 'coo', never wider (#5247b). Same Tier-2 ceiling, plus a
    # THIRD condition: an announced maintenance window must be OPEN and the PR must be
    # on that window's approved manifest. Added as a separate authority rather than by
    # relaxing 'coo', so nothing that merges today gains any new power.
    "coo_window": ("ARCHIE_COO_AUTO_MERGE_MAX_TIER", 2),
}
_DEFAULT_AUTHORITY = "forge"  # most restrictive; an unknown caller never inherits COO powers

# Manifest item_types that denote an actual GitHub pull request. Anything else
# — 'unified_task', 'proposal', 'code_issue' (written by services.proposer_service
# onto this SAME maintenance_window_items table) — carries a `ref` that is a
# SOURCE-ROW id, not a PR number, and must never authorise a merge just because
# that id happens to collide with a real PR number (#380 review round 2, Critical 1).
_PR_ITEM_TYPES = ("repair_bay_pr", "pr")


def _pr_on_open_window(pr_number: int, repo: str = None) -> tuple:
    """Is there an OPEN maintenance window whose manifest contains this (repo, PR)? (#5247b)

    Four things must hold, and each exists for a reason:

      * a window is OPEN — not merely planned or announced. An announced window is
        a proposal; an open one is the period the owner agreed to.
      * the item's item_type denotes an actual pull request (_PR_ITEM_TYPES) —
        NOT a unified_task/proposal/code_issue row from proposer_service.py.
        Those share this same table and repo string, and their `ref` is a
        SOURCE-ROW id — measured to overlap real PR numbers (unified_tasks ids
        535-5985, improvement_proposals ids 328-11758, latest PR #2790). Matching
        on ref+repo alone let a window containing 'proposal ref 2790' authorise
        an unrelated PR #2790 (#380 review round 2, Critical 1).
      * the PR is ON that window's manifest — the owner was shown a SPECIFIC list
        beforehand. add_item() already refuses to extend a manifest once the window
        opens, so the list cannot grow after approval; honouring it here is what
        makes that refusal meaningful.
      * the item is still 'planned' — an item already marked deployed/failed must
        not be merged twice.

    FAILS CLOSED. No window, no manifest hit, a lookup error, or the schedule
    service being unavailable all return False. An unattended merge must never
    happen because a check could not be performed.

    REPO QUALIFICATION: PR numbers collide across repos. Matching on the number
    alone let a window listing archie-platform #48 authorise archie-code #48.
    An item naming no repo authorises NOTHING — fail closed, never assume the
    default repo, or the hole silently reopens.
    """
    try:
        from services.maintenance_schedule_service import get_manifest, list_windows

        want_repo = (repo or REPO_FULL or "").strip()
        open_windows = list_windows(status="open", limit=5) or []
        if not open_windows:
            return False, "no maintenance window is open"
        for w in open_windows:
            for item in get_manifest(w["id"]) or []:
                if str(item.get("ref") or "") != str(pr_number):
                    continue
                item_type = (item.get("item_type") or "").strip()
                if item_type not in _PR_ITEM_TYPES:
                    # Same ref, same repo, wrong kind of row — a source-row id
                    # collision, not a pull request. Skip it and keep scanning
                    # the rest of this window's manifest rather than denying
                    # outright, in case a genuine PR item with the same ref
                    # exists elsewhere on it.
                    continue
                item_repo = (item.get("repo") or "").strip()
                if not item_repo:
                    return False, (
                        f"PR #{pr_number} is on window {w['id']} but the entry names no repo "
                        f"— refusing (a repo-less entry authorises nothing)"
                    )
                if item_repo != want_repo:
                    return False, (
                        f"PR #{pr_number} on window {w['id']} is for {item_repo}, "
                        f"not {want_repo} — a window for one repo grants nothing in another"
                    )
                if (item.get("status") or "planned") != "planned":
                    return False, f"PR #{pr_number} already '{item.get('status')}' on window {w['id']}"
                return True, f"on the manifest of open window {w['id']} for {item_repo}"
        return False, f"PR #{pr_number} is not on any open window's approved manifest"
    except Exception as exc:  # noqa: BLE001 - fail closed, always
        return False, f"window check failed ({type(exc).__name__}) — refusing"


def verdict_refusal(summary: str, verdict_ok: bool, coverage_ack: bool = False) -> "str | None":
    """Why a stored verdict does not authorize a merge — or None if it does.

    ONE definition of the SAFETY half of merge governance, shared by every
    attended surface. Pure, so the decision is testable without a DB, GitHub or
    a Flask app.

    Deliberately covers ONLY the verdict. It does NOT re-impose the allowlist or
    the tier ceiling: those are AUTHORITY limits, and an authenticated human
    clicking Merge is precisely the authority they exist to require (decision
    #953 — safety properties are universal, authority limits are per-actor).
    Staleness is enforced separately, for every actor, inside merge_pr via
    _override_stale_verdict_check (#5672).

    ``ai_bridge.agent_loop.tab_merge_refusal`` delegates its verdict branches
    here so the Approvals tab and the two @admin_required Repair Bay routes
    cannot drift apart — a duplicated safety rule is how #2458 happened.
    """
    if not summary:
        return "no stored F.O.R.G.E. review — a dead review is not an approval"
    if verdict_ok:
        return None

    # THIRD STATE (#5834 follow-up): the model APPROVED what it read and the verdict was
    # demoted only because files were truncated away. The standing rule has always said a
    # coverage demotion is dischargeable by a human who reads the rest, while a REQUEST
    # CHANGES is not — but the coverage gate rewrites the final verdict, so both looked
    # identical here and the UI could offer neither. Fail CLOSED if the check itself breaks.
    try:
        from .pr_review_service import coverage_only_demotion  # noqa: PLC0415

        _coverage_only = coverage_only_demotion(summary)
    except Exception:  # noqa: BLE001 - an unverifiable demotion is not a dischargeable one
        _coverage_only = False

    if _coverage_only:
        if coverage_ack:
            return None
        return (
            "COVERAGE ONLY — the reviewer APPROVED what it read, but some files were "
            "truncated away before it saw them. Read the dropped files and confirm, or "
            "re-review with a wider window."
        )
    return "the stored verdict is NOT an approval — re-review before merging"


def _override_stale_verdict_check(pr_number: int, repo: str = None) -> tuple:
    """(ok, why) — refuse a human_override merge on a PROVEN-stale verdict (#5672).

    Runs for EVERY interactive override merge. Deliberately narrower than
    _automerge_governance_ok's condition 1b: the unattended gate fails closed on
    an unstamped row, but the override contract already requires a human to have
    verified the stored verdict in code, so here only a PROVEN mismatch refuses —
    the recorded reviewed_head_sha exists, the current head is readable, and they
    differ. Everything unprovable (no review row, no stamp, unreadable head, any
    exception) allows with a logged warning rather than re-litigating the gate.
    The remedy for a refusal is one re-review; merging around it needs raw `gh`,
    which is the correct amount of friction for merging unreviewed code.
    """
    try:
        from tools.repair_bay.services.pr_review_service import (  # noqa: PLC0415
            get_review,
            pr_head_sha,
        )

        review = get_review(pr_number, repo=repo)
        if not review:
            logger.warning(
                "[MergeGate] override merge of PR #%s with NO stored review — allowed (unprovable)", pr_number
            )
            return (True, "no stored review — staleness unprovable")
        reviewed_sha = str((review.get("metadata") or {}).get("reviewed_head_sha") or "").strip()
        if not reviewed_sha:
            logger.warning(
                "[MergeGate] override merge of PR #%s: review row has no reviewed_head_sha stamp — allowed (unprovable)",
                pr_number,
            )
            return (True, "review row predates SHA stamping — staleness unprovable")
        current_sha = pr_head_sha(pr_number, repo)
        if not current_sha:
            logger.warning(
                "[MergeGate] override merge of PR #%s: current head SHA unreadable — allowed (unprovable)", pr_number
            )
            return (True, "current head unreadable — staleness unprovable")
        if reviewed_sha != current_sha:
            return (
                False,
                f"STALE VERDICT for PR #{pr_number}: the review covers {reviewed_sha[:8]} but the "
                f"head is now {current_sha[:8]} — commits landed after the review. human_override "
                f"clears authority limits, not this: re-run review_pr() so the verdict covers the "
                f"code being merged",
            )
        return (True, f"verdict covers current head {current_sha[:8]}")
    except Exception as exc:
        logger.warning(
            "[MergeGate] override staleness check errored for PR #%s: %s — allowed (unprovable)", pr_number, exc
        )
        return (True, f"staleness check errored ({exc}) — unprovable")


def _automerge_governance_ok(pr_number: int, repo: str = None, authority: str = _DEFAULT_AUTHORITY) -> tuple:
    """Is an UNATTENDED merge of ``pr_number`` permitted? Returns ``(ok, reason)``.

    ``authority`` names the ACTOR merging — ``'forge'`` (default, Tier 1) or ``'coo'``
    (A.R.C.H.I.E., Tier 2). Tier 3 always escalates to Kytran and is never auto-merged.
    An unrecognised authority falls back to the most restrictive ceiling.

    THE choke point for merge governance (#5194, #5370). THREE independent conditions,
    all required:
      1. the stored F.O.R.G.E. review VERDICT is an approval,
      2. the PR touches ONLY auto-merge-allowlisted paths (#5370), and
      3. the PR's tier is <= ``FORGE_AUTO_MERGE_MAX_TIER`` (default 1).

    Conditions 1 and 2 are SAFETY properties and bind every actor identically;
    condition 3 is an AUTHORITY limit and is per-actor (decision #953). Keep new
    checks on the correct side of that line — a safety check placed inside a
    per-authority branch protects only one caller.

    FAILS CLOSED — a missing review row, an unparseable verdict, or any error denies
    the merge. A dead review is not an approval (feedback_forge-no-silent-override).

    Why this lives here and not in the callers: ``merge_pr`` has FIVE call sites
    (github_routes x2, forge_pipeline, and agent_loop's archie_pr_review_worker Tier 1
    + Tier 2). ``pr_review_service.mark_review_done`` carefully gates on verdict, tier,
    engine-authorship, repo and sensitive paths — but ``_run_archie_pr_review_worker``
    is a SECOND, parallel merge path that reproduced none of it: it selects reviews by
    ``review_status='reviewed'`` (which only means a review FINISHED, not that it
    approved), reads the summary purely for notification text, and merges Tier 2
    unconditionally. That is how PR #2458 reached main on a ``needs_changes`` verdict
    on 2026-07-25 — blocked twice beforehand only by an accidental HTTP 405
    "still a draft". Gating each caller would leave the next new caller unprotected.
    """
    try:
        from tools.repair_bay.services.pr_review_service import (  # noqa: PLC0415
            _automerge_paths_allowed,
            classify_pr_tier,
            get_review,
            pr_head_sha,
            verdict_is_approved,
        )

        review = get_review(pr_number, repo=repo)
        if not review:
            return (False, f"no stored F.O.R.G.E. review for PR #{pr_number} — refusing unattended merge")

        summary = review.get("ai_summary") or ""
        if not verdict_is_approved(summary):
            return (
                False,
                f"F.O.R.G.E. verdict for PR #{pr_number} is not an approval — refusing unattended merge",
            )

        # CONDITION 1b — THE VERDICT MUST COVER THE CODE BEING MERGED (#5646).
        #
        # Conditions 1 and 3 asked "is there an approval?" and "is the tier low
        # enough?" — never "did that approval SEE this commit?". The ordinary
        # workflow produces a stale verdict EVERY time: open PR -> review ->
        # address feedback -> push -> merge. The gate was blind exactly where it is
        # most needed.
        #
        # MEASURED on PR #2600 (2026-08-16): commit 347127e96 at 02:30:27Z, stored
        # APPROVE at 02:38:36Z, then commit c787958fc at 02:41:41Z touching a file
        # (linkedin_post_comments.py) the review had never seen. The gate reported a
        # clean approval. This is the #2458 shape one level up — the verdict was a
        # genuine approval, just of DIFFERENT code.
        #
        # SAFETY property, so it sits here with the other universal checks and NOT
        # inside the per-authority tier branch (decision #953): "the verdict covers
        # the code" binds F.O.R.G.E., the COO and every future actor identically.
        #
        # FAILS CLOSED on an unknown SHA either side. An older review row predating
        # this change has no stamp, so it cannot prove freshness and is refused —
        # deliberately: the remedy is one re-review, whereas trusting an unstamped
        # row silently reinstates the exact hole this closes.
        reviewed_sha = str((review.get("metadata") or {}).get("reviewed_head_sha") or "").strip()
        current_sha = pr_head_sha(pr_number, repo)
        if not reviewed_sha:
            return (
                False,
                f"the stored review for PR #{pr_number} does not record which commit it covers "
                f"(pre-#5646 row) — re-run review_pr() before merging",
            )
        if not current_sha:
            return (
                False,
                f"could not read the current head SHA for PR #{pr_number} — refusing to assume "
                f"the stored verdict is current",
            )
        if reviewed_sha != current_sha:
            return (
                False,
                f"STALE VERDICT for PR #{pr_number}: the review covers {reviewed_sha[:8]} but the "
                f"head is now {current_sha[:8]} — commits landed after the review; re-run "
                f"review_pr() so the verdict covers the code being merged",
            )

        # CONDITION 2 — SENSITIVE-PATH ALLOWLIST. Deny-by-default; code that RUNS
        # the platform is never auto-merged, by ANY actor.
        #
        # This check already existed in pr_review_service.mark_review_done, but NOT
        # here — so the tier worker's parallel path merged straight past it. PROVEN
        # on PR #2538 (2026-07-28): it auto-merged while changing
        # ai_bridge/agent_loop.py and pr_review_service.py, and
        # _automerge_paths_allowed(2538) returns False naming exactly those two
        # files. The gate WOULD have refused it; nothing ever asked.
        #
        # This is the SAME omission twice. #2409 reached main carrying
        # delegation_service.py "purely because the diff was small enough for
        # Tier 1" — which is why the allowlist was written. #2458 then merged on a
        # needs_changes verdict via this very second path, and the fix (#2459)
        # moved VERDICT and TIER to this choke point but left PATHS behind. The
        # stated lesson of #2459 was "gate the CHOKE POINT, never per-caller"; it
        # was applied to two conditions out of three.
        #
        # Placed BEFORE the tier/authority logic on purpose: per decision #953,
        # safety properties are UNIVERSAL while authority limits are per-actor. A
        # path allowlist is a safety property, so it binds F.O.R.G.E., the COO and
        # any future actor identically — it must not sit inside a per-authority
        # branch. It costs one GitHub call, and only after the cheap verdict check
        # has already passed, so it is spent only on merges that were otherwise
        # going to happen. `human_override=True` never reaches here: merge_pr
        # skips this whole function for an authenticated interactive caller.
        _paths_ok, _blocking = _automerge_paths_allowed(pr_number, repo or REPO_FULL)
        if not _paths_ok:
            _shown = ", ".join(_blocking[:5]) + (f" (+{len(_blocking) - 5} more)" if len(_blocking) > 5 else "")
            return (
                False,
                f"PR #{pr_number} changes files outside the auto-merge allowlist ({_shown}) "
                f"— refusing unattended merge; a human must merge it deliberately",
            )

        tier = classify_pr_tier(review)
        env_key, default_ceiling = _AUTHORITY_CEILING.get(
            (authority or "").lower(), _AUTHORITY_CEILING[_DEFAULT_AUTHORITY]
        )
        try:
            max_auto = int(os.getenv(env_key, str(default_ceiling)))
        except (TypeError, ValueError):
            max_auto = default_ceiling
        if tier > max_auto:
            return (
                False,
                f"PR #{pr_number} is Tier {tier} > {env_key}={max_auto} for authority "
                f"{authority!r} — gated for the next level up, refusing unattended merge",
            )
        # CONDITION 3 — 'coo_window' ONLY (#5247b). Everything above is unchanged for
        # every existing authority; this narrows the new one further. An unattended
        # merge under COO authority is permitted only INSIDE the window the owner
        # agreed to, for a PR that was on the list they were shown.
        if (authority or "").lower() == "coo_window":
            on_window, why = _pr_on_open_window(pr_number, repo=repo or REPO_FULL)
            if not on_window:
                return (False, f"PR #{pr_number}: {why} — refusing window-scoped merge")
            return (True, f"approved, Tier {tier} <= {max_auto}, {why}")

        return (True, f"approved, Tier {tier} <= {max_auto} under authority {authority!r}")
    except Exception as exc:  # fail CLOSED
        logger.warning("merge governance check failed for PR #%s (denying): %s", pr_number, exc)
        return (False, f"governance check errored for PR #{pr_number} — refusing unattended merge")


def merge_pr(
    pr_number: int,
    method: str = "squash",
    repo: str = None,
    human_override: bool = False,
    authority: str = _DEFAULT_AUTHORITY,
) -> Dict:
    """Merge a pull request via PUT (GitHub requires PUT for merges).

    ``human_override=True`` skips the unattended-merge governance gate (#5194) and is
    for INTERACTIVE, authenticated callers only (the Repair Bay merge button, an
    operator running /merge-pr). Every automated path must leave it False.

    ``repo`` (owner/name) selects the target repo; defaults to REPO_FULL
    (archie-platform). Threaded everywhere so a watch-product PR merges against
    its OWN repo instead of the hardcoded default (#4494). NOTE: the write token
    is archie-platform-scoped, so a non-default merge needs a write-capable token.

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
    _repo = repo or REPO_FULL

    # GOVERNANCE GATE (#5194) — checked BEFORE any GitHub call so a refusal costs
    # nothing and cannot race. Fails closed; see _automerge_governance_ok.
    if not human_override:
        _gov_ok, _gov_why = _automerge_governance_ok(pr_number, repo, authority=authority)
        if not _gov_ok:
            logger.warning("[MergeGate] refusing PR #%s: %s", pr_number, _gov_why)
            return {
                "success": False,
                "merged": False,
                "governance_blocked": True,
                "error": f"Refusing to merge PR #{pr_number}: {_gov_why}",
            }
        logger.info("[MergeGate] PR #%s cleared for unattended merge (%s)", pr_number, _gov_why)
    else:
        # #5672 — human_override clears AUTHORITY limits (tier ceiling, path
        # allowlist), never the SAFETY property that the verdict covers the code
        # being merged (decision #953). PROVEN on PR #2614 (2026-08-16): the gate
        # correctly refused a stale verdict, and human_override=True then merged
        # commits the review had never seen — because the override skipped the
        # whole gate rather than only the authority half. Refuse PROVEN staleness
        # for every actor; an unprovable case (pre-#5646 row with no SHA stamp,
        # or an unreadable head) stays with the human — the override contract
        # already requires the caller to verify the stored verdict in code.
        _fresh_ok, _fresh_why = _override_stale_verdict_check(pr_number, repo)
        if not _fresh_ok:
            logger.warning("[MergeGate] refusing OVERRIDE merge of PR #%s: %s", pr_number, _fresh_why)
            return {
                "success": False,
                "merged": False,
                "governance_blocked": True,
                "stale_verdict": True,
                "error": f"Refusing to merge PR #{pr_number}: {_fresh_why}",
            }

    pre_ok, pre = _api_get(f"/repos/{_repo}/pulls/{pr_number}")
    if pre_ok:
        state = (pre.get("mergeable_state") or "").lower()
        mergeable = pre.get("mergeable")
        if state == "unknown" or mergeable is None:
            import time as _time

            _time.sleep(2)
            pre_ok2, pre2 = _api_get(f"/repos/{_repo}/pulls/{pr_number}")
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
    allowed, rl = check_before_write(token=_get_token())
    if not allowed:
        logger.warning("merge PR #%s blocked by rate guard: %s", pr_number, rl.get("reason"))
        return {
            "success": False,
            "merged": False,
            "error": f"github rate limit guard: {rl.get('reason')}",
            "rate_limited": True,
            "rate_limit": rl,
        }
    try:
        resp = requests.put(
            f"{API_BASE}/repos/{_repo}/pulls/{pr_number}/merge",
            headers=_api_headers(),
            json={"merge_method": method},
            timeout=30,
        )
        observe(resp, is_write=True)
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
        pr_ok, pr_data = _api_get(f"/repos/{_repo}/pulls/{pr_number}")
        if pr_ok:
            branch = pr_data.get("head", {}).get("ref")
            if branch and branch != "main":
                try:
                    requests.delete(
                        f"{API_BASE}/repos/{_repo}/git/refs/heads/{branch}",
                        headers=_api_headers(),
                        timeout=10,
                    )
                except Exception:
                    pass

    # The PR is merged, so any pending merge APPROVAL for it is now moot (#5862).
    # Closed at the choke point rather than per-caller: merge_pr has several call sites
    # and human_override merges bypass every one of the automated ones, which is exactly
    # how 4 of 4 pending approvals ended up pointing at already-merged PRs. Bookkeeping
    # only — it must never turn a SUCCESSFUL merge into a failure, hence the broad catch.
    try:
        from tools.department_hq.services.approvals_reconcile import (
            close_pr_merge_approvals_for,
        )

        close_pr_merge_approvals_for(pr_number, _repo)
    except Exception as _appr_exc:  # noqa: BLE001
        logger.warning("post-merge approval cleanup skipped for #%s: %s", pr_number, _appr_exc)

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
            # The BASE ref, flattened like head_ref beside it. Its absence here is why
            # `pr_reviews.base_branch` was NULL on 1,878 of 2,518 rows: poll_open_prs
            # reads `pr["base"]["ref"]`, and this payload has never carried a `base`
            # key at all — so the writer read a key the producer does not emit and
            # silently stored None every time (#5866, same shape as the _docker_exec
            # `output`-vs-`stdout` phantom in #2622).
            #
            # It matters because it decides whether a merge SHIPS or folds into a
            # parent branch: on 2026-08-25 a 4-PR stack was "merged" by clicking the
            # TOP one, which landed in its own parent and never moved main.
            "base_ref": (pr.get("base") or {}).get("ref"),
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

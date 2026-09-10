"""Apply a cloud coding result to the repo (#6680, Phase 4b).

Pure helpers (no DB, no network) plus the approval executor at the bottom. The
executor composes the EXISTING github_service primitives — create_branch /
push_changes(content_overrides) / create_pr — so `main` is only ever a base and the
shared /mnt/archie_brain tree is never read or written. Every apply is a Tier-2 human
approval bound to a content hash and the base blob sha the model read.

BLOCKED_GLOBS mirrors archie_engine/scope_guard.py (the hub cannot import the engine);
tests/test_cloud_code_apply.py checks the copy against the engine file when mounted.
"""

from __future__ import annotations

import fnmatch
import hashlib
import logging
import posixpath
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

ACTION_TYPE = "cloud_code_apply"  # Tier-2 approval type (Ship category, prefix cloud_code_)
BRANCH_PREFIX = "cockpit/apply-"
PR_LABEL = "cockpit-apply"
MAX_PATH_LEN = 240
MAX_FILE_BYTES = 200 * 1024

# scope_guard.PLATFORM_SCOPE.allowed_paths + archie-comms/ (where the cockpit lives).
# database/migrations/ stays revoked, as the owner ruled for the engine.
ALLOWED_PREFIXES = ("platform_v2/", "ai_bridge/", "scripts/", "docs/", "archie-comms/")

ENGINE_BLOCKED_GLOBS = (
    "*.env",
    ".env*",
    "*.key",
    "*.pem",
    "*.pfx",
    "secrets/*",
    "docker-compose*",
    "Dockerfile*",
    "scripts/dr/*",
    ".git/*",
    ".github/*",
    "*agent_service.py",
    "*department_dispatcher.py",
    "*repair_bay/services/github_service.py",
    "*repair_bay/services/pr_review_service.py",
    "scripts/check_agent_single_writer.py",
    "scripts/agents/*",
    "scripts/backup/*",
)
# The lane must never be able to rewrite its own gate.
BLOCKED_GLOBS = ENGINE_BLOCKED_GLOBS + ("*internal_auth.py", "*cloud_code_apply.py", "*cloud_code_lane.py")
_BLOCKED_SEGMENTS = {".git", "secrets", ".ssh", ".gnupg", ".aws"}

# A target path is interpolated into a GitHub contents URL, so anything that can change
# the MEANING of that URL is refused here rather than escaped later. `?` and `#` would
# smuggle a query or fragment in — `docs/a.md?ref=dev` yields `...?ref=dev&ref=main`, so
# base_sha could bind to a blob on a different ref than the model was shown — and `%`
# would slip a pre-encoded byte past get_file_at_ref's quoting. The set is deliberately
# narrower than "valid on ext4": it covers every real path in this repo and nothing else.
# get_file_at_ref quotes independently, so neither layer is load-bearing on its own.
_UNSAFE_PATH_CHAR = re.compile(r"[^A-Za-z0-9._/+-]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_target(path) -> str:
    """Return the normalised repo-relative path, or raise ValueError with a user-facing reason."""
    if not isinstance(path, str) or not path.strip():
        raise ValueError("target_path required")
    p = path.strip()
    if "\x00" in p:
        raise ValueError("target_path contains NUL")
    if len(p) > MAX_PATH_LEN:
        raise ValueError(f"target_path is longer than {MAX_PATH_LEN} characters")
    if "\\" in p:
        raise ValueError("target_path must use forward slashes")
    unsafe = _UNSAFE_PATH_CHAR.search(p)
    if unsafe:
        raise ValueError(f"target_path contains an unsupported character ({unsafe.group()!r})")
    if p.startswith("/"):
        raise ValueError("target_path must be repo-relative (no leading /)")
    norm = posixpath.normpath(p)
    segments = norm.split("/")
    if ".." in segments or norm.startswith("../"):
        raise ValueError("target_path escapes the repository")
    if not norm.startswith(ALLOWED_PREFIXES):
        raise ValueError(f"target_path must start with one of: {', '.join(ALLOWED_PREFIXES)}")
    if any(seg.lower() in _BLOCKED_SEGMENTS for seg in segments):
        raise ValueError("target_path is inside a protected directory")
    base = posixpath.basename(norm)
    # Match case-insensitively so the gate cannot be sidestepped by a cloud model
    # spelling a filename in a different case (ext4 and GitHub are both case-sensitive,
    # so e.g. `Agent_Service.py` is a distinct path from the real `agent_service.py` —
    # but it must still be refused). Both the compared text AND the glob pattern are
    # lowered — ENGINE_BLOCKED_GLOBS is mostly lowercase but not entirely (`Dockerfile*`
    # keeps its engine-file spelling for the parity test), so lowering only one side
    # would leave that one blocked-by-mixed-case entry bypassable. The RETURNED path
    # keeps its original casing; only the comparison is lowered.
    norm_lower = norm.lower()
    base_lower = base.lower()
    for g in BLOCKED_GLOBS:
        gl = g.lower()
        if fnmatch.fnmatch(norm_lower, gl) or fnmatch.fnmatch(base_lower, gl):
            raise ValueError(f"target_path is blocked by policy ({g})")
    return norm


_FENCE = re.compile(r"\A\s*```[\w+.\-]*[ \t]*\r?\n(.*?)\r?\n?```\s*\Z", re.S)


def strip_fences(text) -> str:
    """One whole-response fenced block → its body; anything else unchanged. Exactly one trailing newline."""
    text = text or ""
    if not text.strip():
        return ""
    m = _FENCE.match(text)
    body = m.group(1) if m else text
    return body.rstrip() + "\n"


def content_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def build_edit_prompt(target_path: str, prompt: str, current: Optional[str]) -> str:
    head = (
        f"You are editing the file {target_path} in the archie-platform repository. "
        "Return the COMPLETE new contents of that file and nothing else — no prose, no fences."
    )
    if current is None:
        body = f"--- {target_path} does not exist yet ---"
    else:
        body = f"--- current contents of {target_path} ---\n{current}\n--- end of {target_path} ---"
    return f"{head}\n\nTask: {prompt}\n\n{body}"


def branch_name(job_id: int, target_path: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", target_path.lower()).strip("-")[:40].rstrip("-")
    return f"{BRANCH_PREFIX}{job_id}-{slug}"


def _served(meta: dict) -> str:
    return ((meta.get("result") or {}).get("model_used") or meta.get("model") or "?").strip()


def commit_message(job_id: int, target_path: str, meta: dict) -> str:
    return (
        f"feat(cockpit-apply): {target_path} via {meta.get('provider', '?')}:{_served(meta)} (job #{job_id})\n\n"
        f"Applied from the A.R.C.H.I.E. cockpit Code Builder. Prompt: "
        f"{(meta.get('prompt_original') or meta.get('prompt') or '')[:200]}\n\n"
        "Co-Authored-By: A.R.C.H.I.E. Cockpit <cockpit@kytranempowerment.com>"
    )


def pr_title(target_path: str, meta: dict) -> str:
    first = (meta.get("prompt_original") or meta.get("prompt") or "").strip().splitlines()[0:1]
    return f"[cockpit] {target_path}: {(first[0] if first else '')[:60]}".rstrip(": ")


def pr_body(job_id: int, target_path: str, meta: dict, base_sha: Optional[str]) -> str:
    return "\n".join(
        [
            "## Cockpit apply",
            f"- job #{job_id} · provider `{meta.get('provider', '?')}` · requested `{meta.get('model', '?')}` · served `{_served(meta)}`",
            f"- target `{target_path}` · base blob sha `{base_sha or 'new file'}`",
            "",
            "### Prompt",
            (meta.get("prompt_original") or meta.get("prompt") or "")[:2000],
            "",
            "Opened from the cockpit; content came from a cloud model with no test gate — human merge only.",
            "",
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
        ]
    )


def apply_precondition(status: str, meta: dict) -> Optional[str]:
    """None when the job can be applied, else the user-facing reason (a 409)."""
    meta = meta or {}
    if status != "completed":
        return f"job is {status}, not completed"
    if not ((meta.get("result") or {}).get("response") or "").strip():
        return "job has no answer to apply"
    if not meta.get("target_path"):
        return "job was run without a target file — re-run it with one"
    if meta.get("pr_number"):
        return f"already applied as PR #{meta['pr_number']}"
    return None


# ---- approval request (the only subsystem touchpoint besides the executor) ---------------
def request_tier2_approval(*, job_id: int, meta: dict, content: str, requested_by: str) -> Optional[int]:
    """Ask-first. None when request_approval() could not enqueue (one pending apply at a time)."""
    from ai_bridge.agent_loop import request_approval

    target = meta.get("target_path")
    return request_approval(
        action_type=ACTION_TYPE,
        action_data={
            "job_id": job_id,
            "target_path": target,
            "base_sha": meta.get("base_sha"),
            "content_sha256": content_sha256(content),
            "provider": meta.get("provider"),
            "model": meta.get("model"),
            "requested_by": requested_by,
        },
        reason=f"Apply cloud coding result to {target} (job #{job_id})",
        requested_by="cloud_code_lane",
        tier=2,
    )


# ---- executor (runs in the approval-queue drain, after the owner said yes) ------------
def _load_job(job_id: int) -> Optional[dict]:
    from database import get_db_cursor

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT id, status, metadata FROM bridge_jobs WHERE id=%s", (int(job_id),))
        row = cur.fetchone()
    return dict(row) if row else None


def _stamp_job(job_id: int, patch: dict) -> None:
    import json as _json

    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE bridge_jobs SET metadata = COALESCE(metadata,'{}'::jsonb) || %s::jsonb, updated_at=NOW() WHERE id=%s",
            (_json.dumps(patch), int(job_id)),
        )


def execute(action_data: dict, *, gh=None, load_job=None, stamp_job=None) -> dict:
    """Approval executor for ACTION_TYPE.

    sha check → branch → ONE commit (content_overrides, literal text) → PR. `main` is only a
    base. A branch THIS call created is deleted on any later failure; one that already
    existed is refused and never touched (it belongs to an earlier apply, possibly with an
    open PR).

    Contract — deliberately narrower than "never raises":
      * Every HANDLED failure returns {"executed": False, "error": ...}. Those routed through
        fail() also make a BEST-EFFORT stamp of apply_error, so the cockpit shows the reason
        verbatim — but an unknown job id has no row to stamp, and a stamp that itself raises
        is logged and swallowed rather than costing the caller its refusal. So a returned
        error is authoritative; the absence of apply_error on the job is not.
      * A success stamps pr_number/pr_url/branch/applied_at. If that stamp fails the PR still
        exists, so the result stays executed=True and carries stamp_error.
      * Both stamp_job call sites are guarded, so a DB blip never costs the caller its result.
      * NOT caught: a transport or DB exception out of `load_job` or the `gh` write calls
        (create_branch / push_changes / create_pr / delete_branch) propagates to the caller —
        the agent-loop branch wraps this call in its own try/except. `gh.get_file_at_ref` IS
        handled and becomes a refusal. An exception after create_branch succeeds can strand a
        `cockpit/apply-*` branch; delete it on sight, as with `archie/forge/*`.
    """
    if gh is None:
        from tools.repair_bay.services import github_service as gh  # noqa: N813
    load_job = load_job or _load_job
    stamp_job = stamp_job or _stamp_job
    job_id = int((action_data or {}).get("job_id") or 0)

    def fail(msg: str) -> dict:
        # Mirrors the success-path guard below. A refusal is exactly when the job most
        # needs apply_error recorded, and raising here would lose BOTH the refusal reason
        # and the stamp — so swallow, log, and return the refusal regardless. Kept local
        # rather than pushed down into _stamp_job: production must still surface a real DB
        # failure, which the success path does by returning stamp_error to the caller.
        if job_id:
            try:
                stamp_job(job_id, {"apply_error": msg})
            except Exception as exc:
                logger.error("cloud_code_apply: job #%s refusal could not be stamped (%s): %s", job_id, msg, exc)
        return {"executed": False, "error": msg}

    job = load_job(job_id) if job_id else None
    if not job:
        return {"executed": False, "error": f"job #{job_id} not found"}
    meta = job.get("metadata") or {}
    target = meta.get("target_path") or action_data.get("target_path")
    base_sha = meta.get("base_sha")
    content = strip_fences((meta.get("result") or {}).get("response") or "")
    if not target or not content.strip():
        return fail("job has no target file or no answer")
    if content_sha256(content) != action_data.get("content_sha256"):
        return fail("the job's answer changed since the approval was raised — apply again")
    try:
        current = gh.get_file_at_ref(target, "main")
    except Exception as exc:
        return fail(f"could not read {target} from main: {exc}")
    now_sha = current["sha"] if current else None
    if now_sha != base_sha:
        return fail(
            f"{target} changed on main since the model read it (was {(base_sha or 'new file')[:7]}, "
            f"now {(now_sha or 'new file')[:7]}) — re-run the job to pick up the new base"
        )
    branch = branch_name(job_id, target)
    r = gh.create_branch(branch, base="main")
    if not r.get("success"):
        return fail(f"branch: {r.get('error')}")
    # branch_name() is deterministic per (job, target), so a re-execution lands on the
    # branch the FIRST apply pushed. create_branch answers existed=True there. Reading
    # only `success` would carry on into push_changes, get committed=False (the content
    # is already on the branch), and take the delete arm below — destroying the first
    # apply's branch and closing its open PR. Refuse, and delete nothing.
    #
    # The message names the branch and the recovery rather than concluding the job was
    # applied before: the only EVIDENCE is that a ref by that name exists, which is also
    # true of a branch stranded by an exception after create_branch succeeded, or one a
    # failed delete_branch left behind (its return value is unchecked at both delete
    # sites). Recovery needs a human either way, so say what to check.
    if r.get("existed"):
        return fail(
            f"branch {branch} already exists — nothing was changed; "
            f"if no PR was opened for this job, delete the branch and apply again"
        )
    r = gh.push_changes(branch, [target], commit_message(job_id, target, meta), content_overrides={target: content})
    if not r.get("success") or not r.get("committed"):
        gh.delete_branch(branch)
        return fail(
            "the answer is identical to main — nothing to apply" if r.get("success") else f"push: {r.get('error')}"
        )
    r = gh.create_pr(
        branch, title=pr_title(target, meta), body=pr_body(job_id, target, meta, base_sha), labels=[PR_LABEL]
    )
    # A success carrying no pr_number is treated exactly like a failed PR. github_service
    # does `pr_number = data.get("number")` and returns success without asserting it, so
    # the job would otherwise stamp pr_number=None and report executed=True — an "applied"
    # job with no PR link, while a branch with a commit sits on the remote.
    if not r.get("success") or not r.get("pr_number"):
        gh.delete_branch(branch)
        return fail("pull request: no number returned" if r.get("success") else f"pull request: {r.get('error')}")
    out = {"executed": True, "pr_number": r["pr_number"], "pr_url": r["pr_url"], "branch": branch}
    # The PR exists on the remote by this point, so a DB blip on the stamp must not be
    # reported as a failed apply — that would be the lie. Surface stamp_error instead and
    # keep executed=True. Deliberately narrow: it wraps ONLY this stamp, because the
    # GitHub calls above already handle their own failures. An UNSTAMPED success is what
    # blinds apply_precondition, which is the realistic route into the existed-branch case.
    try:
        stamp_job(
            job_id,
            {
                "pr_number": r["pr_number"],
                "pr_url": r["pr_url"],
                "branch": branch,
                "applied_at": _now_iso(),
                "apply_error": None,
            },
        )
    except Exception as exc:
        logger.error(
            "cloud_code_apply: PR #%s opened but job #%s could not be stamped: %s", r["pr_number"], job_id, exc
        )
        out["stamp_error"] = str(exc)
    return out

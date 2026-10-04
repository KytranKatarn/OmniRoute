"""Queue a CODEX review for a PR from the Repair Bay UI, and report on it.

Why a queue instead of an ssh call from the platform
---------------------------------------------------
The obvious implementation — the endpoint shells out over ssh to run
``scripts/forge_codex_review.sh`` — cannot work here, and both halves were verified
rather than assumed:

* The platform container cannot ssh back to its own host. Every address returns
  ``Permission denied (publickey)``; the mounted key is not in the host's
  authorized_keys for root.
* ``/mnt/archie_brain`` is mounted **read-only** in the container, so the platform
  cannot drop a request file into the repo either.

``/mnt/archie_sandbox`` is the one path writable from both sides. So the endpoint
writes a small JSON request into a spool directory and ``scripts/codex_review_queue.sh``
(on the host, where codex and the git credentials live) picks it up. The web app gains
no code execution and no new credential — it writes a file, like a print spool.

This is also the right shape on the merits: codex is reached by invoking the CLI
directly. Codex lives *outside* Department-HQ by design — jobs.py records that "codex,
opencode and the host codex CLI call the OmniRoute gateway directly over HTTP, so they
never reach the DHQ dispatcher" — and there is no ``codex`` row in
``contractor_providers``, so a DHQ dispatch to the Codex (CLI) contractor would resolve
no provider and fail at execution.

Safety
------
The PR number is the only value that reaches a shell command downstream, and it is
coerced to digits here before anything is written. The queue runner independently
re-validates it and quarantines anything malformed rather than executing it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

QUEUE_DIR = Path(os.getenv("CODEX_REVIEW_QUEUE", "/mnt/archie_sandbox/.codex-review-queue"))
PENDING_DIR = QUEUE_DIR / "pending"
DONE_DIR = QUEUE_DIR / "done"

# How long the UI should keep showing "in flight" before it stops claiming progress.
# The driver runs a full-diff review; REVIEW_TIMEOUT on the host is 900s, so anything
# past that is stale rather than slow.
STALE_AFTER_SECONDS = 1200

_DIGITS = re.compile(r"^[0-9]+$")


def _valid_pr(pr_number: Any) -> Optional[int]:
    """Return a positive int PR number, or None.

    Deliberately strict: this value is interpolated into a JSON request that a shell
    script later parses, and that script only accepts digits. Rejecting here means a
    hostile or malformed value never reaches the spool at all.
    """
    if isinstance(pr_number, bool):  # bool is an int subclass — reject explicitly
        return None
    if isinstance(pr_number, int):
        candidate = str(pr_number)
    elif isinstance(pr_number, str):
        candidate = pr_number.strip()
    else:
        return None
    if not _DIGITS.match(candidate):
        return None
    try:
        value = int(candidate)
    except ValueError:
        return None
    return value if value > 0 else None


def queue_dir_available() -> bool:
    """True when the spool is mounted and writable in THIS process.

    Deliberately does NOT create anything. An earlier version called mkdir() here,
    which made this check self-fulfilling: probing for availability created the
    directory it was probing for, so the "spool not mounted" 503 path could never be
    reached — a missing mount silently looked healthy. Creation belongs in
    enqueue_codex_review(), which is the thing that actually needs the directory.
    """
    try:
        if not PENDING_DIR.is_dir():
            return False
        probe = PENDING_DIR / f".write-probe-{os.getpid()}"
        probe.write_text("{}", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:  # noqa: BLE001 — a probe must never raise into a request
        return False


def _result_path(request_id: str) -> Path:
    return DONE_DIR / f"{request_id}.json"


def pending_request_for(pr: int) -> Optional[str]:
    """id of an un-processed request for this PR, if one is already queued."""
    try:
        for path in sorted(PENDING_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — a half-written file is not ours to judge
                continue
            if data.get("pr") == pr:
                return path.stem
    except Exception:  # noqa: BLE001
        return None
    return None


def enqueue_codex_review(pr_number: Any, repo: Optional[str] = None, dry_run: bool = False) -> Dict[str, Any]:
    """Drop a review request in the spool. Returns a result dict; never raises."""
    pr = _valid_pr(pr_number)
    if pr is None:
        return {"success": False, "error": f"invalid PR number: {pr_number!r}"}

    existing = pending_request_for(pr)
    if existing:
        return {
            "success": False,
            "error": f"PR #{pr} already has a review queued (request {existing}). "
            f"Wait for it to finish rather than queueing a second.",
            "request_id": existing,
        }

    # Create the spool only now — after the cheap checks — so a missing mount costs
    # nothing and reports the deployment problem instead of half-working.
    try:
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as exc:  # noqa: BLE001
        return {
            "success": False,
            "error": f"codex review queue not available at {QUEUE_DIR}: {exc}",
        }
    if not queue_dir_available():
        return {
            "success": False,
            "error": f"codex review queue not available at {QUEUE_DIR} "
            f"(is /mnt/archie_sandbox mounted into the platform container?)",
        }

    request_id = f"{int(time.time())}-{pr}"
    request = {
        "kind": "codex_review",
        "pr": pr,
        "repo": repo or None,
        "dry_run": bool(dry_run),
        "requested_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so the runner can never pick up a half-written file.
        tmp = PENDING_DIR / f".{request_id}.tmp"
        tmp.write_text(json.dumps(request, indent=2), encoding="utf-8")
        tmp.rename(PENDING_DIR / f"{request_id}.json")
    except Exception as exc:  # noqa: BLE001
        logger.error("[CodexReview] failed to enqueue PR #%s: %s", pr, exc)
        return {"success": False, "error": f"could not write queue request: {exc}"}

    logger.info("[CodexReview] queued PR #%s as %s (dry_run=%s)", pr, request_id, dry_run)
    return {
        "success": True,
        "request_id": request_id,
        "pr": pr,
        "dry_run": bool(dry_run),
        "message": (f"CODEX review queued for PR #{pr}" + (" (dry run — nothing will be posted)" if dry_run else "")),
    }


def codex_review_status(pr_number: Any) -> Dict[str, Any]:
    """Report the newest known outcome for this PR's request."""
    pr = _valid_pr(pr_number)
    if pr is None:
        return {"status": "invalid", "error": f"invalid PR number: {pr_number!r}"}

    pending = pending_request_for(pr)
    newest: Optional[Dict[str, Any]] = None
    newest_id: Optional[str] = None
    try:
        for path in sorted(DONE_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if data.get("pr") != pr:
                continue
            # Sorted by filename (timestamp-prefixed), so the last match is the newest.
            newest, newest_id = data, path.stem
    except Exception:  # noqa: BLE001
        pass

    if pending:
        return {"status": "pending", "request_id": pending, "pr": pr}
    if newest is None:
        return {"status": "none", "pr": pr, "message": "no CODEX review requested for this PR yet"}
    out = dict(newest)
    out["request_id"] = newest_id
    if newest.get("status") == "ok" and newest.get("log"):
        try:
            age = time.time() - os.path.getmtime(newest["log"])
            if age > STALE_AFTER_SECONDS:
                out["stale"] = True
        except OSError:
            pass
    return out


def read_review_log(pr_number: Any, max_chars: int = 8000) -> Optional[str]:
    """Tail of the reviewer's output, for the UI. Truncated — never unbounded."""
    pr = _valid_pr(pr_number)
    if pr is None:
        return None
    newest_log: Optional[str] = None
    try:
        for path in sorted(DONE_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if data.get("pr") == pr and data.get("log"):
                newest_log = data["log"]
    except Exception:  # noqa: BLE001
        return None
    if not newest_log:
        return None
    try:
        text = Path(newest_log).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text[-max_chars:]

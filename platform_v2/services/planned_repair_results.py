"""Bounded, server-side reconciliation of planned coder results.

Polls trusted task writeback; no browser-supplied PR or artifact is accepted.
Only reviewed, in-scope results enter the existing merge/completion lane.
"""

import hashlib
import logging
import re

from psycopg2.extras import Json

from database import get_db_cursor
from services.repair_submission import metadata

logger = logging.getLogger(__name__)
REPO = "KytranKatarn/archie-platform"
MAX_FILES = 25


def _review_ok(review, head):
    from tools.repair_bay.services.pr_review_service import verdict_is_approved
    from tools.repair_bay.services.github_service import verdict_refusal

    stamps = metadata((review or {}).get("metadata"))
    return bool(
        review
        and review.get("review_status") == "reviewed"
        and stamps.get("head_sha") == head
        and stamps.get("reviewed_head_sha") == head
        and verdict_is_approved(review.get("ai_summary") or "")
        and not verdict_refusal(review.get("ai_summary") or "", True)
    )


def build_manifest(proposal, task, review, github):
    """Return immutable reviewed-head evidence or refuse incomplete/foreign results."""
    from services.planned_repair_service import classify

    meta = metadata(proposal.get("metadata"))
    args = metadata(task.get("delegation_args"))
    task_meta = metadata(task.get("metadata"))
    if args.get("capability") != "codex_task" or metadata(args.get("args")).get("repair_proposal_id") != proposal["id"]:
        raise ValueError("Coding task does not belong to this repair")
    branch = task_meta.get("codex_branch") or ""
    pr_number = task_meta.get("codex_pr")
    if not re.fullmatch(r"codex/[a-z0-9-]+", branch) or type(pr_number) is not int or pr_number <= 0:
        raise ValueError("Coding task PR identity is unavailable")
    ok, pr = github._api_get(f"/repos/{REPO}/pulls/{pr_number}")
    if not ok or not isinstance(pr, dict):
        raise ValueError("GitHub PR identity is unavailable")
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    if (
        (head.get("repo") or {}).get("full_name") != REPO
        or (base.get("repo") or {}).get("full_name") != REPO
        or head.get("ref") != branch
        or base.get("ref") != "main"
        or pr.get("number") != pr_number
    ):
        raise ValueError("Coding result repository or branch does not match")
    if pr.get("state") != "open" and not pr.get("merged"):
        raise ValueError("Coding PR was closed without merging")
    sha = head.get("sha") or ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha) or not _review_ok(review, sha):
        raise ValueError("Current PR head needs an approved F.O.R.G.E. review")
    count = pr.get("changed_files")
    if type(count) is not int or not 0 < count <= MAX_FILES:
        raise ValueError("PR exceeds bounded manifest coverage")
    ok, files = github._api_get(f"/repos/{REPO}/pulls/{pr_number}/files", params={"per_page": 100, "page": 1})
    if not ok or not isinstance(files, list) or len(files) != count:
        raise ValueError("Complete PR file inventory is unavailable")
    entries = []
    paths = set()
    for item in files:
        path, status = item.get("filename"), item.get("status")
        if not isinstance(path, str) or path in paths or status not in {"added", "modified", "removed", "renamed"}:
            raise ValueError("Unsupported or duplicate PR artifact")
        paths.add(path)
        # Reuse current scope AND target-based governance on every changed path,
        # including a rename's old location. No extracted-file policy escape.
        checked = [path] + ([item.get("previous_filename")] if status == "renamed" else [])
        for target in checked:
            if not isinstance(target, str):
                raise ValueError("Rename source is unavailable")
            # Added files do not exist locally yet. Scope checks must not depend
            # on source availability; use the same explicit policy helper.
            from services.planned_repair_policy import validate_artifact_path

            validate_artifact_path(target)
        entry = {"path": path, "status": status}
        if status == "renamed":
            entry["previous_path"] = item["previous_filename"]
        if status != "removed":
            blob = github.get_file_at_ref(path, ref=sha)
            if not blob or blob.get("sha") != item.get("sha"):
                raise ValueError("Reviewed artifact is unavailable or changed")
            raw = blob["content"].encode("utf-8")
            if len(raw) != blob.get("size"):
                raise ValueError("Reviewed artifact content is incomplete")
            blob_sha = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
            if blob_sha != blob.get("sha"):
                raise ValueError("Reviewed artifact blob fingerprint does not match")
            entry["sha256"] = hashlib.sha256(raw).hexdigest()
        entries.append(entry)
    route = classify(proposal)
    if not route.get("eligible") or route["file_path"] not in paths:
        raise ValueError("PR does not repair the approved target")
    # Re-read after collecting blobs so a concurrent push cannot stamp stale work.
    ok, latest = github._api_get(f"/repos/{REPO}/pulls/{pr_number}")
    if not ok or (latest.get("head") or {}).get("sha") != sha:
        raise ValueError("PR head changed while collecting artifacts")
    return {"version": 1, "repo": REPO, "pr_number": pr_number, "head_sha": sha, "branch": branch, "files": entries}


def reconcile_planned_results(limit=3):
    """Track existing tasks even when admission is paused. Never merge/deploy/close."""
    from tools.repair_bay.services import github_service as github
    from services.time_utils import now_utc

    with get_db_cursor(commit=False) as (_, cur):
        cur.execute(
            """SELECT * FROM improvement_proposals
               WHERE status='approved' AND metadata->>'source'='code_health_audit'
                 AND metadata->'planned_repair'->>'task_id' IS NOT NULL
               ORDER BY COALESCE(metadata->'planned_repair'->>'checked_at',''),id LIMIT %s""",
            (max(1, min(int(limit), 10)),),
        )
        proposals = [dict(row) for row in cur.fetchall()]
    linked = blocked = 0
    for proposal in proposals:
        link = metadata(proposal["metadata"]).get("planned_repair") or {}
        task_id = link["task_id"]
        try:
            with get_db_cursor(commit=False) as (_, cur):
                cur.execute("SELECT * FROM unified_tasks WHERE id=%s", (task_id,))
                task = cur.fetchone()
                pr_number = metadata((task or {}).get("metadata")).get("codex_pr")
                cur.execute("SELECT * FROM pr_reviews WHERE repo=%s AND pr_number=%s", (REPO, pr_number))
                review = cur.fetchone()
            if not task:
                raise ValueError("Linked coding task is unavailable")
            if not pr_number:
                manifest = None
                error = (
                    None
                    if task.get("status") in {"deferred", "pending", "in_progress"}
                    else "Coding task needs operator review"
                )
            else:
                manifest = build_manifest(proposal, task, review, github)
                error = None
        except Exception as exc:
            manifest, error = None, str(exc)[:300]
            blocked += 1
        # Compare task identity and status under lock. A stale snapshot cannot
        # replace another attempt, a newly submitted patch or an existing PR.
        with get_db_cursor(commit=True) as (_, cur):
            cur.execute("SELECT status,metadata FROM improvement_proposals WHERE id=%s FOR UPDATE", (proposal["id"],))
            row = cur.fetchone()
            current = metadata((row or {}).get("metadata"))
            current_link = current.get("planned_repair") or {}
            if not row or row["status"] != "approved" or current_link.get("task_id") != task_id:
                continue
            if current.get("pr_number") or current.get("repair_submission"):
                continue
            before = metadata(proposal["metadata"])
            if any(current.get(key) != before.get(key) for key in ("source", "file_path", "issue_code", "module_name")):
                continue
            stamp = dict(current_link, checked_at=now_utc().isoformat(), result_error=error)
            updates = {"planned_repair": stamp}
            status = "approved"
            if manifest:
                cur.execute("SELECT * FROM unified_tasks WHERE id=%s FOR SHARE", (task_id,))
                current_task = cur.fetchone()
                cur.execute(
                    "SELECT * FROM pr_reviews WHERE repo=%s AND pr_number=%s FOR SHARE", (REPO, manifest["pr_number"])
                )
                current_review = cur.fetchone()
                if (
                    not current_task
                    or metadata(current_task.get("metadata")) != metadata(task.get("metadata"))
                    or current_task.get("delegation_args") != task.get("delegation_args")
                    or not _review_ok(current_review, manifest["head_sha"])
                ):
                    continue
                status = "pr_open"
                updates.update(
                    pr_number=manifest["pr_number"],
                    pr_url=f"https://github.com/{REPO}/pull/{manifest['pr_number']}",
                    branch=manifest["branch"],
                    apply_mode="planned_codex_pr",
                    code_applied=False,
                    repair_artifacts=manifest,
                    repair_submission={"stage": "pr_open"},
                )
                linked += 1
            cur.execute(
                "UPDATE improvement_proposals SET status=%s,metadata=COALESCE(metadata,'{}'::jsonb) || %s WHERE id=%s",
                (status, Json(updates), proposal["id"]),
            )
    return {"checked": len(proposals), "linked": linked, "blocked": blocked}

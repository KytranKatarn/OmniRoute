"""Bounded planned-PR refresh and serving-process verification retries."""

import os
import re
from urllib.parse import urlsplit

import requests
from psycopg2.extras import Json

from database import get_db_cursor
from services.planned_repair_results import REPO, _review_ok, build_manifest
from services.repair_submission import metadata


def request_serving_verification(proposal_id):
    """Never verify imports in the scheduler. Call the scoped web authority."""
    base = os.environ.get("PLATFORM_INTERNAL_URL") or os.environ.get("BRIDGE_URL")
    key = os.environ.get("INTERNAL_API_KEY")
    if not base or not key:
        raise ValueError("Internal serving verification is not configured")
    if "://" not in base:
        base = "http://" + base
    url = urlsplit(base)
    if (
        url.scheme not in {"http", "https"}
        or not re.fullmatch(r"100\.64\.0\.[0-9]{1,3}", url.hostname or "")
        or int(url.hostname.rsplit(".", 1)[1]) > 255
        or url.username
        or url.password
        or url.path not in {"", "/"}
        or url.query
        or url.fragment
    ):
        raise ValueError("Internal verification requires a configured mesh endpoint")
    try:
        response = requests.post(
            base.rstrip("/") + f"/api/internal/repair/proposals/{int(proposal_id)}/verify",
            headers={"Authorization": f"Bearer {key}"},
            timeout=15,
            allow_redirects=False,
        )
        if response.status_code != 200:
            raise ValueError("Serving verification refused or unavailable")
        result = response.json()
        if not isinstance(result, dict) or type(result.get("success")) is not bool:
            raise ValueError("Serving verification response is invalid")
        return result
    except requests.RequestException as exc:
        raise ValueError("Serving verification is unavailable") from exc


def reconcile_planned_completion(limit=3):
    """Refresh trusted manifests, preserve human merge, retry failed verification."""
    from services.time_utils import now_utc
    from tools.repair_bay.services import github_service as github

    with get_db_cursor(commit=False) as (_, cur):
        cur.execute(
            """SELECT * FROM improvement_proposals WHERE status='pr_open'
               AND metadata->>'apply_mode'='planned_codex_pr'
               AND metadata->>'source'='code_health_audit'
               ORDER BY COALESCE(metadata->'planned_repair'->>'completion_checked_at',''),id LIMIT %s""",
            (max(1, min(int(limit), 10)),),
        )
        rows = [dict(row) for row in cur.fetchall()]
    verified = blocked = 0
    for row in rows:
        original = metadata(row["metadata"])
        task_id = (original.get("planned_repair") or {}).get("task_id")
        number = original.get("pr_number")
        manifest = proof = None
        error = None
        try:
            with get_db_cursor(commit=False) as (_, cur):
                cur.execute("SELECT * FROM unified_tasks WHERE id=%s", (task_id,))
                task = cur.fetchone()
                cur.execute("SELECT * FROM pr_reviews WHERE repo=%s AND pr_number=%s", (REPO, number))
                review = cur.fetchone()
            if not task or metadata(task.get("metadata")).get("codex_pr") != number:
                raise ValueError("Linked task PR changed; operator review is required")
            # Revalidate eligibility without pretending the stored proposal reverted.
            candidate = dict(row, status="approved", metadata=dict(original))
            candidate["metadata"].pop("pr_number", None)
            candidate["metadata"].pop("repair_submission", None)
            manifest = build_manifest(candidate, task, review, github)
            ok, pr = github._api_get(f"/repos/{REPO}/pulls/{number}")
            if not ok or (pr.get("head") or {}).get("sha") != manifest["head_sha"]:
                raise ValueError("PR head changed during completion tracking")
            if pr.get("merged"):
                sha = pr.get("merge_commit_sha") or ""
                if not re.fullmatch(r"[0-9a-f]{40}", sha) or not pr.get("merged_at"):
                    raise ValueError("GitHub merge evidence is incomplete")
                proof = {key: manifest[key] for key in ("repo", "pr_number", "head_sha")}
                proof.update(merge_sha=sha, merged_at=pr["merged_at"])
        except Exception as exc:
            error = str(exc)[:300]
        with get_db_cursor(commit=True) as (_, cur):
            cur.execute("SELECT status,metadata FROM improvement_proposals WHERE id=%s FOR UPDATE", (row["id"],))
            current_row = cur.fetchone()
            current = metadata((current_row or {}).get("metadata"))
            if not current_row or current_row["status"] != "pr_open" or current != original:
                continue
            link = dict(
                current.get("planned_repair") or {}, completion_checked_at=now_utc().isoformat(), result_error=error
            )
            updates = {"planned_repair": link}
            if manifest and not error:
                cur.execute("SELECT * FROM unified_tasks WHERE id=%s FOR SHARE", (task_id,))
                latest_task = cur.fetchone()
                cur.execute("SELECT * FROM pr_reviews WHERE repo=%s AND pr_number=%s FOR SHARE", (REPO, number))
                latest_review = cur.fetchone()
                if (
                    not latest_task
                    or latest_task.get("metadata") != task.get("metadata")
                    or latest_task.get("delegation_args") != task.get("delegation_args")
                    or not _review_ok(latest_review, manifest["head_sha"])
                ):
                    continue
                updates["repair_artifacts"] = manifest
                if proof:
                    updates.update(
                        planned_merge=proof, merged_pr=number, merged_at=proof["merged_at"], code_applied=False
                    )
                    updates["repair_submission"] = dict(
                        current.get("repair_submission") or {}, stage="merged_awaiting_verification"
                    )
            cur.execute(
                "UPDATE improvement_proposals SET metadata=COALESCE(metadata,'{}'::jsonb) || %s WHERE id=%s",
                (Json(updates), row["id"]),
            )
        if proof and not error:
            try:
                result = request_serving_verification(row["id"])
                if result.get("success"):
                    verified += 1
                else:
                    error = str(result.get("error") or "Completion remains unverified")[:300]
            except Exception as exc:
                error = str(exc)[:300]
            if error:
                with get_db_cursor(commit=True) as (_, cur):
                    # CAS avoids overwriting another attempt, refresh or successful receipt.
                    cur.execute(
                        """UPDATE improvement_proposals SET metadata=jsonb_set(metadata,
                           '{planned_repair,result_error}',%s::jsonb)
                           WHERE id=%s AND status='pr_open' AND metadata->'planned_merge'=%s::jsonb
                           AND metadata->'planned_repair'->>'completion_checked_at'=%s""",
                        (Json(error), row["id"], Json(proof), link["completion_checked_at"]),
                    )
        if error:
            blocked += 1
    return {"checked": len(rows), "verified": verified, "blocked": blocked}

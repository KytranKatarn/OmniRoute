"""Shared attribution and active counts for Code Health repair proposals."""

import logging

from database import get_db_cursor

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("archived", "implemented", "rejected", "deployed", "failed", "superseded")

# These regex checks report one condition per file. Static/lint findings may
# identify different symbols in the same file and must never be collapsed here.
_FILE_FINDINGS = {"LARGE_FILE", "SQL_INJECTION_RISK", "DIRECT_OLLAMA", "DIRECT_CLOUD"}


def reconcile_duplicate_proposals(module_name, dry_run=True):
    """Retire unworked alias twins, retaining fixes and an active survivor.

    Scope by path ownership, preserve the original paths, and never treat a
    duplicate as a completed repair. Run inside one transaction with row locks.
    """
    stats = {"duplicates": 0, "archived": 0, "cards_cancelled": 0, "dry_run": dry_run}
    escaped = module_name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with get_db_cursor(commit=not dry_run) as (_, cur):
        cur.execute(
            """SELECT id, status, code_changes, module_name,
                      metadata->>'file_path' AS file_path,
                      metadata->>'issue_code' AS issue_code,
                      metadata->>'scan_tier' AS scan_tier,
                      metadata->>'module_name' AS metadata_module
               FROM improvement_proposals
               WHERE status NOT IN %s
                 AND metadata->>'source' = 'code_health_audit'
                 AND (metadata->>'file_path' LIKE %s OR metadata->>'file_path' LIKE %s)
               ORDER BY id FOR UPDATE""",
            (TERMINAL_STATUSES, f"platform_v2/tools/{escaped}/%", f"[APP_CORE]/tools/{escaped}/%"),
        )
        groups = {}
        for row in cur.fetchall():
            path = row["file_path"] or ""
            if module_from_file_path(path) != module_name:
                continue
            if row["issue_code"] not in _FILE_FINDINGS or row["scan_tier"] not in (None, "regex"):
                continue
            normalized = path.replace("[APP_CORE]/", "platform_v2/", 1)
            groups.setdefault((normalized, row["issue_code"]), []).append(row)
        for rows in groups.values():
            if len(rows) < 2:
                continue
            # Keep the most progressed record; tie-break by oldest ID. Records
            # with generated patches are always preserved, even if duplicated.
            keeper = min(
                rows, key=lambda r: (not bool(r["code_changes"]), r["status"] in ("pending", "approved"), r["id"])
            )
            duplicates = [
                r["id"]
                for r in rows
                if r["id"] != keeper["id"] and r["status"] in ("pending", "approved") and not r["code_changes"]
            ]
            stats["duplicates"] += len(duplicates)
            if dry_run or not duplicates:
                continue
            cur.execute(
                """UPDATE improvement_proposals
                   SET status = 'archived', metadata = COALESCE(metadata, '{}'::jsonb) ||
                       jsonb_build_object('superseded_by', %s, 'archive_reason',
                                          'duplicate:file_finding', 'archived_at', NOW()::text)
                   WHERE id = ANY(%s) AND status IN ('pending', 'approved')
                     AND COALESCE(code_changes, '') = ''
                   RETURNING id""",
                (keeper["id"], duplicates),
            )
            retired = [r["id"] for r in cur.fetchall()]
            stats["archived"] += len(retired)
            if retired:
                cur.execute(
                    """UPDATE autonomy_approval_queue SET status = 'cancelled',
                           rejected_reason = 'duplicate proposal superseded', updated_at = NOW()
                       WHERE status = 'pending'
                         AND action_type IN ('deploy_approve', 'improvement_approve_red', 'improvement_approve')
                         AND action_data->>'proposal_id' = ANY(%s)""",
                    ([str(pid) for pid in retired],),
                )
                stats["cards_cancelled"] += cur.rowcount
    return stats


def module_from_file_path(fp):
    if not fp:
        return None
    for marker in ("platform_v2/tools/", "[APP_CORE]/tools/"):
        if marker in fp:
            return fp.split(marker, 1)[1].split("/", 1)[0]
    for prefixes, module in (
        (("platform_v2/", "[APP_CORE]/"), "[APP_CORE]"),
        (("ai_bridge/", "[AI_BRIDGE]/"), "[AI_BRIDGE]"),
        (("database/migrations/", "[MIGRATIONS]/"), "[MIGRATIONS]"),
    ):
        if fp.startswith(prefixes):
            return module
    return fp.split("/", 1)[0]


def open_proposal_counts(code_health_only=True):
    """Count active records, accepting scalar, metadata, and legacy path identity."""
    source_filter = "AND metadata->>'source' = 'code_health_audit'" if code_health_only else ""
    with get_db_cursor(commit=False) as (_, cur):
        cur.execute(
            f"""SELECT module_name, metadata->>'module_name' AS metadata_module,
                       metadata->>'file_path' AS file_path, COUNT(*) AS cnt
                FROM improvement_proposals
                WHERE status NOT IN %s {source_filter}
                GROUP BY module_name, metadata->>'module_name', metadata->>'file_path'""",
            (TERMINAL_STATUSES,),
        )
        rows = cur.fetchall()
    counts = {}
    for row in rows:
        # The path owns attribution: older scans label Faith's aliased path
        # [APP_CORE]/tools/faith/routes.py as metadata module [APP_CORE].
        module = module_from_file_path(row["file_path"]) or row["module_name"] or row["metadata_module"]
        if module:
            counts[module] = counts.get(module, 0) + row["cnt"]
    return counts


def reconcile_module_attribution(dry_run=True):
    """Fix module attribution drift on active proposals.

    When a proposal's file_path clearly identifies a module (e.g.
    ``[APP_CORE]/tools/email_manager/hq_routes.py``) but module_name is NULL
    or metadata->>'module_name' is a placeholder like ``[APP_CORE]``, the
    open_proposal_counts function can still attribute it correctly via
    module_from_file_path. However, the Consciousness > Code Health tab and
    the Department Orchestration panel read module_name directly, so drift
    there shows as incorrect per-module counts.

    This corrects module_name (and metadata.module_name) to the module
    derived from file_path, for active proposals only. Idempotent: a second
    run finds 0 to fix.
    """
    stats = {"examined": 0, "fixed": 0, "dry_run": dry_run, "samples": []}
    with get_db_cursor(commit=False) as (_, cur):
        cur.execute(
            """SELECT id, module_name, metadata->>'module_name' AS metadata_module,
                      metadata->>'file_path' AS file_path
               FROM improvement_proposals
               WHERE status NOT IN %s
                 AND metadata->>'file_path' IS NOT NULL
                 AND (module_name IS NULL OR module_name = ''
                      OR module_name IN ('[APP_CORE]', '[AI_BRIDGE]', '[MIGRATIONS]')
                      OR metadata->>'module_name' IN ('[APP_CORE]', '[AI_BRIDGE]', '[MIGRATIONS]'))
               ORDER BY id""",
            (TERMINAL_STATUSES,),
        )
        rows = cur.fetchall()

    updates = []
    for row in rows:
        stats["examined"] += 1
        derived = module_from_file_path(row["file_path"])
        if not derived or derived in ("[APP_CORE]", "[AI_BRIDGE]", "[MIGRATIONS]"):
            continue  # path doesn't yield a useful module — leave alone
        needs_scalar = not row["module_name"] or row["module_name"] in ("[APP_CORE]", "[AI_BRIDGE]", "[MIGRATIONS]")
        needs_meta = (row["metadata_module"] or "") in ("[APP_CORE]", "[AI_BRIDGE]", "[MIGRATIONS]", "")
        if needs_scalar or needs_meta:
            updates.append({"id": row["id"], "module": derived})
            if len(stats["samples"]) < 5:
                stats["samples"].append(
                    {
                        "id": row["id"],
                        "file_path": row["file_path"],
                        "old_module": row["module_name"] or row["metadata_module"],
                        "new_module": derived,
                    }
                )

    if updates and not dry_run:
        with get_db_cursor(commit=True) as (_, cur):
            for upd in updates:
                cur.execute(
                    """UPDATE improvement_proposals
                       SET module_name = %s,
                           metadata = COALESCE(metadata, '{}'::jsonb) ||
                               jsonb_build_object('module_name', %s)
                       WHERE id = %s""",
                    (upd["module"], upd["module"], upd["id"]),
                )
            stats["fixed"] = len(updates)
        logger.info("[attribution-reconciler] fixed module attribution on %d proposal(s)", stats["fixed"])
    else:
        stats["fixed"] = len(updates)  # dry-run: report what WOULD be fixed
    return stats

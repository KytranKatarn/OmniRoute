"""Shared attribution and active counts for Code Health repair proposals."""

from database import get_db_cursor

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

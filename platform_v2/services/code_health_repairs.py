"""Shared attribution and active counts for Code Health repair proposals."""

from database import get_db_cursor

TERMINAL_STATUSES = ("archived", "implemented", "rejected", "deployed", "failed", "superseded")


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

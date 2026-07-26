"""Living Platform Registry — collector (task #5230, Phase 1).

WHAT THIS REPLACES
`.claude/rules/module-capability-index.md` is 314 hand-typed lines that every new
session reads FIRST and then acts on. Hand-maintained documentation does not just
go stale — it asserts false things that agents believe *because they are written
down*: two phantom tables that left backups unmonitored while appearing monitored,
three modules listed as Codex-writable that never were, `auth_events` documented
as existing when it does not.

So: collect from the live source (`module_registry.MODULES`, a list of
`ModuleDefinition` dataclasses) instead of from prose.

TWO RULES THAT SHAPE EVERYTHING HERE
--------------------------------------
1. **`notes` is human-owned and the collector must never write it.** The valuable
   half of the old index is the hand-written rationale ("SABnzbd `set_config` is
   unreliable — edit sabnzbd.ini directly"). That cannot be derived. If a regen
   wiped it, everyone would go straight back to hand-editing the markdown and the
   whole exercise would be worse than useless.

2. **Nothing is ever deleted.** A module that disappears gets `status='absent'`
   with `last_seen_at` frozen. A disappearance is the single most interesting
   event this table can record — deleting the row erases exactly the evidence.
   Same rule as the backup-freshness and gov-watch ingest monitors: absence is a
   finding, not a cleanup.

WHY IT READS THE MODULE OBJECTS AND NOT THE FILE TEXT
Parsing `module_registry.py` as text would be a second implementation of Python
that drifts from the real one. Importing it means the registry is whatever the
app actually loads — if the import breaks, collection fails loudly rather than
reporting a confident wrong answer.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from database import get_db_cursor
from services.time_utils import now_utc

logger = logging.getLogger(__name__)

# Columns the collector owns. `notes` is deliberately ABSENT — see rule 1.
_COLLECTED = (
    "name",
    "description",
    "category",
    "route",
    "blueprint_import",
    "external_url",
    "required_permissions",
    "minimum_role",
    "minimum_tier",
    "enabled",
    "beta",
    "coming_soon",
    "version",
    "tags",
    "show_on_dashboard",
)


def collect_modules() -> list[dict[str, Any]]:
    """Read the LIVE module registry. Raises if it cannot be imported.

    Deliberately not fail-soft: a collector that returns [] on ImportError would
    mark every module 'absent' and render an empty index — a confident wrong
    answer, which is the exact failure mode this task exists to remove.
    """
    import module_registry as mr

    out: list[dict[str, Any]] = []
    for m in mr.MODULES:
        category = m.category.value if hasattr(m.category, "value") else str(m.category)
        out.append(
            {
                "module_id": m.id,
                "name": m.name,
                # The registry stores descriptions with <br> for the dashboard.
                "description": (m.description or "").replace("<br>", " · ").strip(),
                "category": category,
                "route": m.route or None,
                "blueprint_import": m.blueprint_import or None,
                "external_url": m.external_url or None,
                "required_permissions": list(m.required_permissions or []),
                "minimum_role": m.minimum_role,
                "minimum_tier": m.minimum_tier,
                "enabled": bool(m.enabled),
                "beta": bool(getattr(m, "beta", False)),
                "coming_soon": bool(getattr(m, "coming_soon", False)),
                "version": getattr(m, "version", None),
                "tags": list(getattr(m, "tags", []) or []),
                "show_on_dashboard": bool(getattr(m, "show_on_dashboard", True)),
            }
        )
    return out


def reconcile(modules: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Upsert collected modules; mark anything no longer present as absent.

    Returns a summary: {collected, inserted, updated, absent, reappeared}.
    NEVER deletes a row.
    """
    modules = collect_modules() if modules is None else modules
    if not modules:
        # Cannot happen via collect_modules (it raises), but a caller could pass
        # []. Refuse rather than mark the entire platform absent.
        raise ValueError("refusing to reconcile an empty module set — that would mark every module absent")

    seen = {m["module_id"] for m in modules}
    now = now_utc()
    summary = {"collected": len(modules), "inserted": 0, "updated": 0, "absent": 0, "reappeared": 0}

    cols = ", ".join(_COLLECTED)
    placeholders = ", ".join(["%s"] * len(_COLLECTED))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _COLLECTED)

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("SELECT module_id, status FROM platform_registry_module")
        existing = {
            r["module_id"] if isinstance(r, dict) else r[0]: (r["status"] if isinstance(r, dict) else r[1])
            for r in cur.fetchall()
        }

        for m in modules:
            values = []
            for c in _COLLECTED:
                v = m[c]
                values.append(json.dumps(v) if isinstance(v, (list, dict)) else v)
            cur.execute(
                f"""
                INSERT INTO platform_registry_module (module_id, {cols}, status, first_seen_at, last_seen_at, collected_at)
                VALUES (%s, {placeholders}, 'present', %s, %s, %s)
                ON CONFLICT (module_id) DO UPDATE SET
                    {updates},
                    status       = 'present',
                    last_seen_at = EXCLUDED.last_seen_at,
                    collected_at = EXCLUDED.collected_at
                """,
                # notes is not in the column list, so ON CONFLICT cannot touch it.
                [m["module_id"], *values, now, now, now],
            )
            prior = existing.get(m["module_id"])
            if prior is None:
                summary["inserted"] += 1
            else:
                summary["updated"] += 1
                if prior == "absent":
                    summary["reappeared"] += 1

        # Absent: previously collected, not in this run. last_seen_at is NOT
        # touched — freezing it is the whole point, it answers "when did it go?"
        gone = [mid for mid, st in existing.items() if mid not in seen and st != "absent"]
        if gone:
            cur.execute(
                "UPDATE platform_registry_module SET status='absent', collected_at=%s WHERE module_id = ANY(%s)",
                (now, gone),
            )
            summary["absent"] = len(gone)
            logger.warning("platform_registry: %d module(s) went absent: %s", len(gone), ", ".join(sorted(gone)))

    return summary


def get_modules(include_absent: bool = True) -> list[dict[str, Any]]:
    """Read the registry back, notes included, ordered for rendering."""
    sql = """
        SELECT * FROM platform_registry_module
        {where}
        ORDER BY category, (NOT enabled), module_id
    """.format(
        where="" if include_absent else "WHERE status = 'present'"
    )
    with get_db_cursor() as (_conn, cur):
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]


def set_notes(module_id: str, notes: str | None) -> bool:
    """Set the human-owned notes for a module. The only writer of that column."""
    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "UPDATE platform_registry_module SET notes = %s WHERE module_id = %s",
            (notes, module_id),
        )
        return cur.rowcount > 0


def registry_summary() -> dict[str, Any]:
    """Counts for the generated header — including freshness, so the document
    can DECLARE ITS OWN STALENESS rather than implying it is current."""
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE status = 'present')            AS present,
                   count(*) FILTER (WHERE status = 'absent')             AS absent,
                   count(*) FILTER (WHERE status = 'present' AND enabled) AS enabled,
                   count(*) FILTER (WHERE notes IS NOT NULL AND notes <> '') AS with_notes,
                   max(collected_at)                                     AS collected_at
            FROM platform_registry_module
            """
        )
        row = cur.fetchone()
        return dict(row) if isinstance(row, dict) else {}

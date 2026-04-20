"""C.O.D.E.X. — Event-Driven Auto-Documentation.

Watches ``project_decisions`` for undocumented entries and writes a
matching ``knowledge_base`` vault_note for each. Closes the "manual
vault-note write at session end" overhead that the 2026-04-18
retrospective flagged (Project #272 Phase 2 / Task #2108).

This is distinct from ``auto_doc_service`` (D.A.R.W.I.N. project
intelligence reports, gap-driven, 7-day project cooldown). Both live
under Documentation & Knowledge but target different events:

  * D.A.R.W.I.N. → whole-project gaps → long-form reports
  * C.O.D.E.X.   → individual log_decision events → ADR summaries

Scope note (Phase 1 of #2108): decisions only. Task completions are
higher-volume and frequently ephemeral; they can be added in a later
pass if Kytran wants them documented too.

Dedup strategy: the service sets
``knowledge_base.source_type = 'codex_event_doc'`` and
``knowledge_base.source_id = 'decision:<id>'`` on every row it inserts.
"Undocumented" then means: no ``knowledge_base`` row with that
``source_type + source_id`` pair. No migration required.

Callers
-------
1. MCP tool ``mcp__archie__run_auto_documentation`` — force-run on demand
2. Agent-loop job ``codex_event_docs`` — scheduled every 30 min
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

SOURCE_TYPE = "codex_event_doc"
IMPORTANCE_SCORE = 0.70
DEFAULT_LOOKBACK_DAYS = 30
DEFAULT_MAX_ITEMS_PER_RUN = 10


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def get_undocumented_decisions(
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    limit: int = DEFAULT_MAX_ITEMS_PER_RUN,
) -> List[Dict[str, Any]]:
    """Return decisions within the window that don't yet have an auto-doc.

    A decision is "documented" if any ``knowledge_base`` row exists with
    ``source_type = 'codex_event_doc'`` AND
    ``source_id = 'decision:<decision_id>'``.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            SELECT pd.id, pd.decision_number, pd.title, pd.status,
                   pd.context, pd.decision, pd.alternatives, pd.consequences,
                   pd.project_id, pd.task_id, pd.created_at,
                   up.name AS project_name, up.slug AS project_slug
            FROM project_decisions pd
            LEFT JOIN unified_projects up ON up.id = pd.project_id
            WHERE pd.created_at > now() - (%s || ' days')::interval
              AND NOT EXISTS (
                  SELECT 1 FROM knowledge_base kb
                  WHERE kb.source_type = %s
                    AND kb.source_id = 'decision:' || pd.id::text
              )
            ORDER BY pd.created_at DESC
            LIMIT %s
            """,
            (str(lookback_days), SOURCE_TYPE, limit),
        )
        return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------


def _format_decision_body(decision: Dict[str, Any]) -> str:
    """Render a decision row into Markdown suitable for a vault_note."""
    parts: List[str] = []
    adr_num = decision.get("decision_number") or "?"
    project_name = decision.get("project_name") or "unassigned"
    created = decision.get("created_at")
    when = created.strftime("%Y-%m-%d") if created else "?"

    parts.append(f"**ADR-{adr_num:03d}** · project: *{project_name}* · {when}")
    parts.append("")

    if decision.get("status") and decision["status"] != "accepted":
        parts.append(f"> Status: **{decision['status']}**")
        parts.append("")

    if decision.get("context"):
        parts.append("## Context")
        parts.append(decision["context"])
        parts.append("")

    parts.append("## Decision")
    parts.append(decision["decision"])
    parts.append("")

    if decision.get("alternatives"):
        parts.append("## Alternatives considered")
        parts.append(decision["alternatives"])
        parts.append("")

    if decision.get("consequences"):
        parts.append("## Consequences")
        parts.append(decision["consequences"])
        parts.append("")

    parts.append("---")
    parts.append(
        f"*Auto-documented by C.O.D.E.X. from "
        f"project_decisions row #{decision['id']}. See `project_decisions` "
        f"for the raw source of truth.*"
    )
    return "\n".join(parts)


def _build_decision_vault_note(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Return ``{title, content, tags, category, source_id}`` ready to insert."""
    adr_num = decision.get("decision_number") or 0
    title = f"ADR-{adr_num:03d} — {decision['title']}"
    project_slug = decision.get("project_slug") or "unassigned"
    tags = [
        "auto-documented",
        "decision",
        f"adr-{adr_num:03d}",
        project_slug,
    ]
    return {
        "title": title[:500],
        "content": _format_decision_body(decision),
        "tags": tags,
        "category": project_slug,
        "source_id": f"decision:{decision['id']}",
    }


# ---------------------------------------------------------------------------
# Insert — the only write path. Idempotent via dedup query before call.
# ---------------------------------------------------------------------------


def _insert_vault_note(payload: Dict[str, Any]) -> Optional[int]:
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO knowledge_base
                   (title, content, knowledge_type, source_type, source_id,
                    importance_score, tags, category)
                VALUES (%s, %s, 'vault_note', %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    payload["title"],
                    payload["content"],
                    SOURCE_TYPE,
                    payload["source_id"],
                    IMPORTANCE_SCORE,
                    payload["tags"],
                    payload["category"],
                ),
            )
            return cur.fetchone()["id"]
    except Exception as e:
        logger.error(
            "C.O.D.E.X. auto-doc insert failed for %s: %s",
            payload.get("source_id"),
            e,
        )
        return None


def document_decision(decision: Dict[str, Any]) -> Optional[int]:
    """Build + insert a vault_note for one decision row. Returns kb_id or None."""
    payload = _build_decision_vault_note(decision)
    return _insert_vault_note(payload)


# ---------------------------------------------------------------------------
# Public entrypoint
# ---------------------------------------------------------------------------


def run_event_auto_docs(
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    max_items_per_run: int = DEFAULT_MAX_ITEMS_PER_RUN,
) -> Dict[str, Any]:
    """Scan for undocumented decisions, generate vault_notes, report summary.

    Safe to call repeatedly — the dedup check prevents duplicate notes.
    Returns a structured payload for both the MCP tool and the
    agent_loop job to log.
    """
    ran_at = datetime.now(timezone.utc).isoformat()
    candidates = get_undocumented_decisions(lookback_days=lookback_days, limit=max_items_per_run)

    created: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []

    for decision in candidates:
        kb_id = document_decision(decision)
        if kb_id:
            created.append(
                {
                    "decision_id": decision["id"],
                    "decision_number": decision.get("decision_number"),
                    "title": decision["title"],
                    "kb_id": kb_id,
                }
            )
        else:
            failed.append(
                {
                    "decision_id": decision["id"],
                    "title": decision["title"],
                }
            )

    severity = "info"
    reasons: List[str] = []
    if failed:
        severity = "warning"
        reasons.append(f"{len(failed)} decision(s) failed to document")
    if created:
        reasons.append(f"{len(created)} new auto-doc(s) written")

    return {
        "ran_at": ran_at,
        "lookback_days": lookback_days,
        "candidates_found": len(candidates),
        "created": created,
        "failed": failed,
        "severity": severity,
        "reasons": reasons,
        "summary_metrics": {
            "candidates": len(candidates),
            "created": len(created),
            "failed": len(failed),
        },
    }


def format_alert_message(result: Dict[str, Any]) -> str:
    """Compact message for Telegram / system_notifications."""
    metrics = result["summary_metrics"]
    lines = [
        "C.O.D.E.X. — event auto-documentation",
        f"Severity: *{result['severity'].upper()}* · " f"{metrics['created']} new, {metrics['failed']} failed",
        "",
        f"• candidates scanned: {metrics['candidates']}",
        f"• vault_notes created: {metrics['created']}",
        f"• failures: {metrics['failed']}",
    ]
    if result.get("created"):
        lines.append("")
        lines.append("Documented:")
        for item in result["created"][:5]:
            num = item.get("decision_number") or "?"
            lines.append(f"  – ADR-{num:03d}: {item['title'][:60]}")
        if len(result["created"]) > 5:
            lines.append(f"  …and {len(result['created']) - 5} more")
    return "\n".join(lines)

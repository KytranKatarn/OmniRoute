"""Bridge-driven generation, confidence gate, Dept HQ routing."""

from __future__ import annotations

import logging
import os
from typing import Optional

from database import get_db_cursor

logger = logging.getLogger(__name__)

NIGHTLY_CAP = int(os.getenv("TRANSLATION_NIGHTLY_CAP", "5000"))

AUTO_APPROVE_MIN = 0.85
REVIEW_MIN = 0.60

REVIEW_PROJECT_NAME = "Platform Translation Coverage"


def _ensure_review_project() -> int:
    """Get or create the review project. Return its id."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT id FROM unified_projects WHERE name = %s",
            (REVIEW_PROJECT_NAME,),
        )
        row = cur.fetchone()
        if row:
            return row["id"]
        # project_type is the real column name (not type)
        cur.execute(
            """INSERT INTO unified_projects
                   (name, slug, description, status, priority, project_type, tags)
               VALUES (%s, %s, %s, 'planning', 7, 'feature',
                       ARRAY['translations','coverage'])
               RETURNING id""",
            (
                REVIEW_PROJECT_NAME,
                "platform-translation-coverage",
                "Low-confidence translation reviews routed by the nightly coverage scan.",
            ),
        )
        return cur.fetchone()["id"]


def _route_to_review(
    gap_id: int,
    source: str,
    language: str,
    key: str,
    suggested_translation: str,
    confidence: float,
    gap_type: str,
) -> int:
    project_id = _ensure_review_project()
    priority = 8 if confidence < REVIEW_MIN else 6
    title = f"Review {language} for {source}: {(suggested_translation or '')[:60]}"
    description = (
        f"**Key:** `{key}`\n"
        f"**Source:** `{source}`\n"
        f"**Gap type:** `{gap_type}`\n"
        f"**Confidence:** {confidence:.2f}\n\n"
        f"**Suggested translation:**\n\n> {suggested_translation or '(none)'}\n\n"
        f"Review in Consciousness Languages tab → Coverage Health → drill into "
        f"`{source}` × `{language}`."
    )
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO unified_tasks
                   (project_id, title, description, status, priority,
                    task_type, estimated_effort)
               VALUES (%s, %s, %s, 'pending', %s, 'review', 'tiny')
               RETURNING id""",
            (project_id, title, description, priority),
        )
        task_id = cur.fetchone()["id"]
        cur.execute(
            "UPDATE translation_gaps SET status='routed', task_id=%s WHERE id=%s",
            (task_id, gap_id),
        )
    return task_id


def _generate_translation(en_text: str, language: str, glossary: Optional[list] = None) -> dict:
    """Return {'translated': str, 'confidence': float}.

    Calls the Dept HQ dispatcher with the 'translate' capability. Returns an
    empty translation on any dispatch failure so the caller can skip cleanly.
    """
    from tools.department_hq.services.department_dispatcher import dispatch_json

    glossary_block = ""
    if glossary:
        lines = "\n".join(f"- {g['source_text']} → {g['translated_text']}" for g in glossary[:10])
        glossary_block = f"\n\nBrand glossary (use consistently):\n{lines}\n"

    prompt = (
        f"Translate the following English UI string to {language}.\n"
        f'Respond ONLY with JSON: {{"translated": "...", "confidence": 0.0-1.0}}.\n'
        f"{glossary_block}\n\nTEXT: {en_text}"
    )
    # Pin translation to the GPU Starships when available — R.O.S.E.T.T.A.'s
    # mistral:7b fits the RTX 3070 (8GB), turning ~19s hub-CPU generations into
    # ~2-3s. Ordered list = cluster fallback; the dispatcher skips busy/resting
    # nodes and falls through to hub routing if neither GPU node is free
    # (welfare/rest-gated, per PR #1352). KB #270009.
    r = dispatch_json(
        capability="translate",
        prompt=prompt,
        module_id="coverage_scan",
        prefer_agent="R.O.S.E.T.T.A.",
        preferred_node=["Starship-246", "Starship-245"],
    )
    if not isinstance(r, dict):
        return {"translated": "", "confidence": 0.0}
    translated = r.get("translated", "") or ""
    try:
        confidence = float(r.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {"translated": translated, "confidence": confidence}


def process_missing_gap(gap: dict) -> bool:
    """Fetch EN source, generate, gate, write. Return True on success."""
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT text FROM translations
               WHERE source_label=%s AND language='en' AND key=%s LIMIT 1""",
            (gap["source"], gap["key"]),
        )
        row = cur.fetchone()
        if not row:
            return False
        en_text = row["text"]
        cur.execute(
            """SELECT source_text, translated_text FROM translation_memory
               WHERE language=%s AND source_text ILIKE %s LIMIT 5""",
            (gap["language"], f"%{en_text[:40]}%"),
        )
        glossary = list(cur.fetchall())

    result = _generate_translation(en_text, gap["language"], glossary)
    translated = result["translated"]
    confidence = result["confidence"]
    if not translated:
        return False

    status = "approved" if confidence >= AUTO_APPROVE_MIN else "pending_review"

    with get_db_cursor(commit=True) as (conn, cur):
        # Migration 323 scoped translations uniqueness by source_label so the
        # same key can exist per product/site without collision.
        cur.execute(
            """INSERT INTO translations
                   (source_label, key, language, text, source, status,
                    generated_by, last_semantic_review_at)
               VALUES (%s, %s, %s, %s, 'ai_generated', %s,
                       'coverage_scan', NOW())
               ON CONFLICT (source_label, key, language) DO UPDATE
                 SET text=EXCLUDED.text,
                     source=EXCLUDED.source,
                     status=EXCLUDED.status,
                     last_semantic_review_at=NOW()""",
            (gap["source"], gap["key"], gap["language"], translated, status),
        )
        cur.execute(
            "UPDATE translation_gaps SET status='resolved', resolved_at=NOW() WHERE id=%s",
            (gap["id"],),
        )

    if status == "pending_review":
        _route_to_review(
            gap["id"],
            gap["source"],
            gap["language"],
            gap["key"],
            translated,
            confidence,
            gap["gap_type"],
        )
    return True

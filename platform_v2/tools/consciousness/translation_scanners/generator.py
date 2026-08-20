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


# Per-language translation routing (bake-off verified 2026-06-01). gemma3:12b is
# the only local model that handles Arabic + Hebrew cleanly (and German more
# precisely than mistral); mistral:7b covers the rest. The AGENT is always the AI
# translate owner R.O.S.E.T.T.A. (worker_type='ai') so the dispatch genuinely bills a
# budgeted AI agent and is welfare/governance tracked (K.I.N./C.R.E.E.D.) —
# model_override decouples the model from the agent, so ar/he/de keep gemma3:12b
# while still billing R.O.S.E.T.T.A. (routing ar/he/de to the internal persona
# 'Amina' silently defeated that: she is worker_type='internal', invisible to the AI
# accounting — its 1.4M tok/30d floated unattributed). Override per language without a
# deploy via platform_settings 'translate_route_<lang>' = "<model>|<agent>".
_LANG_ROUTING = {
    "ar": ("gemma3:12b", "R.O.S.E.T.T.A."),
    "he": ("gemma3:12b", "R.O.S.E.T.T.A."),
    "de": ("gemma3:12b", "R.O.S.E.T.T.A."),
}
_DEFAULT_ROUTING = ("mistral:7b", "R.O.S.E.T.T.A.")
# Models that don't reliably emit the strict JSON envelope — use raw-text mode.
_RAW_OUTPUT_MODELS = {"gemma3:12b"}

# Full language names for the prompt — a model translates far more reliably from
# "French" than from the bare code "fr". The 8 in-scope languages.
_LANG_NAMES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "pt": "Portuguese",
    "zh": "Chinese (Simplified)",
    "ar": "Arabic",
    "he": "Hebrew",
}


def get_translate_routing(language: str) -> tuple:
    """Return ``(model, prefer_agent)`` for a target language. Fail-safe → default.

    Overridable without a deploy via platform_settings
    ``translate_route_<lang>`` = ``"<model>|<agent>"``.
    """
    lang = (language or "").lower()
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=False) as (_c, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key=%s", (f"translate_route_{lang}",))
            row = cur.fetchone()
        if row and row.get("value") and "|" in row["value"]:
            model, agent = row["value"].split("|", 1)
            return model.strip(), agent.strip()
    except Exception:
        pass
    return _LANG_ROUTING.get(lang, _DEFAULT_ROUTING)


def _generate_translation(en_text: str, language: str, glossary: Optional[list] = None) -> dict:
    """Return {'translated': str, 'confidence': float}.

    Routes the 'translate' capability to the per-language specialist through the
    DHQ dispatcher (welfare/governance/cost tracked). gemma3-class models
    (ar/he/de) don't emit the JSON envelope, so those use raw-text mode + lenient
    parse; mistral uses structured JSON with a self-reported confidence. Returns
    an empty translation on any dispatch failure so the caller can skip cleanly.
    """
    from tools.department_hq.services.department_dispatcher import dispatch, dispatch_json

    glossary_block = ""
    if glossary:
        lines = "\n".join(f"- {g['source_text']} → {g['translated_text']}" for g in glossary[:10])
        glossary_block = f"\n\nBrand glossary (use consistently):\n{lines}\n"

    lang_name = _LANG_NAMES.get((language or "").lower(), language)
    model, agent = get_translate_routing(language)

    if model in _RAW_OUTPUT_MODELS:
        # Raw-text mode — gemma3 won't honour "respond ONLY with JSON". No
        # preferred_node pin: a 12B can't co-fit the small starship GPUs, so the
        # dispatcher routes it (hub CPU / capable node) instead of us forcing it.
        prompt = (
            f"Translate this English UI string to {lang_name}. "
            f"Output ONLY the translation — no quotes, no explanation, no notes."
            f"{glossary_block}\n\nTEXT: {en_text}"
        )
        deferred = False
        try:
            r = dispatch(
                capability="translate",
                prompt=prompt,
                module_id="coverage_scan",
                prefer_agent=agent,
                model_override=model,
                local_only=True,
            )
            # #5851 — ADR-013: ALWAYS check .success. Reading .response directly turned a
            # SHED dispatch ("hub saturated — ... retry shortly", 96% of this capability's
            # 1,160 failures/48h, avg 2.9s) into translated="" — indistinguishable from
            # "the model produced nothing". Nothing retried, so the string stayed
            # untranslated, returned on the next scan, and re-flooded an already-saturated
            # hub. An unsuccessful dispatch is not evidence ABOUT THE STRING.
            if not getattr(r, "success", False):
                return {"translated": "", "confidence": 0.0, "deferred": True}
            raw = (getattr(r, "response", "") or "").strip().strip('"').strip()
            translated = raw.splitlines()[0].strip() if raw else ""
        except Exception:
            # An exception says nothing about the string either.
            translated = ""
            deferred = True
        # gemma3 gives no self-confidence; assign a sane default that auto-approves
        # good output. The back-translation QA pass is the quality backstop.
        return {
            "translated": translated,
            "confidence": 0.9 if translated else 0.0,
            "deferred": deferred,
        }

    # JSON mode — mistral honours the envelope and reports a confidence we gate on.
    prompt = (
        f"Translate the following English UI string to {lang_name}.\n"
        f'Respond ONLY with JSON: {{"translated": "...", "confidence": 0.0-1.0}}.\n'
        f"{glossary_block}\n\nTEXT: {en_text}"
    )
    r = dispatch_json(
        capability="translate",
        prompt=prompt,
        module_id="coverage_scan",
        prefer_agent=agent,
        # No preferred_node: capability='translate' is in CAPABILITY_NODE_AFFINITY
        # -> _GPU_CLUSTER (node_ids, rename-safe), so the dispatcher routes this to
        # the GPU starships automatically. The old ["Starship-246","Starship-245"]
        # short names matched neither node_name nor node_id post-rename -> hub (#3800).
        model_override=model,
        local_only=True,
    )
    if not isinstance(r, dict):
        # dispatch_json yields a non-dict when the dispatch itself did not succeed
        # (shed / timeout / error) — deferred, NOT an untranslatable string (#5851).
        return {"translated": "", "confidence": 0.0, "deferred": True}
    translated = r.get("translated", "") or ""
    try:
        confidence = float(r.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {"translated": translated, "confidence": confidence, "deferred": False}


def process_missing_gap(gap: dict) -> bool:
    """True only when a translation was WRITTEN.

    Thin wrapper over process_missing_gap_status so the two existing call sites
    (`if process_missing_gap(gap):`) keep meaning exactly what they meant — a
    deferral must never read as a write.
    """
    return process_missing_gap_status(gap) == "written"


def process_missing_gap_status(gap: dict) -> str:
    """Fetch EN source, generate, gate, write. Returns 'written' | 'skipped' | 'deferred'.

    'deferred' means the DISPATCH did not happen (hub shed the work, timeout, error) — the
    gap is untouched and must be retried, not counted. Distinguishing it from 'skipped' is
    the whole point: they were collapsed into one falsy return, so 1,117 shed dispatches in
    48h looked like 1,117 strings that could not be translated (#5851).
    """
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            """SELECT text FROM translations
               WHERE source_label=%s AND language='en' AND key=%s LIMIT 1""",
            (gap["source"], gap["key"]),
        )
        row = cur.fetchone()
        if not row:
            return "skipped"
        en_text = row["text"]
        cur.execute(
            """SELECT source_text, translated_text FROM translation_memory
               WHERE language=%s AND source_text ILIKE %s LIMIT 5""",
            (gap["language"], f"%{en_text[:40]}%"),
        )
        glossary = list(cur.fetchall())

    result = _generate_translation(en_text, gap["language"], glossary)
    if result.get("deferred"):
        # Leave the gap OPEN and untouched. The dispatcher said "retry shortly"; this is
        # what actually retries — on the next pass, against a hub that has drained.
        return "deferred"
    translated = result["translated"]
    confidence = result["confidence"]
    if not translated:
        return "skipped"

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
    return "written"

"""
A.R.C.H.I.E. Content Studio — Writing Service
===============================================
5-stage AI writing pipeline: Research → Outline → Draft → Edit → SEO
Each stage dispatches to the Bridge using a dedicated writing agent persona.

Author: A.R.C.H.I.E. Platform
Date: 2026-03-14
"""

import json
import logging
import sys
from datetime import datetime

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
from archie_bridge import archie_bridge as ai_bridge  # noqa: E402

from database import get_db_cursor  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONTENT_TEMPLATES = {
    "article": {
        "structure": "Introduction, Body (3-5 sections), Conclusion",
        "typical_length": "800-1500 words",
    },
    "blog_post": {
        "structure": "Hook, Problem, Solution, Examples, CTA",
        "typical_length": "600-1200 words",
    },
    "press_release": {
        "structure": "Headline, Dateline, Lead, Body, Boilerplate, Contact",
        "typical_length": "400-600 words",
    },
    "product_review": {
        "structure": "Overview, Features, Pros/Cons, Comparison, Verdict",
        "typical_length": "800-1200 words",
    },
    "how_to_guide": {
        "structure": "Introduction, Prerequisites, Step-by-step, Tips, FAQ",
        "typical_length": "1000-2000 words",
    },
    "newsletter": {
        "structure": "Subject, Preview, Greeting, Sections, CTA, Sign-off",
        "typical_length": "500-800 words",
    },
    "marketing_copy": {
        "structure": "Headline, Hook, Benefits, Social Proof, CTA",
        "typical_length": "200-500 words",
    },
    "book_chapter": {
        "structure": "Opening, Main content, Transitions, Chapter summary",
        "typical_length": "2000-5000 words",
    },
}

PIPELINE_STAGES = [
    {"id": "research", "name": "Research", "checkpoint": False},
    {"id": "outline", "name": "Outline", "checkpoint": True},
    {"id": "draft", "name": "Draft", "checkpoint": False},
    {"id": "edit", "name": "Edit", "checkpoint": True},
    {"id": "seo", "name": "SEO", "checkpoint": False},
]

_STAGE_IDS = [s["id"] for s in PIPELINE_STAGES]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def start_writing(
    user_id: int, description: str, content_type: str = "article", tone: str = "professional", template: str = None
) -> dict:
    """
    Insert a new writing session and kick off the research stage.
    Returns {session_id, status}.
    """
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO content_writing_sessions
                (user_id, description, content_type, tone, template,
                 current_stage, status, stage_outputs, revision_count)
            VALUES (%s, %s, %s, %s, %s, 'research', 'running', '{}', 0)
            RETURNING id
            """,
            (user_id, description, content_type, tone, template),
        )
        session_id = cur.fetchone()["id"]

    logger.info("Writing session %s created for user %s", session_id, user_id)

    # Run research stage synchronously (fast)
    try:
        _run_stage(session_id, "research")
    except Exception as exc:
        logger.error("Research stage failed for session %s: %s", session_id, exc)
        _set_status(session_id, "error")

    return {"session_id": session_id, "status": "running"}


def approve_checkpoint(session_id: int, user_id: int) -> dict:
    """
    Advance past the current checkpoint stage to the next stage.
    Mirrors the Game Studio approve_checkpoint pattern.
    """
    session = get_writing_status(session_id)
    if not session:
        return {"success": False, "error": "Session not found"}

    current = session["current_stage"]
    # Find current stage index
    try:
        idx = _STAGE_IDS.index(current)
    except ValueError:
        return {"success": False, "error": f"Unknown stage: {current}"}

    # Verify it is actually a checkpoint
    stage_def = PIPELINE_STAGES[idx]
    if not stage_def["checkpoint"]:
        return {"success": False, "error": f"Stage '{current}' is not a checkpoint"}

    if session["status"] not in ("awaiting_approval", "running"):
        return {"success": False, "error": "Session not awaiting approval"}

    # Advance to next stage
    next_idx = idx + 1
    if next_idx >= len(PIPELINE_STAGES):
        # Pipeline complete
        _set_status(session_id, "completed")
        return {"success": True, "status": "completed"}

    next_stage = _STAGE_IDS[next_idx]
    _set_stage(session_id, next_stage, "running")

    try:
        _run_stage(session_id, next_stage)
    except Exception as exc:
        logger.error("Stage %s failed for session %s: %s", next_stage, session_id, exc)
        _set_status(session_id, "error")
        return {"success": False, "error": str(exc)}

    return {"success": True, "current_stage": next_stage}


def get_writing_status(session_id: int) -> dict | None:
    """Return the full session row as a dict, or None if not found."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT * FROM content_writing_sessions WHERE id = %s", (session_id,))
        row = cur.fetchone()
    if not row:
        return None
    result = dict(row)
    # Ensure stage_outputs is a plain dict (psycopg2 may return str)
    if isinstance(result.get("stage_outputs"), str):
        try:
            result["stage_outputs"] = json.loads(result["stage_outputs"])
        except Exception:
            result["stage_outputs"] = {}
    return result


def apply_writing_result(session_id: int) -> dict:
    """
    Create or update a content_documents record with the final SEO output.
    Sets session status to 'published'. Returns {document_id}.
    """
    session = get_writing_status(session_id)
    if not session:
        return {"success": False, "error": "Session not found"}

    stage_outputs = session.get("stage_outputs") or {}
    seo = stage_outputs.get("seo") or {}
    draft = stage_outputs.get("draft") or {}
    outline = stage_outputs.get("outline") or {}

    final_content = seo.get("optimized_content") or draft.get("content", "")
    title = draft.get("title") or outline.get("title") or session["description"][:200]
    word_count = draft.get("word_count", 0)
    meta = {
        "meta_title": seo.get("meta_title", ""),
        "meta_description": seo.get("meta_description", ""),
        "keywords": seo.get("keywords", []),
        "readability_score": seo.get("readability_score", 0),
    }

    with get_db_cursor(commit=True) as (conn, cur):
        existing_doc_id = session.get("document_id")
        if existing_doc_id:
            cur.execute(
                """
                UPDATE content_documents
                SET title=%s, content=%s, word_count=%s, status='published',
                    metadata=%s, updated_at=NOW()
                WHERE id=%s
                RETURNING id
                """,
                (title, final_content, word_count, json.dumps(meta), existing_doc_id),
            )
            doc_id = cur.fetchone()["id"]
        else:
            cur.execute(
                """
                INSERT INTO content_documents
                    (user_id, title, doc_type, content, description, word_count,
                     status, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, 'published', %s)
                RETURNING id
                """,
                (
                    session["user_id"],
                    title,
                    session.get("content_type", "article"),
                    final_content,
                    session["description"],
                    word_count,
                    json.dumps(meta),
                ),
            )
            doc_id = cur.fetchone()["id"]
            # Link document back to session
            cur.execute(
                "UPDATE content_writing_sessions SET document_id=%s, status='published', completed_at=NOW() WHERE id=%s",
                (doc_id, session_id),
            )
            return {"success": True, "document_id": doc_id}

        cur.execute(
            "UPDATE content_writing_sessions SET status='published', completed_at=NOW() WHERE id=%s",
            (session_id,),
        )

    return {"success": True, "document_id": doc_id}


def ai_assist(text: str, action: str, context: dict = None) -> dict:
    """
    Inline AI actions for the editor UI.
    Actions: expand | rewrite | summarize | change_tone
    Returns {result_text}.
    """
    context = context or {}
    tone = context.get("tone", "professional")

    action_prompts = {
        "expand": f"Expand this text with more detail:\n\n{text}",
        "rewrite": f"Rewrite this text to be clearer and more engaging:\n\n{text}",
        "summarize": f"Summarize this text concisely:\n\n{text}",
        "change_tone": f"Rewrite in {tone} tone:\n\n{text}",
    }

    prompt = action_prompts.get(action, f"Improve this text:\n\n{text}")

    try:
        result = ai_bridge(
            prompt=prompt,
            system_prompt="You are a professional content editor. Return only the improved text with no preamble.",
            task_type="content_assist",
            try_local_first=True,
            use_smart_routing=True,
            context={"module": "content_studio", "action": action},
        )
        result_text = result.get("response") or result.get("content") or ""
        return {"success": True, "result_text": result_text}
    except Exception as exc:
        logger.error("ai_assist failed: %s", exc)
        return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _run_stage(session_id: int, stage_id: str) -> None:
    """
    Execute a single pipeline stage, store output, and advance the session.
    For checkpoint stages, sets status='awaiting_approval' after completion.
    For non-checkpoint stages, immediately advances to the next stage.
    """
    session = get_writing_status(session_id)
    if not session:
        raise ValueError(f"Session {session_id} not found")

    description = session["description"]
    content_type = session.get("content_type", "article")
    tone = session.get("tone", "professional")
    template_key = session.get("template") or content_type
    tmpl = CONTENT_TEMPLATES.get(template_key, CONTENT_TEMPLATES["article"])
    stage_outputs = session.get("stage_outputs") or {}

    # Build stage-specific prompt
    if stage_id == "research":
        system = "You are a research agent. Always respond with valid JSON only."
        prompt = (
            f"Given this topic, find key points, facts, and angles.\n"
            f"Topic: {description}\n\n"
            f'Return JSON: {{"key_points": [], "sources": [], "angle": "..."}}'
        )

    elif stage_id == "outline":
        research = stage_outputs.get("research", {})
        system = "You are an outline agent. Always respond with valid JSON only."
        prompt = (
            f"Given the research and content type, create a detailed outline.\n"
            f"Research: {json.dumps(research)}\n"
            f"Content type: {content_type}\n"
            f"Template structure: {tmpl['structure']}\n\n"
            f'Return JSON: {{"title": "...", "sections": [{{"heading": "...", "points": ["..."]}}]}}'
        )

    elif stage_id == "draft":
        outline = stage_outputs.get("outline", {})
        system = "You are a creative writer. Always respond with valid JSON only."
        prompt = (
            f"Given the outline and tone, write the full content.\n"
            f"Outline: {json.dumps(outline)}\n"
            f"Tone: {tone}\n"
            f"Target length: {tmpl['typical_length']}\n\n"
            f'Return JSON: {{"title": "...", "content": "full markdown text", "word_count": 0}}'
        )

    elif stage_id == "edit":
        draft = stage_outputs.get("draft", {})
        revision_count = session.get("revision_count", 0)
        system = "You are a sharp editor. Always respond with valid JSON only."
        prompt = (
            f"Review this draft for grammar, clarity, flow, and tone consistency.\n"
            f"Draft: {json.dumps(draft)}\n"
            f"Tone: {tone}\n\n"
            f'Return JSON: {{"edited_content": "...", "changes_made": ["..."], '
            f'"quality_score": 0, "needs_revision": false, "revision_notes": "..."}}'
        )

    elif stage_id == "seo":
        edit = stage_outputs.get("edit", {})
        draft = stage_outputs.get("draft", {})
        content_for_seo = edit.get("edited_content") or draft.get("content", "")
        system = "You are an SEO specialist. Always respond with valid JSON only."
        prompt = (
            f"Optimize this content for search visibility.\n"
            f"Content: {content_for_seo[:3000]}\n\n"
            f'Return JSON: {{"optimized_content": "...", "meta_title": "...", '
            f'"meta_description": "...", "keywords": ["..."], "readability_score": 0}}'
        )

    else:
        raise ValueError(f"Unknown stage: {stage_id}")

    # Dispatch to Bridge
    result = ai_bridge(
        prompt=prompt,
        system_prompt=system,
        task_type=f"content_{stage_id}",
        try_local_first=True,
        use_smart_routing=True,
        context={"module": "content_studio", "stage": stage_id, "session_id": session_id},
    )

    raw_response = result.get("response") or result.get("content") or "{}"

    # Parse JSON output from agent
    try:
        # Strip markdown code fences if present
        clean = raw_response.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:])
            if clean.endswith("```"):
                clean = clean[: clean.rfind("```")]
        stage_output = json.loads(clean)
    except json.JSONDecodeError:
        logger.warning("Stage %s returned non-JSON, storing raw text", stage_id)
        stage_output = {"raw": raw_response}

    # Special edit logic: send back to draft if quality < 70 and revision < 2
    if stage_id == "edit":
        quality = stage_output.get("quality_score", 100)
        needs_revision = stage_output.get("needs_revision", False)
        revision_count = session.get("revision_count", 0)
        if (quality < 70 or needs_revision) and revision_count < 2:
            # Inject revision notes into draft stage for retry
            stage_outputs["edit_feedback"] = stage_output
            stage_outputs[stage_id] = stage_output
            _save_stage_output(session_id, stage_id, stage_output)
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE content_writing_sessions SET revision_count=revision_count+1, current_stage='draft' WHERE id=%s",
                    (session_id,),
                )
            # Re-run draft with revision notes
            _run_stage(session_id, "draft")
            return

    # Save output
    _save_stage_output(session_id, stage_id, stage_output)

    # Determine next action
    stage_def = next(s for s in PIPELINE_STAGES if s["id"] == stage_id)
    stage_idx = _STAGE_IDS.index(stage_id)

    if stage_def["checkpoint"]:
        # Pause for human approval
        _set_stage(session_id, stage_id, "awaiting_approval")
    else:
        # Auto-advance to next stage
        next_idx = stage_idx + 1
        if next_idx < len(PIPELINE_STAGES):
            next_stage = _STAGE_IDS[next_idx]
            _set_stage(session_id, next_stage, "running")
            _run_stage(session_id, next_stage)
        else:
            _set_status(session_id, "completed")


def _save_stage_output(session_id: int, stage_id: str, output: dict) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            UPDATE content_writing_sessions
            SET stage_outputs = stage_outputs || %s::jsonb
            WHERE id = %s
            """,
            (json.dumps({stage_id: output}), session_id),
        )


def _set_stage(session_id: int, stage_id: str, status: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE content_writing_sessions SET current_stage=%s, status=%s WHERE id=%s",
            (stage_id, status, session_id),
        )


def _set_status(session_id: int, status: str) -> None:
    with get_db_cursor(commit=True) as (conn, cur):
        completed_at = "NOW()" if status in ("completed", "published", "error") else "NULL"
        cur.execute(
            f"UPDATE content_writing_sessions SET status=%s, completed_at={completed_at} WHERE id=%s",
            (status, session_id),
        )

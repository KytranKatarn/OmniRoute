"""services/agent_kb_service.py — agent-proposed KB writes (#3534 Phase 3).

Tool-capable agents may PROPOSE knowledge-base entries mid-task (via the
`store_memory` tool in ai_bridge.agentic_search). Writes are QUARANTINED:
they land as ``source_type='agent_proposed'``, ``review_status='pending'`` and
are excluded from every retrieval path until a platform agent (C.O.D.E.X.)
promotes them. No synchronous governance call in the write path — only fast
inline guards (quota + PII + dedup). Promotion is a separate scheduled job
(``auto_review_pending_writes``) that dispatches each pending entry to C.O.D.E.X.
via the DHQ dispatcher (ADR-013).

Quarantine is enforced in the search layer by the filter
``(source_type IS DISTINCT FROM 'agent_proposed' OR review_status = 'approved')``
applied in ai_bridge.semantic_search + services.rag_service + the MCP search.
"""

import logging
import re

from database import get_db_cursor

logger = logging.getLogger(__name__)

DAILY_WRITE_QUOTA = 20  # per-agent KB writes per day
_MIN_CONTENT = 20
_MAX_CONTENT = 8000

# T3261 PII patterns — reject (do not even quarantine) entries containing PII.
_PII_PATTERNS = [
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b")),
    ("phone", re.compile(r"\b(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("credit_card", re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")),
    ("passport", re.compile(r"\b[A-Z]{2}\d{6,9}\b")),
]


def _detect_pii(text):
    for label, pat in _PII_PATTERNS:
        if pat.search(text or ""):
            return label
    return None


def _audit(agent_id, agent_name, action, details):
    """Best-effort governance audit row (event_category='creed_gate')."""
    try:
        from psycopg2.extras import Json

        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(
                """INSERT INTO governance_audit_log
                       (event_type, event_category, agent_id, action, reason,
                        outcome, timestamp, details)
                   VALUES ('kb_write_by_agent', 'creed_gate', %s, %s, %s,
                           'logged', NOW(), %s)""",
                (agent_id, action, f"agent {agent_name}: {action}", Json(details or {})),
            )
    except Exception as exc:
        logger.debug("[agent_kb] audit skipped: %s", exc)


def _check_and_increment_quota(agent_id):
    """Return (allowed, used_after, limit). Resets the daily window in-SQL."""
    if not agent_id:
        return True, 0, DAILY_WRITE_QUOTA
    try:
        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(
                """UPDATE agent_budgets
                   SET kb_writes_today = 0, kb_writes_reset_at = NOW() + INTERVAL '1 day'
                   WHERE agent_id = %s
                     AND (kb_writes_reset_at IS NULL OR kb_writes_reset_at <= NOW())""",
                (agent_id,),
            )
            cur.execute("SELECT kb_writes_today FROM agent_budgets WHERE agent_id = %s", (agent_id,))
            row = cur.fetchone()
            if not row:
                return True, 0, DAILY_WRITE_QUOTA  # no budget row — don't block
            used = row["kb_writes_today"] or 0
            if used >= DAILY_WRITE_QUOTA:
                return False, used, DAILY_WRITE_QUOTA
            cur.execute(
                "UPDATE agent_budgets SET kb_writes_today = kb_writes_today + 1 WHERE agent_id = %s",
                (agent_id,),
            )
            return True, used + 1, DAILY_WRITE_QUOTA
    except Exception as exc:
        logger.warning("[agent_kb] quota check failed (%s) — denying to be safe", exc)
        return False, 0, DAILY_WRITE_QUOTA


def _is_near_duplicate(title, content):
    """Reject re-proposing the same thing (exact title or content-prefix match
    among existing agent_proposed entries)."""
    snippet = (content or "")[:120]
    try:
        with get_db_cursor(commit=False) as (_c, cur):
            cur.execute(
                """SELECT 1 FROM knowledge_base
                   WHERE source_type = 'agent_proposed'
                     AND (title = %s OR content ILIKE %s)
                   LIMIT 1""",
                (title, f"{snippet}%"),
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def propose_agent_memory(agent_id, agent_name, content, title=None, tags=None):
    """Quarantined agent KB write. Fast inline guards only (no LLM/HTTP).

    Returns {ok: bool, id?: int, reason?: str}. The model NEVER controls
    knowledge_type/source_type/review_status — they are forced here.
    """
    content = (content or "").strip()
    if len(content) < _MIN_CONTENT:
        return {"ok": False, "reason": f"content too short (min {_MIN_CONTENT} chars)"}
    content = content[:_MAX_CONTENT]

    pii = _detect_pii(f"{title or ''}\n{content}")
    if pii:
        _audit(agent_id, agent_name, "rejected_pii", {"pii": pii})
        return {"ok": False, "reason": f"contains PII ({pii}) — not stored"}

    allowed, used, limit = _check_and_increment_quota(agent_id)
    if not allowed:
        return {"ok": False, "reason": f"daily KB-write quota reached ({used}/{limit})"}

    if _is_near_duplicate(title, content):
        return {"ok": False, "reason": "near-duplicate of an existing proposed entry"}

    title = (title or content[:80]).strip()[:200]
    full_tags = list(tags or []) + ["agent_proposed", f"agent:{agent_name}"]
    try:
        with get_db_cursor(commit=True) as (_c, cur):
            # embedding left NULL (deferred to the embedding loop after approval);
            # knowledge_type/source_type/review_status forced — model can't escalate.
            cur.execute(
                """INSERT INTO knowledge_base
                       (knowledge_type, title, content, category, tags,
                        importance_score, source_type, review_status)
                   VALUES ('conversation_memory', %s, %s, 'agent_memory', %s,
                           0.5, 'agent_proposed', 'pending')
                   RETURNING id""",
                (title, content, full_tags),
            )
            kid = cur.fetchone()["id"]
    except Exception as exc:
        logger.warning("[agent_kb] write failed: %s", exc)
        return {"ok": False, "reason": f"write error: {exc}"}

    _audit(agent_id, agent_name, "kb_write_pending", {"kb_id": kid, "title": title[:80]})
    logger.info("[agent_kb] %s proposed KB#%s (pending review)", agent_name, kid)
    return {"ok": True, "id": kid}


# ── Auto-review (promotion) — scheduled job ──────────────────────────────────


def _review_one(row):
    """Dispatch one pending entry to C.O.D.E.X. for a promote/reject verdict."""
    from tools.department_hq.services.department_dispatcher import dispatch_json

    prompt = (
        "You are reviewing a knowledge-base entry an AI agent proposed for the "
        "shared A.R.C.H.I.E. knowledge base. Decide if it is accurate, useful, "
        "non-duplicative, and safe to admit.\n\n"
        f"TITLE: {row.get('title')}\n"
        f"CONTENT:\n{(row.get('content') or '')[:2000]}\n\n"
        'Respond ONLY with JSON: {"decision":"approve"|"reject",'
        '"quality_score":<0.0-1.0>,"reason":"<short>"}. '
        "Reject if vague, speculative, duplicated, unsafe, or low-value."
    )
    try:
        return dispatch_json(capability="summarize", prompt=prompt, module_id="agent_kb_review")
    except Exception as exc:
        logger.warning("[agent_kb_review] dispatch failed for KB#%s: %s", row.get("id"), exc)
        return None


def _set_status(kb_id, status, quality_score, reason):
    try:
        qs = None
        if isinstance(quality_score, (int, float)):
            qs = max(0.0, min(1.0, float(quality_score)))
        with get_db_cursor(commit=True) as (_c, cur):
            cur.execute(
                "UPDATE knowledge_base SET review_status = %s, quality_score = %s WHERE id = %s",
                (status, qs, kb_id),
            )
        _audit(None, "C.O.D.E.X.", f"review_{status}", {"kb_id": kb_id, "reason": (reason or "")[:300]})
    except Exception as exc:
        logger.warning("[agent_kb_review] status update failed for KB#%s: %s", kb_id, exc)


def auto_review_pending_writes(limit=20):
    """Scheduled job: C.O.D.E.X. reviews pending agent_proposed writes.

    Approve → review_status='approved' (+ quality_score); the embedding loop then
    embeds it and the quarantine filter lets it surface. Reject → 'rejected'
    (already excluded from search). Returns a summary dict.
    """
    promoted = rejected = errors = 0
    try:
        with get_db_cursor(commit=False) as (_c, cur):
            cur.execute(
                """SELECT id, title, content FROM knowledge_base
                   WHERE source_type = 'agent_proposed' AND review_status = 'pending'
                   ORDER BY created_at ASC LIMIT %s""",
                (limit,),
            )
            rows = [dict(r) for r in cur.fetchall()]
    except Exception as exc:
        logger.warning("[agent_kb_review] fetch failed: %s", exc)
        return {"promoted": 0, "rejected": 0, "errors": 1, "reviewed": 0}

    for row in rows:
        verdict = _review_one(row)
        if not isinstance(verdict, dict):
            errors += 1
            continue
        decision = str(verdict.get("decision") or "").lower()
        if decision == "approve":
            _set_status(row["id"], "approved", verdict.get("quality_score"), verdict.get("reason"))
            promoted += 1
        else:
            _set_status(row["id"], "rejected", verdict.get("quality_score"), verdict.get("reason"))
            rejected += 1

    if rows:
        logger.info(
            "[agent_kb_review] cycle — reviewed=%d promoted=%d rejected=%d errors=%d",
            len(rows),
            promoted,
            rejected,
            errors,
        )
    return {"promoted": promoted, "rejected": rejected, "errors": errors, "reviewed": len(rows)}

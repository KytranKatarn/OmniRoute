"""Chronicle Slice 10 — build a WRITING-voice profile from an owner's authored corpus.

#5644 slice 3. Reads the authored items Chronicle already holds (LinkedIn posts, his own
hand-written comments, engagement comments, replies, and his profile), asks a LOCAL model to
describe HOW he writes, and stores the result in `chronicle_voice_profile.style_guide`.

Privacy: dispatch is pinned `local_only=True`, same as the story service. Nothing leaves the
cluster.

FOUR DESIGN CONSTRAINTS, each measured rather than assumed:

1. STYLE ONLY, NEVER FACTS. A voice profile is injected into drafting prompts, so anything
   it carries can be parroted into real outbound text. A stray figure would either fabricate
   a claim or trip the no-fabrication validator (#4958), which fails CLOSED and silently
   burns the draft. `_scrub_factual` therefore drops any descriptor carrying a currency
   amount, a percentage, or a 3+ digit run. The allowlist for real FIGURES is
   `collaborator_facts` — a different mechanism on purpose.

2. LATEST PROFILE SNAPSHOT ONLY. Profile captures are content-addressed snapshots (slice 1),
   so the corpus accumulates one row per profile CHANGE. Feeding all of them would weight a
   repeated About section once per revision and skew the voice toward it.

3. CORPUS IS SELECTED BY AUTHORSHIP, NOT BY THE ENTITY GRAPH. Measured 2026-08-16: Terry is
   split across FIVE `chronicle_entity` rows (9/22/38/66/163, one of them the mis-parsed
   "Stephane Dion ; SPAC Ti Terry Caetano"), and joining his authored items through
   `chronicle_entity_link -> mailbox_email_entities` returns **zero** rows. Selecting the
   corpus that way would have produced an empty-but-successful build. The entity id is used
   ONLY to satisfy the table's FK / give the profile an owner.

4. AN EMPTY OR REFUSED BUILD WRITES NOTHING. Overwriting a good style guide with a degraded
   one is worse than leaving yesterday's in place.
"""

import json
import logging
import re

logger = logging.getLogger(__name__)

CAPABILITY = "summarize"  # routed + proven local by the Chronicle story worker

# Folders that are genuinely HIS writing. `linkedin/comments_inbound` is deliberately
# excluded — those are OTHER people's words on his posts and would poison the voice.
_AUTHORED_FOLDERS = (
    "linkedin/posts",
    "linkedin/comments_own",
    "linkedin/engagement",
    "linkedin/comments_reply",
)
_PROFILE_FOLDER = "linkedin/profile"

# The style guide is a CLOSED schema: keys outside this set are dropped rather than stored,
# so a chatty model cannot smuggle a "recent_claims" or "talking_points" field into a
# drafting prompt.
_STYLE_KEYS = (
    "tone",
    "register",
    "sentence_rhythm",
    "structure",
    "rhetorical_devices",
    "openers",
    "closers",
    "formatting_habits",
    "vocabulary",
    "recurring_themes",
    "avoid",
)

_FACTUAL_RE = re.compile(r"[$€£%]|\d{3,}")


def _dispatch_fn():
    """Queue-AWARE dispatch. Lazy import so tests monkeypatch this.

    Deliberately NOT the bare `department_dispatcher.dispatch` the story service uses.
    Measured 2026-08-16: the hub's qwen2.5:7b was cold (`tier: cold, warm_boot_ms: 120000`)
    and a bare dispatch returns success=False, so this build DEFERRED and wrote nothing.
    On a weekly cadence against a frequently-cold 7B that is not a graceful degradation —
    it is a profile that never gets built, while every cycle reports a tidy "deferred".

    `queued_dispatch_text` (KB mistake #276153) runs inline when the model is warm on ANY
    node and otherwise polls `dispatch_pending_queue` until `model_dispatch_worker` drains
    it — so a cold model becomes a WAIT instead of a silent no-op. Background/scheduler
    callers only: it blocks (ADR-013, module-work-pattern.md).
    """
    from services.cluster_dispatch import queued_dispatch_text

    return queued_dispatch_text


def _scrub_factual(value):
    """Drop descriptors carrying figures — see constraint 1. Recurses into lists."""
    if isinstance(value, str):
        return None if _FACTUAL_RE.search(value) else value.strip() or None
    if isinstance(value, list):
        out = [v for v in (_scrub_factual(x) for x in value) if v]
        return out or None
    return None


def coerce_style_guide(raw):
    """Whitelist keys + scrub figures. Pure; returns {} when nothing usable survives."""
    if isinstance(raw, str):
        raw = parse_json_loose(raw)
    if not isinstance(raw, dict):
        return {}
    if not any(k in raw for k in _STYLE_KEYS):
        # Models sometimes wrap the guide one level deep ({"style_guide": {...}},
        # {"data": {...}}). Descend a single benign wrapper; never recurse further —
        # a payload that isn't the guide one level down isn't the guide at all.
        inner_dicts = [v for v in raw.values() if isinstance(v, dict)]
        if len(inner_dicts) == 1:
            raw = inner_dicts[0]
    out = {}
    for key in _STYLE_KEYS:
        cleaned = _scrub_factual(raw.get(key))
        if cleaned:
            out[key] = cleaned
    return out


def parse_json_loose(text):
    """Parse model JSON that may be fence-wrapped or prose-padded (mirrors wtf's
    `_parse_llm_json` — a local model routinely wraps JSON in ```json fences)."""
    if not text:
        return None
    s = str(text).strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    start, end = s.find("{"), s.rfind("}")
    if 0 <= start < end:
        try:
            return json.loads(s[start : end + 1])
        except Exception:
            return None
    return None


def resolve_entity_id(owner_id, author_name):
    """The chronicle_entity whose canonical_name EXACTLY matches the author.

    Exact match is deliberate: an ILIKE '%terry%' would match five rows here, and picking
    one by ORDER BY luck would attach the voice profile to an arbitrary duplicate. Returns
    None when there is not exactly one — the caller reports that rather than guessing.
    """
    from database import get_db_cursor

    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT id FROM chronicle_entity WHERE owner_id=%s AND canonical_name=%s ORDER BY id",
            (owner_id, author_name),
        )
        rows = cur.fetchall()
    ids = [(r["id"] if isinstance(r, dict) else r[0]) for r in rows]
    if len(ids) != 1:
        logger.warning("voice profile: %s canonical_name matches for %r (need exactly 1)", len(ids), author_name)
        return None
    return ids[0]


def _round_robin_budget(by_folder, total_budget):
    """Interleave folders under a TOTAL character budget.

    WHY NOT just newest-first: the corpus is ~147k chars against a local 7B's few-thousand
    token window. Taking the head would fill the whole budget with `linkedin/posts` (83 rows,
    the largest and most recent folder) and the model would never see a single hand-written
    comment — producing a confident style guide for one surface while reporting the full
    sample count. Round-robin guarantees every surface is represented before any is doubled.
    """
    queues = {k: list(v) for k, v in by_folder.items() if v}
    out, used = [], 0
    while queues and used < total_budget:
        for folder in list(queues):
            if not queues[folder]:
                del queues[folder]
                continue
            item = queues[folder].pop(0)
            cost = len(item["text"])
            if used + cost > total_budget:
                del queues[folder]
                continue
            out.append(item)
            used += cost
    return out


def gather_samples(owner_id, author_name, per_folder=40, max_chars=1400, total_budget=12000):
    """Authored writing samples, newest first, plus ONLY the latest profile snapshot."""
    from database import get_db_cursor

    samples = []
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            """
            SELECT folder, body_text, sent_at, created_at
              FROM (
                SELECT folder, body_text, sent_at, created_at,
                       row_number() OVER (PARTITION BY folder
                                          ORDER BY COALESCE(sent_at, created_at) DESC) AS rn
                  FROM mailbox_emails
                 WHERE from_addr = %s AND folder = ANY(%s)
                   AND body_text IS NOT NULL AND length(body_text) > 40
              ) t
             WHERE rn <= %s
             ORDER BY COALESCE(sent_at, created_at) DESC
            """,
            (author_name, list(_AUTHORED_FOLDERS), per_folder),
        )
        rows = [dict(r) for r in cur.fetchall()]

        # Constraint 2: the newest profile snapshot only.
        cur.execute(
            "SELECT folder, body_text, sent_at, created_at FROM mailbox_emails "
            "WHERE from_addr=%s AND folder=%s ORDER BY created_at DESC LIMIT 1",
            (author_name, _PROFILE_FOLDER),
        )
        prof = cur.fetchone()
    if prof:
        rows.append(dict(prof))

    by_folder = {}
    for r in rows:
        body = (r.get("body_text") or "").strip()
        if not body:
            continue
        by_folder.setdefault(r.get("folder"), []).append(
            {
                "folder": r.get("folder"),
                "text": body[:max_chars],
                "at": r.get("sent_at") or r.get("created_at"),
            }
        )
    samples = _round_robin_budget(by_folder, total_budget)
    return samples


def _build_prompt(author_name, samples):
    # Instructions go AFTER the samples: a 7B under format=json attends to the
    # tail of a long prompt, and with the task stated up front it regurgitated
    # the samples themselves as {"data": [...]} (2026-08-17, task #5709 rerun).
    # The literal skeleton anchors both the task and the exact key set.
    joined = "\n\n---\n\n".join(f"[{s['folder']}]\n{s['text']}" for s in samples)
    return (
        f"WRITING SAMPLES BY {author_name}:\n{joined}\n\n"
        "=== END OF SAMPLES ===\n\n"
        f"TASK: You are a writing-style analyst. Describe HOW {author_name} writes — his "
        "voice, not what he wrote about. Do NOT summarize, list, or repeat the samples.\n\n"
        "Return ONLY one JSON object exactly in this shape (omit any key you cannot "
        "support from the samples; each value is a short string or list of short strings):\n"
        "{\n"
        '  "tone": ..., "register": ..., "sentence_rhythm": ..., "structure": ...,\n'
        '  "rhetorical_devices": ..., "openers": ..., "closers": ..., "formatting_habits": ...,\n'
        '  "vocabulary": ..., "recurring_themes": ..., "avoid": ...\n'
        "}\n\n"
        "CRITICAL: describe STYLE ONLY. Do NOT include any statistic, dollar amount, "
        "percentage, date, or factual claim from the samples — those are stripped and would "
        "make the profile unusable. Say 'cites specific figures' rather than repeating one."
    )


def upsert_voice_profile(entity_id, style_guide, sample_count, span_start, span_end, model_used):
    from database import get_db_cursor

    from services.time_utils import now_utc

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO chronicle_voice_profile
                (chronicle_entity_id, style_guide, sample_count, span_start, span_end,
                 model_used, updated_at)
            VALUES (%s, %s::jsonb, %s, %s, %s, %s, %s)
            ON CONFLICT (chronicle_entity_id) DO UPDATE SET
                style_guide = EXCLUDED.style_guide,
                sample_count = EXCLUDED.sample_count,
                span_start = EXCLUDED.span_start,
                span_end = EXCLUDED.span_end,
                model_used = EXCLUDED.model_used,
                updated_at = EXCLUDED.updated_at
            RETURNING id
            """,
            (
                entity_id,
                json.dumps(style_guide),
                sample_count,
                span_start,
                span_end,
                model_used,
                now_utc(),
            ),
        )
        row = cur.fetchone()
    return row["id"] if isinstance(row, dict) else (row[0] if row else None)


def run_voice_profile_build(owner_id=4, author_name="Terry Caetano", per_folder=40, min_samples=12, poll_timeout_s=600):
    """Build (or refresh) the authored voice profile. Returns a status dict."""
    entity_id = resolve_entity_id(owner_id, author_name)
    if not entity_id:
        return {"status": "entity_unresolved", "author": author_name, "written": 0}

    samples = gather_samples(owner_id, author_name, per_folder=per_folder)
    if len(samples) < min_samples:
        # Constraint 4 — a thin corpus produces a confident-sounding but weak guide.
        return {"status": "insufficient_samples", "samples": len(samples), "min_samples": min_samples, "written": 0}

    try:
        response = _dispatch_fn()(
            capability=CAPABILITY,
            prompt=_build_prompt(author_name, samples),
            json_mode=True,
            module_id="chronicle_voice",
            local_only=True,
            poll_timeout_s=poll_timeout_s,
        )
    except Exception:
        logger.exception("voice profile dispatch failed for %s", author_name)
        return {"status": "dispatch_error", "samples": len(samples), "written": 0}

    if not response:
        # Hard failure, queued-task failure, or poll timeout — a DEFER, not a fault.
        # Yesterday's guide stays and the next cycle retries.
        return {"status": "dispatch_unavailable", "samples": len(samples), "written": 0}

    guide = coerce_style_guide(response)
    if not guide:
        return {"status": "unusable_response", "samples": len(samples), "written": 0}

    ats = [s["at"] for s in samples if s.get("at")]
    profile_id = upsert_voice_profile(
        entity_id,
        guide,
        len(samples),
        min(ats) if ats else None,
        max(ats) if ats else None,
        # `queued_dispatch_text` returns TEXT, not a DispatchResult, so the model that
        # actually served the work is not reported back here — it may have been drained on
        # any node by model_dispatch_worker. Record the capability rather than guessing a
        # model name that could be wrong; the real per-run model is in task_execution_log.
        f"capability:{CAPABILITY}",
    )
    return {
        "status": "ok",
        "entity_id": entity_id,
        "profile_id": profile_id,
        "samples": len(samples),
        "keys": sorted(guide),
        "written": 1,
    }


def voice_prompt_block(owner_id=4, author_name="Terry Caetano", max_chars=1200):
    """The stored style guide rendered for injection into a drafting prompt.

    Returns "" when no profile exists — callers MUST treat that as "use the existing
    hardcoded voice hints", never as "this person has no voice".
    """
    from database import get_db_cursor

    entity_id = resolve_entity_id(owner_id, author_name)
    if not entity_id:
        return ""
    with get_db_cursor(commit=False) as (conn, cur):
        cur.execute(
            "SELECT style_guide FROM chronicle_voice_profile WHERE chronicle_entity_id=%s",
            (entity_id,),
        )
        row = cur.fetchone()
    if not row:
        return ""
    guide = row["style_guide"] if isinstance(row, dict) else row[0]
    if isinstance(guide, str):
        guide = parse_json_loose(guide)
    # Re-scrub on READ as well as on write: a guide stored before the scrub existed, or
    # hand-edited in the DB, must not reach a prompt carrying figures.
    guide = coerce_style_guide(guide)
    if not guide:
        return ""

    lines = []
    for key in _STYLE_KEYS:
        val = guide.get(key)
        if not val:
            continue
        rendered = "; ".join(val) if isinstance(val, list) else str(val)
        lines.append(f"- {key.replace('_', ' ')}: {rendered}")
    if not lines:
        return ""
    block = "OBSERVED WRITING VOICE (style only — never treat as facts):\n" + "\n".join(lines)
    return block[:max_chars]

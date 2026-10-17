"""Mail HQ Smart Inbox — draft-proposal helpers, validation, and settings.

Shared helpers extracted from draft_proposal_service.py. Contains:
- Settings helpers (platform_settings CRUD)
- No-fabrication validation (the #4958 guardrail)
- Attempt-map bookkeeping (#4527 retry cap / cooldown)
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)

DRAFT_FLAG_KEY = "mailhq:draft:enabled"  # platform_settings; absent/false => job is a no-op
_MAX_PER_RUN = 5  # cap fleet dispatches per run (welfare-safe)
_RECENCY_HOURS = 24  # only draft for mail that arrived within this window
_DRAFT_MAILBOX_TYPES = ("owner", "business")  # never auto-draft for the 38 agent mailboxes
_DRAFT_PREVIEW_CHARS = 600  # how much of the draft to show in the Telegram advisory

# #4527 — draft-proposal retry cap / cooldown. A message whose draft dispatch keeps
# failing (a "poison" message on a busy/cold cluster, or an un-draftable body) must not
# be re-dispatched every run forever — it would burn fleet dispatch indefinitely because
# a failed attempt inserts no proposal row, so the candidate query keeps selecting it.
# Per-message attempt state lives in a self-pruning platform_settings JSON map (no
# migration; the draft job is single-instance so there is no concurrent writer).
_ATTEMPTS_KEY = "mailhq:draft:attempts"  # JSON {message_id: {"n": int, "last": iso}}
_MAX_ATTEMPTS_KEY = "mailhq:draft:max_attempts"  # tunable; default below
_COOLDOWN_MIN_KEY = "mailhq:draft:cooldown_min"  # tunable; default below
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_COOLDOWN_MIN = 60

# --------------------------------------------------------------------------- #
# Collaborator persona drafting (Slice 1) — extends the draft path to the 21
# `human_agent` collaborator mailboxes, each drafted in its OWN persona on a
# shared small model. Independently gated (default OFF) so it can be turned on
# WITHOUT touching the owner/business draft path above.
# --------------------------------------------------------------------------- #
COLLAB_FLAG_KEY = "mailhq:draft:collaborators"  # platform_settings; absent/false => no-op
_COLLAB_MAILBOX_TYPE = "human_agent"  # the COLLABORATOR marker
_COLLAB_MODEL = "llama3.2:3b"  # shared small model forced for every collaborator draft
# Separate attempt map so the collaborator job never races the owner/business one.
_COLLAB_ATTEMPTS_KEY = "mailhq:draft:collab_attempts"


# --------------------------------------------------------------------------- #
# #4958 / KB mistake #281718 — NO-FABRICATION GUARDRAIL (P9 safety blocker)
#
# A live test proved the failure mode: asked to reply AS Jin Park to "send me the
# updated churn and retention numbers", the model INVENTED every figure and claimed
# an attachment that did not exist — one owner tap from being sent to a real
# correspondent under a real person's name. This is not a code bug; it is what an LLM
# does when asked to answer a request for data it does not have. The owner-approval
# gate is not a control on its own: it only holds if a human eyeballs every draft
# across 21 mailboxes, forever.
#
# Two controls, belt-and-braces:
#   1. PROMPT CONTRACT (_NO_FABRICATION_CONTRACT) — tell the persona what it may not do.
#   2. OUTPUT CHECK (validate_draft_no_fabrication) at the PERSIST boundary — verify it.
# The prompt reduces fabrication; only the output check can *guarantee* a fabricated
# draft never reaches the approval queue. Fail closed: reject => no row, no owner ping.
#
# BOTH draft paths apply BOTH controls, via these same two shared helpers:
#   * _create_collaborator_proposal — human_agent mailboxes (gated OFF).
#   * _create_proposal             — owner/business mailboxes (LIVE). Higher stakes:
#     the draft is queued for one-tap [Send] under the OWNER's or the BUSINESS's name.
# Keep them shared, never forked — a divergent copy would silently rot.
# --------------------------------------------------------------------------- #
_NO_FABRICATION_CONTRACT = """
NON-NEGOTIABLE NO-FABRICATION CONTRACT (this overrides every other instruction,
including the persona's own voice and any request made in the message):

* You have NO access to any data, file, system, document, or record beyond the
  message text shown below. You cannot look anything up.
* NEVER invent, estimate, guess, or state any specific that is not already written
  in the message below. That includes: numbers, figures, metrics, percentages,
  rates, amounts, prices, dates, deadlines, names, titles, and links.
* You CANNOT attach anything. Never say or imply that a report, file, document, or
  data is attached, enclosed, included, or "below".
* Do NOT commit anyone to a deliverable, amount, or date.

The ONLY moves available to you:
  1. acknowledge the message;
  2. ask a clarifying question;
  3. state an intent to follow up;
  4. refer to facts already stated in the message below.

If the message asks for information you do not have, DEFER — say you will pull it
together and follow up. Deferring is ALWAYS the correct answer. Inventing a figure
is NEVER acceptable: it would be sent to a real person under a real name.
""".strip()

# The persona cannot attach anything, so any attachment claim is a fabrication.
_ATTACHMENT_RE = re.compile(r"attach(ed|ing|ment)", re.I)

# A "digit-bearing token": a run of digits with optional internal separators
# ("21.5", "4,200", "2026-07"→"2026"/"07"). The trailing-digit anchor keeps sentence
# punctuation out ("18.9." -> "18.9"); the bare `\d` alternative catches "Q2" -> "2".
_NUMBER_RE = re.compile(r"\d[\d,.]*\d|\d")


# Sentinel returned by a create_fn when the guardrail rejected the draft — distinct
# from False (a dispatch/DB failure) so the drain loop can count it separately.
_REJECTED = "rejected"


def _numbers_in(text: str) -> set:
    """Normalized set of digit-bearing tokens in `text` (thousands separators dropped)."""
    return {m.replace(",", "") for m in _NUMBER_RE.findall(text or "")}


def _inbound_text(c: dict) -> str:
    """FULL inbound thread text (subject + body) a draft is allowed to draw facts from."""
    return "\n".join(str(c.get(k) or "") for k in ("subject", "body_text", "body_preview"))


def validate_draft_no_fabrication(draft: str, inbound_text: str, allowed_facts_text: str = ""):
    """Reject a draft that fabricates. Returns ``(ok: bool, reason: str | None)``.

    The rule is deliberately blunt, because the cost is asymmetric: a wrongly-rejected
    draft costs one retry, while a wrongly-accepted one puts invented business data in
    a real person's mouth, in front of a real correspondent.

    Rejects when the draft:
      (a) claims an attachment — the persona cannot attach anything, so any
          attached/attaching/attachment claim is false by construction; or
      (b) introduces ANY digit-bearing token that does not appear in the inbound
          thread text (subject + body). If the correspondent wrote the figure, the
          persona may restate it; if not, the persona cannot know it.

    False positives are accepted by design. A bare year, an ordinal or a "1./2." list
    marker in the draft will be rejected unless that digit is in the thread — that is
    the intended reading of "any digit-bearing token", and the prompt contract steers
    the model away from those constructions anyway. Rejection is non-destructive: no
    row is written, the message stays a candidate, and the existing retry/cooldown
    cap (#4527) means one stubborn message cannot burn the fleet.

    Reusable + side-effect free: takes plain strings so EITHER draft path (collaborator
    or owner/business) can call it. Pass the FULL inbound text, not the truncated
    prompt snippet — a figure quoted beyond the snippet cutoff is still the
    correspondent's own figure, and clipping it would cause a false rejection.

    ``allowed_facts_text`` is an optional SECOND allowed-facts source (default "" =>
    prior behavior). The collaborator path passes the persona's active curated facts, so
    a figure the owner curated as citable is not treated as invention. Pure invention —
    a figure in neither the thread nor the facts — still fails closed.
    """
    body = (draft or "").strip()
    if not body:
        return False, "empty draft"

    m = _ATTACHMENT_RE.search(body)
    if m:
        return False, f"claims an attachment ({m.group(0)!r}) — the persona cannot attach anything"

    invented = sorted(_numbers_in(body) - _numbers_in(inbound_text) - _numbers_in(allowed_facts_text))
    if invented:
        return False, "introduces figures absent from the inbound thread or curated facts: " + ", ".join(invented)

    return True, None


def _collaborators_enabled() -> bool:
    from .mailhq_settings import is_enabled

    return is_enabled(COLLAB_FLAG_KEY)


def _setting(key: str, default: str | None = None) -> str | None:
    from database import get_db_cursor

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT value FROM platform_settings WHERE key = %s", (key,))
            row = cur.fetchone()
    except Exception as exc:
        logger.debug("[mailhq-draft] setting lookup failed for %s: %s", key, exc)
        return default
    if not row:
        return default
    return row["value"] if isinstance(row, dict) else row[0]


def _draft_enabled() -> bool:
    return str(_setting(DRAFT_FLAG_KEY, "false") or "false").strip().lower() in ("1", "true", "on", "yes")


def _set_setting(key: str, value: str) -> None:
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO platform_settings (key, value) VALUES (%s, %s)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
            (key, value),
        )


def _int_setting(key: str, default: int) -> int:
    try:
        return int(str(_setting(key, default)).strip())
    except (ValueError, TypeError):
        return default


def _load_attempts(key: str = _ATTEMPTS_KEY) -> dict:
    """Load the per-message draft-attempt map from platform_settings (best-effort)."""
    raw = _setting(key, "") or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _save_attempts(attempts: dict, key: str = _ATTEMPTS_KEY) -> None:
    try:
        _set_setting(key, json.dumps(attempts))
    except Exception as exc:  # never let bookkeeping break the job
        logger.debug("[mailhq-draft] could not persist attempts map: %s", exc)


def _parse_iso(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except (ValueError, TypeError):
        return None

"""Mail HQ Smart Inbox — Slices 3 + 4: agent-drafted, approve-to-send proposals.

Slice 3 (background job `run_mailhq_draft_proposals`): for newly-triaged
**action-priority** owner/business mail with no existing proposal, dispatch
R.E.S.O.L.V.E. (DHQ `capability='support'`, local fleet) to draft a reply, then
persist the proposal as an `autonomy_approval_queue` row (`action_type='email_reply'`)
and ping the owner via A.R.C.H.I.E. on Telegram with Approve / Cancel buttons.

Slice 4 executor (`execute_email_reply`): sends the drafted reply via the shared
`send_service.send_email_via_stalwart`. Called from BOTH the Telegram approve button
(`telegram_gateway._email_callback` action `replysend`) and the DHQ web Approvals tab
(`approvals_routes._approve_autonomy`). Idempotent — a double-tap cannot double-send.

Guardrails (mailhq-smart-inbox-design.md): nothing sends without the owner's tap; all
inference via DHQ dispatch (local fleet); A.R.C.H.I.E. is the sole outbound voice; the
draft job is gated OFF by default (`platform_settings mailhq:draft:enabled`) until the
send executor has been safety-tested.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

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


def validate_draft_no_fabrication(draft: str, inbound_text: str):
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
    """
    body = (draft or "").strip()
    if not body:
        return False, "empty draft"

    m = _ATTACHMENT_RE.search(body)
    if m:
        return False, f"claims an attachment ({m.group(0)!r}) — the persona cannot attach anything"

    invented = sorted(_numbers_in(body) - _numbers_in(inbound_text))
    if invented:
        return False, "introduces figures absent from the inbound thread: " + ", ".join(invented)

    return True, None


def _collaborators_enabled() -> bool:
    return str(_setting(COLLAB_FLAG_KEY, "false") or "false").strip().lower() in ("1", "true", "on", "yes")


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


# --------------------------------------------------------------------------- #
# Slice 3 — background draft-proposal job
# --------------------------------------------------------------------------- #
def run_mailhq_draft_proposals() -> dict:
    """Scheduled job: create approve-to-send proposals for new action-priority mail.

    Returns a small summary dict for the job log. Fully isolated per message — one
    bad dispatch never aborts the batch.
    """
    if not _draft_enabled():
        return {"skipped": True, "reason": f"{DRAFT_FLAG_KEY} is off"}

    from database import get_db_cursor
    from services.time_utils import now_utc

    cutoff = now_utc() - timedelta(hours=_RECENCY_HOURS)
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT m.id, m.subject, m.from_address, m.body_text, m.body_preview,
                      m.mailbox_id, m.thread_id, m.message_id AS rfc_message_id,
                      mb.address AS mailbox_address, mb.mailbox_type,
                      mb.display_name AS mailbox_name
                 FROM email_messages m
                 JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                WHERE m.ai_priority = 'action'
                  AND mb.mailbox_type = ANY(%s)
                  AND m.received_at >= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM autonomy_approval_queue q
                       WHERE q.action_type = 'email_reply'
                         AND q.action_data->>'message_id' = m.id::text
                  )
                  -- Never auto-draft a reply to one of OUR OWN mailboxes: replying to
                  -- self re-syncs as new action mail → another proposal → reply loop.
                  AND lower(m.from_address) NOT IN (
                      SELECT lower(address) FROM email_mailboxes WHERE provisioned = TRUE
                  )
                  -- Skip no-reply / automated senders — a drafted reply is pointless.
                  AND lower(coalesce(m.from_address, '')) !~ '(no-?reply|do-?not-?reply|mailer-daemon|postmaster)@'
                ORDER BY m.received_at DESC
                LIMIT %s""",
            (list(_DRAFT_MAILBOX_TYPES), cutoff, _MAX_PER_RUN),
        )
        candidates = [dict(r) for r in cur.fetchall()]

    # #4527 — retry cap / cooldown (poison-message guard), plus the #4958 rejected tally:
    # both live in the shared drain loop, so this path and the collaborator path can
    # never drift apart. NOTE `_process_candidates` tests `ok is True` — required, since
    # a `_REJECTED` return is a truthy string and a plain truth-test would miscount a
    # rejected (hallucinated) draft as created.
    summary = _process_candidates(candidates, _create_proposal, _ATTEMPTS_KEY, log_prefix="[mailhq-draft]")

    if candidates or summary["capped"] or summary["cooling"]:
        logger.info(
            "[mailhq-draft] %d candidate(s) -> %d created, %d capped, %d cooling, %d rejected",
            len(candidates),
            summary["created"],
            summary["capped"],
            summary["cooling"],
            summary.get("rejected", 0),
        )
    return {"candidates": len(candidates), **summary}


def _create_proposal(c: dict) -> bool:
    """Draft a reply for one message and enqueue an approve-to-send proposal."""
    from psycopg2.extras import Json

    from database import get_db_cursor

    from .fleet_dispatch import queued_dispatch_text

    body_snippet = (c.get("body_text") or c.get("body_preview") or "")[:1000]
    prompt = (
        "Draft a concise, professional email reply to the following message.\n\n"
        f"{_NO_FABRICATION_CONTRACT}\n\n"
        f"Mailbox: {c.get('mailbox_name')}\n"
        f"From: {c.get('from_address')}\n"
        f"Subject: {c.get('subject')}\n"
        f"Message:\n{body_snippet}\n\n"
        "Write only the reply body text — no subject line, no greeting header, "
        "no 'Here is a draft' preamble. Start directly with the reply content."
    )

    # Queue-aware dispatch: waits for a free R.E.S.O.L.V.E. agent (cold-load queue)
    # rather than failing synchronously on a busy/small cluster. (`local_only` defaults
    # True in fleet_dispatch — drafting never leaves the local fleet.)
    draft = queued_dispatch_text(capability="support", prompt=prompt)
    if not draft:
        logger.warning("[mailhq-draft] draft dispatch failed/empty for msg=%s", c.get("id"))
        return False
    draft = draft.strip()

    # Control 2 (#4958) — HARD OUTPUT CHECK, FAIL CLOSED. The prompt contract above is a
    # request; this is the guarantee. Stakes are HIGHER here than on the collaborator
    # path: this one is LIVE (`mailhq:draft:enabled`) and queues one-tap [Send] drafts
    # under the OWNER's or the BUSINESS's name. Checked against the FULL inbound text
    # (not the 1000-char prompt snippet) so a figure the correspondent quoted late in a
    # long mail is still recognised as theirs. A rejected draft writes NO approval row
    # and does NOT ping the owner.
    ok, reason = validate_draft_no_fabrication(draft, _inbound_text(c))
    if not ok:
        logger.warning(
            "[mailhq-draft] draft REJECTED (no-fabrication) msg=%s mailbox=%s: %s",
            c.get("id"),
            c.get("mailbox_address"),
            reason,
        )
        return _REJECTED

    agent = "R.E.S.O.L.V.E."  # capability='support' routes to R.E.S.O.L.V.E.

    subject = (c.get("subject") or "").strip() or "(no subject)"
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    action_data = {
        "message_id": c["id"],
        "mailbox_id": c["mailbox_id"],
        "from_address": c["mailbox_address"],  # reply FROM our mailbox
        "to_address": c["from_address"],  # TO the original sender
        "subject": reply_subject,
        "in_reply_to": c.get("rfc_message_id"),
        "thread_id": c.get("thread_id"),
        "draft_reply": draft,
        "agent": agent,
        "original_subject": subject,
    }

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO autonomy_approval_queue
                   (action_type, action_data, tier, status, priority, requested_by, reason)
               VALUES ('email_reply', %s, 2, 'pending', 5, 'mailhq', %s)
               RETURNING id""",
            (Json(action_data), f"Draft reply to {c['from_address']} re: {subject[:80]}"),
        )
        qrow = cur.fetchone()
    queue_id = qrow["id"] if isinstance(qrow, dict) else qrow[0]

    _send_proposal_buttons(queue_id, c, draft, agent)
    return True


# --------------------------------------------------------------------------- #
# Slice 1 — collaborator persona draft job (human_agent mailboxes)
# --------------------------------------------------------------------------- #
def _process_candidates(candidates: list, create_fn, attempts_key: str, *, log_prefix: str = "[mailhq-collab]") -> dict:
    """Shared retry-cap/cooldown drain loop — used by BOTH draft jobs.

    Parameterised on the attempt-map key + the per-candidate create function, so the two
    producers (owner/business and collaborator) share one poison-message guard and one
    counter shape instead of reimplementing (or racing) each other. Each job passes its
    own ``attempts_key``, so they never share attempt state.
    Returns ``{"created", "capped", "cooling", "rejected"}``.

    ``create_fn`` returns ``True`` (created), ``_REJECTED`` (the #4958 no-fabrication
    guardrail dropped the draft) or falsey (dispatch/DB failure). A guardrail rejection
    counts as an attempt on purpose: drafting is stochastic, so a re-draft may well
    comply — and if it never does, the existing retry cap (#4527) stops the retries.
    """
    from services.time_utils import now_utc

    attempts = _load_attempts(attempts_key)
    max_attempts = _int_setting(_MAX_ATTEMPTS_KEY, _DEFAULT_MAX_ATTEMPTS)
    cooldown = timedelta(minutes=_int_setting(_COOLDOWN_MIN_KEY, _DEFAULT_COOLDOWN_MIN))
    now = now_utc()

    created = capped = cooling = rejected = 0
    for c in candidates:
        mid = str(c.get("id"))
        rec = attempts.get(mid)
        if rec:
            if int(rec.get("n", 0)) >= max_attempts:
                capped += 1
                continue  # poison message — give up until it ages out of the window
            last = _parse_iso(rec.get("last"))
            if last and (now - last) < cooldown:
                cooling += 1
                continue  # still cooling down from the last failed attempt
        try:
            ok = create_fn(c)
        except Exception as exc:
            logger.error("%s proposal failed for msg=%s: %s", log_prefix, c.get("id"), exc)
            ok = False
        if ok is True:
            created += 1
            attempts.pop(mid, None)
        else:
            if ok == _REJECTED:
                rejected += 1
            attempts[mid] = {"n": int((rec or {}).get("n", 0)) + 1, "last": now.isoformat()}

    # Prune entries past the recency window so the attempts map can't grow unbounded.
    horizon = now - timedelta(hours=_RECENCY_HOURS)
    attempts = {k: v for k, v in attempts.items() if (_parse_iso(v.get("last")) or now) >= horizon}
    _save_attempts(attempts, attempts_key)
    return {"created": created, "capped": capped, "cooling": cooling, "rejected": rejected}


def run_mailhq_collaborator_drafts() -> dict:
    """Scheduled job: persona-voiced approve-to-send drafts for collaborator mail.

    Extends the draft path to ``mailbox_type='human_agent'`` mailboxes. Each
    action-priority inbound is drafted in ITS OWN collaborator's voice (their
    ``agents.system_prompt``) on the shared small model ``llama3.2:3b``, then queued
    into the SAME ``autonomy_approval_queue`` (`action_type='email_reply'`) gate the
    owner already approves. Independently gated (default OFF); a no-op until enabled.
    """
    if not _collaborators_enabled():
        return {"skipped": True, "reason": f"{COLLAB_FLAG_KEY} is off"}

    from database import get_db_cursor
    from services.time_utils import now_utc

    cutoff = now_utc() - timedelta(hours=_RECENCY_HOURS)
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT m.id, m.subject, m.from_address, m.body_text, m.body_preview,
                      m.mailbox_id, m.thread_id, m.message_id AS rfc_message_id,
                      mb.address AS mailbox_address, mb.mailbox_type,
                      mb.display_name AS mailbox_name,
                      mb.owner_agent_id AS collaborator_agent_id,
                      COALESCE(a.display_name, a.name) AS collaborator_name,
                      a.system_prompt AS collaborator_system_prompt
                 FROM email_messages m
                 JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                 JOIN agents a ON a.id = mb.owner_agent_id
                WHERE m.ai_priority = 'action'
                  AND mb.mailbox_type = %s
                  AND m.received_at >= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM autonomy_approval_queue q
                       WHERE q.action_type = 'email_reply'
                         AND q.action_data->>'message_id' = m.id::text
                  )
                  -- Never auto-draft a reply to one of OUR OWN mailboxes (reply loop).
                  AND lower(m.from_address) NOT IN (
                      SELECT lower(address) FROM email_mailboxes WHERE provisioned = TRUE
                  )
                  -- Skip no-reply / automated senders — a drafted reply is pointless.
                  AND lower(coalesce(m.from_address, '')) !~ '(no-?reply|do-?not-?reply|mailer-daemon|postmaster)@'
                ORDER BY m.received_at DESC
                LIMIT %s""",
            (_COLLAB_MAILBOX_TYPE, cutoff, _MAX_PER_RUN),
        )
        candidates = [dict(r) for r in cur.fetchall()]

    summary = _process_candidates(candidates, _create_collaborator_proposal, _COLLAB_ATTEMPTS_KEY)
    if candidates or summary["capped"] or summary["cooling"]:
        logger.info(
            "[mailhq-collab] %d candidate(s) -> %d created, %d capped, %d cooling, %d rejected",
            len(candidates),
            summary["created"],
            summary["capped"],
            summary["cooling"],
            summary.get("rejected", 0),
        )
    return {"candidates": len(candidates), **summary}


def _create_collaborator_proposal(c: dict) -> bool:
    """Draft a reply for one collaborator-mailbox message and enqueue the proposal.

    The collaborator's ``system_prompt`` IS the drafting system prompt (persona/voice);
    ``model_override='llama3.2:3b'`` + ``local_only=True`` force the shared small model
    on the local fleet regardless of which agent the ``support`` capability routes to.
    The proposal is ATTRIBUTED to the collaborator (name + agent id + mailbox), so the
    owner's approval card shows whose reply it is — not R.E.S.O.L.V.E.
    """
    from psycopg2.extras import Json

    from database import get_db_cursor

    # Cluster-wide, cold-load-tolerant dispatch (supports model_override). NEVER
    # dispatch_json — that masks cold-load queueing and drops the work (KB #276153).
    from services.cluster_dispatch import queued_dispatch_text

    name = (c.get("collaborator_name") or c.get("mailbox_name") or "the mailbox owner").strip()
    system_prompt = (c.get("collaborator_system_prompt") or "").strip() or None
    body_snippet = (c.get("body_text") or c.get("body_preview") or "")[:1000]
    prompt = (
        f"Draft a concise, professional email reply in {name}'s voice to the message below.\n\n"
        f"{_NO_FABRICATION_CONTRACT}\n\n"
        f"Mailbox: {c.get('mailbox_name')} <{c.get('mailbox_address')}>\n"
        f"From: {c.get('from_address')}\n"
        f"Subject: {c.get('subject')}\n"
        f"Message:\n{body_snippet}\n\n"
        "Write only the reply body text — no subject line, no greeting header, "
        "no 'Here is a draft' preamble. Start directly with the reply content."
    )

    draft = queued_dispatch_text(
        capability="support",
        prompt=prompt,
        system_prompt=system_prompt,
        model_override=_COLLAB_MODEL,
        local_only=True,
    )
    if not draft:
        logger.warning("[mailhq-collab] draft dispatch failed/empty for msg=%s", c.get("id"))
        return False
    draft = draft.strip()

    # Control 2 (#4958) — HARD OUTPUT CHECK, FAIL CLOSED. The prompt contract above is
    # a request; this is the guarantee. Checked against the FULL inbound text (not the
    # 1000-char prompt snippet) so a figure the correspondent quoted late in a long mail
    # is still recognised as theirs. A rejected draft writes NO approval row and does NOT
    # ping the owner — a hallucination must never reach a one-tap [Send] button.
    ok, reason = validate_draft_no_fabrication(draft, _inbound_text(c))
    if not ok:
        logger.warning(
            "[mailhq-collab] draft REJECTED (no-fabrication) msg=%s mailbox=%s: %s",
            c.get("id"),
            c.get("mailbox_address"),
            reason,
        )
        return _REJECTED

    agent = name  # attribute the draft to the collaborator, NOT R.E.S.O.L.V.E.

    subject = (c.get("subject") or "").strip() or "(no subject)"
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    action_data = {
        "message_id": c["id"],
        "mailbox_id": c["mailbox_id"],
        "from_address": c["mailbox_address"],  # reply FROM the collaborator's mailbox
        "to_address": c["from_address"],  # TO the original sender
        "subject": reply_subject,
        "in_reply_to": c.get("rfc_message_id"),
        "thread_id": c.get("thread_id"),
        "draft_reply": draft,
        "agent": agent,  # collaborator name -> shown on the approval card
        "collaborator_agent_id": c.get("collaborator_agent_id"),
        "mailbox_type": "human_agent",
        "original_subject": subject,
    }

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO autonomy_approval_queue
                   (action_type, action_data, tier, status, priority, requested_by, reason)
               VALUES ('email_reply', %s, 2, 'pending', 5, 'mailhq', %s)
               RETURNING id""",
            (
                Json(action_data),
                f"Draft reply as {agent} ({c['mailbox_address']}) to {c['from_address']} re: {subject[:80]}",
            ),
        )
        qrow = cur.fetchone()
    queue_id = qrow["id"] if isinstance(qrow, dict) else qrow[0]

    _send_proposal_buttons(queue_id, c, draft, agent)
    return True


def _send_proposal_buttons(queue_id: int, c: dict, draft: str, agent: str) -> None:
    """A.R.C.H.I.E. → Telegram: gist + draft preview + Approve/Cancel buttons.

    Single-token callback actions (`replysend` / `replycancel`) so the gateway's
    `data.split("_", 2)` parser stays correct (a 2-word action would break it).
    """
    try:
        from services.telegram_service import send_with_buttons

        preview = (draft or "").strip()[:_DRAFT_PREVIEW_CHARS]
        title = f"Reply ready · {c.get('mailbox_address')}"
        message = (
            f"From: {(c.get('from_address') or '?')[:120]}\n"
            f"Subject: {(c.get('subject') or '(no subject)')[:160]}\n\n"
            f"{agent} drafted:\n{preview}"
        )
        buttons = [
            {"text": "✅ Send", "callback_data": f"email_replysend_{queue_id}"},
            {"text": "❌ Cancel", "callback_data": f"email_replycancel_{queue_id}"},
        ]
        r = send_with_buttons(
            category="info",
            title=title,
            message=message,
            buttons=buttons,
            source_agent="A.R.C.H.I.E.",
            source_department="Customer Success & Support",
        )
        if not r.get("sent"):
            logger.warning("[mailhq-draft] button advisory not sent (%s) for q=%s", r.get("reason"), queue_id)
        # Store the Telegram message id so approving from the DHQ Approvals tab can
        # clear the phone's live buttons (_approve_autonomy echoes via this id). (#4521)
        mid = r.get("message_id")
        if mid:
            from database import get_db_cursor

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE autonomy_approval_queue SET telegram_message_id = %s WHERE id = %s",
                    (mid, queue_id),
                )
    except Exception as exc:
        logger.error("[mailhq-draft] button advisory failed for q=%s: %s", queue_id, exc)


# --------------------------------------------------------------------------- #
# Slice 4 — approve-to-send executor (shared by Telegram + DHQ web)
# --------------------------------------------------------------------------- #
def execute_email_reply(queue_id: int, approved_by: int | None = None) -> dict:
    """Send the drafted reply for an `email_reply` proposal. Idempotent.

    Atomically claims the row by stamping `executed_at` (only when it is still NULL
    and the row is pending/approved) BEFORE sending, so a second approval tap finds
    nothing to claim and cannot double-send. Marks status `executed` or `failed`.
    Returns {"success": bool, ...}.
    """
    from psycopg2.extras import Json

    from database import get_db_cursor

    # Atomic claim — flip executed_at NULL -> NOW() and record who approved.
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
                  SET executed_at = NOW(), updated_at = NOW(),
                      status = 'approved',
                      approved_by = COALESCE(approved_by, %s),
                      approved_at = COALESCE(approved_at, NOW())
                WHERE id = %s
                  AND action_type = 'email_reply'
                  AND executed_at IS NULL
                  AND status IN ('pending', 'approved')
                RETURNING action_data""",
            (approved_by, queue_id),
        )
        claimed = cur.fetchone()

    if not claimed:
        # Already executing/executed, rejected/expired, missing, or wrong type.
        return {"success": False, "error": "not claimable (already handled, rejected, or missing)"}

    ad = claimed["action_data"] if isinstance(claimed, dict) else claimed[0]
    ad = ad if isinstance(ad, dict) else json.loads(ad or "{}")

    from .send_service import send_email_via_stalwart

    send_res = send_email_via_stalwart(
        from_address=ad.get("from_address"),
        to_address=ad.get("to_address"),
        subject=ad.get("subject"),
        body=ad.get("draft_reply") or "",
        in_reply_to=ad.get("in_reply_to"),
    )
    ok = bool(send_res.get("success"))

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
                  SET status = %s, execution_result = %s, updated_at = NOW()
                WHERE id = %s""",
            ("executed" if ok else "failed", Json(send_res), queue_id),
        )

    if ok:
        logger.info("[mailhq-draft] sent reply for q=%s -> %s", queue_id, ad.get("to_address"))
    else:
        logger.error("[mailhq-draft] send FAILED for q=%s: %s", queue_id, send_res.get("error"))
    return {"success": ok, "result": send_res, "to": ad.get("to_address")}


def reject_email_reply(queue_id: int, rejected_by: int | None = None) -> dict:
    """Cancel an `email_reply` proposal (owner tapped Cancel). Idempotent."""
    from database import get_db_cursor

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """UPDATE autonomy_approval_queue
                  SET status = 'rejected',
                      rejected_reason = 'Cancelled by owner',
                      approved_by = COALESCE(approved_by, %s),
                      updated_at = NOW()
                WHERE id = %s
                  AND action_type = 'email_reply'
                  AND status = 'pending'
                RETURNING id""",
            (rejected_by, queue_id),
        )
        row = cur.fetchone()
    return {"success": bool(row)}

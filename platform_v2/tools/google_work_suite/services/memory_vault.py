"""
Email Memory Vault — Phase 1 (ingest + triage + cache).

Project #377. Design: .claude/plans/email-history-ingestion-design.md

Three scheduled fleet workers (registered in ai_bridge/agent_loop.py), all gated
behind the work-control flag ``memory_vault`` (DEFAULT OFF — nothing runs until the
owner re-auths the Google accounts and enables it from the Autonomy tab):

  gmail_full_ingest_crawler()    — every 6h, NO inference. Cheap list-only enumeration
                                   of EVERY message id/threadId into profile_ingest_ledger
                                   (state='new'), advancing a resumable per-account cursor.
  gmail_profile_triage_worker()  — every 5m, max_instances=1. Claims 'new' ledger rows,
                                   fetches metadata, caches to google_email_cache, and runs
                                   the 3-gate triage (Gmail labels -> sender heuristics ->
                                   optional 1.5B classify) to mark important / bulk.
  gmail_profile_progress_observer() — every 30m, NO inference. Per-account ledger state
                                   counts + enumeration progress; best-effort Telegram on
                                   an error spike.

Phase 1 does NOT read message bodies or run extraction — that is Phase 2. The owner
PII / privacy-floor decision is therefore not required until Phase 2.
"""

import hashlib
import logging

from database import get_db_cursor

from .gmail_service import _extract_headers, list_all_message_ids
from .google_api_service import get_gmail_client

logger = logging.getLogger(__name__)

# Work-control flags (services.work_control_service / platform_settings).
_FLAG_MASTER = "memory_vault"  # master kill-switch (default OFF)
_FLAG_GATE3 = (
    "memory_vault_gate3"  # enable the 1.5B classify gate (default OFF -> high recall)
)

# Throughput dials (tunable without code change later via a settings row).
_ENUM_PAGE_BUDGET = 20  # list pages per crawler run (~20 * 500 = 10000 ids/run)
_ENUM_PAGE_SIZE = 500
_TRIAGE_BATCH = (
    300  # messages metadata-fetched + triaged per run (interleaved across accounts)
)

# GATE 1 — Gmail's own categorisation; free bulk signal.
_BULK_LABELS = {
    "CATEGORY_PROMOTIONS",
    "CATEGORY_SOCIAL",
    "CATEGORY_UPDATES",
    "CATEGORY_FORUMS",
    "SPAM",
}

# GATE 2 — sender heuristics. kytranempowerment@ is Kytran's Google-SSO hub
# (LinkedIn/Facebook/social logins) so it floods with machine noise; these filters
# keep the 7B extraction (Phase 2) off that noise. (Owner decision 2026-06-09.)
_BULK_SENDER_SUBSTR = (
    "noreply",
    "no-reply",
    "no_reply",
    "donotreply",
    "do-not-reply",
    "notifications@",
    "notification@",
    "mailer-daemon",
    "postmaster@",
    "newsletter",
    "automated@",
    "updates@",
    "info@meetup",
)
_BULK_SENDER_DOMAINS = (
    "linkedin.com",
    "facebook.com",
    "facebookmail.com",
    "accounts.google.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "mail.instagram.com",
    "youtube.com",
    "pinterest.com",
    "tiktok.com",
    "reddit.com",
    "quora.com",
    "medium.com",
    "google.com",  # security alerts / login notices
)

# Owner account-context tags (unified profile, account-tagged — Owner decision 2026-06-09).
_ACCOUNT_CONTEXT = {
    "terry.p.caetano@gmail.com": "personal",
    "kytranempowerment@gmail.com": "business",
}


# ---------------------------------------------------------------------------
# Flag helpers
# ---------------------------------------------------------------------------
def _enabled(flag, default=False):
    try:
        from services.work_control_service import is_enabled

        return is_enabled(flag, default=default)
    except Exception as exc:  # work_control unavailable -> stay OFF (fail safe)
        logger.debug("memory_vault: work_control unavailable for %s: %s", flag, exc)
        return default


def _accounts():
    """All connected Google accounts: [(id, email, context), ...]."""
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT id, email FROM google_accounts ORDER BY id")
        rows = cur.fetchall()
    out = []
    for r in rows:
        email = (r["email"] or "").lower()
        out.append((r["id"], email, _ACCOUNT_CONTEXT.get(email, "personal")))
    return out


# ---------------------------------------------------------------------------
# Worker 1 — crawler (every 6h, no inference)
# ---------------------------------------------------------------------------
def gmail_full_ingest_crawler():
    """List-only enumeration of all message ids into the ledger; resumable per account."""
    if not _enabled(_FLAG_MASTER):
        return {"skipped": "memory_vault disabled"}

    summary = {}
    for account_id, email, context in _accounts():
        try:
            summary[email] = _crawl_account(account_id, context)
        except Exception as exc:
            logger.error(
                "memory_vault crawler failed for account %s: %s", account_id, exc
            )
            summary[email] = {"error": str(exc)}
    logger.info("memory_vault crawler run: %s", summary)
    return summary


def _crawl_account(account_id, context):
    # Load / init cursor
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO profile_account_cursor (account_id) VALUES (%s) "
            "ON CONFLICT (account_id) DO NOTHING",
            (account_id,),
        )
        cur.execute(
            "SELECT last_page_token, enumeration_complete, total_enumerated "
            "FROM profile_account_cursor WHERE account_id = %s",
            (account_id,),
        )
        cur_row = cur.fetchone()

    if cur_row["enumeration_complete"]:
        return {"enumeration_complete": True, "total": cur_row["total_enumerated"]}

    page_token = cur_row["last_page_token"]
    total = cur_row["total_enumerated"]
    inserted = 0

    for _page in range(_ENUM_PAGE_BUDGET):
        stubs, next_token = list_all_message_ids(
            account_id, page_token=page_token, max_per_page=_ENUM_PAGE_SIZE
        )
        if stubs:
            with get_db_cursor(commit=True) as (conn, cur):
                for s in stubs:
                    cur.execute(
                        "INSERT INTO profile_ingest_ledger "
                        "(account_id, gmail_id, thread_id, account_context, state) "
                        "VALUES (%s, %s, %s, %s, 'new') "
                        "ON CONFLICT (account_id, gmail_id) DO NOTHING",
                        (account_id, s["id"], s.get("threadId"), context),
                    )
                    inserted += cur.rowcount
                total += len(stubs)
        page_token = next_token
        if not next_token:
            break

    complete = page_token is None
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE profile_account_cursor SET last_page_token = %s, "
            "enumeration_complete = %s, total_enumerated = %s, "
            "last_run_at = now(), updated_at = now() WHERE account_id = %s",
            (page_token, complete, total, account_id),
        )
    return {
        "enumeration_complete": complete,
        "new_ledger_rows": inserted,
        "total_seen": total,
    }


# ---------------------------------------------------------------------------
# Worker 2 — triage (every 5m, max_instances=1)
# ---------------------------------------------------------------------------
def gmail_profile_triage_worker():
    """Fetch metadata for 'new' ledger rows, cache them, and 3-gate triage to important/bulk."""
    if not _enabled(_FLAG_MASTER):
        return {"skipped": "memory_vault disabled"}

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, account_id, gmail_id, thread_id, account_context FROM ("
            "  SELECT id, account_id, gmail_id, thread_id, account_context, "
            "         ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY id) AS rn "
            "  FROM profile_ingest_ledger WHERE state = 'new'"
            ") t ORDER BY rn, account_id LIMIT %s",
            (_TRIAGE_BATCH,),
        )
        rows = cur.fetchall()

    if not rows:
        return {"triaged": 0}

    gate3 = _enabled(_FLAG_GATE3)
    counts = {"important": 0, "bulk": 0, "error": 0}
    # cache one gmail client per account across the batch
    clients = {}

    for row in rows:
        acct = row["account_id"]
        try:
            service = clients.get(acct)
            if service is None:
                service = clients[acct] = get_gmail_client(acct)
            meta = _fetch_and_cache(service, acct, row["gmail_id"])
            state, reason, is_sent = _triage(meta, gate3)
            chash = hashlib.md5(
                f"{meta['sender']}|{meta['subject']}|{meta['internal_date']}".encode(
                    "utf-8"
                )
            ).hexdigest()
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE profile_ingest_ledger SET state = %s, triage_reason = %s, "
                    "is_sent = %s, content_hash = %s, size_bytes = %s, triaged_at = now() "
                    "WHERE id = %s",
                    (state, reason, is_sent, chash, meta.get("size_bytes"), row["id"]),
                )
            counts[state.replace("triaged_", "")] = (
                counts.get(state.replace("triaged_", ""), 0) + 1
            )
        except Exception as exc:
            logger.warning(
                "memory_vault triage failed for ledger %s: %s", row["id"], exc
            )
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE profile_ingest_ledger SET state = 'error', error = %s, "
                    "triaged_at = now() WHERE id = %s",
                    (str(exc)[:500], row["id"]),
                )
            counts["error"] += 1

    logger.info("memory_vault triage run: %s", counts)
    return {"triaged": len(rows), **counts}


def _fetch_and_cache(service, account_id, gmail_id):
    """Fetch message metadata, upsert google_email_cache, return the bits triage needs."""
    import psycopg2.extras

    msg = (
        service.users()
        .messages()
        .get(
            userId="me",
            id=gmail_id,
            format="metadata",
            metadataHeaders=["Subject", "From", "To", "Date"],
        )
        .execute()
    )
    headers = _extract_headers(msg.get("payload", {}).get("headers", []))
    labels = msg.get("labelIds", []) or []
    is_read = "UNREAD" not in labels
    subject = headers.get("subject", "(no subject)")
    sender = headers.get("from", "")
    to_list = [r.strip() for r in headers.get("to", "").split(",") if r.strip()]
    internal_date = msg.get("internalDate", "0")

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """
            INSERT INTO google_email_cache
                (account_id, gmail_id, thread_id, subject, sender,
                 recipients, received_at, labels, has_attachments, is_read)
            VALUES (%s, %s, %s, %s, %s, %s,
                    TO_TIMESTAMP(%s::BIGINT / 1000), %s, %s, %s)
            ON CONFLICT (account_id, gmail_id) DO UPDATE SET
                labels  = EXCLUDED.labels,
                is_read = EXCLUDED.is_read
            """,
            (
                account_id,
                gmail_id,
                msg.get("threadId"),
                subject[:200],
                sender[:200],
                psycopg2.extras.Json(to_list),
                internal_date,
                psycopg2.extras.Json(labels),
                False,
                is_read,
            ),
        )

    return {
        "labels": labels,
        "sender": sender,
        "subject": subject,
        "internal_date": internal_date,
        "size_bytes": msg.get("sizeEstimate"),
    }


def _triage(meta, gate3_enabled):
    """Return (state, reason, is_sent). High-recall: ambiguous -> important unless GATE 3 on."""
    labels = set(meta["labels"])
    sender = (meta["sender"] or "").lower()
    is_sent = "SENT" in labels

    # Kytran's own sent mail is the gold voice source — always keep.
    if is_sent:
        return "triaged_important", "sent-mail", True
    # Explicit importance markers.
    if "IMPORTANT" in labels or "STARRED" in labels:
        return "triaged_important", "gmail-important-flag", False
    # GATE 1 — Gmail bulk categories.
    bulk_label = labels & _BULK_LABELS
    if bulk_label:
        return "triaged_bulk", f"gmail-label:{sorted(bulk_label)[0]}", False
    # GATE 2 — sender heuristics (SSO / social / no-reply machine senders).
    if any(s in sender for s in _BULK_SENDER_SUBSTR) or any(
        d in sender for d in _BULK_SENDER_DOMAINS
    ):
        return "triaged_bulk", "sender-heuristic", False
    # GATE 3 — optional cheap classifier for the genuinely ambiguous remainder.
    if gate3_enabled:
        verdict = _classify_importance(meta)
        if verdict == "bulk":
            return "triaged_bulk", "gate3-classify", False
        return "triaged_important", "gate3-classify", False
    # Default: high recall — keep ambiguous mail.
    return "triaged_important", "high-recall-default", False


def _classify_importance(meta):
    """Cheap 1.5B classify on the outpost CPU tier via DHQ. Returns 'important'|'bulk'."""
    try:
        from tools.department_hq.services.department_dispatcher import dispatch

        prompt = (
            "Classify whether this email is personally or professionally important to the "
            "account owner, or just bulk / automated / marketing noise. Reply with ONLY one "
            f"word: important OR bulk.\nFrom: {meta['sender']}\nSubject: {meta['subject']}"
        )
        r = dispatch("classify", prompt, module_id="memory_vault")
        if r and r.success and "bulk" in (r.response or "").strip().lower()[:12]:
            return "bulk"
        return "important"  # default to keep on any ambiguity / failure (high recall)
    except Exception as exc:
        logger.debug("memory_vault gate3 classify failed: %s", exc)
        return "important"


# ---------------------------------------------------------------------------
# Worker 3 — progress observer (every 30m, no inference)
# ---------------------------------------------------------------------------
def gmail_profile_progress_observer():
    if not _enabled(_FLAG_MASTER):
        return {"skipped": "memory_vault disabled"}

    report = {}
    error_total = 0
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT l.account_id, ga.email, l.state, COUNT(*) AS n "
            "FROM profile_ingest_ledger l JOIN google_accounts ga ON ga.id = l.account_id "
            "GROUP BY l.account_id, ga.email, l.state ORDER BY l.account_id"
        )
        for row in cur.fetchall():
            acct = report.setdefault(row["email"], {})
            acct[row["state"]] = row["n"]
            if row["state"] == "error":
                error_total += row["n"]
        cur.execute(
            "SELECT ga.email, c.enumeration_complete, c.total_enumerated "
            "FROM profile_account_cursor c JOIN google_accounts ga ON ga.id = c.account_id"
        )
        for row in cur.fetchall():
            acct = report.setdefault(row["email"], {})
            acct["enumeration_complete"] = row["enumeration_complete"]
            acct["total_enumerated"] = row["total_enumerated"]

    logger.info("memory_vault progress: %s", report)

    if error_total >= 50:
        try:
            from services.telegram_service import send_system

            send_system(
                f"⚠️ Memory Vault: {error_total} ledger rows in error state — check triage worker."
            )
        except Exception as exc:
            logger.debug("memory_vault telegram alert failed: %s", exc)

    return report


# ===========================================================================
# Phase 2 — extraction (LOCAL 7B analyze -> evidence-linked profile_facts + contacts)
# ===========================================================================

_FLAG_EXTRACT = "memory_vault_extract"  # gate Phase-2 extraction (default OFF)
_EXTRACT_BATCH = (
    8  # important emails analyzed per run (7B GPU, interleaved across accounts)
)
_EXTRACT_BODY_CHARS = 6000  # body chars sent to the model (cost cap)

_EXTRACT_SYSTEM = (
    "You are a careful analyst building a private, factual profile of the email account "
    "OWNER from their own mailbox. Extract only what the email actually evidences — never "
    "invent. Respond with STRICT JSON only."
)


def _norm_email(sender):
    """Extract + normalize the address from a 'Name <addr>' From header."""
    s = (sender or "").strip()
    if "<" in s and ">" in s:
        s = s[s.find("<") + 1 : s.find(">")]
    s = s.strip().lower()
    if "@" in s:
        local, _, domain = s.partition("@")
        local = local.split("+", 1)[0]
        s = local + "@" + domain
    return s


def _display_name(sender):
    s = (sender or "").strip()
    if "<" in s:
        name = s[: s.find("<")].strip().strip('"')
        if name:
            return name[:120]
    return _norm_email(sender)[:120]


def gmail_profile_extract_worker():
    """
    Read each important email's body, extract evidence-linked facts via a LOCAL 7B agent
    (capability='analyze', allow_cloud=False), write profile_facts + upsert profile_contacts.
    Interleaved across accounts; gated behind the 'memory_vault_extract' flag.
    Every fact carries source_gmail_id + ledger_id so the profile is traceable, never invented.
    """
    if not _enabled(_FLAG_MASTER):
        return {"skipped": "memory_vault disabled"}
    if not _enabled(_FLAG_EXTRACT):
        return {"skipped": "extract disabled"}

    from .gmail_service import get_email

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, account_id, gmail_id, account_context, owner_id FROM ("
            "  SELECT l.id, l.account_id, l.gmail_id, l.account_context, ga.owner_id, "
            "         ROW_NUMBER() OVER (PARTITION BY l.account_id ORDER BY l.id) AS rn "
            "  FROM profile_ingest_ledger l JOIN google_accounts ga ON ga.id = l.account_id "
            "  WHERE l.state = 'triaged_important'"
            ") t ORDER BY rn, account_id LIMIT %s",
            (_EXTRACT_BATCH,),
        )
        rows = cur.fetchall()

    if not rows:
        return {"extracted": 0}

    counts = {"extracted": 0, "facts": 0, "error": 0}
    for row in rows:
        try:
            full = get_email(row["account_id"], row["gmail_id"])
            facts = _extract_facts(full, row["account_context"])
            n = _store_facts(row, full, facts)
            _upsert_contact(row, full)
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE profile_ingest_ledger SET state = 'extracted', "
                    "extracted_at = now() WHERE id = %s",
                    (row["id"],),
                )
            counts["extracted"] += 1
            counts["facts"] += n
        except Exception as exc:
            logger.warning(
                "memory_vault extract failed for ledger %s: %s", row["id"], exc
            )
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "UPDATE profile_ingest_ledger SET state = 'extract_error', "
                    "error = %s WHERE id = %s",
                    (("extract: " + str(exc))[:500], row["id"]),
                )
            counts["error"] += 1

    logger.info("memory_vault extract run: %s", counts)
    return counts


def _extract_facts(full, context):
    """Dispatch the email body to a LOCAL 7B analyst; return the parsed fact JSON."""
    from tools.department_hq.services.department_dispatcher import dispatch_json

    subject = full.get("subject", "") or ""
    sender = full.get("sender", "") or ""
    body = (full.get("body_plain") or full.get("body_html") or "")[:_EXTRACT_BODY_CHARS]
    prompt = (
        f"Account context: {context}. This email is from the owner's mailbox.\n"
        f"From: {sender}\nSubject: {subject}\n\nBody:\n{body}\n\n"
        "Extract a STRICT JSON object with keys:\n"
        '  "summary": one sentence on what this reveals about the owner or their life,\n'
        '  "people": [{"name": str, "email": str, "relationship": str}],\n'
        '  "orgs": [str],\n'
        '  "commitments": [str]  (promises, tasks, deadlines, plans),\n'
        '  "events": [str]  (things that happened or will happen; include dates if present),\n'
        '  "topics": [str],\n'
        '  "sentiment": one word.\n'
        "Use [] when nothing applies. Extract only what the email evidences; do not invent."
    )
    data = dispatch_json(
        "analyze",
        prompt,
        module_id="memory_vault_extract",
        system_prompt=_EXTRACT_SYSTEM,
        local_only=True,  # hard-pin to local fleet — email content never leaves the cluster
    )
    return data or {}


def _store_facts(row, full, data):
    """Flatten the extracted JSON into evidence-linked profile_facts rows. Returns count."""
    if not isinstance(data, dict):
        return 0
    fact_rows = []  # (fact_type, subject, content)

    summary = data.get("summary")
    if isinstance(summary, str) and summary.strip():
        fact_rows.append(("summary", None, summary.strip()))
    for p in data.get("people") or []:
        if isinstance(p, dict):
            nm = (p.get("name") or p.get("email") or "").strip()
            rel = (p.get("relationship") or "").strip()
            if nm:
                fact_rows.append(
                    ("person", nm[:200], (nm + (" — " + rel if rel else "")).strip())
                )
        elif isinstance(p, str) and p.strip():
            fact_rows.append(("person", p.strip()[:200], p.strip()))
    for key, ftype in (
        ("orgs", "org"),
        ("commitments", "commitment"),
        ("events", "event"),
        ("topics", "topic"),
    ):
        for item in data.get(key) or []:
            if isinstance(item, str) and item.strip():
                fact_rows.append((ftype, None, item.strip()))
    sent = data.get("sentiment")
    if isinstance(sent, str) and sent.strip():
        fact_rows.append(("sentiment", None, sent.strip()[:40]))

    if not fact_rows:
        return 0
    with get_db_cursor(commit=True) as (conn, cur):
        for ftype, subj, content in fact_rows:
            cur.execute(
                "INSERT INTO profile_facts "
                "(owner_id, account_id, ledger_id, source_gmail_id, account_context, "
                " fact_type, subject, content) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    row["owner_id"],
                    row["account_id"],
                    row["id"],
                    row["gmail_id"],
                    row["account_context"],
                    ftype,
                    subj,
                    content[:2000],
                ),
            )
    return len(fact_rows)


def _upsert_contact(row, full):
    """Maintain the per-contact row (counts + last_seen). Relationship/voice = synthesis (2.2)."""
    email = _norm_email(full.get("sender", ""))
    if not email or "@" not in email:
        return
    name = _display_name(full.get("sender", ""))
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "INSERT INTO profile_contacts "
            "(owner_id, email, display_name, account_context, message_count, first_seen, last_seen) "
            "VALUES (%s, %s, %s, %s, 1, now(), now()) "
            "ON CONFLICT (owner_id, email) DO UPDATE SET "
            "  message_count = profile_contacts.message_count + 1, "
            "  last_seen = now(), "
            "  display_name = COALESCE(NULLIF(EXCLUDED.display_name, ''), profile_contacts.display_name), "
            "  updated_at = now()",
            (row["owner_id"], email, name, row["account_context"]),
        )


# ===========================================================================
# Phase 2.2 — synthesis (facts -> owner profile + life timeline) via hub 12B
# ===========================================================================

_SYNTH_FACT_LIMIT = 200  # facts fed to the synthesizer per owner (context cap)
_SYNTH_SYSTEM = (
    "You are building a private profile of a person from facts extracted from THEIR OWN "
    "email mailbox. Use only the facts provided; never invent. Respond with STRICT JSON only."
)


def gmail_profile_synthesis_worker():
    """
    Roll extracted profile_facts into the owner's profile: a 'who is this person' summary,
    a communication-style fingerprint, and a chronological life/work TIMELINE. Runs LOCAL on
    the hub 12B (research_synthesis -> D.A.R.W.I.N.). Writes profile_owner. Every input is a
    real extracted fact (traceable) — the timeline reconstructs, it does not confabulate.
    """
    if not _enabled(_FLAG_MASTER):
        return {"skipped": "memory_vault disabled"}

    from tools.department_hq.services.department_dispatcher import dispatch_json

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT DISTINCT owner_id FROM profile_facts")
        owners = [r["owner_id"] for r in cur.fetchall()]

    if not owners:
        return {"synthesized": 0}

    done = 0
    for owner_id in owners:
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT f.fact_type, f.subject, f.content, "
                    "       to_char(c.received_at, 'YYYY-MM') AS ym "
                    "FROM profile_facts f "
                    "LEFT JOIN google_email_cache c "
                    "  ON c.account_id = f.account_id AND c.gmail_id = f.source_gmail_id "
                    "WHERE f.owner_id = %s "
                    "ORDER BY c.received_at NULLS LAST LIMIT %s",
                    (owner_id, _SYNTH_FACT_LIMIT),
                )
                facts = cur.fetchall()
            if not facts:
                continue
            lines = []
            for f in facts:
                d = ("[" + f["ym"] + "] ") if f["ym"] else ""
                subj = (f["subject"] + ": ") if f["subject"] else ""
                lines.append(f"- {d}({f['fact_type']}) {subj}{f['content']}")
            facts_blob = "\n".join(lines)[:14000]
            prompt = (
                "Facts extracted from the person's own email (dated [YYYY-MM] where known):\n\n"
                + facts_blob
                + "\n\nProduce a STRICT JSON object:\n"
                '  "summary": 2-4 sentences — who this person is (work, life, what matters),\n'
                '  "default_voice": 1-2 sentences — their communication style/tone,\n'
                '  "timeline": [{"date": "YYYY-MM" or "YYYY", "event": str}] — chronological key '
                "life/work events from the dated facts.\n"
                "Use only the facts; do not invent. Keep the timeline to the clearest ~20 events."
            )
            data = dispatch_json(
                "research_synthesis",
                prompt,
                module_id="memory_vault_synth",
                system_prompt=_SYNTH_SYSTEM,
                local_only=True,
            )
            if not isinstance(data, dict):
                continue

            import psycopg2.extras

            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO profile_owner (owner_id, summary, default_voice, timeline, updated_at) "
                    "VALUES (%s, %s, %s, %s, now()) "
                    "ON CONFLICT (owner_id) DO UPDATE SET "
                    "  summary = EXCLUDED.summary, default_voice = EXCLUDED.default_voice, "
                    "  timeline = EXCLUDED.timeline, updated_at = now()",
                    (
                        owner_id,
                        (data.get("summary") or "")[:4000],
                        (data.get("default_voice") or "")[:2000],
                        psycopg2.extras.Json(data.get("timeline") or []),
                    ),
                )
            try:
                _synthesize_contacts(owner_id)
            except Exception as cexc:
                logger.warning(
                    "memory_vault contact synthesis failed for owner %s: %s",
                    owner_id,
                    cexc,
                )
            done += 1
        except Exception as exc:
            logger.warning(
                "memory_vault synthesis failed for owner %s: %s", owner_id, exc
            )

    logger.info("memory_vault synthesis: %d owner profile(s) built", done)
    return {"synthesized": done}


# ===========================================================================
# Phase 2.4 — per-contact synthesis + embeddings + retrieval surface
# ===========================================================================

_CONTACT_SYNTH_LIMIT = 25  # top contacts (by fact volume) synthesized per run
_CONTACT_MIN_FACTS = 2  # need at least this many facts to synthesize a contact
_EMBED_BATCH = 100  # rows embedded per embed-worker run


def _synthesize_contacts(owner_id):
    """For the owner's most-corresponded contacts, roll their facts into a relationship
    summary + communication-style fingerprint (research_synthesis -> D.A.R.W.I.N., local).
    """
    from tools.department_hq.services.department_dispatcher import dispatch_json

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT f.fact_type, f.content, c.sender "
            "FROM profile_facts f "
            "JOIN google_email_cache c "
            "  ON c.account_id = f.account_id AND c.gmail_id = f.source_gmail_id "
            "WHERE f.owner_id = %s AND c.sender IS NOT NULL "
            "ORDER BY c.received_at DESC NULLS LAST LIMIT 1000",
            (owner_id,),
        )
        rows = cur.fetchall()

    by_contact = {}
    for r in rows:
        em = _norm_email(r["sender"])
        if not em or "@" not in em:
            continue
        by_contact.setdefault(em, []).append((r["fact_type"], r["content"]))

    ranked = sorted(by_contact.items(), key=lambda kv: len(kv[1]), reverse=True)
    done = 0
    for email, facts in ranked[:_CONTACT_SYNTH_LIMIT]:
        if len(facts) < _CONTACT_MIN_FACTS:
            continue
        blob = "\n".join("- (%s) %s" % (t, c) for t, c in facts[:60])[:6000]
        prompt = (
            "Facts about the owner's correspondence with %s, drawn from their email:\n\n%s"
            '\n\nSTRICT JSON: {"relationship": 1-2 sentences on who this is to the owner and '
            'the nature of the relationship, "comm_style": 1 sentence on how the owner '
            "communicates with them (tone/formality)}. Use only the facts; do not invent."
            % (email, blob)
        )
        data = dispatch_json(
            "research_synthesis",
            prompt,
            module_id="memory_vault_contact_synth",
            system_prompt=_SYNTH_SYSTEM,
            local_only=True,
        )
        if not isinstance(data, dict):
            continue
        import psycopg2.extras

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE profile_contacts SET relationship_summary = %s, comm_style = %s, "
                "updated_at = now() WHERE owner_id = %s AND email = %s",
                (
                    (data.get("relationship") or "")[:2000],
                    psycopg2.extras.Json({"style": data.get("comm_style") or ""}),
                    owner_id,
                    email,
                ),
            )
        done += 1
    logger.info(
        "memory_vault contact synthesis: %d contact(s) for owner %s", done, owner_id
    )
    return done


def _to_vec(emb):
    """Format a python float list as a pgvector literal for ::vector casts."""
    return "[" + ",".join(repr(float(x)) for x in emb) + "]"


def profile_embed_worker():
    """Embed un-embedded profile_facts / profile_contacts / profile_owner summaries with
    nomic-embed-text (768) for semantic retrieval. Gated behind memory_vault."""
    if not _enabled(_FLAG_MASTER):
        return {"skipped": "memory_vault disabled"}

    from embedding_service import generate_embedding

    counts = {"facts": 0, "contacts": 0, "owner": 0, "error": 0}

    def _embed_rows(select_sql, update_sql, key, text_key, params):
        with get_db_cursor() as (conn, cur):
            cur.execute(select_sql, params)
            rows = cur.fetchall()
        n = 0
        for row in rows:
            try:
                txt = row[text_key]
                if not txt:
                    continue
                emb = generate_embedding(txt)
                if not emb:
                    continue
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(update_sql, (_to_vec(emb), row[key]))
                n += 1
            except Exception as exc:
                logger.debug("embed %s=%s failed: %s", key, row.get(key), exc)
                counts["error"] += 1
        return n

    counts["facts"] = _embed_rows(
        "SELECT id, content FROM profile_facts "
        "WHERE embedding IS NULL AND content IS NOT NULL ORDER BY id LIMIT %s",
        "UPDATE profile_facts SET embedding = %s::vector WHERE id = %s",
        "id",
        "content",
        (_EMBED_BATCH,),
    )
    counts["contacts"] = _embed_rows(
        "SELECT id, relationship_summary FROM profile_contacts "
        "WHERE embedding IS NULL AND relationship_summary IS NOT NULL ORDER BY id LIMIT %s",
        "UPDATE profile_contacts SET embedding = %s::vector WHERE id = %s",
        "id",
        "relationship_summary",
        (_EMBED_BATCH,),
    )
    counts["owner"] = _embed_rows(
        "SELECT owner_id, summary FROM profile_owner "
        "WHERE embedding IS NULL AND summary IS NOT NULL",
        "UPDATE profile_owner SET embedding = %s::vector WHERE owner_id = %s",
        "owner_id",
        "summary",
        (),
    )

    logger.info("memory_vault embed run: %s", counts)
    return counts


# ---------------------------------------------------------------------------
# Retrieval surface — read-only, NO inference. The mail agent + wellness apps
# call these before drafting/acting so they speak with the owner's real context.
# ---------------------------------------------------------------------------
def get_owner_context(owner_id, max_facts=20):
    """The owner's profile (summary, voice, timeline) + recent facts. Read-only."""
    out = {"summary": None, "default_voice": None, "timeline": [], "facts": []}
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT summary, default_voice, timeline FROM profile_owner WHERE owner_id = %s",
            (owner_id,),
        )
        row = cur.fetchone()
        if row:
            out["summary"] = row["summary"]
            out["default_voice"] = row["default_voice"]
            out["timeline"] = row["timeline"] or []
        cur.execute(
            "SELECT fact_type, subject, content FROM profile_facts "
            "WHERE owner_id = %s ORDER BY id DESC LIMIT %s",
            (owner_id, max_facts),
        )
        out["facts"] = [dict(r) for r in cur.fetchall()]
    return out


def get_contact_context(owner_id, sender, query=None, max_facts=12):
    """What the owner knows about a correspondent (resolved by email). If `query` + embeddings
    are present, the contact's facts are ranked semantically; else most-recent. Read-only.
    """
    email = _norm_email(sender or "")
    out = {"email": email, "contact": None, "facts": []}
    if not email or "@" not in email:
        return out
    like = "%" + email + "%"
    q_emb = None
    if query:
        try:
            from embedding_service import generate_embedding

            q_emb = generate_embedding(query)
        except Exception:
            q_emb = None
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT display_name, relationship_summary, comm_style, message_count "
            "FROM profile_contacts WHERE owner_id = %s AND email = %s",
            (owner_id, email),
        )
        c = cur.fetchone()
        if c:
            style = (
                c["comm_style"].get("style")
                if isinstance(c["comm_style"], dict)
                else None
            )
            out["contact"] = {
                "display_name": c["display_name"],
                "relationship_summary": c["relationship_summary"],
                "comm_style": style,
                "message_count": c["message_count"],
            }
        if q_emb:
            cur.execute(
                "SELECT f.fact_type, f.subject, f.content FROM profile_facts f "
                "JOIN google_email_cache gc "
                "  ON gc.account_id = f.account_id AND gc.gmail_id = f.source_gmail_id "
                "WHERE f.owner_id = %s AND lower(gc.sender) LIKE %s AND f.embedding IS NOT NULL "
                "ORDER BY f.embedding <=> %s::vector LIMIT %s",
                (owner_id, like, _to_vec(q_emb), max_facts),
            )
        else:
            cur.execute(
                "SELECT f.fact_type, f.subject, f.content FROM profile_facts f "
                "JOIN google_email_cache gc "
                "  ON gc.account_id = f.account_id AND gc.gmail_id = f.source_gmail_id "
                "WHERE f.owner_id = %s AND lower(gc.sender) LIKE %s "
                "ORDER BY gc.received_at DESC NULLS LAST LIMIT %s",
                (owner_id, like, max_facts),
            )
        out["facts"] = [dict(r) for r in cur.fetchall()]
    return out

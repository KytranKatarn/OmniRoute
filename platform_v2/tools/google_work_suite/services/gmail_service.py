"""
Gmail Service — inbox sync, email fetch/send/draft, agent inbox processing.
"""

import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import psycopg2.extras
from database import get_db_cursor
from tools.google_work_suite.services.google_api_service import (
    get_gmail_client,
    get_account,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_headers(headers_list):
    """Convert a list of {name, value} header dicts into a plain dict."""
    return {h["name"].lower(): h["value"] for h in (headers_list or [])}


def _walk_parts(payload):
    """Recursively yield all MIME parts from a Gmail message payload."""
    if "parts" in payload:
        for part in payload["parts"]:
            yield from _walk_parts(part)
    else:
        yield payload


def _decode_body(data):
    """Base64url-decode a Gmail body data string."""
    if not data:
        return ""
    try:
        return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    except Exception:
        return ""


def _build_mime(to, subject, body, reply_to_msg=None):
    """Construct a MIMEText message, optionally threading it as a reply."""
    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if reply_to_msg:
        headers = _extract_headers(reply_to_msg.get("payload", {}).get("headers", []))
        msg_id = headers.get("message-id", "")
        refs = headers.get("references", "")
        if msg_id:
            msg["In-Reply-To"] = msg_id
            msg["References"] = f"{refs} {msg_id}".strip()

    return msg


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sync_inbox(account_id, max_results=50, label_ids=None):
    """
    Pull recent messages from Gmail and upsert into google_email_cache.
    Returns the number of messages synced.
    """
    try:
        service = get_gmail_client(account_id)
        list_args = {"userId": "me", "maxResults": max_results}
        if label_ids:
            list_args["labelIds"] = label_ids
        else:
            list_args["labelIds"] = ["INBOX"]
        result = service.users().messages().list(**list_args).execute()
        messages = result.get("messages", [])
        synced = 0

        for msg_stub in messages:
            try:
                msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=msg_stub["id"],
                        format="metadata",
                        metadataHeaders=["Subject", "From", "To", "Date"],
                    )
                    .execute()
                )
                headers = _extract_headers(msg.get("payload", {}).get("headers", []))
                has_attachments = any(p.get("filename") for p in _walk_parts(msg.get("payload", {})))
                labels = msg.get("labelIds", [])
                is_read = "UNREAD" not in labels

                # recipients is jsonb — wrap as JSON array
                to_list = [r.strip() for r in headers.get("to", "").split(",") if r.strip()]

                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        """
                        INSERT INTO google_email_cache
                            (account_id, gmail_id, thread_id, subject, sender,
                             recipients, received_at, labels, has_attachments, is_read)
                        VALUES (%s, %s, %s, %s, %s, %s,
                                TO_TIMESTAMP(%s::BIGINT / 1000),
                                %s, %s, %s)
                        ON CONFLICT (account_id, gmail_id) DO UPDATE SET
                            labels          = EXCLUDED.labels,
                            is_read         = EXCLUDED.is_read,
                            has_attachments = EXCLUDED.has_attachments,
                            cached_at       = NOW()
                        """,
                        (
                            account_id,
                            msg["id"],
                            msg.get("threadId"),
                            headers.get("subject", "(no subject)")[:200],
                            headers.get("from", "")[:200],
                            psycopg2.extras.Json(to_list),
                            msg.get("internalDate", "0"),
                            psycopg2.extras.Json(labels),
                            has_attachments,
                            is_read,
                        ),
                    )
                synced += 1
            except Exception as e:
                logger.warning("Failed to sync message %s: %s", msg_stub["id"], e)

        # Update last_sync_at
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE google_accounts SET last_sync_at=NOW() WHERE id=%s",
                (account_id,),
            )

        logger.info("Synced %d messages for account %s", synced, account_id)
        return synced

    except Exception as e:
        logger.error("sync_inbox failed for account %s: %s", account_id, e)
        raise


def list_all_message_ids(account_id, page_token=None, max_per_page=500, query=""):
    """
    List message stubs ({id, threadId}) across the WHOLE mailbox (not just INBOX),
    one page per call. Returns (messages, next_page_token).

    Used by the Email Memory Vault crawler (Project #377) for cheap, resumable
    full-history enumeration — IDs only, no per-message fetch (that cost lives in
    the budgeted triage worker). includeSpamTrash=False skips Spam/Trash.
    """
    service = get_gmail_client(account_id)
    kwargs = {"userId": "me", "maxResults": max_per_page, "includeSpamTrash": False}
    if page_token:
        kwargs["pageToken"] = page_token
    if query:
        kwargs["q"] = query
    resp = service.users().messages().list(**kwargs).execute()
    return resp.get("messages", []), resp.get("nextPageToken")


def get_inbox(account_id, page=1, per_page=20, label=None):
    """Return cached inbox rows with optional label filter, paginated."""
    try:
        offset = (page - 1) * per_page
        with get_db_cursor() as (conn, cur):
            query = (
                "SELECT id, gmail_id, thread_id, subject, sender, recipients, "
                "received_at, labels, has_attachments, is_read, snippet, "
                "ai_sentiment, ai_priority, ai_category, ai_summary, filed_to_kb "
                "FROM google_email_cache WHERE account_id=%s"
            )
            params = [account_id]
            if label:
                query += " AND labels @> %s::jsonb"
                params.append(f'["{label}"]')
            query += " ORDER BY received_at DESC LIMIT %s OFFSET %s"
            params += [per_page, offset]
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error("get_inbox failed for account %s: %s", account_id, e)
        raise


def get_email(account_id, gmail_id):
    """
    Fetch full email from Gmail API. Parse MIME body and list attachments.
    Returns a dict with subject, sender, body_plain, body_html, attachments.
    """
    try:
        service = get_gmail_client(account_id)
        msg = service.users().messages().get(userId="me", id=gmail_id, format="full").execute()
        headers = _extract_headers(msg.get("payload", {}).get("headers", []))
        body_plain = ""
        body_html = ""
        attachments = []

        for part in _walk_parts(msg.get("payload", {})):
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")
            filename = part.get("filename", "")
            if filename:
                attachments.append(
                    {
                        "filename": filename,
                        "mimeType": mime,
                        "size": part.get("body", {}).get("size", 0),
                        "attachmentId": part.get("body", {}).get("attachmentId"),
                    }
                )
            elif mime == "text/plain" and not body_plain:
                body_plain = _decode_body(data)
            elif mime == "text/html" and not body_html:
                body_html = _decode_body(data)

        result = {
            "gmail_id": gmail_id,
            "thread_id": msg.get("threadId"),
            "subject": headers.get("subject", "(no subject)"),
            "sender": headers.get("from", ""),
            "recipients": headers.get("to", ""),
            "date": headers.get("date", ""),
            "labels": msg.get("labelIds", []),
            "body_plain": body_plain,
            "body_html": body_html,
            "attachments": attachments,
            "snippet": msg.get("snippet", ""),
        }

        # Merge AI analysis from cache if available
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT ai_sentiment, ai_priority, ai_category, ai_summary, filed_to_kb "
                    "FROM google_email_cache WHERE account_id = %s AND gmail_id = %s",
                    (account_id, gmail_id),
                )
                cached = cur.fetchone()
                if cached:
                    result["ai_sentiment"] = cached["ai_sentiment"]
                    result["ai_priority"] = cached["ai_priority"]
                    result["ai_category"] = cached["ai_category"]
                    result["ai_summary"] = cached["ai_summary"]
                    result["filed_to_kb"] = cached["filed_to_kb"]
        except Exception:
            pass

        return result
    except Exception as e:
        logger.error("get_email failed (account=%s, id=%s): %s", account_id, gmail_id, e)
        raise


def send_email(account_id, to, subject, body, reply_to_id=None):
    """
    Send an email. If account has draft_only permission, creates a draft instead.
    Returns {status, message_id} or {status:'drafted', draft_id}.
    """
    try:
        account = get_account(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")

        if account["permission_level"] == "draft_only":
            return create_draft(account_id, to, subject, body, reply_to_id=reply_to_id)

        service = get_gmail_client(account_id)
        reply_msg = None
        if reply_to_id:
            try:
                reply_msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=reply_to_id,
                        format="metadata",
                        metadataHeaders=["Message-ID", "References"],
                    )
                    .execute()
                )
            except Exception as e:
                logger.warning("Could not fetch reply-to message %s: %s", reply_to_id, e)

        mime_msg = _build_mime(to, subject, body, reply_to_msg=reply_msg)
        encoded = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
        sent = service.users().messages().send(userId="me", body={"raw": encoded}).execute()
        logger.info("Sent email to %s (account=%s, id=%s)", to, account_id, sent.get("id"))
        return {"status": "sent", "message_id": sent.get("id")}

    except Exception as e:
        logger.error("send_email failed (account=%s): %s", account_id, e)
        raise


def create_draft(account_id, to, subject, body, reply_to_id=None):
    """Create a Gmail draft. Returns {status:'drafted', draft_id}."""
    try:
        service = get_gmail_client(account_id)
        reply_msg = None
        if reply_to_id:
            try:
                reply_msg = (
                    service.users()
                    .messages()
                    .get(
                        userId="me",
                        id=reply_to_id,
                        format="metadata",
                        metadataHeaders=["Message-ID", "References"],
                    )
                    .execute()
                )
            except Exception as e:
                logger.warning("Could not fetch reply-to message %s: %s", reply_to_id, e)

        mime_msg = _build_mime(to, subject, body, reply_to_msg=reply_msg)
        encoded = base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()
        draft = service.users().drafts().create(userId="me", body={"message": {"raw": encoded}}).execute()
        logger.info("Created draft (account=%s, id=%s)", account_id, draft.get("id"))
        return {"status": "drafted", "draft_id": draft.get("id")}

    except Exception as e:
        logger.error("create_draft failed (account=%s): %s", account_id, e)
        raise


def apply_label(account_id, gmail_id, label_name, remove=False):
    """
    Add (or remove) a label from a Gmail message.
    Set remove=True to remove the label instead.
    """
    try:
        service = get_gmail_client(account_id)
        body = {"removeLabelIds": [label_name]} if remove else {"addLabelIds": [label_name]}
        service.users().messages().modify(userId="me", id=gmail_id, body=body).execute()
        logger.debug(
            "%s label %s on message %s (account=%s)",
            "Removed" if remove else "Applied",
            label_name,
            gmail_id,
            account_id,
        )
    except Exception as e:
        logger.error("apply_label failed (account=%s, msg=%s): %s", account_id, gmail_id, e)
        raise


def search_emails(account_id, query):
    """Search Gmail and return matching messages from cache."""
    try:
        service = get_gmail_client(account_id)
        result = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
        gmail_ids = [m["id"] for m in result.get("messages", [])]
        if not gmail_ids:
            return []

        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, gmail_id, subject, sender, received_at, is_read, snippet "
                "FROM google_email_cache WHERE account_id=%s AND gmail_id = ANY(%s) "
                "ORDER BY received_at DESC",
                (account_id, gmail_ids),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.error("search_emails failed (account=%s): %s", account_id, e)
        raise


def process_agent_inbox(account_id):
    """
    Sync inbox, apply automation rules, dispatch unmatched emails to Bridge AI.
    """
    try:
        sync_inbox(account_id)

        account = get_account(account_id)
        if not account:
            raise ValueError(f"Account {account_id} not found")

        owner_id = account["owner_id"]

        # Load unread cached emails
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT gmail_id, subject, sender, snippet FROM google_email_cache "
                "WHERE account_id=%s AND is_read=FALSE ORDER BY received_at DESC LIMIT 50",
                (account_id,),
            )
            unread = [dict(row) for row in cur.fetchall()]

        if not unread:
            return {"processed": 0}

        # Load active automation rules for this account (conditions/actions are JSONB)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, name, conditions, actions FROM google_email_rules "
                "WHERE account_id=%s AND is_active=TRUE ORDER BY id ASC",
                (account_id,),
            )
            rules = [dict(row) for row in cur.fetchall()]

        processed = 0
        for email_row in unread:
            gmail_id = email_row["gmail_id"]
            subject = email_row.get("subject", "")
            sender = email_row.get("sender", "")
            matched = False

            for rule in rules:
                conditions = rule.get("conditions") or {}
                from_c = conditions.get("from") or ""
                subj_c = conditions.get("subject_contains") or ""
                body_c = conditions.get("body_contains") or ""

                from_match = (not from_c) or from_c.lower() in sender.lower()
                subj_match = (not subj_c) or subj_c.lower() in subject.lower()
                body_match = True
                if body_c:
                    try:
                        full = get_email(account_id, gmail_id)
                        body_text = (full.get("body_plain", "") or "") + (full.get("body_html", "") or "")
                        body_match = body_c.lower() in body_text.lower()
                    except Exception:
                        body_match = False

                if from_match and subj_match and body_match:
                    _execute_rule_action(account_id, gmail_id, rule)
                    matched = True
                    break

            if not matched:
                # Dispatch to Bridge AI for analysis
                _dispatch_to_bridge(account_id, email_row, owner_id, account["permission_level"])

            # Mark as read in cache
            try:
                apply_label(account_id, gmail_id, "UNREAD", remove=True)
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE google_email_cache SET is_read=TRUE WHERE account_id=%s AND gmail_id=%s",
                        (account_id, gmail_id),
                    )
            except Exception as e:
                logger.warning("Could not mark %s as read: %s", gmail_id, e)

            processed += 1

        logger.info(
            "process_agent_inbox: %d emails processed for account %s",
            processed,
            account_id,
        )
        return {"processed": processed}

    except Exception as e:
        logger.error("process_agent_inbox failed (account=%s): %s", account_id, e)
        raise


def _execute_rule_action(account_id, gmail_id, rule):
    """Apply a rule's JSONB actions to a Gmail message (label / forward / auto-reply)."""
    actions = rule.get("actions") or {}
    rule_id = rule.get("id")

    label = actions.get("label")
    if label:
        try:
            apply_label(account_id, gmail_id, label)
        except Exception as e:
            logger.warning("Rule label failed (rule=%s, msg=%s): %s", rule_id, gmail_id, e)

    forward_to = actions.get("forward_to")
    auto_reply = actions.get("auto_reply")
    if not (forward_to or auto_reply):
        return

    try:
        original = get_email(account_id, gmail_id)
    except Exception as e:
        logger.warning("Rule action could not load email %s (rule=%s): %s", gmail_id, rule_id, e)
        return

    orig_subject = original.get("subject", "") or ""
    orig_sender = original.get("sender", "") or ""
    orig_body = original.get("body_plain") or original.get("snippet", "") or ""

    if forward_to:
        try:
            fwd_body = (
                "---------- Forwarded message ----------\n"
                f"From: {orig_sender}\nSubject: {orig_subject}\n\n{orig_body}"
            )
            send_email(account_id, to=forward_to, subject=f"Fwd: {orig_subject}", body=fwd_body)
        except Exception as e:
            logger.warning("Rule forward failed (rule=%s, msg=%s): %s", rule_id, gmail_id, e)

    if auto_reply:
        try:
            template = actions.get("auto_reply_template") or (
                "Thank you for your message. This is an automated reply; "
                "I will follow up personally as soon as possible."
            )
            subj = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
            send_email(
                account_id,
                to=orig_sender,
                subject=subj,
                body=template,
                reply_to_id=gmail_id,
            )
        except Exception as e:
            logger.warning("Rule auto-reply failed (rule=%s, msg=%s): %s", rule_id, gmail_id, e)


def _dispatch_to_bridge(account_id, email_row, owner_id, permission_level):
    """Ask Bridge AI to analyse an email and optionally auto-reply."""
    try:
        from tools.department_hq.services.department_dispatcher import (
            dispatch_json as _dhq_dispatch,
        )  # noqa: PLC0415

        gmail_id = email_row["gmail_id"]
        subject = email_row.get("subject", "")
        sender = email_row.get("sender", "")
        snippet = email_row.get("snippet", "")

        # Fetch body for richer context (best-effort)
        body = snippet
        try:
            full = get_email(account_id, gmail_id)
            body = full.get("body_plain") or snippet
        except Exception:
            pass

        # Fetch agent name from account owner if possible
        agent_name = f"agent_{owner_id}"
        try:
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    "SELECT display_name FROM google_accounts WHERE id = %s",
                    (account_id,),
                )
                row = cur.fetchone()
                if row and row["display_name"]:
                    agent_name = row["display_name"]
        except Exception:
            pass

        system_prompt = (
            f"You are {agent_name}'s email assistant. Analyze this email and decide:\n"
            "1. Priority: urgent/high/normal/low\n"
            "2. Category: meeting_request/report_request/question/notification/spam\n"
            "3. Action: reply/schedule_meeting/create_task/forward/archive/ignore\n"
            "4. If reply: draft a professional response\n"
            "5. If schedule_meeting: extract proposed times and attendees\n"
            "6. If create_task: extract task title and deadline\n"
            'Return ONLY valid JSON: {"priority":"...","category":"...","action":"...","draft_reply":"...","meeting_details":{"attendees":[],"preferred_time":""},"task_details":{"title":"","deadline":""}}'
        )
        prompt = f"From: {sender}\nSubject: {subject}\n\n{body[:2000]}"

        raw = _dhq_dispatch(
            capability="summarization",
            prompt=prompt,
            module_id="google_work_suite",
            system_prompt=system_prompt,
        )

        import json  # noqa: PLC0415

        # dispatch_json returns a dict; extract response text and parse
        response_text = raw.get("response", "") if isinstance(raw, dict) else str(raw or "")
        clean = response_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        result = json.loads(clean) if clean else {}

        _execute_email_action(account_id, gmail_id, sender, subject, result)

    except Exception as e:
        logger.warning("Bridge dispatch failed for message %s: %s", email_row.get("gmail_id"), e)


def _execute_email_action(account_id, gmail_id, sender, subject, decision):
    """Execute the action decided by AI analysis of an email."""
    try:
        action = decision.get("action", "ignore")
        if action == "reply" and decision.get("draft_reply"):
            send_email(
                account_id,
                sender,
                f"Re: {subject}",
                decision["draft_reply"],
                reply_to_id=gmail_id,
            )
        elif action == "schedule_meeting":
            details = decision.get("meeting_details", {})
            from .calendar_service import schedule_meeting  # noqa: PLC0415

            attendees = details.get("attendees") or [sender]
            preferred_time = details.get("preferred_time") or None
            schedule_meeting(
                account_id,
                f"Meeting: {subject}",
                attendees,
                preferred_time=preferred_time,
            )
        elif action == "create_task":
            details = decision.get("task_details", {})
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "INSERT INTO unified_tasks (project_id, title, priority, status, created_at) "
                    "VALUES (1, %s, 5, 'pending', NOW())",
                    (details.get("title") or subject,),
                )
        elif action == "forward":
            # Forward logic depends on configuration — skip silently
            pass
        elif action == "archive":
            apply_label(account_id, gmail_id, "INBOX", remove=True)
        elif action == "flag":
            apply_label(account_id, gmail_id, "STARRED")
        # 'ignore' = mark read only (handled by caller)
    except Exception as e:
        logger.warning(
            "_execute_email_action failed (action=%s, msg=%s): %s",
            decision.get("action"),
            gmail_id,
            e,
        )


# ---------------------------------------------------------------------------
# AI Email Analysis
# ---------------------------------------------------------------------------


def analyze_email(account_id, gmail_id):
    """
    Analyze a single email using AI Bridge. Returns sentiment, priority,
    category, and summary. Stores results in google_email_cache.
    """
    try:
        email = get_email(account_id, gmail_id)
        body = email.get("body_plain") or email.get("snippet") or ""
        subject = email.get("subject", "")
        sender = email.get("sender", "")

        prompt = (
            "Analyze this email and return ONLY valid JSON with these fields:\n"
            '{"sentiment": "positive|neutral|negative|urgent",\n'
            ' "priority": "low|medium|high|critical",\n'
            ' "category": "business|personal|newsletter|notification|spam|support|finance|social",\n'
            ' "summary": "one-line summary of the email"}\n\n'
            f"From: {sender}\nSubject: {subject}\n\n{body[:2000]}"
        )

        from tools.department_hq.services.department_dispatcher import dispatch_json

        analysis = dispatch_json(
            capability="summarization",
            prompt=prompt,
            module_id="google_work_suite",
            system_prompt="You are an email analysis assistant. Return ONLY valid JSON, no markdown.",
        )

        if not analysis or not isinstance(analysis, dict):
            analysis = {
                "sentiment": "neutral",
                "priority": "medium",
                "category": "notification",
                "summary": subject,
            }

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE google_email_cache
                   SET ai_sentiment = %s, ai_priority = %s, ai_category = %s,
                       ai_summary = %s, ai_analyzed_at = NOW()
                   WHERE account_id = %s AND gmail_id = %s""",
                (
                    analysis.get("sentiment", "neutral"),
                    analysis.get("priority", "medium"),
                    analysis.get("category", "notification"),
                    analysis.get("summary", subject)[:500],
                    account_id,
                    gmail_id,
                ),
            )

        logger.info(
            "Analyzed email %s: priority=%s, category=%s",
            gmail_id,
            analysis.get("priority"),
            analysis.get("category"),
        )
        return analysis
    except Exception as e:
        logger.error("analyze_email failed (account=%s, msg=%s): %s", account_id, gmail_id, e)
        return {"error": str(e)}


def analyze_batch(account_id, limit=5):
    """Analyze up to `limit` unanalyzed emails for an account."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT gmail_id FROM google_email_cache
               WHERE account_id = %s AND ai_analyzed_at IS NULL
               ORDER BY received_at DESC LIMIT %s""",
            (account_id, limit),
        )
        rows = cur.fetchall()

    results = []
    for row in rows:
        r = analyze_email(account_id, row["gmail_id"])
        results.append(r)
    return {"analyzed": len(results), "results": results}


def file_to_knowledge_base(account_id, gmail_id, user_id=None):
    """Save an email to the user's personal saved emails collection."""
    try:
        email = get_email(account_id, gmail_id)
        subject = email.get("subject", "(no subject)")
        sender = email.get("sender", "")
        body = email.get("body_plain") or email.get("snippet") or ""
        date = email.get("date", "")

        with get_db_cursor(commit=True) as (conn, cur):
            # Get owner_id from account if user_id not provided
            if not user_id:
                cur.execute("SELECT owner_id FROM google_accounts WHERE id = %s", (account_id,))
                row = cur.fetchone()
                user_id = row["owner_id"] if row else None

            if not user_id:
                return {"error": "Could not determine user for this account"}

            cur.execute(
                """INSERT INTO user_saved_emails
                       (user_id, account_id, gmail_id, subject, sender, body_text,
                        received_at, ai_sentiment, ai_priority, ai_category, ai_summary)
                   VALUES (%s, %s, %s, %s, %s, %s,
                           %s, %s, %s, %s, %s)
                   ON CONFLICT (user_id, gmail_id) DO UPDATE SET
                       subject = EXCLUDED.subject,
                       body_text = EXCLUDED.body_text,
                       ai_sentiment = EXCLUDED.ai_sentiment,
                       ai_priority = EXCLUDED.ai_priority,
                       ai_category = EXCLUDED.ai_category,
                       ai_summary = EXCLUDED.ai_summary,
                       saved_at = NOW()
                   RETURNING id""",
                (
                    user_id,
                    account_id,
                    gmail_id,
                    subject[:500],
                    sender[:200],
                    body[:10000],
                    date or None,
                    email.get("ai_sentiment"),
                    email.get("ai_priority"),
                    email.get("ai_category"),
                    email.get("ai_summary"),
                ),
            )
            saved_id = cur.fetchone()["id"]

            cur.execute(
                "UPDATE google_email_cache SET filed_to_kb = TRUE WHERE account_id = %s AND gmail_id = %s",
                (account_id, gmail_id),
            )

        logger.info("Saved email %s for user %d as #%d", gmail_id, user_id, saved_id)
        return {"success": True, "saved_id": saved_id}
    except Exception as e:
        logger.error("file_to_knowledge_base failed: %s", e)
        return {"error": str(e)}


def bulk_operation(account_id, gmail_ids, operation):
    """
    Perform bulk operations on multiple emails.
    Operations: mark_read, mark_unread, star, unstar, archive, trash
    """
    service = get_gmail_client(account_id)
    count = 0
    for gid in gmail_ids:
        try:
            if operation == "mark_read":
                service.users().messages().modify(userId="me", id=gid, body={"removeLabelIds": ["UNREAD"]}).execute()
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE google_email_cache SET is_read=TRUE WHERE account_id=%s AND gmail_id=%s",
                        (account_id, gid),
                    )
            elif operation == "mark_unread":
                service.users().messages().modify(userId="me", id=gid, body={"addLabelIds": ["UNREAD"]}).execute()
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "UPDATE google_email_cache SET is_read=FALSE WHERE account_id=%s AND gmail_id=%s",
                        (account_id, gid),
                    )
            elif operation == "star":
                service.users().messages().modify(userId="me", id=gid, body={"addLabelIds": ["STARRED"]}).execute()
            elif operation == "unstar":
                service.users().messages().modify(userId="me", id=gid, body={"removeLabelIds": ["STARRED"]}).execute()
            elif operation == "archive":
                service.users().messages().modify(userId="me", id=gid, body={"removeLabelIds": ["INBOX"]}).execute()
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "DELETE FROM google_email_cache WHERE account_id=%s AND gmail_id=%s",
                        (account_id, gid),
                    )
            elif operation == "trash":
                service.users().messages().trash(userId="me", id=gid).execute()
                with get_db_cursor(commit=True) as (conn, cur):
                    cur.execute(
                        "DELETE FROM google_email_cache WHERE account_id=%s AND gmail_id=%s",
                        (account_id, gid),
                    )
            count += 1
        except Exception as e:
            logger.warning("bulk_operation %s failed for %s: %s", operation, gid, e)
    return {"success": True, "count": count}

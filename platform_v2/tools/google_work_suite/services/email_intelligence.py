"""
Email Intelligence — IMAP receiving, AI categorization, draft generation

Uses Python stdlib imaplib + email (no new dependencies).
AI analysis via orchestration engine (dolphin3, always-loaded chat model).

Author: A.R.C.H.I.E. Platform
Created: 2026-02-17
"""

import email
import email.header
import email.utils
import imaplib
import json
import logging
import os
from database import _get_db_password
import re
import time
from datetime import datetime
from typing import List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("email_intelligence")


def get_db():
    """Get database connection"""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=_get_db_password(),
    )


def _decode_header(value: str) -> str:
    """Decode RFC 2047 encoded email header."""
    if not value:
        return ""
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return " ".join(decoded)


def _get_body(msg) -> Tuple[str, str]:
    """Extract text and HTML body from email message."""
    body_text = ""
    body_html = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in disposition:
                continue

            try:
                payload = part.get_payload(decode=True)
                if payload is None:
                    continue
                charset = part.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")

                if content_type == "text/plain" and not body_text:
                    body_text = text
                elif content_type == "text/html" and not body_html:
                    body_html = text
            except Exception:
                continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                text = payload.decode(charset, errors="replace")
                if msg.get_content_type() == "text/html":
                    body_html = text
                else:
                    body_text = text
        except Exception:
            pass

    return body_text, body_html


def _get_attachments(msg) -> List[str]:
    """Get list of attachment filenames."""
    attachments = []
    if msg.is_multipart():
        for part in msg.walk():
            disposition = str(part.get("Content-Disposition", ""))
            if "attachment" in disposition:
                filename = part.get_filename()
                if filename:
                    attachments.append(_decode_header(filename))
    return attachments


class EmailIntelligence:
    """
    IMAP inbox management with AI-powered analysis.

    - check_inbox(): Connect via IMAP, fetch new emails, store in email_inbox
    - analyze_email(): AI categorization, summary, sentiment, priority
    - generate_draft_reply(): Create draft response via AI
    - file_to_knowledge_base(): Store important emails in knowledge_base
    """

    def __init__(self):
        self._ollama_url = os.getenv("OLLAMA_URL", "http://host.docker.internal:11434")

    def check_inbox(self, setting_id: Optional[int] = None) -> dict:
        """
        Check IMAP inbox for new emails.

        Args:
            setting_id: Specific IMAP setting to check. If None, checks all active settings.

        Returns:
            dict with counts of fetched and analyzed emails.
        """
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if setting_id:
            cur.execute(
                "SELECT * FROM email_imap_settings WHERE id = %s AND is_active = true",
                (setting_id,),
            )
            settings = cur.fetchall()
        else:
            cur.execute("SELECT * FROM email_imap_settings WHERE is_active = true")
            settings = cur.fetchall()

        total_fetched = 0
        total_analyzed = 0
        errors = []

        for setting in settings:
            try:
                fetched, analyzed = self._check_single_inbox(cur, conn, setting)
                total_fetched += fetched
                total_analyzed += analyzed
            except Exception as e:
                logger.error(f"Failed to check inbox {setting['name']}: {e}")
                errors.append({"setting": setting["name"], "error": str(e)})

        cur.close()
        conn.close()

        return {
            "fetched": total_fetched,
            "analyzed": total_analyzed,
            "errors": errors,
            "settings_checked": len(settings),
        }

    def _check_single_inbox(self, cur, conn, setting: dict) -> Tuple[int, int]:
        """Check a single IMAP inbox and return (fetched, analyzed) counts."""
        host = setting["imap_host"]
        port = setting["imap_port"]
        user = setting["imap_user"]
        password = setting["imap_password_encrypted"]
        folder = setting.get("folder", "INBOX")
        last_uid = setting.get("last_uid", 0)
        encryption = setting.get("encryption", "ssl")

        # Connect
        if encryption == "ssl":
            mailbox = imaplib.IMAP4_SSL(host, port, timeout=30)
        else:
            mailbox = imaplib.IMAP4(host, port, timeout=30)
            if encryption == "tls":
                mailbox.starttls()

        mailbox.login(user, password)
        try:
            mailbox.select(folder, readonly=True)

            # Search for UIDs greater than last_uid
            if last_uid > 0:
                status, data = mailbox.uid("search", None, f"UID {last_uid + 1}:*")
            else:
                # First run: get last 50 emails
                status, data = mailbox.uid("search", None, "ALL")

            if status != "OK" or not data[0]:
                return 0, 0

            uid_list = data[0].split()

            # On first run, take all emails (up to 500)
            if last_uid == 0 and len(uid_list) > 500:
                uid_list = uid_list[-500:]

            fetched = 0
            analyzed = 0
            max_uid = last_uid

            for uid_bytes in uid_list:
                uid = int(uid_bytes)
                if uid <= last_uid:
                    continue

                try:
                    status, msg_data = mailbox.uid("fetch", str(uid), "(RFC822)")
                    if status != "OK" or not msg_data[0]:
                        continue

                    raw_email = msg_data[0][1]
                    msg = email.message_from_bytes(raw_email)

                    # Parse headers
                    from_raw = msg.get("From", "")
                    from_name, from_addr = email.utils.parseaddr(from_raw)
                    from_name = _decode_header(from_name)
                    subject = _decode_header(msg.get("Subject", "(no subject)"))
                    to_addr = msg.get("To", "")
                    cc_addr = msg.get("Cc", "")
                    date_str = msg.get("Date", "")
                    message_id = msg.get("Message-ID", "")
                    in_reply_to = msg.get("In-Reply-To", "").strip()
                    references_header = msg.get("References", "").strip()

                    # Compute thread_id from References chain
                    thread_id = None
                    if references_header:
                        # First reference is the original thread starter
                        first_ref = references_header.split()[0].strip("<>")
                        thread_id = first_ref
                    elif in_reply_to:
                        thread_id = in_reply_to.strip("<>")
                    else:
                        # This email starts a new thread
                        thread_id = message_id

                    # Parse date
                    received_at = None
                    if date_str:
                        try:
                            parsed = email.utils.parsedate_to_datetime(date_str)
                            received_at = parsed.strftime("%Y-%m-%d %H:%M:%S")
                        except Exception:
                            received_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # Body
                    body_text, body_html = _get_body(msg)

                    # Attachments
                    attachments = _get_attachments(msg)

                    # Check for duplicate by message_id
                    if message_id:
                        cur.execute(
                            "SELECT id FROM email_inbox WHERE message_id = %s",
                            (message_id,),
                        )
                        if cur.fetchone():
                            continue

                    # Try CRM match
                    crm_customer_id = None
                    if from_addr:
                        cur.execute(
                            "SELECT id FROM crm_customers WHERE email = %s LIMIT 1",
                            (from_addr.lower(),),
                        )
                        crm_row = cur.fetchone()
                        if crm_row:
                            crm_customer_id = crm_row["id"]

                    # Insert
                    cur.execute(
                        """
                        INSERT INTO email_inbox
                        (imap_setting_id, uid, message_id, from_address, from_name, to_address,
                         cc_address, subject, body_text, body_html, received_at,
                         has_attachments, attachment_names, crm_customer_id,
                         in_reply_to, references_header, thread_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            setting["id"],
                            uid,
                            message_id,
                            from_addr,
                            from_name,
                            to_addr,
                            cc_addr,
                            subject,
                            body_text[:50000] if body_text else None,
                            body_html[:50000] if body_html else None,
                            received_at,
                            len(attachments) > 0,
                            json.dumps(attachments),
                            crm_customer_id,
                            in_reply_to or None,
                            references_header or None,
                            thread_id,
                        ),
                    )
                    email_id = cur.fetchone()["id"]
                    conn.commit()
                    fetched += 1

                    if uid > max_uid:
                        max_uid = uid

                    # Auto-analyze: only analyze first 10 during fetch, rest queued for background
                    if setting.get("auto_analyze", True) and analyzed < 10:
                        try:
                            self.analyze_email(email_id)
                            analyzed += 1
                            time.sleep(1)  # GPU safety between AI calls
                        except Exception as e:
                            logger.warning(f"Auto-analysis failed for email #{email_id}: {e}")

                except Exception as e:
                    logger.error(f"Failed to fetch UID {uid}: {e}")

            # Update last_uid and last_check
            if max_uid > last_uid:
                cur.execute(
                    """
                    UPDATE email_imap_settings
                    SET last_uid = %s, last_check_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    """,
                    (max_uid, setting["id"]),
                )
                conn.commit()
            else:
                cur.execute(
                    "UPDATE email_imap_settings SET last_check_at = NOW() WHERE id = %s",
                    (setting["id"],),
                )
                conn.commit()

            return fetched, analyzed
        finally:
            try:
                mailbox.close()
            except Exception:
                pass
            mailbox.logout()

    def analyze_email(self, email_id: int) -> dict:
        """
        Run AI analysis on a single email.
        Uses dolphin3 via Ollama (always-loaded chat model, no GPU swap).

        Returns dict with category, summary, sentiment, priority, suggested_action.
        """
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM email_inbox WHERE id = %s", (email_id,))
        email_row = cur.fetchone()
        if not email_row:
            cur.close()
            conn.close()
            return {"error": "Email not found"}

        # Build analysis prompt
        content = email_row["body_text"] or email_row.get("body_html", "") or ""
        # Truncate for model context
        if len(content) > 3000:
            content = content[:1500] + "\n...\n" + content[-1500:]

        prompt = f"""Analyze this email and respond in JSON format only:

From: {email_row['from_name'] or ''} <{email_row['from_address']}>
Subject: {email_row['subject'] or '(no subject)'}
Date: {email_row['received_at'] or 'unknown'}
Attachments: {email_row.get('attachment_names', '[]')}

Body:
{content}

Respond with ONLY a JSON object:
{{
  "category": "urgent|action_required|informational|spam|newsletter",
  "summary": "1-2 sentence summary",
  "sentiment": "positive|neutral|negative|mixed",
  "priority": 1-5 (1=highest),
  "suggested_action": "brief suggestion for how to respond or handle"
}}"""

        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            dispatch_result = dispatcher.request_work(
                "classify", prompt, "email_intelligence", json_mode=True, timeout=120
            )

            if not dispatch_result.success:
                cur.close()
                conn.close()
                return {"error": "AI analysis failed"}

            # Parse JSON from response
            analysis = self._parse_json_response(dispatch_result.response)

            # Update email record
            cur.execute(
                """
                UPDATE email_inbox
                SET ai_category = %s, ai_summary = %s, ai_sentiment = %s,
                    ai_priority = %s, ai_suggested_action = %s, ai_analyzed_at = NOW()
                WHERE id = %s
                """,
                (
                    analysis.get("category", "informational"),
                    analysis.get("summary", ""),
                    analysis.get("sentiment", "neutral"),
                    analysis.get("priority", 3),
                    analysis.get("suggested_action", ""),
                    email_id,
                ),
            )
            conn.commit()
            cur.close()
            conn.close()

            return analysis

        except Exception as e:
            logger.error(f"Email analysis failed for #{email_id}: {e}")
            cur.close()
            conn.close()
            return {"error": str(e)}

    def generate_draft_reply(self, email_id: int, instructions: str = "") -> Optional[int]:
        """
        Generate an AI draft reply for an email.

        Args:
            email_id: ID of the email to reply to
            instructions: Optional additional instructions for the draft

        Returns:
            draft ID, or None on failure
        """
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM email_inbox WHERE id = %s", (email_id,))
        email_row = cur.fetchone()
        if not email_row:
            cur.close()
            conn.close()
            return None

        content = email_row["body_text"] or email_row.get("body_html", "") or ""
        if len(content) > 2000:
            content = content[:1000] + "\n...\n" + content[-1000:]

        extra = f"\nAdditional instructions: {instructions}" if instructions else ""

        prompt = f"""Write a professional email reply to this message.{extra}

Original email:
From: {email_row['from_name'] or ''} <{email_row['from_address']}>
Subject: {email_row['subject'] or ''}
Body:
{content}

Write a concise, professional reply. Include a greeting and sign-off.
Sign as "A.R.C.H.I.E." (AI Assistant for Kytran Empowerment).
Respond with ONLY the email body text, no JSON."""

        try:
            from tools.department_hq.services.department_dispatcher import get_dispatcher

            dispatcher = get_dispatcher()
            dispatch_result = dispatcher.request_work("email_composition", prompt, "email_intelligence", timeout=120)

            if not dispatch_result.success:
                cur.close()
                conn.close()
                return None

            draft_text = dispatch_result.response.strip()

            if not draft_text:
                cur.close()
                conn.close()
                return None

            # Determine reply subject
            subject = email_row["subject"] or ""
            if not subject.lower().startswith("re:"):
                subject = f"Re: {subject}"

            # Insert draft
            cur.execute(
                """
                INSERT INTO email_drafts
                (inbox_email_id, to_address, subject, body_text, body_html, ai_generated)
                VALUES (%s, %s, %s, %s, %s, TRUE)
                RETURNING id
                """,
                (
                    email_id,
                    email_row["from_address"],
                    subject,
                    draft_text,
                    f"<pre style='font-family: sans-serif;'>{draft_text}</pre>",
                ),
            )
            draft_id = cur.fetchone()["id"]
            conn.commit()
            cur.close()
            conn.close()

            return draft_id

        except Exception as e:
            logger.error(f"Draft generation failed for email #{email_id}: {e}")
            cur.close()
            conn.close()
            return None

    def file_to_knowledge_base(self, email_id: int) -> Optional[int]:
        """
        Store an email in the knowledge_base for future reference.

        Returns knowledge_base entry ID, or None on failure.
        """
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        cur.execute("SELECT * FROM email_inbox WHERE id = %s", (email_id,))
        email_row = cur.fetchone()
        if not email_row:
            cur.close()
            conn.close()
            return None

        title = f"Email: {email_row['subject'] or '(no subject)'} from {email_row['from_address']}"
        content = email_row["body_text"] or email_row.get("body_html", "") or ""

        # Build metadata
        metadata = {
            "email_id": email_id,
            "from": email_row["from_address"],
            "from_name": email_row.get("from_name"),
            "received_at": str(email_row.get("received_at", "")),
            "ai_category": email_row.get("ai_category"),
            "ai_summary": email_row.get("ai_summary"),
        }

        try:
            cur.execute(
                """
                INSERT INTO knowledge_base
                (title, content, source_type, source_url, importance_score, tags, metadata)
                VALUES (%s, %s, 'email', %s, 0.5, %s, %s)
                RETURNING id
                """,
                (
                    title[:500],
                    content[:50000],
                    f"email://{email_row['from_address']}/{email_row.get('message_id', '')}",
                    json.dumps(["email", email_row.get("ai_category", "inbox")]),
                    json.dumps(metadata),
                ),
            )
            kb_id = cur.fetchone()["id"]

            # Link back
            cur.execute(
                "UPDATE email_inbox SET kb_entry_id = %s WHERE id = %s",
                (kb_id, email_id),
            )
            conn.commit()
            cur.close()
            conn.close()

            return kb_id

        except Exception as e:
            logger.error(f"Failed to file email #{email_id} to KB: {e}")
            cur.close()
            conn.close()
            return None

    def _parse_json_response(self, text: str) -> dict:
        """Extract JSON from an AI response that may contain extra text."""
        # Try direct parse
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Try to find JSON block
        match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Fallback
        return {
            "category": "informational",
            "summary": text[:200] if text else "Analysis failed",
            "sentiment": "neutral",
            "priority": 3,
            "suggested_action": "Review manually",
        }

# Email HQ Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the email_manager module into a three-panel command center with full body sync, AI priority triage, department-grouped sidebar, and kytran@kytranempowerment.com as a provisioned owner inbox.

**Architecture:** Four sequential phases — (1) provision kytran@ in Stalwart + DB, (2) replace metadata-only IMAP sync with full RFC822 body sync into a new `email_messages` table, (3) dispatch each new message to DHQ agents for ACTION/REVIEW/INFO triage, (4) rebuild the frontend as a three-panel layout with smart pinned views, rich message rows, AI read pane, and Fold 5 responsive CSS.

**Tech Stack:** Python/Flask (backend), PostgreSQL (database), imaplib stdlib (IMAP), smtplib stdlib (SMTP), DHQ dispatch_json (AI triage), vanilla JS + LCARS CSS tokens (frontend), DOMPurify (HTML sanitization)

**Spec:** `docs/superpowers/specs/2026-05-10-email-hq-redesign.md`

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `platform_v2/database/migrations/375_email_hq_redesign.sql` | email_messages table + mailbox_type owner constraint |
| Modify | `platform_v2/tools/email_manager/stalwart_service.py` | Add quota_gb param to create_mailbox |
| Modify | `platform_v2/tools/email_manager/mailbox_routes.py` | Add provision-owner endpoint |
| Create | `platform_v2/tools/email_manager/email_parser.py` | MIME body/preview/attachment extraction |
| Modify | `platform_v2/tools/email_manager/sync_jobs.py` | Full RFC822 body sync into email_messages |
| Create | `platform_v2/tools/email_manager/triage_service.py` | AI priority dispatch via DHQ |
| Create | `platform_v2/tools/email_manager/messages_routes.py` | New message CRUD + smart view endpoints |
| Modify | `platform_v2/tools/email_manager/__init__.py` | Register messages_routes blueprint |
| Modify | `platform_v2/templates/tools/email_manager.html` | Three-panel layout replacing 6-tab structure |
| Create | `platform_v2/static/js/email-manager.js` | Left panel, message list, read pane JS |
| Create | `platform_v2/static/css/email-manager.css` | Three-panel + responsive Fold 5 CSS |
| Create | `platform_v2/tests/test_email_hq.py` | All phase tests |

---

## Task 1: DB Migration

**Files:**
- Create: `platform_v2/database/migrations/375_email_hq_redesign.sql`

- [ ] **Step 1: Write migration file**

```sql
-- platform_v2/database/migrations/375_email_hq_redesign.sql

CREATE TABLE IF NOT EXISTS email_messages (
    id               SERIAL PRIMARY KEY,
    mailbox_id       INTEGER NOT NULL REFERENCES email_mailboxes(id) ON DELETE CASCADE,
    message_id       TEXT NOT NULL,
    uid              INTEGER,
    subject          TEXT,
    from_address     TEXT,
    to_address       TEXT,
    cc_address       TEXT,
    reply_to         TEXT,
    received_at      TIMESTAMPTZ,
    body_html        TEXT,
    body_text        TEXT,
    body_preview     TEXT,
    has_attachments  BOOLEAN DEFAULT FALSE,
    attachment_names TEXT[],
    size_bytes       INTEGER,
    is_read          BOOLEAN DEFAULT FALSE,
    is_starred       BOOLEAN DEFAULT FALSE,
    is_archived      BOOLEAN DEFAULT FALSE,
    ai_priority      TEXT CHECK (ai_priority IN ('action', 'review', 'info')),
    ai_suggestion    TEXT,
    ai_agent_id      INTEGER REFERENCES agents(id),
    ai_triaged_at    TIMESTAMPTZ,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(mailbox_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_email_messages_mailbox
    ON email_messages(mailbox_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_messages_unread
    ON email_messages(mailbox_id, is_read) WHERE is_read = FALSE;
CREATE INDEX IF NOT EXISTS idx_email_messages_priority
    ON email_messages(ai_priority) WHERE ai_priority IS NOT NULL;

ALTER TABLE email_mailboxes
    DROP CONSTRAINT IF EXISTS email_mailboxes_mailbox_type_check;
ALTER TABLE email_mailboxes
    ADD CONSTRAINT email_mailboxes_mailbox_type_check
    CHECK (mailbox_type IN ('ai_agent', 'business', 'owner'));
```

- [ ] **Step 2: Run migration**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /platform_v2/database/migrations/375_email_hq_redesign.sql
```

Expected output: `CREATE TABLE`, `CREATE INDEX` x3, `ALTER TABLE` x2

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d email_messages"
```

Expected: table with `ai_priority`, `body_html`, `body_text` columns.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/database/migrations/375_email_hq_redesign.sql
git commit -m "feat(email): migration 375 — email_messages table + owner mailbox type"
```

---

## Task 2: stalwart_service.py — quota_gb Parameter

**Files:**
- Modify: `platform_v2/tools/email_manager/stalwart_service.py`

- [ ] **Step 1: Write failing test** (`platform_v2/tests/test_email_hq.py`)

```python
from unittest.mock import patch, MagicMock

class TestStalwartService:
    def test_create_mailbox_accepts_quota_gb(self):
        with patch('tools.email_manager.stalwart_service.requests.post') as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            from tools.email_manager.stalwart_service import StalwartService
            svc = StalwartService()
            result = svc.create_mailbox('kytran', quota_gb=10)
            assert mock_post.called
            # quota_gb=10 means 10 * 1024^3 bytes passed to Stalwart
            call_json = mock_post.call_args[1]['json']
            assert call_json.get('quota') == 10 * 1024 * 1024 * 1024
```

- [ ] **Step 2: Run to confirm failure**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_email_hq.py::TestStalwartService -v 2>&1 | tail -10
```

- [ ] **Step 3: Read current create_mailbox**

```bash
grep -n "def create_mailbox\|quota" /mnt/archie_brain/platform_v2/tools/email_manager/stalwart_service.py
```

- [ ] **Step 4: Update signature**

Find the `create_mailbox` method. Update it to accept `quota_gb=1` and pass `quota_bytes` in the payload:

```python
def create_mailbox(self, local_part: str, quota_gb: int = 1) -> dict:
    password = self._generate_password()
    quota_bytes = quota_gb * 1024 * 1024 * 1024
    payload = {
        "type": "individual",
        "name": local_part,
        "quota": quota_bytes,
        "secrets": [{"type": "plain", "value": password}],
    }
    try:
        resp = requests.post(
            f"{self.base_url}/api/principal",
            json=payload,
            auth=self.auth,
            verify=False,
            timeout=10,
        )
        if resp.status_code in (200, 201):
            return {"ok": True, "password": password}
        return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
    except Exception as e:
        logger.error(f"Stalwart create_mailbox error: {e}")
        return {"ok": False, "error": str(e)}
```

Note: Match the exact structure of the existing method — only add `quota_gb` param and compute `quota_bytes`.

- [ ] **Step 5: Run tests — expect pass**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_email_hq.py::TestStalwartService -v 2>&1 | tail -5
```

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/email_manager/stalwart_service.py platform_v2/tests/test_email_hq.py
git commit -m "feat(email): stalwart create_mailbox accepts quota_gb param"
```

---

## Task 3: Provision kytran@ Endpoint

**Files:**
- Modify: `platform_v2/tools/email_manager/mailbox_routes.py`

- [ ] **Step 1: Write failing test** (add to `test_email_hq.py`)

```python
class TestOwnerProvisioning:
    def test_provision_owner_creates_db_row(self, client, admin_session):
        with patch('tools.email_manager.mailbox_routes.StalwartService') as MockSvc:
            inst = MockSvc.return_value
            inst.get_mailbox.return_value = None
            inst.create_mailbox.return_value = {'ok': True, 'password': 'pw123'}
            resp = client.post('/tools/email-manager/api/email/mailboxes/provision-owner')
            assert resp.status_code == 200
            assert resp.get_json()['address'] == 'kytran@kytranempowerment.com'

    def test_provision_owner_idempotent(self, client, admin_session):
        with patch('tools.email_manager.mailbox_routes.StalwartService') as MockSvc:
            MockSvc.return_value.get_mailbox.return_value = {'name': 'kytran'}
            resp = client.post('/tools/email-manager/api/email/mailboxes/provision-owner')
            assert resp.status_code == 200
            assert resp.get_json()['already_exists'] is True
```

- [ ] **Step 2: Run to confirm 404**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_email_hq.py::TestOwnerProvisioning -v 2>&1 | tail -10
```

- [ ] **Step 3: Add route to mailbox_routes.py**

```python
@email_manager_bp.route("/api/email/mailboxes/provision-owner", methods=["POST"])
@admin_required
def provision_owner_mailbox():
    from database import get_db_cursor
    from services.time_utils import now_utc

    OWNER_ADDRESS = "kytran@kytranempowerment.com"
    OWNER_LOCAL = "kytran"
    OWNER_DISPLAY = "Kytran Katarn"

    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT id FROM email_mailboxes WHERE address = %s", (OWNER_ADDRESS,))
        if cur.fetchone():
            return jsonify({"success": True, "already_exists": True, "address": OWNER_ADDRESS})

    svc = StalwartService()
    existing = svc.get_mailbox(OWNER_LOCAL)
    if existing:
        result = svc.update_password(OWNER_LOCAL)
        password = result.get("password", "")
    else:
        result = svc.create_mailbox(OWNER_LOCAL, quota_gb=10)
        if not result.get("ok"):
            return jsonify({"success": False, "error": result.get("error")}), 500
        password = result["password"]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO email_mailboxes
                (address, display_name, mailbox_type, provisioned, active, imap_password, created_at)
               VALUES (%s, %s, 'owner', true, true, %s, %s)
               RETURNING id""",
            (OWNER_ADDRESS, OWNER_DISPLAY, password, now_utc()),
        )
        mailbox_id = cur.fetchone()["id"]

    return jsonify({"success": True, "already_exists": False,
                    "address": OWNER_ADDRESS, "mailbox_id": mailbox_id})
```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Deploy and call endpoint**

```bash
docker compose restart archie_platform
# In browser or curl with admin session:
# POST http://192.168.1.200:3000/tools/email-manager/api/email/mailboxes/provision-owner
```

Expected: `{"success": true, "already_exists": false, "mailbox_id": <N>}`

- [ ] **Step 6: Verify in Stalwart**

```bash
curl -sk -u "admin:${STALWART_ADMIN_PASSWORD}" \
  https://192.168.1.200:8443/api/principal/kytran | python3 -m json.tool
```

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/email_manager/mailbox_routes.py platform_v2/tests/test_email_hq.py
git commit -m "feat(email): provision-owner endpoint for kytran@kytranempowerment.com"
```

---

## Task 4: email_parser.py — MIME Body Extraction

**Files:**
- Create: `platform_v2/tools/email_manager/email_parser.py`

- [ ] **Step 1: Write failing tests** (add to `test_email_hq.py`)

```python
import email as email_lib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

class TestEmailParser:
    def _plain(self, body="Hello world"):
        return email_lib.message_from_string(
            f"Subject: Test\r\nFrom: a@b.com\r\nTo: c@d.com\r\n"
            f"Message-ID: <t@t.com>\r\n\r\n{body}"
        )

    def test_extract_plain_text(self):
        from tools.email_manager.email_parser import extract_body_parts
        result = extract_body_parts(self._plain("Hello world"))
        assert result["body_text"] == "Hello world"
        assert result["body_preview"] == "Hello world"
        assert result["has_attachments"] is False

    def test_preview_capped_at_300(self):
        from tools.email_manager.email_parser import extract_body_parts
        result = extract_body_parts(self._plain("A" * 500))
        assert len(result["body_preview"]) == 300

    def test_multipart_extracts_html_and_text(self):
        from tools.email_manager.email_parser import extract_body_parts
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Multi"
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Message-ID"] = "<m@m.com>"
        msg.attach(MIMEText("Plain body", "plain"))
        msg.attach(MIMEText("<b>HTML body</b>", "html"))
        result = extract_body_parts(msg)
        assert result["body_text"] == "Plain body"
        assert "<b>HTML body</b>" in result["body_html"]

    def test_attachment_name_extracted(self):
        from email.mime.base import MIMEBase
        from email import encoders
        from tools.email_manager.email_parser import extract_body_parts
        msg = MIMEMultipart()
        msg["Subject"] = "Att"
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Message-ID"] = "<a@a.com>"
        msg.attach(MIMEText("body", "plain"))
        part = MIMEBase("application", "octet-stream")
        part.set_payload(b"data")
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename="invoice.pdf")
        msg.attach(part)
        result = extract_body_parts(msg)
        assert result["has_attachments"] is True
        assert "invoice.pdf" in result["attachment_names"]
```

- [ ] **Step 2: Run to confirm ModuleNotFoundError**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_email_hq.py::TestEmailParser -v 2>&1 | tail -10
```

- [ ] **Step 3: Create email_parser.py**

```python
# platform_v2/tools/email_manager/email_parser.py
import email
import email.header
import re
from email.utils import parsedate_to_datetime
from typing import Optional


def decode_header_value(value: Optional[str]) -> str:
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


def extract_body_parts(msg) -> dict:
    body_html = ""
    body_text = ""
    attachment_names = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = msg.get_content_type() if not msg.is_multipart() else part.get_content_type()
            content_disp = str(part.get("Content-Disposition") or "")
            if "attachment" in content_disp:
                fname = part.get_filename()
                if fname:
                    attachment_names.append(decode_header_value(fname))
                continue
            if part.get_content_type() == "text/plain" and not body_text:
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(charset, errors="replace").strip()
            elif part.get_content_type() == "text/html" and not body_html:
                charset = part.get_content_charset() or "utf-8"
                payload = part.get_payload(decode=True)
                if payload:
                    body_html = payload.decode(charset, errors="replace").strip()
    else:
        charset = msg.get_content_charset() or "utf-8"
        payload = msg.get_payload(decode=True)
        if payload:
            text = payload.decode(charset, errors="replace").strip()
            if msg.get_content_type() == "text/html":
                body_html = text
            else:
                body_text = text

    preview_source = body_text or _strip_html(body_html)
    return {
        "body_html": body_html or None,
        "body_text": body_text or None,
        "body_preview": preview_source[:300].strip(),
        "has_attachments": bool(attachment_names),
        "attachment_names": attachment_names,
    }


def _strip_html(html: str) -> str:
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def parse_received_at(msg):
    date_str = msg.get("Date")
    if not date_str:
        return None
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return None
```

- [ ] **Step 4: Run tests — expect 4 passed**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_email_hq.py::TestEmailParser -v 2>&1 | tail -10
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/email_manager/email_parser.py platform_v2/tests/test_email_hq.py
git commit -m "feat(email): email_parser.py — MIME body/preview/attachment extraction"
```

---

## Task 5: Full Body Sync

**Files:**
- Modify: `platform_v2/tools/email_manager/sync_jobs.py`

- [ ] **Step 1: Write failing test** (add to `test_email_hq.py`)

```python
class TestFullBodySync:
    def test_sync_inserts_email_messages(self):
        from tools.email_manager.sync_jobs import sync_single_mailbox_full
        raw = (
            b"Subject: Invoice\r\nFrom: stripe@stripe.com\r\n"
            b"To: billing@kytranempowerment.com\r\n"
            b"Message-ID: <inv-1@stripe.com>\r\n\r\nYour invoice is ready."
        )
        with patch('tools.email_manager.sync_jobs.imaplib.IMAP4_SSL') as MockIMAP:
            conn = MockIMAP.return_value.__enter__.return_value
            conn.select.return_value = ('OK', [b'1'])
            conn.uid.side_effect = [
                ('OK', [b'1']),
                ('OK', [(b'1 (RFC822 {N})', raw)]),
            ]
            with patch('tools.email_manager.sync_jobs.get_synced_uids', return_value=set()):
                with patch('tools.email_manager.sync_jobs.insert_email_message') as mock_ins:
                    sync_single_mailbox_full(1, 'billing@kytranempowerment.com', 'pw')
                    assert mock_ins.called
                    kwargs = mock_ins.call_args[1]
                    assert kwargs['subject'] == 'Invoice'
                    assert 'Your invoice is ready' in (kwargs['body_text'] or '')
```

- [ ] **Step 2: Run to confirm ImportError**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_email_hq.py::TestFullBodySync -v 2>&1 | tail -10
```

- [ ] **Step 3: Read current sync_jobs.py structure**

```bash
cat /mnt/archie_brain/platform_v2/tools/email_manager/sync_jobs.py
```

Note the existing sync function name and how it calls IMAP before editing.

- [ ] **Step 4: Add helpers + new sync function to sync_jobs.py**

Add at the end of `sync_jobs.py`:

```python
def get_synced_uids(mailbox_id: int) -> set:
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT uid FROM email_messages WHERE mailbox_id = %s AND uid IS NOT NULL",
            (mailbox_id,)
        )
        return {row["uid"] for row in cur.fetchall()}


def insert_email_message(*, mailbox_id, uid, message_id, subject, from_address,
                          to_address, cc_address, reply_to, body_html, body_text,
                          body_preview, has_attachments, attachment_names,
                          size_bytes, received_at):
    import psycopg2.extras
    from database import get_db_cursor
    from services.time_utils import now_utc
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO email_messages (
                mailbox_id, uid, message_id, subject, from_address, to_address,
                cc_address, reply_to, body_html, body_text, body_preview,
                has_attachments, attachment_names, size_bytes, received_at, created_at
               ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (mailbox_id, message_id) DO NOTHING""",
            (mailbox_id, uid, message_id, subject, from_address, to_address,
             cc_address, reply_to, body_html, body_text, body_preview,
             has_attachments, psycopg2.extras.Json(attachment_names),
             size_bytes, received_at, now_utc())
        )


def sync_single_mailbox_full(mailbox_id: int, address: str, imap_password: str) -> dict:
    import imaplib
    import email as email_lib
    from tools.email_manager.email_parser import extract_body_parts, parse_received_at, decode_header_value

    local_part = address.split("@")[0]
    new_count = 0
    error_count = 0
    try:
        with imaplib.IMAP4_SSL("192.168.1.200", 993) as conn:
            conn.login(local_part, imap_password)
            conn.select("INBOX", readonly=False)
            _, uid_data = conn.uid("search", None, "ALL")
            all_uids = [int(u) for u in uid_data[0].split() if u]
            synced = get_synced_uids(mailbox_id)
            new_uids = [u for u in all_uids if u not in synced][:50]
            for uid in new_uids:
                try:
                    _, msg_data = conn.uid("fetch", str(uid), "(RFC822)")
                    if not msg_data or msg_data[0] is None:
                        continue
                    raw = msg_data[0][1]
                    msg = email_lib.message_from_bytes(raw)
                    parts = extract_body_parts(msg)
                    insert_email_message(
                        mailbox_id=mailbox_id, uid=uid,
                        message_id=decode_header_value(msg.get("Message-ID", f"<no-id-{uid}@local>")),
                        subject=decode_header_value(msg.get("Subject", "(no subject)")),
                        from_address=msg.get("From", ""), to_address=msg.get("To", ""),
                        cc_address=msg.get("Cc"), reply_to=msg.get("Reply-To"),
                        body_html=parts["body_html"], body_text=parts["body_text"],
                        body_preview=parts["body_preview"],
                        has_attachments=parts["has_attachments"],
                        attachment_names=parts["attachment_names"],
                        size_bytes=len(raw), received_at=parse_received_at(msg),
                    )
                    new_count += 1
                    # Queue AI triage asynchronously
                    try:
                        from database import get_db_cursor as _gdc
                        with _gdc() as (_c, _cur):
                            _cur.execute(
                                "SELECT em.id, mb.mailbox_type FROM email_messages em "
                                "JOIN email_mailboxes mb ON mb.id = em.mailbox_id "
                                "WHERE em.mailbox_id = %s AND em.uid = %s",
                                (mailbox_id, uid)
                            )
                            row = _cur.fetchone()
                        if row:
                            from tools.email_manager.triage_service import triage_message_async
                            triage_message_async(
                                row["id"], row["mailbox_type"],
                                decode_header_value(msg.get("Subject", "")),
                                msg.get("From", ""), parts["body_preview"],
                            )
                    except Exception as te:
                        logger.warning(f"Triage queue error for UID {uid}: {te}")
                except Exception as e:
                    logger.warning(f"Failed UID {uid} for {address}: {e}")
                    error_count += 1
    except Exception as e:
        logger.error(f"IMAP sync failed for {address}: {e}")
        return {"new_count": 0, "error_count": 1, "error": str(e)}
    return {"new_count": new_count, "error_count": error_count}
```

Also find the existing scheduled sync function and add a call to `sync_single_mailbox_full` for each active mailbox (owner first):

```python
# Inside the existing sync loop — add after existing metadata sync:
from database import get_db_cursor as _gdc2
with _gdc2() as (_c2, _cur2):
    _cur2.execute(
        "SELECT id, address, imap_password FROM email_mailboxes "
        "WHERE provisioned = true AND active = true "
        "ORDER BY (mailbox_type = 'owner') DESC, id"
    )
    for mb in _cur2.fetchall():
        sync_single_mailbox_full(mb["id"], mb["address"], mb["imap_password"])
```

- [ ] **Step 5: Run tests — expect pass**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_email_hq.py::TestFullBodySync -v 2>&1 | tail -10
```

- [ ] **Step 6: Deploy and verify sync**

```bash
docker compose restart archie_platform archie_scheduler
sleep 360  # wait one sync cycle
docker exec archie_database psql -U archie -d archie \
  -c "SELECT COUNT(*) as total, SUM(CASE WHEN body_text IS NOT NULL THEN 1 ELSE 0 END) as with_body FROM email_messages;"
```

Expected: `with_body` > 0

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/email_manager/sync_jobs.py platform_v2/tests/test_email_hq.py
git commit -m "feat(email): full RFC822 body sync into email_messages table"
```

---

## Task 6: AI Triage Service

**Files:**
- Create: `platform_v2/tools/email_manager/triage_service.py`

- [ ] **Step 1: Write failing tests** (add to `test_email_hq.py`)

```python
class TestTriageService:
    def test_triage_writes_action_priority(self):
        with patch('tools.email_manager.triage_service.dispatch_json') as mock_d:
            mock_d.return_value = MagicMock(
                success=True,
                response='{"priority": "action", "suggestion": "Pay by May 15."}'
            )
            with patch('tools.email_manager.triage_service.get_db_cursor') as mock_db:
                cur = MagicMock()
                mock_db.return_value.__enter__.return_value = (MagicMock(), cur)
                from tools.email_manager.triage_service import triage_message
                triage_message(42, 'business', 'Invoice #441', 'stripe@stripe.com', 'Pay invoice')
                update_args = cur.execute.call_args_list[-1][0]
                assert 'action' in str(update_args)

    def test_triage_survives_dispatch_failure(self):
        with patch('tools.email_manager.triage_service.dispatch_json') as mock_d:
            mock_d.return_value = MagicMock(success=False, response="")
            with patch('tools.email_manager.triage_service.get_db_cursor'):
                from tools.email_manager.triage_service import triage_message
                triage_message(1, 'business', 'Test', 'a@b.com', 'preview')

    def test_business_uses_classify(self):
        with patch('tools.email_manager.triage_service.dispatch_json') as mock_d:
            mock_d.return_value = MagicMock(success=False, response="")
            with patch('tools.email_manager.triage_service.get_db_cursor'):
                from tools.email_manager.triage_service import triage_message
                triage_message(1, 'business', 'S', 'a@b.com', 'p')
                assert mock_d.call_args[1]['capability'] == 'classify'

    def test_owner_uses_summarize(self):
        with patch('tools.email_manager.triage_service.dispatch_json') as mock_d:
            mock_d.return_value = MagicMock(success=False, response="")
            with patch('tools.email_manager.triage_service.get_db_cursor'):
                from tools.email_manager.triage_service import triage_message
                triage_message(1, 'owner', 'S', 'a@b.com', 'p')
                assert mock_d.call_args[1]['capability'] == 'summarize'
```

- [ ] **Step 2: Run to confirm ModuleNotFoundError**

- [ ] **Step 3: Create triage_service.py**

```python
# platform_v2/tools/email_manager/triage_service.py
import json
import logging
import threading

logger = logging.getLogger(__name__)

TRIAGE_PROMPT = """Classify this email as exactly one of: action, review, info.
- action: requires a response or payment within 7 days
- review: worth reading, no immediate action
- info: notification or confirmation, no action needed

Respond ONLY with JSON: {{"priority": "action|review|info", "suggestion": "<one sentence>"}}

Subject: {subject}
From: {from_address}
Preview: {preview}"""


def triage_message(message_id_pk, mailbox_type, subject, from_address, body_preview):
    from tools.department_hq.services.department_dispatcher import dispatch_json
    from database import get_db_cursor
    from services.time_utils import now_utc

    capability = "summarize" if mailbox_type == "owner" else "classify"
    prompt = TRIAGE_PROMPT.format(
        subject=subject or "(no subject)",
        from_address=from_address or "",
        preview=(body_preview or "")[:300],
    )
    try:
        result = dispatch_json(capability=capability, prompt=prompt, max_tokens=120,
                               context={"source": "email_triage", "message_id": message_id_pk})
    except Exception as e:
        logger.warning(f"Triage dispatch error for {message_id_pk}: {e}")
        return

    if not result.success:
        return

    try:
        data = json.loads(result.response)
        priority = data.get("priority", "").lower()
        suggestion = data.get("suggestion", "")
        if priority not in ("action", "review", "info"):
            priority = next((p for p in ("action", "review", "info")
                             if p in result.response.lower()), "info")
    except (json.JSONDecodeError, AttributeError):
        priority, suggestion = "info", ""

    agent_id = getattr(result, "agent_id", None)
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE email_messages SET ai_priority=%s, ai_suggestion=%s, "
                "ai_agent_id=%s, ai_triaged_at=%s WHERE id=%s",
                (priority, suggestion, agent_id, now_utc(), message_id_pk),
            )
    except Exception as e:
        logger.error(f"Triage DB update failed for {message_id_pk}: {e}")


def triage_message_async(message_id_pk, mailbox_type, subject, from_address, body_preview):
    t = threading.Thread(
        target=triage_message,
        args=(message_id_pk, mailbox_type, subject, from_address, body_preview),
        daemon=True,
    )
    t.start()
```

- [ ] **Step 4: Run tests — expect 4 passed**

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/email_manager/triage_service.py platform_v2/tests/test_email_hq.py
git commit -m "feat(email): AI triage service — ACTION/REVIEW/INFO via DHQ classify/summarize"
```

---

## Task 7: messages_routes.py

**Files:**
- Create: `platform_v2/tools/email_manager/messages_routes.py`

- [ ] **Step 1: Write failing tests** (add to `test_email_hq.py`)

```python
class TestMessagesRoutes:
    def test_list_messages(self, client, admin_session):
        resp = client.get('/tools/email-manager/api/email/messages?mailbox_id=1&limit=10')
        assert resp.status_code == 200
        assert 'messages' in resp.get_json()

    def test_smart_all_business(self, client, admin_session):
        resp = client.get('/tools/email-manager/api/email/messages/smart/all-business')
        assert resp.status_code == 200

    def test_smart_all_unread(self, client, admin_session):
        resp = client.get('/tools/email-manager/api/email/messages/smart/all-unread')
        assert resp.status_code == 200

    def test_archive(self, client, admin_session):
        with patch('tools.email_manager.messages_routes.get_db_cursor') as mock_db:
            cur = MagicMock()
            mock_db.return_value.__enter__.return_value = (MagicMock(), cur)
            resp = client.post('/tools/email-manager/api/email/messages/1/archive')
            assert resp.status_code == 200

    def test_sidebar_counts(self, client, admin_session):
        resp = client.get('/tools/email-manager/api/email/sidebar/counts')
        assert resp.status_code == 200
        data = resp.get_json()
        assert 'mailboxes' in data
        assert 'smart_views' in data
```

- [ ] **Step 2: Run to confirm 404s**

- [ ] **Step 3: Create messages_routes.py**

```python
# platform_v2/tools/email_manager/messages_routes.py
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Blueprint, jsonify, request, session, abort
from database import get_db_cursor

logger = logging.getLogger(__name__)

email_messages_bp = Blueprint("email_messages", __name__, url_prefix="/tools/email-manager")


def _admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            abort(403)
        return f(*args, **kwargs)
    return decorated


@email_messages_bp.route("/api/email/messages")
@_admin_required
def list_messages():
    mailbox_id = request.args.get("mailbox_id", type=int)
    priority = request.args.get("priority")
    unread_only = request.args.get("unread") == "true"
    limit = min(request.args.get("limit", 50, type=int), 200)
    offset = request.args.get("offset", 0, type=int)

    conditions = ["m.is_archived = false"]
    params = []
    if mailbox_id:
        conditions.append("m.mailbox_id = %s"); params.append(mailbox_id)
    if priority:
        conditions.append("m.ai_priority = %s"); params.append(priority)
    if unread_only:
        conditions.append("m.is_read = false")

    where = " AND ".join(conditions)
    with get_db_cursor() as (conn, cur):
        cur.execute(f"SELECT COUNT(*) as total FROM email_messages m WHERE {where}", params)
        total = cur.fetchone()["total"]
        cur.execute(
            f"""SELECT m.id, m.mailbox_id, m.subject, m.from_address, m.to_address,
                       m.body_preview, m.received_at, m.is_read, m.is_starred,
                       m.ai_priority, m.ai_suggestion, m.has_attachments,
                       mb.address AS mailbox_address, mb.mailbox_type
                FROM email_messages m JOIN email_mailboxes mb ON mb.id = m.mailbox_id
                WHERE {where} ORDER BY m.received_at DESC NULLS LAST
                LIMIT %s OFFSET %s""",
            params + [limit, offset],
        )
        messages = [dict(r) for r in cur.fetchall()]
    for m in messages:
        if m.get("received_at"):
            m["received_at"] = m["received_at"].isoformat()
    return jsonify({"messages": messages, "total": total})


@email_messages_bp.route("/api/email/messages/smart/all-business")
@_admin_required
def smart_all_business():
    limit = min(request.args.get("limit", 50, type=int), 200)
    offset = request.args.get("offset", 0, type=int)
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT m.id, m.mailbox_id, m.subject, m.from_address, m.body_preview,
                      m.received_at, m.is_read, m.ai_priority, mb.address AS mailbox_address
               FROM email_messages m JOIN email_mailboxes mb ON mb.id = m.mailbox_id
               WHERE mb.mailbox_type = 'business' AND m.is_archived = false
               ORDER BY m.received_at DESC NULLS LAST LIMIT %s OFFSET %s""",
            [limit, offset],
        )
        messages = [dict(r) for r in cur.fetchall()]
    for m in messages:
        if m.get("received_at"):
            m["received_at"] = m["received_at"].isoformat()
    return jsonify({"messages": messages})


@email_messages_bp.route("/api/email/messages/smart/all-unread")
@_admin_required
def smart_all_unread():
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT m.id, m.mailbox_id, m.subject, m.from_address, m.body_preview,
                      m.received_at, m.ai_priority, mb.address AS mailbox_address
               FROM email_messages m JOIN email_mailboxes mb ON mb.id = m.mailbox_id
               WHERE m.is_read = false AND m.is_archived = false
               ORDER BY CASE m.ai_priority WHEN 'action' THEN 0 WHEN 'review' THEN 1 ELSE 2 END,
                        m.received_at DESC NULLS LAST LIMIT 100""",
        )
        messages = [dict(r) for r in cur.fetchall()]
    for m in messages:
        if m.get("received_at"):
            m["received_at"] = m["received_at"].isoformat()
    return jsonify({"messages": messages})


@email_messages_bp.route("/api/email/messages/<int:msg_id>")
@_admin_required
def get_message(msg_id):
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """SELECT m.*, mb.address AS mailbox_address, mb.mailbox_type, mb.imap_password
               FROM email_messages m JOIN email_mailboxes mb ON mb.id = m.mailbox_id
               WHERE m.id = %s""", (msg_id,)
        )
        msg = cur.fetchone()
        if not msg:
            return jsonify({"error": "not found"}), 404
        cur.execute("UPDATE email_messages SET is_read = true WHERE id = %s AND is_read = false", (msg_id,))
    result = dict(msg)
    result.pop("imap_password", None)
    for key in ("received_at", "ai_triaged_at", "created_at"):
        if result.get(key):
            result[key] = result[key].isoformat()
    return jsonify(result)


@email_messages_bp.route("/api/email/messages/<int:msg_id>/archive", methods=["POST"])
@_admin_required
def archive_message(msg_id):
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("UPDATE email_messages SET is_archived = true WHERE id = %s", (msg_id,))
    return jsonify({"success": True})


@email_messages_bp.route("/api/email/messages/<int:msg_id>", methods=["DELETE"])
@_admin_required
def delete_message(msg_id):
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute("DELETE FROM email_messages WHERE id = %s", (msg_id,))
    return jsonify({"success": True})


@email_messages_bp.route("/api/email/messages/<int:msg_id>/star", methods=["POST"])
@_admin_required
def toggle_star(msg_id):
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE email_messages SET is_starred = NOT is_starred WHERE id = %s RETURNING is_starred",
            (msg_id,)
        )
        row = cur.fetchone()
    return jsonify({"success": True, "is_starred": row["is_starred"] if row else False})


def _send_smtp(from_address, to_address, subject, body, imap_password, in_reply_to=None):
    msg = MIMEMultipart()
    msg["From"] = from_address
    msg["To"] = to_address
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    msg.attach(MIMEText(body, "plain"))
    with smtplib.SMTP("192.168.1.200", 587) as smtp:
        smtp.starttls()
        smtp.login(from_address.split("@")[0], imap_password)
        smtp.sendmail(from_address, [to_address], msg.as_string())


@email_messages_bp.route("/api/email/messages/<int:msg_id>/reply", methods=["POST"])
@_admin_required
def reply_to_message(msg_id):
    payload = request.get_json() or {}
    body = payload.get("body", "").strip()
    if not body:
        return jsonify({"error": "body required"}), 400
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT m.subject, m.from_address, m.message_id,
                      mb.address AS mailbox_address, mb.imap_password
               FROM email_messages m JOIN email_mailboxes mb ON mb.id = m.mailbox_id
               WHERE m.id = %s""", (msg_id,)
        )
        orig = cur.fetchone()
    if not orig:
        return jsonify({"error": "not found"}), 404
    subject = orig["subject"] if orig["subject"].startswith("Re:") else f"Re: {orig['subject']}"
    try:
        _send_smtp(orig["mailbox_address"], orig["from_address"], subject, body,
                   orig["imap_password"], in_reply_to=orig["message_id"])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"success": True})


@email_messages_bp.route("/api/email/messages/<int:msg_id>/forward", methods=["POST"])
@_admin_required
def forward_message(msg_id):
    payload = request.get_json() or {}
    to_address = payload.get("to_address", "").strip()
    if not to_address:
        return jsonify({"error": "to_address required"}), 400
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT m.subject, m.body_text, m.from_address,
                      mb.address AS mailbox_address, mb.imap_password
               FROM email_messages m JOIN email_mailboxes mb ON mb.id = m.mailbox_id
               WHERE m.id = %s""", (msg_id,)
        )
        orig = cur.fetchone()
    if not orig:
        return jsonify({"error": "not found"}), 404
    note = payload.get("body", "").strip()
    fwd_body = f"{note}\n\n--- Forwarded ---\nFrom: {orig['from_address']}\n\n{orig['body_text'] or ''}"
    try:
        _send_smtp(orig["mailbox_address"], to_address,
                   f"Fwd: {orig['subject']}", fwd_body, orig["imap_password"])
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"success": True})


@email_messages_bp.route("/api/email/messages/<int:msg_id>/ai-action", methods=["POST"])
@_admin_required
def ai_action(msg_id):
    from tools.department_hq.services.department_dispatcher import dispatch_json
    payload = request.get_json() or {}
    action = payload.get("action", "summarize")
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT subject, body_text, body_preview, from_address FROM email_messages WHERE id = %s",
            (msg_id,)
        )
        msg = cur.fetchone()
    if not msg:
        return jsonify({"error": "not found"}), 404
    prompts = {
        "draft_reply": f"Draft a professional reply.\n\nSubject: {msg['subject']}\nFrom: {msg['from_address']}\n\n{msg['body_text'] or msg['body_preview']}",
        "summarize":   f"Summarize in 2-3 sentences.\n\nSubject: {msg['subject']}\n\n{msg['body_text'] or msg['body_preview']}",
        "assign":      f"Which team should handle this?\n\nSubject: {msg['subject']}\n\n{msg['body_preview']}",
        "flag":        f"What follow-up is needed and by when?\n\nSubject: {msg['subject']}\n\n{msg['body_preview']}",
    }
    capability = "creative" if action == "draft_reply" else "summarize"
    result = dispatch_json(capability=capability, prompt=prompts.get(action, prompts["summarize"]), max_tokens=300)
    return jsonify({"success": result.success, "result": result.response if result.success else "AI unavailable"})


@email_messages_bp.route("/api/email/sidebar/counts")
@_admin_required
def sidebar_counts():
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT mb.id, mb.address, mb.display_name, mb.mailbox_type,
                      COUNT(m.id) FILTER (WHERE m.is_read = false AND m.is_archived = false) AS unread
               FROM email_mailboxes mb LEFT JOIN email_messages m ON m.mailbox_id = mb.id
               WHERE mb.active = true GROUP BY mb.id
               ORDER BY (mb.mailbox_type = 'owner') DESC, mb.mailbox_type, mb.address"""
        )
        mailboxes = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT
                COUNT(*) FILTER (WHERE m.is_read = false AND mb.mailbox_type = 'owner') AS owner_unread,
                COUNT(*) FILTER (WHERE m.is_read = false AND mb.mailbox_type = 'business') AS business_unread,
                COUNT(*) FILTER (WHERE m.is_read = false) AS total_unread
               FROM email_messages m JOIN email_mailboxes mb ON mb.id = m.mailbox_id
               WHERE m.is_archived = false"""
        )
        smart = dict(cur.fetchone())
    return jsonify({"mailboxes": mailboxes, "smart_views": smart})
```

- [ ] **Step 4: Run tests — expect 5 passed**

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/email_manager/messages_routes.py platform_v2/tests/test_email_hq.py
git commit -m "feat(email): messages_routes.py — list, smart views, reply, forward, archive, AI actions"
```

---

## Task 8: Register Blueprint

**Files:**
- Modify: `platform_v2/tools/email_manager/__init__.py`

- [ ] **Step 1: Read __init__.py**

```bash
cat /mnt/archie_brain/platform_v2/tools/email_manager/__init__.py
```

- [ ] **Step 2: Register email_messages_bp**

Following the existing `register_*_routes` pattern in the file, add:

```python
from tools.email_manager.messages_routes import email_messages_bp

# Inside the registration function / app factory:
app.register_blueprint(email_messages_bp)
```

If the module uses a single blueprint (not app-level registration), import and mount the new routes on the existing blueprint instead — match the existing pattern exactly.

- [ ] **Step 3: Deploy and smoke test**

```bash
docker compose restart archie_platform
curl -s 'http://192.168.1.200:3000/tools/email-manager/api/email/sidebar/counts' \
  -H "Cookie: session=<admin_session>" | python3 -m json.tool
```

Expected: JSON with `mailboxes` array.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/email_manager/__init__.py
git commit -m "feat(email): register email_messages_bp blueprint"
```

---

## Task 9: Frontend HTML + CSS

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html`
- Create: `platform_v2/static/css/email-manager.css`

**Security note:** Email HTML bodies MUST be sanitized before rendering. Add DOMPurify to the template and use `DOMPurify.sanitize()` before any `element.innerHTML = emailHtml` call. Never render raw email HTML directly.

- [ ] **Step 1: Replace email_manager.html body with three-panel layout**

Replace everything inside `{% block content %}` with:

```html
{% block content %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/email-manager.css') }}">
<script src="https://cdn.jsdelivr.net/npm/dompurify@3.0.6/dist/purify.min.js"></script>

<div class="em-root" id="emailHQ">

  <div class="em-nav" id="emNav">
    <div class="em-nav-header">
      <button class="em-hamburger" id="emHamburger" aria-label="Menu">☰</button>
      <span class="em-nav-title">📬 EMAIL HQ</span>
      <span class="em-badge em-badge-red" id="emTotalBadge"></span>
    </div>
    <div class="em-section-label">Pinned</div>
    <div class="em-nav-item em-pinned" data-view="owner" onclick="emSelectView('owner')">
      <span>★ kytran@</span>
      <span class="em-badge em-badge-red" id="badgeOwner"></span>
    </div>
    <div class="em-nav-item" data-view="all-business" onclick="emSelectView('all-business')">
      <span>📬 All Business</span>
      <span class="em-badge em-badge-amber" id="badgeBusiness"></span>
    </div>
    <div class="em-nav-item" data-view="all-unread" onclick="emSelectView('all-unread')">
      <span>🔔 All Unread</span>
      <span class="em-badge em-badge-blue" id="badgeUnread"></span>
    </div>
    <div class="em-section-label">Departments (17)</div>
    <div id="emDeptList" class="em-dept-list"></div>
    <div class="em-compose-btn" onclick="emOpenCompose()">✍ Compose</div>
  </div>

  <div class="em-list" id="emList">
    <div class="em-list-header">
      <span class="em-list-title" id="emListTitle">Select a mailbox</span>
      <span class="em-list-count" id="emListCount"></span>
    </div>
    <div class="em-filters" id="emFilters">
      <span class="em-chip em-chip-active" data-filter="all" onclick="emSetFilter('all')">All</span>
      <span class="em-chip" data-filter="unread" onclick="emSetFilter('unread')">Unread</span>
      <span class="em-chip" data-filter="action" onclick="emSetFilter('action')">🔴 Action</span>
      <span class="em-chip" data-filter="review" onclick="emSetFilter('review')">🟡 Review</span>
    </div>
    <div id="emMessageList" class="em-message-list">
      <div class="em-empty">Select a mailbox or smart view.</div>
    </div>
  </div>

  <div class="em-read" id="emRead">
    <div class="em-read-empty" id="emReadEmpty"><p>Select a message to read it.</p></div>
    <div class="em-read-content" id="emReadContent" style="display:none">
      <div class="em-read-header">
        <div>
          <div class="em-read-subject" id="emReadSubject"></div>
          <div class="em-read-meta" id="emReadMeta"></div>
        </div>
        <span class="em-priority-badge" id="emReadPriority"></span>
      </div>
      <div class="em-read-body" id="emReadBody"></div>
      <div class="em-read-actions">
        <button class="em-btn em-btn-primary" onclick="emReply()">↩ Reply</button>
        <button class="em-btn" onclick="emForward()">↪ Forward</button>
        <button class="em-btn" onclick="emArchive()">📁 Archive</button>
        <button class="em-btn em-btn-danger" onclick="emDelete()">🗑 Delete</button>
      </div>
      <div class="em-ai-panel" id="emAiPanel">
        <div class="em-ai-label">🤖 AI Actions — <span id="emAiAgent"></span></div>
        <div class="em-ai-btns">
          <button class="em-ai-btn" onclick="emAiAction('draft_reply')">✍ Draft Reply</button>
          <button class="em-ai-btn" onclick="emAiAction('summarize')">📋 Summarize</button>
          <button class="em-ai-btn em-ai-btn-purple" onclick="emAiAction('assign')">👤 Assign Agent</button>
          <button class="em-ai-btn em-ai-btn-amber" onclick="emAiAction('flag')">🚩 Flag Follow-up</button>
        </div>
        <div class="em-ai-suggestion" id="emAiSuggestion"></div>
      </div>
    </div>
  </div>

</div>

<div class="bm-overlay" id="emComposeModal">
  <div class="bm-shell">
    <div class="bm-frame"></div>
    <div class="bm-content">
      <div class="bm-header">
        <span id="emComposeTitle">New Message</span>
        <button class="bm-close" onclick="emCloseCompose()">✕</button>
      </div>
      <div class="bm-body">
        <input class="em-input" id="emComposeTo" placeholder="To:">
        <input class="em-input" id="emComposeFrom" placeholder="From:">
        <input class="em-input" id="emComposeSubject" placeholder="Subject:">
        <textarea class="em-textarea" id="emComposeBody" rows="10" placeholder="Message body..."></textarea>
      </div>
      <div class="bm-footer">
        <button class="em-btn em-btn-primary" onclick="emSendCompose()">Send</button>
        <button class="em-btn" onclick="emCloseCompose()">Cancel</button>
      </div>
    </div>
  </div>
</div>

<script src="{{ url_for('static', filename='js/email-manager.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Create email-manager.css**

```css
/* platform_v2/static/css/email-manager.css */
.em-root { display:flex; height:calc(100vh - 60px); background:var(--archie-bg-primary,#080810); color:var(--archie-text-primary,#e2e8f0); overflow:hidden; font-family:'IBM Plex Mono',monospace; }

/* NAV */
.em-nav { width:220px; flex-shrink:0; border-right:1px solid #1a1a3a; display:flex; flex-direction:column; background:#0a0a18; overflow-y:auto; }
.em-nav-header { padding:10px 12px; border-bottom:1px solid #1a1a3a; display:flex; align-items:center; gap:8px; }
.em-nav-title { font-weight:bold; font-size:12px; color:#60a5fa; flex:1; }
.em-hamburger { background:none; border:none; color:#aaa; font-size:14px; cursor:pointer; display:none; }
.em-section-label { padding:8px 12px 2px; font-size:9px; text-transform:uppercase; letter-spacing:1px; color:#555; }
.em-nav-item { padding:6px 12px; display:flex; justify-content:space-between; align-items:center; cursor:pointer; font-size:11px; color:#aaa; }
.em-nav-item:hover { background:#0f1a2e; }
.em-nav-item.em-active { background:#0f1a2e; border-left:2px solid #60a5fa; color:#e2e8f0; }
.em-pinned { color:#4ade80 !important; }
.em-badge { font-size:9px; padding:1px 6px; border-radius:10px; font-weight:bold; }
.em-badge:empty { display:none; }
.em-badge-red { background:#7f1d1d; color:#fca5a5; }
.em-badge-amber { background:#1c1005; color:#f59e0b; }
.em-badge-blue { background:#1e3a5f; color:#93c5fd; }
.em-dept-header { padding:5px 12px; cursor:pointer; font-size:10px; color:#777; display:flex; justify-content:space-between; }
.em-dept-header:hover,.em-dept-header.em-open { color:#ccc; background:#0f1a2e; }
.em-mailbox-item { padding:3px 12px 3px 24px; font-size:10px; color:#888; cursor:pointer; display:flex; justify-content:space-between; }
.em-mailbox-item:hover { background:#0f1a2e; color:#ccc; }
.em-mailbox-item.em-active { color:#60a5fa; background:#0f1a2e; }
.em-compose-btn { margin:10px; padding:8px; background:#1d4ed8; color:#fff; text-align:center; border-radius:4px; cursor:pointer; font-size:11px; font-weight:bold; }
.em-compose-btn:hover { background:#2563eb; }

/* LIST */
.em-list { width:300px; flex-shrink:0; border-right:1px solid #1a1a3a; display:flex; flex-direction:column; background:#090912; overflow:hidden; }
.em-list-header { padding:8px 12px; border-bottom:1px solid #1a1a3a; display:flex; justify-content:space-between; align-items:center; }
.em-list-title { font-weight:bold; font-size:11px; color:#60a5fa; }
.em-list-count { font-size:9px; color:#555; }
.em-filters { padding:6px 8px; display:flex; gap:4px; border-bottom:1px solid #1a1a3a; flex-wrap:wrap; }
.em-chip { padding:2px 8px; border-radius:10px; font-size:9px; cursor:pointer; background:#1a1a2e; color:#888; }
.em-chip:hover { color:#ccc; }
.em-chip.em-chip-active { background:#1d4ed8; color:#fff; }
.em-message-list { flex:1; overflow-y:auto; }
.em-msg-row { display:flex; gap:8px; padding:8px 10px; border-bottom:1px solid #12122a; cursor:pointer; align-items:flex-start; }
.em-msg-row:hover { background:#0d0d20; }
.em-msg-row.em-unread { background:#0f1528; }
.em-msg-row.em-active { background:#1e3a5f; }
.em-msg-avatar { width:28px; height:28px; border-radius:50%; background:#374151; color:#9ca3af; display:flex; align-items:center; justify-content:center; font-size:11px; font-weight:bold; flex-shrink:0; margin-top:2px; }
.em-msg-body { flex:1; min-width:0; }
.em-msg-top { display:flex; justify-content:space-between; align-items:center; gap:4px; }
.em-msg-sender { font-size:10px; color:#aaa; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.em-unread .em-msg-sender { color:#fff; font-weight:bold; }
.em-msg-subject { font-size:9px; color:#888; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.em-unread .em-msg-subject { color:#e2e8f0; font-weight:bold; }
.em-msg-bottom { display:flex; justify-content:space-between; align-items:center; margin-top:2px; }
.em-msg-preview { font-size:8px; color:#444; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:160px; }
.em-msg-mailbox-tag { font-size:7px; padding:1px 4px; border-radius:6px; background:#0f2238; color:#60a5fa; flex-shrink:0; }
.em-priority-chip { font-size:7px; padding:1px 5px; border-radius:6px; flex-shrink:0; }
.em-p-action { background:#7f1d1d; color:#fca5a5; }
.em-p-review { background:#713f12; color:#fde68a; }
.em-p-info { background:#052e16; color:#6ee7b7; }

/* READ PANE */
.em-read { flex:1; display:flex; flex-direction:column; background:#06060e; overflow:hidden; }
.em-read-empty { flex:1; display:flex; align-items:center; justify-content:center; color:#333; font-size:12px; }
.em-read-content { flex:1; overflow-y:auto; padding:16px; display:flex; flex-direction:column; gap:12px; }
.em-read-header { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; }
.em-read-subject { font-size:16px; font-weight:bold; color:#fff; margin-bottom:4px; }
.em-read-meta { font-size:10px; color:#666; }
.em-read-body { color:#d1d5db; line-height:1.7; font-size:12px; }
.em-read-body a { color:#60a5fa; }
.em-read-actions { display:flex; gap:8px; flex-wrap:wrap; }
.em-ai-panel { border:1px solid #1e3a5f; border-radius:6px; padding:12px; background:#040d1a; }
.em-ai-label { color:#60a5fa; font-size:9px; font-weight:bold; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; }
.em-ai-btns { display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px; }
.em-ai-btn { background:#0f2238; color:#60a5fa; padding:5px 10px; border-radius:3px; border:1px solid #1e3a5f; cursor:pointer; font-size:9px; }
.em-ai-btn:hover { background:#1e3a5f; }
.em-ai-btn-purple { color:#a78bfa !important; border-color:#312e81 !important; }
.em-ai-btn-amber { color:#f59e0b !important; border-color:#422006 !important; }
.em-ai-suggestion { font-size:10px; color:#94a3b8; font-style:italic; line-height:1.5; background:#060f1c; border:1px solid #1e3a5f; border-radius:4px; padding:8px; min-height:32px; }

/* BUTTONS + INPUTS */
.em-btn { padding:6px 12px; border-radius:4px; border:none; cursor:pointer; font-size:10px; background:#1e293b; color:#ccc; }
.em-btn:hover { background:#2d3748; }
.em-btn-primary { background:#1d4ed8; color:#fff; }
.em-btn-primary:hover { background:#2563eb; }
.em-btn-danger { color:#ef4444; }
.em-input { width:100%; padding:7px 10px; background:#0f172a; border:1px solid #1e3a5f; border-radius:4px; color:#e2e8f0; font-size:11px; margin-bottom:6px; box-sizing:border-box; }
.em-textarea { width:100%; padding:7px 10px; background:#0f172a; border:1px solid #1e3a5f; border-radius:4px; color:#e2e8f0; font-size:11px; box-sizing:border-box; resize:vertical; }
.em-empty { padding:40px; text-align:center; color:#333; font-size:11px; }
.em-priority-badge { font-size:9px; padding:3px 8px; border-radius:8px; }

/* RESPONSIVE ≤600px (Fold 5 folded) */
@media (max-width: 600px) {
  .em-hamburger { display:block; }
  .em-nav { position:absolute; left:-220px; top:0; bottom:0; width:220px; z-index:100; transition:left .2s; box-shadow:4px 0 20px rgba(0,0,0,.5); }
  .em-nav.em-open { left:0; }
  .em-list { width:100%; border-right:none; }
  .em-read { display:none; position:absolute; inset:0; z-index:50; background:#06060e; }
  .em-read.em-open { display:flex; }
}
/* RESPONSIVE 601–1024px */
@media (min-width:601px) and (max-width:1024px) {
  .em-nav { width:180px; }
  .em-list { width:240px; }
}
```

- [ ] **Step 3: Deploy and verify layout renders**

```bash
docker compose restart archie_platform
```

Open `http://192.168.1.200:3000/tools/email-manager` — confirm three panels render with no console errors.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/templates/tools/email_manager.html platform_v2/static/css/email-manager.css
git commit -m "feat(email): three-panel HTML layout + responsive CSS (Fold 5 aware)"
```

---

## Task 10: Frontend JS

**Files:**
- Create: `platform_v2/static/js/email-manager.js`

**Security:** All email body HTML is sanitized via `DOMPurify.sanitize()` before rendering. Plain text fields always use `element.textContent`. Never use `element.innerHTML` with unsanitized user data.

- [ ] **Step 1: Create email-manager.js**

```javascript
// platform_v2/static/js/email-manager.js
// DOMPurify loaded via CDN in template (required for HTML body rendering)

const DEPT_MAP = {
  'Executive Office':               ['archie'],
  'Operations & Infrastructure':    ['base'],
  'Logistics & Supply Chain':       ['cargo'],
  'Finance & Accounting':           ['ledger'],
  'Engineering & Technology':       ['forge', 'probe'],
  'Security & Compliance':          ['vigil', 'shield'],
  'Research & Development':         ['darwin', 'quill', 'scroll', 'heritage'],
  'Creative & Design':              ['muse', 'restore', 'visage', 'pixel'],
  'Marketing & Communications':     ['signal'],
  'Documentation & Knowledge':      ['codex'],
  'Customer Success & Support':     ['resolve'],
  'Human Resources & Culture':      ['kin'],
  'Medical & Wellness':             ['vital'],
  'Legal & Regulatory':             ['gavel'],
  'Diplomatic & External Relations':['accord'],
  'Analytics & Intelligence':       ['spectra', 'watch'],
  'News & Media':                   ['fact', 'bias', 'verify', 'publish', 'ink', 'draft', 'maven'],
};

const PRIORITY = {
  action: { label: '🔴 ACTION', css: 'em-p-action' },
  review: { label: '🟡 REVIEW', css: 'em-p-review' },
  info:   { label: '🟢 INFO',   css: 'em-p-info' },
};

let state = { view: null, mailboxId: null, msgId: null, filter: 'all', mailboxes: [], replyId: null };

document.addEventListener('DOMContentLoaded', () => {
  loadSidebarCounts();
  buildDeptList();
  setInterval(loadSidebarCounts, 30000);
  document.getElementById('emHamburger').addEventListener('click', () =>
    document.getElementById('emNav').classList.toggle('em-open'));
});

// ── Sidebar counts ───────────────────────────────────────────
async function loadSidebarCounts() {
  const data = await apiFetch('/tools/email-manager/api/email/sidebar/counts');
  if (!data) return;
  state.mailboxes = data.mailboxes || [];
  const sv = data.smart_views || {};
  setBadge('badgeOwner', sv.owner_unread);
  setBadge('badgeBusiness', sv.business_unread);
  setBadge('badgeUnread', sv.total_unread);
  setBadge('emTotalBadge', sv.total_unread);
  state.mailboxes.forEach(mb => {
    const el = document.querySelector(`[data-mailbox-id="${mb.id}"] .em-mb-count`);
    if (el) el.textContent = mb.unread > 0 ? String(mb.unread) : '';
  });
}

function setBadge(id, count) {
  const el = document.getElementById(id);
  if (el) el.textContent = count > 0 ? String(count) : '';
}

// ── Dept list ────────────────────────────────────────────────
function buildDeptList() {
  const container = document.getElementById('emDeptList');
  container.textContent = '';
  Object.entries(DEPT_MAP).forEach(([dept, agents]) => {
    const group = document.createElement('div');
    group.className = 'em-dept-group';
    const header = document.createElement('div');
    header.className = 'em-dept-header';
    const nameSpan = document.createElement('span');
    nameSpan.textContent = dept;
    const toggle = document.createElement('span');
    toggle.textContent = '▸';
    header.appendChild(nameSpan);
    header.appendChild(toggle);
    const list = document.createElement('div');
    list.style.display = 'none';
    header.addEventListener('click', () => {
      const open = list.style.display !== 'none';
      list.style.display = open ? 'none' : 'block';
      header.classList.toggle('em-open', !open);
      toggle.textContent = open ? '▸' : '▾';
    });
    agents.forEach(local => {
      const item = document.createElement('div');
      item.className = 'em-mailbox-item';
      item.dataset.mailboxLocal = local;
      const nameEl = document.createElement('span');
      nameEl.textContent = local + '@';
      const countEl = document.createElement('span');
      countEl.className = 'em-mb-count';
      item.appendChild(nameEl);
      item.appendChild(countEl);
      item.addEventListener('click', () => selectMailboxByLocal(local));
      list.appendChild(item);
    });
    group.appendChild(header);
    group.appendChild(list);
    container.appendChild(group);
  });
}

// ── View / mailbox selection ─────────────────────────────────
async function emSelectView(view) {
  state.view = view; state.mailboxId = null;
  document.querySelectorAll('.em-nav-item').forEach(el => el.classList.remove('em-active'));
  document.querySelector(`[data-view="${view}"]`)?.classList.add('em-active');
  const titles = { owner: 'kytran@kytranempowerment.com', 'all-business': 'All Business', 'all-unread': 'All Unread' };
  document.getElementById('emListTitle').textContent = titles[view] || view;
  if (view === 'owner') {
    const mb = state.mailboxes.find(m => m.mailbox_type === 'owner');
    if (mb) loadMessageList(`/tools/email-manager/api/email/messages?mailbox_id=${mb.id}&limit=50`);
  } else if (view === 'all-business') {
    loadMessageList('/tools/email-manager/api/email/messages/smart/all-business');
  } else if (view === 'all-unread') {
    loadMessageList('/tools/email-manager/api/email/messages/smart/all-unread');
  }
}

async function selectMailboxByLocal(local) {
  const mb = state.mailboxes.find(m => m.address.startsWith(local + '@'));
  if (!mb) return;
  state.mailboxId = mb.id; state.view = null;
  document.getElementById('emListTitle').textContent = mb.address;
  loadMessageList(`/tools/email-manager/api/email/messages?mailbox_id=${mb.id}&limit=50`);
}

// ── Message list ─────────────────────────────────────────────
async function loadMessageList(url) {
  const data = await apiFetch(url);
  if (!data) return;
  const msgs = data.messages || [];
  document.getElementById('emListCount').textContent = msgs.length ? `${msgs.length} messages` : '';
  renderMessageList(msgs);
}

function renderMessageList(messages) {
  const container = document.getElementById('emMessageList');
  container.textContent = '';
  if (!messages.length) {
    const empty = document.createElement('div');
    empty.className = 'em-empty';
    empty.textContent = 'No messages.';
    container.appendChild(empty);
    return;
  }
  messages.forEach(m => {
    const row = document.createElement('div');
    row.className = 'em-msg-row' + (m.is_read ? '' : ' em-unread');
    row.dataset.msgId = m.id;

    const avatar = document.createElement('div');
    avatar.className = 'em-msg-avatar';
    avatar.textContent = (m.from_address || '?')[0].toUpperCase();

    const body = document.createElement('div');
    body.className = 'em-msg-body';

    const top = document.createElement('div');
    top.className = 'em-msg-top';
    const sender = document.createElement('span');
    sender.className = 'em-msg-sender';
    sender.textContent = m.from_address || '';
    top.appendChild(sender);
    if (m.ai_priority && PRIORITY[m.ai_priority]) {
      const badge = document.createElement('span');
      badge.className = `em-priority-chip ${PRIORITY[m.ai_priority].css}`;
      badge.textContent = PRIORITY[m.ai_priority].label;
      top.appendChild(badge);
    }

    const subjectEl = document.createElement('div');
    subjectEl.className = 'em-msg-subject';
    subjectEl.textContent = m.subject || '(no subject)';

    const bottom = document.createElement('div');
    bottom.className = 'em-msg-bottom';
    const preview = document.createElement('span');
    preview.className = 'em-msg-preview';
    preview.textContent = m.body_preview || '';
    const tag = document.createElement('span');
    tag.className = 'em-msg-mailbox-tag';
    tag.textContent = m.mailbox_address ? m.mailbox_address.split('@')[0] + '@' : '';
    bottom.appendChild(preview);
    bottom.appendChild(tag);

    body.appendChild(top);
    body.appendChild(subjectEl);
    body.appendChild(bottom);
    row.appendChild(avatar);
    row.appendChild(body);
    row.addEventListener('click', () => openMessage(m.id));
    container.appendChild(row);
  });
}

// ── Read pane ────────────────────────────────────────────────
async function openMessage(msgId) {
  state.msgId = msgId;
  document.querySelectorAll('.em-msg-row').forEach(el => el.classList.remove('em-active'));
  const row = document.querySelector(`[data-msg-id="${msgId}"]`);
  if (row) { row.classList.add('em-active'); row.classList.remove('em-unread'); }

  const msg = await apiFetch(`/tools/email-manager/api/email/messages/${msgId}`);
  if (!msg) return;

  document.getElementById('emReadEmpty').style.display = 'none';
  document.getElementById('emReadContent').style.display = 'flex';

  // Use textContent for all user-supplied metadata fields (XSS safe)
  document.getElementById('emReadSubject').textContent = msg.subject || '(no subject)';
  document.getElementById('emReadMeta').textContent =
    `From: ${msg.from_address || ''} · To: ${msg.to_address || ''} · ${msg.received_at ? new Date(msg.received_at).toLocaleString() : ''}`;

  const priorityEl = document.getElementById('emReadPriority');
  if (msg.ai_priority && PRIORITY[msg.ai_priority]) {
    priorityEl.textContent = PRIORITY[msg.ai_priority].label;
    priorityEl.className = `em-priority-badge ${PRIORITY[msg.ai_priority].css}`;
  } else {
    priorityEl.textContent = '';
  }

  const bodyEl = document.getElementById('emReadBody');
  if (msg.body_html) {
    // DOMPurify sanitizes HTML before rendering — required, never skip
    bodyEl.innerHTML = (typeof DOMPurify !== 'undefined')
      ? DOMPurify.sanitize(msg.body_html, { USE_PROFILES: { html: true } })
      : '';
    if (typeof DOMPurify === 'undefined') {
      bodyEl.textContent = msg.body_text || '(HTML body — DOMPurify not loaded)';
    }
  } else {
    bodyEl.textContent = msg.body_text || '(empty message)';
  }

  document.getElementById('emAiSuggestion').textContent = msg.ai_suggestion || 'Awaiting AI triage...';
  document.getElementById('emRead').classList.add('em-open');
  loadSidebarCounts();
}

// ── Actions ──────────────────────────────────────────────────
async function emArchive() {
  if (!state.msgId) return;
  await apiPost(`/tools/email-manager/api/email/messages/${state.msgId}/archive`, {});
  document.querySelector(`[data-msg-id="${state.msgId}"]`)?.remove();
  document.getElementById('emReadContent').style.display = 'none';
  document.getElementById('emReadEmpty').style.display = 'flex';
  loadSidebarCounts();
}

async function emDelete() {
  if (!state.msgId || !confirm('Delete this message permanently?')) return;
  await apiFetch(`/tools/email-manager/api/email/messages/${state.msgId}`, { method: 'DELETE' });
  document.querySelector(`[data-msg-id="${state.msgId}"]`)?.remove();
  document.getElementById('emReadContent').style.display = 'none';
  document.getElementById('emReadEmpty').style.display = 'flex';
}

function emReply() {
  if (!state.msgId) return;
  state.replyId = state.msgId;
  document.getElementById('emComposeTitle').textContent = 'Reply';
  document.getElementById('emComposeModal').classList.add('active');
}

function emForward() {
  if (!state.msgId) return;
  state.replyId = null;
  document.getElementById('emComposeTitle').textContent = 'Forward';
  document.getElementById('emComposeTo').value = '';
  document.getElementById('emComposeModal').classList.add('active');
}

function emOpenCompose() {
  state.replyId = null;
  document.getElementById('emComposeTitle').textContent = 'New Message';
  document.getElementById('emComposeTo').value = '';
  document.getElementById('emComposeSubject').value = '';
  document.getElementById('emComposeBody').value = '';
  document.getElementById('emComposeModal').classList.add('active');
}

function emCloseCompose() {
  document.getElementById('emComposeModal').classList.remove('active');
}

async function emSendCompose() {
  const to = document.getElementById('emComposeTo').value.trim();
  const body = document.getElementById('emComposeBody').value.trim();
  const subject = document.getElementById('emComposeSubject').value.trim();
  if (!to || !body) { alert('To and body are required'); return; }

  const title = document.getElementById('emComposeTitle').textContent;
  if (title === 'Reply' && state.replyId) {
    await apiPost(`/tools/email-manager/api/email/messages/${state.replyId}/reply`, { body });
  } else if (title === 'Forward' && state.msgId) {
    await apiPost(`/tools/email-manager/api/email/messages/${state.msgId}/forward`, { to_address: to, body });
  } else {
    const from = document.getElementById('emComposeFrom').value.trim();
    await apiPost('/tools/email-manager/api/email/compose/send', { from_address: from, to_address: to, subject, body });
  }
  emCloseCompose();
}

function emSetFilter(filter) {
  state.filter = filter;
  document.querySelectorAll('.em-chip').forEach(el => el.classList.remove('em-chip-active'));
  document.querySelector(`[data-filter="${filter}"]`)?.classList.add('em-chip-active');
  if (state.view) {
    emSelectView(state.view);
  } else if (state.mailboxId) {
    let url = `/tools/email-manager/api/email/messages?mailbox_id=${state.mailboxId}&limit=50`;
    if (filter === 'unread') url += '&unread=true';
    else if (['action', 'review', 'info'].includes(filter)) url += `&priority=${filter}`;
    loadMessageList(url);
  }
}

async function emAiAction(action) {
  if (!state.msgId) return;
  const el = document.getElementById('emAiSuggestion');
  el.textContent = 'Thinking...';
  const result = await apiPost(`/tools/email-manager/api/email/messages/${state.msgId}/ai-action`, { action });
  el.textContent = (result && result.result) ? result.result : 'AI unavailable';
}

// ── HTTP helpers ─────────────────────────────────────────────
async function apiFetch(url, opts = {}) {
  try {
    const resp = await fetch(url, { ...opts, headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) } });
    if (!resp.ok) return null;
    return resp.json();
  } catch { return null; }
}

async function apiPost(url, body) {
  return apiFetch(url, { method: 'POST', body: JSON.stringify(body) });
}
```

- [ ] **Step 2: Deploy and test**

```bash
docker compose restart archie_platform
```

Open `http://192.168.1.200:3000/tools/email-manager`. Test:
- Left panel shows pinned views and dept groups
- Clicking `★ kytran@` loads message list
- Clicking `All Business` loads business inbox
- Clicking a message opens the read pane (body renders, badges show)
- Reply modal opens with correct prefill
- Archive removes message from list and closes read pane
- AI action buttons return suggestions

- [ ] **Step 3: Test on Fold 5 (folded)**

Load `http://192.168.1.200:3000/tools/email-manager` on phone with screen folded:
- Hamburger button visible
- Tapping hamburger opens left drawer
- Tapping a message opens full-screen read pane
- Back navigation returns to message list

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/email-manager.js
git commit -m "feat(email): JS frontend — three-panel, dept list, message list, read pane, reply/forward/AI"
```

---

## Task 11: PR + Final Verification

- [ ] **Step 1: Run full test suite**

```bash
docker exec archie_platform python -m pytest platform_v2/tests/test_email_hq.py -v 2>&1 | tail -30
```

Expected: All tests pass.

- [ ] **Step 2: Check logs for errors**

```bash
docker logs archie_platform --since 10m 2>&1 | grep -iE "^.*error|traceback" | grep -iv "debug\|404" | head -20
```

Expected: No email_manager errors.

- [ ] **Step 3: Verify kytran@ data**

```bash
docker exec archie_database psql -U archie -d archie \
  -c "SELECT mb.address, mb.mailbox_type, COUNT(em.id) as msgs, SUM(CASE WHEN em.ai_priority IS NOT NULL THEN 1 ELSE 0 END) as triaged FROM email_mailboxes mb LEFT JOIN email_messages em ON em.mailbox_id = mb.id WHERE mb.mailbox_type = 'owner' GROUP BY mb.address, mb.mailbox_type;"
```

- [ ] **Step 4: Create PR**

```bash
git push origin HEAD
gh pr create \
  --title "feat(email): Email HQ redesign — three-panel layout, full body sync, AI triage, kytran@ inbox" \
  --body "$(cat <<'EOF'
## Summary
- Provisions kytran@kytranempowerment.com as owner inbox (10GB quota) pinned at top
- New email_messages table — full RFC822 bodies synced every 5 min (owner mailbox first)
- AI triage: each incoming message dispatched to DHQ (classify/summarize) → ACTION/REVIEW/INFO badge
- Three-panel command center: Smart Pinned nav · Rich message list · AI read pane
- Reply / Forward / Archive / Delete + AI Draft Reply / Summarize / Assign / Flag
- DOMPurify used for all HTML body rendering (XSS safe)
- Fully responsive: Fold 5 folded (drawer+slides) · Fold 5 unfolded (all 3 panels)

## Test plan
- [ ] pytest platform_v2/tests/test_email_hq.py — all pass
- [ ] POST provision-owner → Stalwart account + DB row created
- [ ] Wait 5 min → email_messages rows with body_text populated
- [ ] ai_priority populated after triage
- [ ] Email HQ opens three-panel — smart views load, message opens in read pane
- [ ] Reply sends via SMTP, Forward works
- [ ] Fold 5 folded: drawer + full-screen panels
- [ ] Fold 5 unfolded: all three panels visible

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

| Spec requirement | Covered in |
|-----------------|-----------|
| kytran@ provisioned | Task 3 |
| email_messages table | Task 1 |
| owner mailbox_type | Task 1 |
| Full body sync | Task 4 + Task 5 |
| AI triage ACTION/REVIEW/INFO | Task 6 |
| Smart Pinned + collapsed depts | Task 9 (HTML) + Task 10 (JS) |
| Rich message list (avatar/preview/badge/tag) | Task 10 |
| Reply / Forward | Task 7 + Task 10 |
| Archive / Delete / Star | Task 7 + Task 10 |
| AI read pane actions | Task 7 + Task 10 |
| DOMPurify for HTML bodies | Task 9 (CDN load) + Task 10 (sanitize call) |
| Fold 5 responsive | Task 9 (CSS media queries) |
| All Unread / All Business | Task 7 (routes) + Task 10 (emSelectView) |
| Sidebar unread counts | Task 7 (sidebar/counts) + Task 10 (loadSidebarCounts) |
| TDD throughout | Every backend task has tests before implementation |
| No direct Ollama | All LLM via dispatch_json |
| Idempotent migration | IF NOT EXISTS + DROP CONSTRAINT IF EXISTS |

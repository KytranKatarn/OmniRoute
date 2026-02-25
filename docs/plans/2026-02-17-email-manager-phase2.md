# Email Manager Phase 2 — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add 10 features to Email Manager: quick UI improvements, SMTP draft sending, background auto-analysis, delete action, email threading, multi-account indicator, and full Telegram email integration (smart notifications + reply/archive/star via Telegram).

**Architecture:** Build on existing Email Manager module (`platform_v2/tools/email_manager/`) and Telegram Gateway (`ai_bridge/telegram_gateway.py`). Quick wins are frontend-only or minimal backend. Medium features wire existing infrastructure (SMTP settings, Agent Loop). Telegram integration adds new handlers to the existing bot and a new APScheduler job for smart email notifications.

**Tech Stack:** Flask/Jinja2, PostgreSQL, Ollama dolphin3, python-telegram-bot (async), APScheduler, IMAP/SMTP

---

## Task 1: Starred Filter Button

Add a "Starred" filter button to the inbox category bar, between "All" and "Urgent".

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html` (category bar ~line 209-232, loadInbox ~line 3040)
- Modify: `platform_v2/tools/email_manager/imap_routes.py` (stats endpoint, inbox query)

**Step 1: Add Starred filter button to category bar**

In `email_manager.html`, find the category filter bar (around line 209-232). After the "All" button and before "Urgent", add:

```html
<button class="inbox-filter inbox-filter--starred" data-filter="starred" onclick="filterInbox('starred')">
    <i data-lucide="star" style="width:14px;height:14px;fill:#FFC800;color:#FFC800"></i> Starred
    <span class="inbox-filter-count" id="filter-count-starred">0</span>
</button>
```

**Step 2: Add starred count to stats query**

In `imap_routes.py`, find the `get_inbox_stats()` endpoint (~line 304). Add starred count to the query:

```python
COUNT(*) FILTER (WHERE is_starred = TRUE) as starred,
```

Return `starred` in the JSON response.

**Step 3: Update loadInboxStats() to show starred count**

In the JS `loadInboxStats()` function, after setting unread count, add:

```javascript
const starredEl = document.getElementById('filter-count-starred');
if (starredEl) starredEl.textContent = data.starred || 0;
```

**Step 4: Handle starred filter in loadInbox()**

In `loadInbox()`, when building the fetch URL, if `inboxCurrentFilter === 'starred'`, add `&starred=true` to the query string.

**Step 5: Add starred filter to backend**

In `imap_routes.py` `get_inbox()` endpoint (~line 208), add handling for `starred` query parameter:

```python
starred = request.args.get("starred")
if starred == "true":
    conditions.append("is_starred = TRUE")
```

**Step 6: Add CSS for starred filter button**

```css
.inbox-filter--starred { border-color: #FFC800; }
.inbox-filter--starred.active { background: rgba(255, 200, 0, 0.15); color: #FFC800; }
```

**Step 7: Commit**

```bash
git add platform_v2/templates/tools/email_manager.html platform_v2/tools/email_manager/imap_routes.py
git commit -m "feat(email): add starred filter to inbox category bar"
```

---

## Task 2: Mark Read/Unread from Detail View

Add a toggle button in the email detail panel to mark the email as read or unread.

**Files:**
- Modify: `platform_v2/tools/email_manager/imap_routes.py` (~line 424, add new endpoint)
- Modify: `platform_v2/templates/tools/email_manager.html` (detail panel ~line 264, add button + JS)

**Step 1: Add toggle read endpoint**

In `imap_routes.py`, after the star toggle endpoint (~line 462), add:

```python
@email_manager_bp.route("/api/inbox/<int:email_id>/read", methods=["POST"])
@login_required
def toggle_read(email_id):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("UPDATE email_inbox SET is_read = NOT is_read, updated_at = NOW() WHERE id = %s RETURNING is_read", (email_id,))
        row = cur.fetchone()
        if not row:
            return jsonify({"success": False, "error": "Email not found"}), 404
        conn.commit()
        return jsonify({"success": True, "is_read": row["is_read"]})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 2: Add toggle button to detail panel**

In the email detail panel HTML (~line 264-300), find the action buttons area. Add a read/unread toggle button:

```html
<button class="em-btn em-btn--sm" id="detail-read-toggle" onclick="toggleDetailRead()" title="Toggle read/unread">
    <i data-lucide="mail-open" id="detail-read-icon"></i> <span id="detail-read-label">Mark Unread</span>
</button>
```

**Step 3: Add toggleDetailRead() JS function**

```javascript
async function toggleDetailRead() {
    if (!currentEmailId) return;
    try {
        const resp = await fetch(`/tools/email-manager/api/inbox/${currentEmailId}/read`, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            const icon = document.getElementById('detail-read-icon');
            const label = document.getElementById('detail-read-label');
            if (data.is_read) {
                icon.setAttribute('data-lucide', 'mail-open');
                label.textContent = 'Mark Unread';
            } else {
                icon.setAttribute('data-lucide', 'mail');
                label.textContent = 'Mark Read';
            }
            if (window.lucide) lucide.createIcons();
            loadInbox();
            loadInboxStats();
        }
    } catch (e) { console.error('Toggle read failed:', e); }
}
```

**Step 4: Update viewEmail() to set initial read/unread button state**

In `viewEmail()` (~line 3152), after populating the detail panel, set the toggle button state based on the email's `is_read` value:

```javascript
const readIcon = document.getElementById('detail-read-icon');
const readLabel = document.getElementById('detail-read-label');
if (email.is_read) {
    readIcon.setAttribute('data-lucide', 'mail-open');
    readLabel.textContent = 'Mark Unread';
} else {
    readIcon.setAttribute('data-lucide', 'mail');
    readLabel.textContent = 'Mark Read';
}
if (window.lucide) lucide.createIcons();
```

**Step 5: Commit**

```bash
git add platform_v2/tools/email_manager/imap_routes.py platform_v2/templates/tools/email_manager.html
git commit -m "feat(email): mark read/unread toggle from detail view"
```

---

## Task 3: Delete Action with Confirmation

Add delete functionality to both individual emails (detail view) and bulk actions, with a confirmation dialog.

**Files:**
- Modify: `platform_v2/tools/email_manager/imap_routes.py` (add delete endpoint, add delete to bulk)
- Modify: `platform_v2/templates/tools/email_manager.html` (add delete button, confirmation modal, bulk option)

**Step 1: Add single delete endpoint**

In `imap_routes.py`, add after the archive endpoint:

```python
@email_manager_bp.route("/api/inbox/<int:email_id>/delete", methods=["DELETE"])
@login_required
def delete_email(email_id):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM email_inbox WHERE id = %s", (email_id,))
        if cur.rowcount == 0:
            return jsonify({"success": False, "error": "Email not found"}), 404
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 2: Add "delete" to bulk action whitelist**

In the bulk endpoint (~line 378), add `"delete"` to the allowed actions set. Add the delete case:

```python
elif action == "delete":
    id_placeholders = ",".join(["%s"] * len(ids))
    cur.execute(f"DELETE FROM email_inbox WHERE id IN ({id_placeholders})", ids)
```

**Step 3: Add delete button to detail panel**

In the detail panel action buttons area, add:

```html
<button class="em-btn em-btn--sm em-btn--danger" onclick="deleteEmail()" title="Delete email">
    <i data-lucide="trash-2"></i> Delete
</button>
```

Add CSS for danger button:
```css
.em-btn--danger { border-color: #FF4444; color: #FF4444; }
.em-btn--danger:hover { background: rgba(255, 68, 68, 0.15); }
```

**Step 4: Add confirmation modal HTML**

Before the closing `</div>` of the main container, add:

```html
<div class="em-confirm-overlay" id="confirm-overlay" style="display:none">
    <div class="em-confirm-dialog">
        <div class="em-confirm-title" id="confirm-title">Confirm Delete</div>
        <div class="em-confirm-message" id="confirm-message">Are you sure?</div>
        <div class="em-confirm-actions">
            <button class="em-btn em-btn--sm" onclick="closeConfirm()">Cancel</button>
            <button class="em-btn em-btn--sm em-btn--danger" id="confirm-action-btn" onclick="">Confirm</button>
        </div>
    </div>
</div>
```

Add CSS:
```css
.em-confirm-overlay {
    position: fixed; top: 0; left: 0; width: 100%; height: 100%;
    background: rgba(0,0,0,0.7); display: flex; align-items: center;
    justify-content: center; z-index: 1000;
}
.em-confirm-dialog {
    background: #1a1a2e; border: 1px solid #00FFFF; border-radius: 8px;
    padding: 24px; min-width: 320px; max-width: 480px;
}
.em-confirm-title { color: #00FFFF; font-size: 16px; font-weight: 600; margin-bottom: 12px; }
.em-confirm-message { color: #ccc; margin-bottom: 20px; }
.em-confirm-actions { display: flex; gap: 12px; justify-content: flex-end; }
```

**Step 5: Add deleteEmail() and confirmation JS**

```javascript
function showConfirm(title, message, onConfirm) {
    document.getElementById('confirm-title').textContent = title;
    document.getElementById('confirm-message').textContent = message;
    document.getElementById('confirm-action-btn').onclick = function() {
        closeConfirm();
        onConfirm();
    };
    document.getElementById('confirm-overlay').style.display = 'flex';
}

function closeConfirm() {
    document.getElementById('confirm-overlay').style.display = 'none';
}

function deleteEmail() {
    if (!currentEmailId) return;
    showConfirm('Delete Email', 'Are you sure you want to permanently delete this email?', async function() {
        try {
            const resp = await fetch(`/tools/email-manager/api/inbox/${currentEmailId}/delete`, { method: 'DELETE' });
            const data = await resp.json();
            if (data.success) {
                document.getElementById('email-detail-panel').style.display = 'none';
                currentEmailId = null;
                loadInbox();
                loadInboxStats();
            }
        } catch (e) { console.error('Delete failed:', e); }
    });
}
```

**Step 6: Add delete to bulk actions bar**

Add a delete button to the bulk action bar:

```html
<button class="em-btn em-btn--sm em-btn--danger" onclick="bulkDelete()">
    <i data-lucide="trash-2"></i> Delete
</button>
```

```javascript
function bulkDelete() {
    const ids = getSelectedIds();
    if (!ids.length) return;
    showConfirm('Delete Emails', 'Permanently delete ' + ids.length + ' email(s)?', function() {
        bulkAction('delete');
    });
}
```

**Step 7: Commit**

```bash
git add platform_v2/tools/email_manager/imap_routes.py platform_v2/templates/tools/email_manager.html
git commit -m "feat(email): delete action with confirmation dialog"
```

---

## Task 4: Send Drafts via SMTP

Wire the existing "Send" button on AI-generated drafts to actually send emails via SMTP using the configured email settings. Support both "Send Now" (direct) and "Send via Approval" (tier-2 IAAE flow).

**Files:**
- Modify: `platform_v2/tools/email_manager/imap_routes.py` (update draft send endpoint ~line 645)
- Modify: `platform_v2/templates/tools/email_manager.html` (wire send button in detail panel)

**Step 1: Update the draft send endpoint to support direct send**

In `imap_routes.py`, update the existing `/api/drafts/<id>/send` endpoint (~line 645) to accept a `direct` parameter. When `direct=true`, send immediately via SMTP. Otherwise, use existing approval flow.

Add SMTP send logic:
- Get default SMTP settings from `email_settings` table
- Build MIMEMultipart email with proper From/To/Subject
- If replying (has `inbox_email_id`), add In-Reply-To and References headers
- Connect via SMTP_SSL (port 465) or SMTP+STARTTLS (port 587)
- Log to `email_logs` table
- Log governance event
- Update draft status to 'sent'

**Step 2: Add Send buttons to draft section in detail panel**

In the email detail panel where drafts are shown, add two buttons:

```html
<button class="em-btn em-btn--sm em-btn--primary" onclick="sendDraft(DRAFT_ID, true)">
    <i data-lucide="send"></i> Send Now
</button>
<button class="em-btn em-btn--sm" onclick="sendDraft(DRAFT_ID, false)">
    <i data-lucide="shield-check"></i> Send via Approval
</button>
```

Add CSS for primary button:
```css
.em-btn--primary { border-color: #00FFFF; color: #00FFFF; }
.em-btn--primary:hover { background: rgba(0,255,255,0.15); }
```

**Step 3: Add sendDraft() JS function**

```javascript
async function sendDraft(draftId, direct) {
    if (!draftId) return;
    const action = direct ? 'send this email now' : 'queue this for approval';
    showConfirm('Send Email', 'Are you sure you want to ' + action + '?', async function() {
        try {
            const resp = await fetch('/tools/email-manager/api/drafts/' + draftId + '/send', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ direct: direct })
            });
            const data = await resp.json();
            if (data.success) {
                alert(data.message);
                viewEmail(currentEmailId);
            } else {
                alert('Error: ' + data.error);
            }
        } catch (e) { console.error('Send failed:', e); }
    });
}
```

**Step 4: Import necessary modules in imap_routes.py**

At the top of imap_routes.py, ensure these are imported:

```python
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
```

Also import `log_governance_event` from `ai_bridge.agent_loop` if not already present.

**Step 5: Commit**

```bash
git add platform_v2/tools/email_manager/imap_routes.py platform_v2/templates/tools/email_manager.html
git commit -m "feat(email): send drafts via SMTP with direct send and approval flow"
```

---

## Task 5: Background Auto-Analysis via Agent Loop

Add an APScheduler job that automatically analyzes unanalyzed emails in batches, so users don't have to manually click "Analyze Remaining".

**Files:**
- Modify: `ai_bridge/agent_loop.py` (add new scheduled job ~line 215)

**Step 1: Add auto-analyze job registration to agent_loop.py**

In `agent_loop.py`, after the existing `agent_email_inbox` job registration (~line 175), add a new job:

```python
self.scheduler.add_job(
    with_app_context(self._auto_analyze_emails),
    trigger=IntervalTrigger(minutes=10),
    id="agent_email_analyze",
    name="Agent Loop: Auto-Analyze Emails",
    replace_existing=True,
)
```

**Step 2: Add the _auto_analyze_emails method**

In the AgentLoop class, add:

```python
def _auto_analyze_emails(self):
    """Auto-analyze unanalyzed emails in background (3 per batch, GPU-safe)."""
    try:
        from ai_bridge.email_intelligence import EmailIntelligence
        ei = EmailIntelligence()
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("""
            SELECT id FROM email_inbox
            WHERE ai_analyzed_at IS NULL AND is_archived = FALSE
            ORDER BY received_at DESC LIMIT 3
        """)
        rows = cur.fetchall()
        if not rows:
            return

        analyzed = 0
        for row in rows:
            try:
                ei.analyze_email(row["id"])
                analyzed += 1
                time.sleep(1)  # GPU safety delay
            except Exception as e:
                logger.error(f"Auto-analyze email {row['id']} failed: {e}")
                break  # Stop on error (GPU may be overloaded)

        if analyzed > 0:
            log_governance_event(
                "email_auto_analyze", "execute", "success",
                {"analyzed": analyzed, "remaining": len(rows) - analyzed}
            )
            logger.info(f"Auto-analyzed {analyzed} emails")
    except Exception as e:
        logger.error(f"Auto-analyze job failed: {e}")
```

**Step 3: Ensure `import time` is present**

Check if `time` is already imported in agent_loop.py. Add if missing.

**Step 4: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(email): background auto-analysis job (3 emails every 10 min)"
```

---

## Task 6: Multi-Account Indicator

Show which IMAP account each email came from in the inbox table and detail view.

**Files:**
- Modify: `platform_v2/tools/email_manager/imap_routes.py` (join imap settings in inbox query)
- Modify: `platform_v2/templates/tools/email_manager.html` (show account badge in table)

**Step 1: Update inbox query to include account name**

In `imap_routes.py` `get_inbox()` (~line 208), update the SELECT to join `email_imap_settings`:

```sql
SELECT e.*, eis.name as account_name
FROM email_inbox e
LEFT JOIN email_imap_settings eis ON e.imap_setting_id = eis.id
```

Update the WHERE clause to use `e.` prefix on all email_inbox columns.

**Step 2: Update email detail query similarly**

In `get_email_detail()` (~line 424), also join to get account_name.

**Step 3: Show account name in inbox table rows**

In `buildInboxRow()` JS function (~line 2884), add account badge column. Add "Account" column header to the table. Update all colSpan references from 8 to 9.

**Step 4: Add account badge CSS**

```css
.account-badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    background: rgba(0, 255, 255, 0.1);
    color: #88cccc;
    border: 1px solid rgba(0, 255, 255, 0.2);
    white-space: nowrap;
}
```

**Step 5: Show account in detail view**

In `viewEmail()`, display account name near from/to fields using textContent (not innerHTML).

**Step 6: Commit**

```bash
git add platform_v2/tools/email_manager/imap_routes.py platform_v2/templates/tools/email_manager.html
git commit -m "feat(email): multi-account indicator showing source IMAP account"
```

---

## Task 7: Email Threading

Group emails by conversation thread using In-Reply-To / References headers and subject matching.

**Files:**
- Create: `database/migrations/098_email_threading.sql`
- Modify: `ai_bridge/email_intelligence.py` (extract thread headers during IMAP fetch)
- Modify: `platform_v2/tools/email_manager/imap_routes.py` (add thread API endpoint)
- Modify: `platform_v2/templates/tools/email_manager.html` (thread view in detail panel)

**Step 1: Create migration for threading columns**

Create `database/migrations/098_email_threading.sql`:

```sql
-- Email threading support
ALTER TABLE email_inbox ADD COLUMN IF NOT EXISTS in_reply_to TEXT;
ALTER TABLE email_inbox ADD COLUMN IF NOT EXISTS references_header TEXT;
ALTER TABLE email_inbox ADD COLUMN IF NOT EXISTS thread_id TEXT;

-- Index for thread lookups
CREATE INDEX IF NOT EXISTS idx_email_thread_id ON email_inbox(thread_id) WHERE thread_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_email_message_id ON email_inbox(message_id) WHERE message_id IS NOT NULL;

-- Backfill: each email without thread_id gets its own message_id as thread_id
UPDATE email_inbox SET thread_id = message_id WHERE thread_id IS NULL AND message_id IS NOT NULL;
```

**Step 2: Run migration**

```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/098_email_threading.sql
```

**Step 3: Extract thread headers during IMAP fetch**

In `email_intelligence.py`, in `_check_single_inbox()` where headers are parsed, extract In-Reply-To and References headers. Compute thread_id: use first message-id in References chain, or in_reply_to, or own message_id. Add these to the INSERT query.

**Step 4: Add thread endpoint**

In `imap_routes.py`, add `GET /api/inbox/<id>/thread`:

```python
@email_manager_bp.route("/api/inbox/<int:email_id>/thread", methods=["GET"])
@login_required
def get_email_thread(email_id):
    # Get thread_id for this email, then fetch all emails with same thread_id
    # Return sorted by received_at ASC
```

**Step 5: Show thread in detail panel**

In `viewEmail()`, after loading the email detail, fetch thread data. If thread count > 1, render a collapsible thread section showing each message with from, date, and summary/preview. Use textContent for user-generated content (from_name, subject, summary) to prevent XSS.

Add a `<div id="email-thread-container"></div>` to the detail panel HTML.

**Step 6: Add thread CSS**

```css
.thread-section { margin-top: 16px; border-top: 1px solid #333; padding-top: 12px; }
.thread-section h4 { color: #00FFFF; font-size: 14px; margin-bottom: 8px; }
.thread-msg {
    padding: 8px 12px; border-left: 2px solid #333; margin-bottom: 4px;
    cursor: pointer; transition: all 0.2s;
}
.thread-msg:hover { border-left-color: #00FFFF; background: rgba(0,255,255,0.05); }
.thread-msg--active { border-left-color: #FFC800; background: rgba(255,200,0,0.05); }
```

**Step 7: Commit**

```bash
git add database/migrations/098_email_threading.sql ai_bridge/email_intelligence.py platform_v2/tools/email_manager/imap_routes.py platform_v2/templates/tools/email_manager.html
git commit -m "feat(email): email threading with conversation grouping"
```

---

## Task 8: Telegram Smart Notifications

Send instant Telegram notifications for urgent/action_required emails, and periodic digests for everything else.

**Files:**
- Create: `database/migrations/099_telegram_email_notifications.sql`
- Modify: `ai_bridge/agent_loop.py` (add email notification job + notification methods)
- Modify: `ai_bridge/telegram_gateway.py` (access to bot for sending)

**Step 1: Create migration**

Create `database/migrations/099_telegram_email_notifications.sql`:

```sql
-- Track which emails have been notified via Telegram
ALTER TABLE email_inbox ADD COLUMN IF NOT EXISTS telegram_notified_at TIMESTAMP;

-- Email notification preferences per Telegram user
CREATE TABLE IF NOT EXISTS telegram_email_prefs (
    id SERIAL PRIMARY KEY,
    telegram_user_id INTEGER REFERENCES telegram_users(id),
    notify_urgent BOOLEAN DEFAULT TRUE,
    notify_action_required BOOLEAN DEFAULT TRUE,
    notify_informational BOOLEAN DEFAULT FALSE,
    notify_newsletter BOOLEAN DEFAULT FALSE,
    notify_spam BOOLEAN DEFAULT FALSE,
    digest_enabled BOOLEAN DEFAULT TRUE,
    digest_interval_minutes INTEGER DEFAULT 60,
    last_digest_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_tep_telegram_user UNIQUE (telegram_user_id)
);
```

**Step 2: Run migration**

```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/099_telegram_email_notifications.sql
```

**Step 3: Add email notification job to agent_loop.py**

Register a new APScheduler job that runs every 30 seconds:

```python
self.scheduler.add_job(
    with_app_context(self._notify_email_telegram),
    trigger=IntervalTrigger(seconds=30),
    id="agent_email_telegram_notify",
    name="Agent Loop: Email Telegram Notifications",
    replace_existing=True,
)
```

**Step 4: Implement _notify_email_telegram in AgentLoop**

This method:
1. Gets authorized Telegram users with email prefs (LEFT JOIN telegram_email_prefs)
2. For each user, queries un-notified urgent/action_required emails
3. Sends instant Telegram notification with inline action buttons (Reply, Archive, Star, Mark Read)
4. Marks emails as `telegram_notified_at = NOW()`
5. For digest: checks if enough time has passed since last_digest_at
6. Queries remaining un-notified non-urgent emails
7. Sends a digest summary message
8. Updates last_digest_at

**Step 5: Implement _send_email_notification and _send_email_digest helper methods**

- `_send_email_notification(telegram_id, email, instant)`: Format single email as Telegram message with emoji per category, inline buttons
- `_send_email_digest(telegram_id, emails)`: Format digest with numbered list, summary per email

Both use `asyncio.run_coroutine_threadsafe()` to send via the Telegram bot's event loop.

Inline button callback_data format: `email_reply_{id}`, `email_archive_{id}`, `email_star_{id}`, `email_read_{id}`

**Step 6: Commit**

```bash
git add database/migrations/099_telegram_email_notifications.sql ai_bridge/agent_loop.py
git commit -m "feat(email): Telegram smart notifications — instant for urgent, digest for rest"
```

---

## Task 9: Telegram Email Interaction

Add Telegram callback handlers for email actions (reply, archive, star, mark read) and handle reply-via-Telegram to send email responses via SMTP.

**Files:**
- Modify: `ai_bridge/telegram_gateway.py` (add email callback handlers, reply flow, cancel command)

**Step 1: Register email callback handler**

In `telegram_gateway.py` `__init__` where handlers are registered (~line 102-111), add:

```python
from telegram.ext import CallbackQueryHandler
self.application.add_handler(CallbackQueryHandler(self._email_callback, pattern=r"^email_"))
self.application.add_handler(CommandHandler("cancel", self._cmd_cancel))
```

**Step 2: Implement _email_callback handler**

Parse callback_data (format: `email_{action}_{id}`). Actions:
- `archive`: SET is_archived = TRUE, edit message to show "Archived"
- `star`: Toggle is_starred, edit message to show status
- `read`: SET is_read = TRUE, edit message to show "Marked as read"
- `reply`: Set `context.user_data["pending_reply_email_id"] = email_id`, prompt user to type reply

**Step 3: Handle reply messages in _handle_message**

At the top of `_handle_message` (~line 365), check for `context.user_data.get("pending_reply_email_id")`. If set, call `_send_email_reply()` instead of normal routing.

**Step 4: Implement _send_email_reply**

1. Get reply text from message
2. If text is "/cancel", abort and clear state
3. Get original email (from_address, subject, message_id)
4. Get default SMTP settings
5. Build MIMEText email with In-Reply-To header
6. Send via SMTP
7. Log to email_logs
8. Log governance event
9. Mark original as read
10. Clear pending_reply_email_id
11. Confirm to user

**Step 5: Add _cmd_cancel handler**

Clears `pending_reply_email_id` from context.user_data if present.

**Step 6: Add necessary imports to telegram_gateway.py**

Ensure `smtplib`, `MIMEText`, `get_db`, `log_governance_event` are imported.

**Step 7: Commit**

```bash
git add ai_bridge/telegram_gateway.py
git commit -m "feat(email): Telegram email interaction — reply, archive, star, mark read via inline buttons"
```

---

## Task 10: Light Mode CSS Compatibility

Ensure all new components work correctly with light color scheme. Defensive CSS only.

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html` (add light mode CSS overrides)

**Step 1: Add light mode CSS rules**

At the end of the `<style>` section in `email_manager.html`, add:

```css
@media (prefers-color-scheme: light) {
    .em-stats-bar { background: #f0f4f8; border-color: #0088aa; }
    .em-stats-label { color: #333; }
    .em-stats-value { color: #006688; }
    .em-bulk-bar { background: #fff8e0; border-color: #cc9f00; }
    .em-confirm-dialog { background: #ffffff; border-color: #0088aa; }
    .em-confirm-message { color: #333; }
    .thread-msg { border-left-color: #ddd; }
    .thread-msg:hover { border-left-color: #0088aa; background: rgba(0,136,170,0.05); }
    .thread-from { color: #333; }
    .thread-preview { color: #666; }
    .account-badge { background: rgba(0,136,170,0.1); color: #006688; border-color: rgba(0,136,170,0.2); }
}
```

**Step 2: Commit**

```bash
git add platform_v2/templates/tools/email_manager.html
git commit -m "feat(email): light mode CSS compatibility for Phase 2 components"
```

---

## Execution Order

Tasks 1-3 are independent quick wins. Task 4 depends on existing SMTP config. Task 5 is independent. Task 6-7 are independent. Tasks 8-9 depend on each other (8 first, then 9). Task 10 is last (cleanup).

Recommended order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10

## Post-Implementation

After all tasks are complete:
1. Restart container: `docker compose restart archie_platform`
2. Update Dev HQ via MCP tools
3. Update MEMORY.md with key patterns learned

# Email HQ — Module Design

**Date**: 2026-04-24
**Category**: AI Command (platform dashboard)
**Status**: Approved by user 2026-04-24

---

## Goal

Enable Kytran to see and oversee all email activity across AI agents, human agents, and business addresses — in one platform module. Agents can send and receive email; Kytran has full visibility of every mailbox.

---

## Email Address Hierarchy

| Type | Format | Count |
|------|--------|-------|
| AI agents | `{codename}@kytranempowerment.com` | 34 (forge@, vigil@, archie@, codex@, etc.) |
| Human agents | `firstname.lastname@kytranempowerment.com` | As hired |
| Business/functional | `{role}@kytranempowerment.com` | 10 initial |

**Business addresses to provision:**
`billing@`, `support@`, `info@`, `admin@`, `security@`, `no-reply@`, `hello@`, `careers@`, `press@`, `legal@`

---

## Module: email_manager (re-enabled, moved to ai_command)

Currently disabled (`⛔`). Re-enable in `module_registry.py` under `ai_command` category. Existing routes.py + imap_routes.py are kept and extended.

---

## Tab Structure (5 tabs)

### Tab 1 — Overview
- **Stats row**: Total unread · Sent today · Agents wired · Not provisioned
- **Live activity feed**: Last 50 email events across all mailboxes
  - Each row: agent name · direction (↗ SENT / ↙ RECV) · subject (truncated) · from/to · timestamp
  - 30s auto-refresh

### Tab 2 — Inbox
- **Left sidebar** (200px): All mailboxes grouped (AI agents / Business / Human). Unread badge per mailbox. "All Inboxes" at top.
- **Right panel**: Thread list for selected mailbox (from, subject, date, read/unread). Click → full email view (headers + body).
- Kytran can read every mailbox.
- Filter: unread / all / flagged

### Tab 3 — Sent
- Same sidebar structure as Inbox.
- Shows outbound messages per mailbox.
- Columns: To · Subject · Date sent · Status (delivered/bounced)

### Tab 4 — Agents
- Table: agent name · email address · mailbox status (✅ Active / ⚠ Not provisioned / ❌ Error)
- "Provision" button per row → calls Stalwart admin API to create mailbox
- "Provision All AI Agents" bulk action
- Business addresses section below with same status + provision controls
- Human agents section (manual entry of firstname.lastname)

### Tab 5 — Settings
- SMTP config display (pre-filled from .env — read-only, shows server/port/from)
- IMAP polling interval (default: 5 min)
- Stalwart admin API connection test button
- Email templates section (password reset, alert notifications)

---

## Backend Architecture

### New: `stalwart_service.py`
Wraps Stalwart admin API (REST). Functions:
- `create_mailbox(address)` → provision new mailbox in Stalwart
- `delete_mailbox(address)` → remove mailbox
- `list_mailboxes()` → all accounts on the server
- `test_connection()` → health check for Agents/Settings tab

Stalwart admin API base URL from env `STALWART_ADMIN_URL` (default `http://192.168.1.200:8080`).
Admin credentials from `STALWART_ADMIN_USER` / `STALWART_ADMIN_PASSWORD`.

### DB migrations

**Migration A** — `agents.email` column:
```sql
ALTER TABLE agents ADD COLUMN IF NOT EXISTS email VARCHAR(200);
```

**Migration B** — `email_mailboxes` table:
```sql
CREATE TABLE IF NOT EXISTS email_mailboxes (
    id SERIAL PRIMARY KEY,
    address VARCHAR(200) NOT NULL UNIQUE,
    mailbox_type VARCHAR(20) NOT NULL CHECK (mailbox_type IN ('ai_agent', 'human_agent', 'business')),
    owner_agent_id INTEGER REFERENCES agents(id),
    display_name VARCHAR(200),
    provisioned BOOLEAN DEFAULT FALSE,
    provisioned_at TIMESTAMP,
    active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

**Migration C** — `email_activity_log` table:
```sql
CREATE TABLE IF NOT EXISTS email_activity_log (
    id SERIAL PRIMARY KEY,
    mailbox_address VARCHAR(200) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('sent', 'received')),
    from_address TEXT,
    to_address TEXT,
    subject TEXT,
    message_id VARCHAR(500),
    size_bytes INTEGER,
    read BOOLEAN DEFAULT FALSE,
    logged_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_email_activity_log_mailbox ON email_activity_log(mailbox_address, logged_at DESC);
```

### New agent loop job: `email_imap_sync`
- Runs every 5 minutes
- For each provisioned mailbox: polls IMAP, syncs new messages to `email_activity_log`
- Updates unread counts
- Uses existing IMAP code from `imap_routes.py`

### Module registry
- Move `email_manager` from disabled to `ai_command` category
- Icon: `mail`
- Route: `/tools/email-manager`
- Permissions: `admin_required`

---

## Stalwart Admin API Notes

Stalwart exposes a REST admin API. Key endpoints:
- `POST /api/principal` — create account (mailbox)
- `DELETE /api/principal/{account}` — delete account
- `GET /api/principal` — list accounts

If Stalwart admin API port is not yet exposed, it may need to be added to docker-compose.yml (internal network only, no public exposure).

---

## Seeding

On first enable, the Agents tab pre-populates `email_mailboxes` with:
- All 34 AI agents auto-mapped: `{codename.lower()}@kytranempowerment.com`
- 10 business addresses
- Status = `not provisioned` until Kytran clicks Provision

---

## Testing

| Scenario | Expected |
|----------|---------|
| Overview tab loads | Stats cards + activity feed visible, 30s refresh works |
| Inbox — select agent mailbox | Thread list loads from IMAP, click message shows full body |
| Sent tab | Shows outbound from `email_logs` table |
| Agents tab — Provision button | Stalwart API called, mailbox created, status → Active |
| Bulk provision all AI agents | All 34 mailboxes provisioned in Stalwart |
| IMAP sync job | New emails appear in email_activity_log, Overview feed updates |
| Settings — connection test | Shows SMTP + Stalwart API status |

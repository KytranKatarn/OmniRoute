# Email HQ Redesign — Full Spec
**Date**: 2026-05-10
**Module**: `email_manager` · `/tools/email-manager`
**Status**: Approved for implementation

---

## Goals

1. Replace the flat single-panel email viewer with a three-panel command center
2. Provision `kytran@kytranempowerment.com` as the owner's personal inbox — pinned at top
3. Store full email bodies in sync (not just metadata) to enable fast reads, AI triage, and search
4. Add AI priority triage using existing DHQ agents (no new models)
5. Add Reply / Forward / Draft Reply functionality (currently compose-only, no reply)
6. Organize 49 mailboxes into smart pinned views + department groups
7. Fully responsive for Samsung Galaxy Z Fold 5 (folded 480px · unfolded 1812px)

---

## Current State (Gaps to Fix)

| Gap | Current | Target |
|-----|---------|--------|
| `kytran@` inbox | Not provisioned, not in DB | Provisioned in Stalwart, pinned at top |
| Email bodies | Metadata only (subject/from/to/size) | Full HTML + plain text synced to DB |
| Reply | Not implemented | Reply / Reply All / Forward / Draft Reply |
| AI triage | None | Priority badge per message (ACTION/REVIEW/INFO) |
| Sidebar | Flat list | Smart Pinned + collapsed dept groups |
| Smart views | None | All Unread, All Business with live unread counts |
| Message list | Subject + sender + time | Avatar · subject · preview · badge · mailbox tag |
| Layout | Single panel | Three-panel (nav · list · read pane) |

---

## Architecture

### Three-Panel Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  EMAIL HQ                                              [15 unread]│
├──────────────┬────────────────────────┬────────────────────────┤
│  LEFT PANEL  │    CENTER PANEL        │    RIGHT PANEL         │
│  200px       │    280px               │    flex (fills rest)   │
│              │                        │                        │
│  ★ kytran@  │  [filter chips]        │  Subject               │
│  📬 Business │  ─────────────────     │  From → To · Time      │
│  🔔 Unread   │  Msg row 1 🔴 ACTION  │  Body (full HTML)      │
│  ─────────── │  Msg row 2 🟡 REVIEW  │                        │
│  Depts (17)  │  Msg row 3 🟢 INFO    │  [Reply][Fwd][Archive] │
│  ▸ Bridge    │  Msg row 4            │  ─────────────────────  │
│  ▾ Engineering│  ...                  │  🤖 AI Actions panel   │
│    forge@    │                        │  [Draft Reply][Assign] │
│    probe@    │                        │  AI suggestion card    │
│  ▸ Creative  │                        │                        │
│              │                        │                        │
│  [✍ Compose] │                        │                        │
└──────────────┴────────────────────────┴────────────────────────┘
```

### Fold 5 Responsive Breakpoints

| State | Width | Behaviour |
|-------|-------|-----------|
| Folded | ≤600px | Hamburger drawer for left panel · message list full-screen · read pane slides in full-screen |
| Tablet | 601–1024px | Left panel collapsible (icon-only when collapsed) · list + read pane split |
| Unfolded | ≥1025px | All three panels visible simultaneously |

---

## Data Model

### 1. New table: `email_messages`

Stores full email content synced from IMAP.

```sql
CREATE TABLE email_messages (
    id              SERIAL PRIMARY KEY,
    mailbox_id      INTEGER NOT NULL REFERENCES email_mailboxes(id) ON DELETE CASCADE,
    message_id      TEXT NOT NULL,                    -- RFC2822 Message-ID header
    uid             INTEGER,                          -- IMAP UID
    subject         TEXT,
    from_address    TEXT,
    to_address      TEXT,
    cc_address      TEXT,
    reply_to        TEXT,
    received_at     TIMESTAMPTZ,
    body_html       TEXT,                             -- full HTML body
    body_text       TEXT,                             -- plain text fallback
    body_preview    TEXT,                             -- first 300 chars of plain text
    has_attachments BOOLEAN DEFAULT FALSE,
    attachment_names TEXT[],                          -- filenames only, no binary
    size_bytes      INTEGER,
    is_read         BOOLEAN DEFAULT FALSE,
    is_starred      BOOLEAN DEFAULT FALSE,
    is_archived     BOOLEAN DEFAULT FALSE,
    ai_priority     TEXT CHECK (ai_priority IN ('action', 'review', 'info', NULL)),
    ai_suggestion   TEXT,                             -- agent's triage note
    ai_agent_id     INTEGER REFERENCES agents(id),   -- which agent triaged this
    ai_triaged_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(mailbox_id, message_id)
);

CREATE INDEX idx_email_messages_mailbox ON email_messages(mailbox_id, received_at DESC);
CREATE INDEX idx_email_messages_unread  ON email_messages(mailbox_id, is_read) WHERE is_read = FALSE;
CREATE INDEX idx_email_messages_priority ON email_messages(ai_priority) WHERE ai_priority IS NOT NULL;
```

### 2. New column: `email_mailboxes.mailbox_type`

Add `'owner'` to the existing type constraint to distinguish `kytran@` from business/agent mailboxes.

```sql
ALTER TABLE email_mailboxes DROP CONSTRAINT IF EXISTS email_mailboxes_mailbox_type_check;
ALTER TABLE email_mailboxes ADD CONSTRAINT email_mailboxes_mailbox_type_check
    CHECK (mailbox_type IN ('ai_agent', 'business', 'owner'));
```

### 3. `kytran@` mailbox row

Inserted during provisioning step (see Phase 1). `display_name = 'Kytran Katarn'`, `mailbox_type = 'owner'`.

---

## Phase 1 — kytran@ Provisioning

**Why first**: All other phases depend on the mailbox existing in DB and Stalwart.

Steps:
1. Call `stalwart_service.create_mailbox('kytran')` → generates password, creates Stalwart account with 10GB quota
2. Insert row into `email_mailboxes`: `address='kytran@kytranempowerment.com'`, `display_name='Kytran Katarn'`, `mailbox_type='owner'`, `provisioned=true`, `active=true`
3. Insert credentials into `email_imap_settings` for IMAP sync
4. Verify with `stalwart_service.get_mailbox('kytran')` — confirm account exists
5. Run one manual IMAP sync pass to confirm connection works

**Stalwart quota**: 10GB (vs 1GB for agents). Owner mailbox gets priority in sync.

---

## Phase 2 — Full Body Sync (IMAP Enhancement)

Update `sync_jobs.py` to fetch full message content instead of metadata only.

### Sync logic changes

```python
# Per-message fetch (currently only fetches RFC822.SIZE)
# New: fetch RFC822 (full message) for unsynced UIDs

def _sync_mailbox_full(conn, mailbox_id, address):
    # 1. Get already-synced UIDs from email_messages
    synced_uids = get_synced_uids(mailbox_id)

    # 2. Fetch all UIDs from IMAP INBOX
    imap_uids = fetch_all_uids(conn)

    # 3. Fetch only new (unsynced) messages
    new_uids = [u for u in imap_uids if u not in synced_uids]

    for uid in new_uids[:50]:  # max 50 per cycle to avoid timeout
        raw = conn.uid('fetch', uid, '(RFC822)')
        msg = email.message_from_bytes(raw)

        body_html, body_text = extract_body(msg)
        preview = (body_text or '')[:300].strip()
        attachments = extract_attachment_names(msg)

        insert_email_message(
            mailbox_id=mailbox_id,
            uid=uid,
            message_id=msg['Message-ID'],
            subject=msg['Subject'],
            from_address=msg['From'],
            body_html=body_html,
            body_text=body_text,
            body_preview=preview,
            has_attachments=bool(attachments),
            attachment_names=attachments,
            received_at=parsedate(msg['Date']),
        )

        # Queue AI triage (async, non-blocking)
        queue_ai_triage(mailbox_id=mailbox_id, message_id=msg['Message-ID'])
```

### Sync schedule

Keep existing 5-min APScheduler job. Owner mailbox (`kytran@`) synced first in each cycle.

---

## Phase 3 — AI Triage Pipeline

After each new message is stored, dispatch to a DHQ agent for priority classification.

### Agent routing

All triage uses `capability='classify'` (mapped to Analytics & Intelligence → S.P.E.C.T.R.A.) for the priority decision. The `context` dict carries mailbox type so the agent can tailor its suggestion. For owner inbox (`kytran@`), use `capability='summarize'` instead (Documentation & Knowledge → C.O.D.E.X.).

| Mailbox / Content | Capability | Home dept |
|-------------------|-----------|-----------|
| `kytran@` (owner inbox) | `summarize` | Documentation & Knowledge |
| All other mailboxes | `classify` | Analytics & Intelligence |

Both capabilities are present in `CAPABILITY_DEPARTMENT_MAP`. No new capabilities needed.

### Triage prompt (per agent dispatch)

```
Classify this email as exactly one of: ACTION, REVIEW, INFO.
- ACTION: requires a response or payment within 7 days
- REVIEW: worth reading but no immediate action needed
- INFO: notifications, confirmations, no action needed

Return JSON: {"priority": "action|review|info", "suggestion": "<one sentence>"}

Subject: {subject}
From: {from_address}
Preview: {body_preview}
```

### Dispatch call

```python
from tools.department_hq.services.department_dispatcher import dispatch_json

result = dispatch_json(
    capability=capability,
    prompt=triage_prompt,
    max_tokens=100,
    context={'source': 'email_triage', 'mailbox': address}
)
# Update email_messages: ai_priority, ai_suggestion, ai_agent_id, ai_triaged_at
```

**Non-blocking**: triage runs in a background thread after sync. Messages show without badge until triage completes (badge appears when page refreshes or via polling).

---

## Phase 4 — Frontend Rebuild

### Left Panel

- **Pinned section** (always visible, never collapsed):
  - `★ kytran@` — green, unread badge in red
  - `📬 All Business` — unread badge in amber
  - `🔔 All Unread` — total unread count badge in blue
- **Departments section** (17 groups, all collapsed by default):
  - Clicking a dept header expands to show its agent mailboxes
  - Each mailbox shows unread count if > 0
  - Active selection highlighted with left border accent
- **Compose button** pinned at bottom

### Center Panel (Message List)

- Filter chips: All · Unread · Action · Review · Today
- Per-row: avatar initial · sender name (bold if unread) · subject (bold if unread) · preview · time · mailbox tag · AI priority badge
- Clicking a row opens read pane, marks message read
- Unread rows have `background: #0f1528` highlight

### Right Panel (Read Pane)

- Header: breadcrumb path (mailbox > subject) + close
- Email metadata: from/to/time + AI priority badge
- Full body rendered (HTML sanitized with bleach, or plain text fallback)
- Actions: Reply · Forward · Archive · Delete
- AI panel (always shown, collapsed by default on mobile):
  - Agent name displayed (e.g. "L.E.D.G.E.R. assigned")
  - Buttons: Draft Reply · Summarize · Assign Agent · Flag Follow-up
  - Suggestion card showing agent's triage note
- **Reply flow**: clicking Reply opens compose modal pre-filled with `Re: {subject}`, `To: {from_address}`, quoted original body

### Compose Modal

Existing modal extended with:
- Reply / Reply All / Forward pre-fill support
- Quoted body section (collapsible)
- From-address defaults to the mailbox the email arrived in

---

## New Routes

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/email/messages` | List messages with filters (mailbox_id, priority, unread, limit, offset) |
| GET | `/api/email/messages/<id>` | Full message detail (marks read) |
| GET | `/api/email/messages/smart/all-business` | Unified business inbox |
| GET | `/api/email/messages/smart/all-unread` | All unread across all mailboxes |
| POST | `/api/email/messages/<id>/reply` | Send reply (creates compose from existing message) |
| POST | `/api/email/messages/<id>/forward` | Forward a message |
| POST | `/api/email/messages/<id>/archive` | Archive (sets is_archived=true) |
| DELETE | `/api/email/messages/<id>` | Delete message |
| POST | `/api/email/messages/<id>/star` | Toggle star |
| POST | `/api/email/messages/<id>/ai-action` | Trigger AI action (draft_reply, summarize, assign, flag) |
| GET | `/api/email/sidebar/counts` | Unread counts for all mailboxes + smart views (used for badge updates) |
| POST | `/api/email/mailboxes/provision-owner` | Provision kytran@ in Stalwart + DB |

---

## Migration

```sql
-- Migration NNN_email_hq_redesign.sql

-- 1. email_messages table
CREATE TABLE IF NOT EXISTS email_messages (
    id              SERIAL PRIMARY KEY,
    mailbox_id      INTEGER NOT NULL REFERENCES email_mailboxes(id) ON DELETE CASCADE,
    message_id      TEXT NOT NULL,
    uid             INTEGER,
    subject         TEXT,
    from_address    TEXT,
    to_address      TEXT,
    cc_address      TEXT,
    reply_to        TEXT,
    received_at     TIMESTAMPTZ,
    body_html       TEXT,
    body_text       TEXT,
    body_preview    TEXT,
    has_attachments BOOLEAN DEFAULT FALSE,
    attachment_names TEXT[],
    size_bytes      INTEGER,
    is_read         BOOLEAN DEFAULT FALSE,
    is_starred      BOOLEAN DEFAULT FALSE,
    is_archived     BOOLEAN DEFAULT FALSE,
    ai_priority     TEXT CHECK (ai_priority IN ('action', 'review', 'info')),
    ai_suggestion   TEXT,
    ai_agent_id     INTEGER REFERENCES agents(id),
    ai_triaged_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(mailbox_id, message_id)
);

-- 2. Add 'owner' to mailbox_type constraint
ALTER TABLE email_mailboxes DROP CONSTRAINT IF EXISTS email_mailboxes_mailbox_type_check;
ALTER TABLE email_mailboxes ADD CONSTRAINT email_mailboxes_mailbox_type_check
    CHECK (mailbox_type IN ('ai_agent', 'business', 'owner'));

-- 3. Indexes
CREATE INDEX IF NOT EXISTS idx_email_messages_mailbox ON email_messages(mailbox_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_email_messages_unread ON email_messages(mailbox_id, is_read) WHERE is_read = FALSE;
CREATE INDEX IF NOT EXISTS idx_email_messages_priority ON email_messages(ai_priority) WHERE ai_priority IS NOT NULL;
```

---

## Build Sequence

| Phase | Description | Key files |
|-------|-------------|-----------|
| 1 | kytran@ provisioning | `stalwart_service.py`, `mailbox_routes.py`, migration |
| 2 | Full body sync | `sync_jobs.py`, `email_messages` table |
| 3 | AI triage pipeline | `sync_jobs.py` (triage dispatch), `imap_routes.py` (triage endpoints) |
| 4a | New API routes | New `messages_routes.py` |
| 4b | Frontend — left panel + message list | `email_manager.html`, `email_manager.js` |
| 4c | Frontend — read pane + reply | `email_manager.html`, `email_manager.js` |
| 4d | Responsive (Fold 5) | `email_manager.css` |

---

## Testing Checklist

- [ ] `kytran@` exists in Stalwart after provisioning
- [ ] `kytran@` row in `email_mailboxes` with type='owner'
- [ ] IMAP sync connects and stores full bodies to `email_messages`
- [ ] AI triage fires after sync and updates `ai_priority` + `ai_suggestion`
- [ ] Three-panel layout renders correctly on 1440px desktop
- [ ] Fold 5 folded (480px): drawer opens, message list full-screen, read pane slides
- [ ] Fold 5 unfolded (1812px): all three panels visible simultaneously
- [ ] Smart view "All Business" shows messages from all 10 business mailboxes
- [ ] Smart view "All Unread" shows unread from all 49+ mailboxes
- [ ] Reply pre-fills subject, to-address, quoted body
- [ ] Unread badge counts update in left panel after reading a message
- [ ] AI priority badge shows correct colour (red/amber/green)
- [ ] Archive hides message from list without deleting

# Telegram + Email Manager Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Inbox tab with AI analysis to the existing Email Manager module, and configure Gmail IMAP/SMTP

**Architecture:** The Email Manager module already has full backend (routes.py for SMTP/outbound, imap_routes.py for IMAP/inbox) and a 2160-line LCARS UI template with 4 tabs (Templates, Sent, Campaigns, Settings). We add a 5th "Inbox" tab with AI badges and an email detail panel, plus configure Gmail credentials.

**Tech Stack:** Flask, psycopg2, Jinja2, LCARS CSS, existing EmailIntelligence class

---

## Track 1: Telegram Bot (COMPLETED)

- Bot: `@Kytran_Bot` — live and polling
- Token in both `.env` files
- Fixes applied: python-telegram-bot installed, async threading fix, column name fix, check constraint fix
- Account linked: Telegram ID `7445959203` → user_id `2`, authorized, notification rule active

---

## Track 2: Email Manager — Inbox Tab + Gmail Config

### Task 1: Add Inbox Tab to email_manager.html

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html`

**Step 1: Add Inbox tab button (after line 101, before Templates tab)**

Insert a new tab button as the FIRST tab (since inbox is the primary view):

```html
<button class="em-tab active" data-tab="inbox">
    <i data-lucide="inbox"></i> Inbox <span id="unread-badge" class="badge">0</span>
</button>
```

Change the existing Templates tab from `active` to just `em-tab`.

**Step 2: Add Inbox tab content panel**

Insert after line 120, before `tab-templates`. Include:
- Filter bar: category buttons (All, Urgent, Action Required, Informational, Spam), search input, "Check Now" button
- Email list table with columns: Star, From, Subject + AI Summary, Category badge, Priority, Sentiment, Date
- Click row → expand inline detail panel with full body, AI analysis, "Reply" and "Archive" buttons
- Category badges color-coded: urgent=red, action_required=orange, informational=cyan, spam=gray, newsletter=purple
- Priority shown as dots (1-5)

**Step 3: Add Inbox JavaScript**

Functions needed:
- `loadInbox(page, filters)` — calls `GET /api/inbox` with params
- `viewEmail(id)` — calls `GET /api/inbox/{id}`, shows detail panel, marks read
- `toggleStar(id)` — calls `POST /api/inbox/{id}/star`
- `archiveEmail(id)` — calls `POST /api/inbox/{id}/archive`
- `generateDraft(id)` — calls `POST /api/inbox/{id}/draft`
- `checkInboxNow()` — calls `POST /api/inbox/check`
- Auto-refresh every 60s when inbox tab active

**Step 4: Add Inbox CSS**

Style the inbox-specific elements: category badges, priority dots, email detail panel, unread row highlight.

**Step 5: Verify inbox tab loads**

Navigate to `/tools/email-manager` and confirm inbox tab appears with the filter bar. (Will be empty until Gmail is configured.)

**Step 6: Commit**

```bash
git add platform_v2/templates/tools/email_manager.html
git commit -m "feat(email): add Inbox tab with AI analysis badges to Email Manager"
```

---

### Task 2: Add IMAP Settings to Settings Tab

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html` (Settings tab section)

**Step 1: Add IMAP configuration section to Settings tab**

The existing Settings tab only has SMTP config. Add an "IMAP / Incoming Email" section with:
- Pre-filled fields: Host (imap.gmail.com), Port (993), Encryption (SSL), Folder (INBOX)
- User email field (auto-populated from logged-in user)
- App Password field (password input, never displayed back)
- Check interval (dropdown: 1, 2, 5, 10, 15, 30 min)
- Auto-analyze toggle
- "Test Connection" button
- "Save" button

**Step 2: Add IMAP settings JavaScript**

- `loadImapSettings()` — calls `GET /api/imap/settings`
- `saveImapSettings()` — calls `POST /api/imap/settings` (create) or `PUT /api/imap/settings/{id}` (update)
- `testImapConnection(id)` — calls `POST /api/imap/settings/{id}/test`
- Pre-fill email from `{{ current_user.email }}`

**Step 3: Also update SMTP settings section for Gmail defaults**

Pre-fill: smtp.gmail.com, port 587, TLS, same App Password

**Step 4: Commit**

```bash
git add platform_v2/templates/tools/email_manager.html
git commit -m "feat(email): add IMAP settings section with Gmail defaults to Settings tab"
```

---

### Task 3: Configure Gmail Credentials

**Step 1: Get Gmail App Password from user**

User needs to:
1. Go to https://myaccount.google.com/apppasswords
2. Generate an App Password for "Mail"
3. Copy the 16-character password

**Step 2: Configure via the Email Manager Settings UI**

Save IMAP and SMTP settings through the new Settings tab with the App Password.

**Step 3: Test connections**

Click "Test Connection" for both IMAP and SMTP.

**Step 4: Trigger inbox check**

Click "Check Now" on the Inbox tab to pull in emails.

**Step 5: Verify AI analysis**

Confirm emails appear with category/priority/sentiment badges after analysis.

---

### Task 4: Polish and Verify

**Step 1: Test email detail view**

Click an email, verify full body renders, AI summary displays.

**Step 2: Test draft reply**

Click "Reply" on an email, verify AI generates a draft, draft appears in detail panel.

**Step 3: Test star/archive**

Verify star toggles, archive removes from inbox list.

**Step 4: Test search/filter**

Filter by category, search by subject/sender.

**Step 5: Final commit**

```bash
git add -A
git commit -m "feat(email): Email Manager inbox with Gmail integration"
```

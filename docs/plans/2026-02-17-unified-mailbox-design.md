# Unified Mailbox Config Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Link SMTP to IMAP accounts so each mailbox is a complete send+receive config, with auto-migration of existing data and legacy fallback.

**Architecture:** Add SMTP columns to `email_imap_settings` table, migrate existing `email_settings` data by domain matching, update send flow to use per-account SMTP with fallback to legacy default, and unify the Settings tab UI into per-account cards.

**Tech Stack:** PostgreSQL (migration), Python/Flask (routes), vanilla JS (template)

**Security note:** All innerHTML usage follows existing codebase patterns using `escapeHtml()` for user-provided content. The existing `escapeHtml` utility is already used throughout the template.

---

### Task 1: Database Migration

**Files:**
- Create: `database/migrations/108_unified_mailbox.sql`

**Step 1: Write the migration SQL**

Add SMTP columns to `email_imap_settings` and migrate data from `email_settings` by matching email domains. Only migrate rows with `test_result = 'success'`.

Key columns: `smtp_host`, `smtp_port`, `smtp_user`, `smtp_password_encrypted`, `smtp_encryption`, `from_email`, `from_name`, `reply_to`, `smtp_test_result`, `smtp_test_message`, `smtp_tested_at`.

Data migration UPDATE matches `SPLIT_PART(imap_user, '@', 2) = SPLIT_PART(from_email, '@', 2)` where `imap.smtp_host IS NULL`.

**Step 2: Run the migration**

Run: `docker exec archie_database psql -U archie -d archie` and execute the SQL.

**Step 3: Verify**

Run: `SELECT id, name, imap_user, smtp_host, from_email, smtp_test_result FROM email_imap_settings;`

Expected: Both accounts have SMTP fields populated.

**Step 4: Commit**

---

### Task 2: Backend — Per-account SMTP endpoints

**Files:**
- Modify: `platform_v2/tools/email_manager/imap_routes.py`

**Step 1: Update `get_imap_settings` SELECT** (line 51-58) to include all SMTP columns.

**Step 2: Update `create_imap_setting` INSERT** (line 85-105) to accept optional SMTP fields.

**Step 3: Update `update_imap_setting` field list** (line 127-138) to include SMTP fields, plus handle `smtp_password` like `imap_password`.

**Step 4: Add `test_account_smtp` endpoint** — `POST /api/imap/settings/<id>/test-smtp`. Uses `smtplib` to test SMTP connection, updates `smtp_test_result` columns. Pattern matches existing `test_settings` in routes.py.

**Step 5: Add `get_smtp_accounts` endpoint** — `GET /api/smtp-accounts`. Returns active accounts with SMTP configured (for compose "From" dropdown).

**Step 6: Commit**

---

### Task 3: Backend — Update send flow

**Files:**
- Modify: `platform_v2/tools/email_manager/routes.py` (send_email, line 624-760)
- Modify: `platform_v2/tools/email_manager/imap_routes.py` (send_draft, line 873-1002)

**Step 1: Add `get_smtp_for_sending(cur, account_id=None)` helper** in routes.py after `render_template_vars`. Tries per-account SMTP first, falls back to legacy `email_settings` default.

**Step 2: Update `send_email`** to accept `account_id` from request body, use `get_smtp_for_sending()` instead of direct `email_settings` query.

**Step 3: Update `send_draft`** to lookup `imap_setting_id` from the inbox email being replied to, then query SMTP from that account. Falls back to legacy `email_settings` if no per-account SMTP.

**Step 4: Commit**

---

### Task 4: Frontend — Unified Settings tab

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html`

**Step 1: Replace Settings tab content** (lines 546-679). Remove separate SMTP panel and inline IMAP form. Replace with a single "Email Accounts" panel rendered by `loadUnifiedAccounts()`.

**Step 2: Add `loadUnifiedAccounts()` JS function.** Fetches `/api/imap/settings`, renders cards showing both incoming (IMAP) and outgoing (SMTP) info with Edit and Test SMTP buttons. Uses existing `escapeHtml()` for all user content.

**Step 3: Replace `loadSettings()` call** with `loadUnifiedAccounts()` in the Settings tab init.

**Step 4: Add unified account edit modal HTML.** Two sections: INCOMING (IMAP) fields and OUTGOING (SMTP) fields in one modal. Field IDs prefixed to avoid conflicts with old IMAP form (which is now removed).

**Step 5: Add `editUnifiedAccount(id)` and `saveUnifiedAccount(event)` JS functions.** Load fills both IMAP+SMTP fields. Save PUTs to `/api/imap/settings/<id>`.

**Step 6: Add `testAccountSmtp(id)` JS function.** POSTs to `/api/imap/settings/<id>/test-smtp`.

**Step 7: Commit**

---

### Task 5: Frontend — Compose "From" dropdown

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html`

**Step 1: Add "From" select** in compose modal before the "Template" select.

**Step 2: Update `showComposeModal()`** to fetch `/api/smtp-accounts` and populate the dropdown. Accept optional `replyAccountId` param for auto-selection.

**Step 3: Update `sendEmail()`** to include `account_id` from the From dropdown in the POST body.

**Step 4: Commit**

---

### Task 6: Frontend — Wizard SMTP step

**Files:**
- Modify: `platform_v2/templates/tools/email_manager.html`

**Step 1: Expand wizard from 4 to 5 steps.** New step 4 = SMTP config, old step 4 (done) becomes step 5.

**Step 2: Add wizard SMTP step HTML** with fields for SMTP host/port/user/password/encryption/from_email/from_name, plus Skip and "Save & Test SMTP" buttons.

**Step 3: Update `wizardSave()`** to go to SMTP step instead of Done. Auto-fill SMTP fields from provider presets (gmail→smtp.gmail.com:587, zoho→smtppro.zoho.com:587, etc.).

**Step 4: Add `wizardSaveSmtp()` and `wizardSkipSmtp()`** functions. Save PUTs SMTP config then tests. Skip goes straight to Done. Both trigger inbox fetch.

**Step 5: Update `wizardGoStep()`** loop to handle 5 steps.

**Step 6: Commit**

---

### Task 7: Deploy & Verify

**Step 1:** `docker compose restart archie_platform`

**Step 2:** Check logs: `docker logs --tail 50 archie_platform` — no errors.

**Step 3:** Settings tab → unified account cards with IMAP+SMTP info.

**Step 4:** Compose → "From" dropdown with SMTP-configured accounts.

**Step 5:** Wizard → SMTP step after IMAP test with provider presets.

**Step 6:** Final commit.

# Google Work Suite Phase 1: Gmail Integration with Agent Accounts — Design Spec

## Overview

Create a new Google Work Suite module that provides Gmail integration with OAuth 2.0 authentication. Agents connected with Gmail accounts get full email autonomy (read, send, reply). Users get read + draft with human approval (unless rules auto-approve). AI-powered email processing via Bridge dispatch classifies incoming emails, generates smart replies, and applies user-defined rules.

**Goal:** Build a unified Google integration hub starting with Gmail — OAuth account connection, inbox sync/cache, compose/reply, agent auto-processing, and user-defined email rules. Agents with Gmail accounts become autonomous email-capable team members.

## Scope

Five capabilities:
1. **Google OAuth** — connect Gmail accounts (users + agents) via OAuth 2.0, token storage + refresh
2. **Gmail inbox** — sync, cache, read, search, labels via Gmail API
3. **Compose/send** — send emails (agents), create drafts (users), reply/forward
4. **Agent auto-processing** — APScheduler polls agent inboxes, Bridge AI classifies + auto-replies
5. **Email rules** — user-defined conditions → actions (auto-reply, forward, label, ignore)

## Database Schema

### New table: `google_accounts`

```sql
CREATE TABLE IF NOT EXISTS google_accounts (
    id SERIAL PRIMARY KEY,
    owner_type VARCHAR(20) NOT NULL,
    owner_id INTEGER NOT NULL,
    email VARCHAR(200) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    access_token TEXT,
    refresh_token TEXT,
    token_expiry TIMESTAMP,
    scopes TEXT,
    is_primary BOOLEAN DEFAULT TRUE,
    permission_level VARCHAR(20) DEFAULT 'full',
    last_sync_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

Permission levels: `'full'` (agents — send directly), `'draft_only'` (users — create drafts, human approves).

### New table: `google_email_cache`

```sql
CREATE TABLE IF NOT EXISTS google_email_cache (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    gmail_id VARCHAR(100) NOT NULL,
    thread_id VARCHAR(100),
    subject TEXT,
    sender VARCHAR(200),
    recipients JSONB DEFAULT '[]',
    snippet TEXT,
    labels JSONB DEFAULT '[]',
    is_read BOOLEAN DEFAULT FALSE,
    is_starred BOOLEAN DEFAULT FALSE,
    has_attachments BOOLEAN DEFAULT FALSE,
    received_at TIMESTAMP,
    cached_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(account_id, gmail_id)
);
```

### New table: `google_email_rules`

```sql
CREATE TABLE IF NOT EXISTS google_email_rules (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    conditions JSONB NOT NULL,
    actions JSONB NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);
```

Conditions: `{"from": "x@y.com", "subject_contains": "invoice", "body_contains": "payment"}`
Actions: `{"auto_reply": true, "template": "Thank you...", "forward_to": "agent@gmail.com", "label": "processed", "ignore": false}`

### Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_google_accounts_owner ON google_accounts(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_google_email_cache_account ON google_email_cache(account_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_google_email_cache_thread ON google_email_cache(thread_id);
CREATE INDEX IF NOT EXISTS idx_google_email_rules_account ON google_email_rules(account_id);
```

## Google API Service

**New file:** `platform_v2/tools/google_work_suite/services/google_api_service.py` (~150 lines)

### OAuth 2.0 Flow

Uses `google-auth-oauthlib` + `google-api-python-client`.

**`get_auth_url(owner_type, owner_id)`** — builds authorization URL with scopes (gmail.modify, gmail.send, calendar, drive.readonly). State encodes owner_type:owner_id.

**`handle_callback(code, state)`** — exchanges code for tokens, stores in `google_accounts` with encrypted tokens. Sets permission_level based on owner_type.

**`get_gmail_client(account_id)`** — loads tokens, refreshes if expired, returns authenticated Gmail API client.

**`refresh_token(account_id)`** — uses refresh_token for new access_token.

### Config (.env)

```
GOOGLE_CLIENT_ID=xxx
GOOGLE_CLIENT_SECRET=xxx
GOOGLE_REDIRECT_URI=http://192.168.1.200:3000/tools/google-work-suite/oauth/callback
GOOGLE_TOKEN_ENCRYPTION_KEY=xxx  # Fernet key
```

### Token encryption

Tokens encrypted at rest using Fernet symmetric encryption. Key from `.env`.

## Gmail Service

**New file:** `platform_v2/tools/google_work_suite/services/gmail_service.py` (~200 lines)

### Core operations

**`sync_inbox(account_id, max_results=50)`** — list messages via API, fetch headers/snippet/labels, UPSERT into cache. Update last_sync_at.

**`get_inbox(account_id, page, per_page, label)`** — query cache with pagination.

**`get_email(account_id, gmail_id)`** — fetch full message body via API, parse MIME.

**`send_email(account_id, to, subject, body, reply_to_id)`** — check permission level. Full → send. Draft_only → create draft. Build MIME, set threading headers if reply.

**`create_draft(account_id, to, subject, body, reply_to_id)`** — Gmail drafts API.

**`apply_label(account_id, gmail_id, label_name)`** — add/remove labels.

**`search_emails(account_id, query)`** — Gmail search API.

### Agent auto-processing

**`process_agent_inbox(account_id)`** — called by APScheduler:
1. Sync inbox
2. For each unread: check rules → execute matching actions
3. No rule match: dispatch to Bridge for classification + draft reply
4. Mark processed as read

## APScheduler Job

**Modified file:** `ai_bridge/agent_loop.py`

Job #23: `agent_email_processing`, runs every 5 minutes. Queries `google_accounts WHERE owner_type='agent'`, calls `process_agent_inbox()` for each.

### Bridge dispatch for email intelligence

No matching rule → dispatch to Bridge:
```python
system_prompt = "Analyze this email. Return JSON: {action: reply|ignore|flag, draft_reply: ..., priority: high|normal|low}"
```
- action=reply + full permission → send immediately
- action=flag → star email + system notification

## API Routes

**New file:** `platform_v2/tools/google_work_suite/routes.py`

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | Render template |
| GET | `/oauth/authorize` | Start OAuth redirect |
| GET | `/oauth/callback` | Handle Google callback |
| GET | `/api/accounts` | List connected accounts |
| DELETE | `/api/accounts/<id>` | Disconnect account |
| GET | `/api/inbox/<account_id>` | Paginated inbox |
| GET | `/api/email/<account_id>/<gmail_id>` | Full email |
| POST | `/api/email/send` | Send or draft |
| POST | `/api/email/sync/<account_id>` | Manual sync |
| GET | `/api/rules/<account_id>` | List rules |
| POST | `/api/rules/<account_id>` | Create/update rule |
| DELETE | `/api/rules/<account_id>/<rule_id>` | Delete rule |

## Frontend

### Template: `google_work_suite.html` (~250 lines)

Tabbed LCARS layout with teal accent (`--gws-accent: #0cf`).

**Top bar:** Account dropdown + "Connect Account" button

**Tabs:** Inbox | Calendar (coming soon) | Drive (coming soon) | Rules

**Inbox tab:** Email list (sender, subject, snippet, time, read/star indicators) + email detail panel (full body, reply/forward). Compose modal (to, subject, body, send/draft buttons). Agent activity indicator.

**Rules tab:** Rule list with conditions/actions summary + active toggle. "New Rule" form.

### JS: `google-work-suite.js` (~400 lines)

Account management, OAuth trigger, inbox loading/pagination, email view, compose/reply, rule CRUD, manual sync.

### CSS: `google-work-suite.css` (~150 lines)

`gws-` prefix. Teal accent `var(--gws-accent, #0cf)`. Standard LCARS panel/tab/modal patterns.

## Module Registration

Add new entry to `module_registry.py`:
- `id="google_work_suite"`, `name="Google Work Suite"`
- `category=ModuleCategory.SAAS_SERVICES`
- `route="/tools/google-work-suite"`

Existing Email Manager, Scheduler, Google Workspace modules remain active during transition. Phase 4 handles consolidation.

## Files Summary

| Action | File | Purpose |
|--------|------|---------|
| **Create** | `database/migrations/160_google_work_suite.sql` | 3 tables + indexes |
| **Create** | `platform_v2/tools/google_work_suite/__init__.py` | Blueprint |
| **Create** | `platform_v2/tools/google_work_suite/routes.py` | 12 endpoints |
| **Create** | `platform_v2/tools/google_work_suite/services/google_api_service.py` | OAuth + API client (~150 lines) |
| **Create** | `platform_v2/tools/google_work_suite/services/gmail_service.py` | Gmail ops + agent processing (~200 lines) |
| **Create** | `platform_v2/templates/tools/google_work_suite.html` | Tabbed LCARS template (~250 lines) |
| **Create** | `platform_v2/static/js/google-work-suite.js` | Inbox, compose, rules (~400 lines) |
| **Create** | `platform_v2/static/css/google-work-suite.css` | LCARS teal theme (~150 lines) |
| **Modify** | `platform_v2/module_registry.py` | Add module entry |
| **Modify** | `platform_v2/requirements.txt` | google-auth, google-api-python-client, cryptography |
| **Modify** | `ai_bridge/agent_loop.py` | Agent email processing job (#23) |

**Total:** ~1,150 lines new code, ~20 lines modifications

## Dependencies

```
google-auth>=2.0
google-auth-oauthlib>=1.0
google-api-python-client>=2.0
cryptography>=41.0
```

## Scope constraints (Phase 1)

- Gmail only — Calendar/Drive tabs shown as "Coming Soon"
- No email thread view (flat list)
- No attachment download/upload (show names only)
- No push notifications (5-minute APScheduler polling)
- No SMTP fallback
- Existing modules untouched (coexist during transition)
- Requires Google Cloud project + OAuth credentials in .env

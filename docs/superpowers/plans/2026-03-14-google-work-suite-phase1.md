# Google Work Suite Phase 1: Gmail Integration — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new Google Work Suite module with Gmail OAuth, inbox sync/cache, compose/reply, agent auto-processing via Bridge, and user-defined email rules — making agents autonomous email team members.

**Architecture:** New `google_work_suite` module with `google_api_service.py` (OAuth + API client), `gmail_service.py` (inbox ops + agent processing), `routes.py` (12 endpoints), and LCARS tabbed frontend. APScheduler job polls agent inboxes every 5 min. Tokens encrypted with Fernet. Permission model: agents=full send, users=draft only (unless rules auto-approve).

**Tech Stack:** Flask, PostgreSQL, google-auth-oauthlib, google-api-python-client, Fernet encryption, vanilla JS, Monaco (not needed Phase 1)

**Key patterns:**
- DB: `from database import get_db_cursor` with `with get_db_cursor(commit=True) as (conn, cur):`
- Routes: `@bp.route(...)` + `@login_required`, local imports, `jsonify()`
- Bridge: `from ai_bridge.archie_bridge import archie_bridge as ai_bridge; result = ai_bridge(prompt, system_prompt, user_id, enable_memory=False)`
- Agent loop: `with_app_context(self._method)`, `IntervalTrigger`, `replace_existing=True`
- LCARS: Antonio font headers, IBM Plex Mono code, CSS vars for theme
- Encryption: Fernet from `cryptography` library
- OAuth: Google requires `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` in .env
- IMPORTANT: All DOM construction must use createElement/textContent — no innerHTML

---

## Task 1: Migration + Dependencies + Module Scaffold

**Files:**
- Create: `database/migrations/160_google_work_suite.sql`
- Create: `platform_v2/tools/google_work_suite/__init__.py`
- Create: `platform_v2/tools/google_work_suite/services/__init__.py`
- Modify: `platform_v2/requirements.txt`
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`

- [ ] **Step 1: Write migration**

```sql
-- Migration 160: Google Work Suite — accounts, email cache, rules
-- Idempotent: safe to run multiple times

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

CREATE TABLE IF NOT EXISTS google_email_rules (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES google_accounts(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    conditions JSONB NOT NULL,
    actions JSONB NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_google_accounts_owner ON google_accounts(owner_type, owner_id);
CREATE INDEX IF NOT EXISTS idx_google_email_cache_account ON google_email_cache(account_id, received_at DESC);
CREATE INDEX IF NOT EXISTS idx_google_email_cache_thread ON google_email_cache(thread_id);
CREATE INDEX IF NOT EXISTS idx_google_email_rules_account ON google_email_rules(account_id);
```

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/160_google_work_suite.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/160_google_work_suite.sql
```

- [ ] **Step 3: Add pip dependencies to requirements.txt**

Append to `platform_v2/requirements.txt`:
```
google-auth>=2.0
google-auth-oauthlib>=1.0
google-api-python-client>=2.0
```

(`cryptography` is likely already installed — check first, add only if missing)

- [ ] **Step 4: Create module scaffold**

`platform_v2/tools/google_work_suite/__init__.py`:
```python
from flask import Blueprint

google_work_suite_bp = Blueprint(
    "google_work_suite",
    __name__,
    url_prefix="/tools/google-work-suite",
)

from . import routes  # noqa: E402, F401
```

`platform_v2/tools/google_work_suite/services/__init__.py`: empty file.

- [ ] **Step 5: Add to module_registry.py**

Add new module entry (after the existing google_workspace entry or at end of MODULES list):
```python
ModuleDefinition(
    id="google_work_suite",
    name="Google Work Suite",
    description="Gmail, Calendar & Drive with AI agents<br>OAuth accounts • Agent email • Smart rules • AI replies",
    icon="mail",
    category=ModuleCategory.SAAS_SERVICES,
    route="/tools/google-work-suite",
    blueprint_import="tools.google_work_suite:google_work_suite_bp",
    required_permissions=[],
    minimum_role="USER",
    enabled=True,
    coming_soon=False,
    priority=12,
    tags=["google", "gmail", "email", "calendar", "agents", "ai"],
),
```

- [ ] **Step 6: Commit**

```bash
git add database/migrations/160_google_work_suite.sql platform_v2/tools/google_work_suite/__init__.py platform_v2/tools/google_work_suite/services/__init__.py platform_v2/requirements.txt platform_v2/module_registry.py
git commit -m "feat(google-work-suite): add migration 160 + module scaffold + dependencies"
```

---

## Task 2: Google API Service — OAuth + Client

**Files:**
- Create: `platform_v2/tools/google_work_suite/services/google_api_service.py`

- [ ] **Step 1: Write the OAuth + API client service (~150 lines)**

```python
"""Google API service — OAuth 2.0 + authenticated API clients.

Public API:
- get_auth_url(owner_type, owner_id)  — build OAuth authorization URL
- handle_callback(code, state)        — exchange code for tokens, store account
- get_gmail_client(account_id)        — return authenticated Gmail API client
- get_account(account_id)             — load account from DB
- list_accounts(owner_type, owner_id) — list connected accounts
- disconnect_account(account_id)      — remove account + tokens
"""
```

Key implementation details:

**OAuth scopes:**
```python
SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
```

**`get_auth_url(owner_type, owner_id)`:**
1. Load GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI from `os.environ`
2. Build `google_auth_oauthlib.flow.Flow.from_client_config()` with scopes
3. Generate state = `f"{owner_type}:{owner_id}:{secrets.token_hex(16)}"` (CSRF protection)
4. Store state nonce in session or DB for verification
5. Return `flow.authorization_url(access_type='offline', include_granted_scopes='true', state=state)`

**`handle_callback(code, state)`:**
1. Parse state → owner_type, owner_id, nonce
2. Exchange code for credentials via `flow.fetch_token(code=code)`
3. Get user email from Gmail API: `service.users().getProfile(userId='me')`
4. Encrypt tokens with Fernet before storing
5. UPSERT into `google_accounts`: email, encrypted access_token, encrypted refresh_token, token_expiry, scopes, permission_level based on owner_type
6. Return `{success, account_id, email}`

**Token encryption:**
```python
from cryptography.fernet import Fernet
FERNET_KEY = os.environ.get("GOOGLE_TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
_fernet = Fernet(FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY)

def _encrypt(text):
    if not text: return None
    return _fernet.encrypt(text.encode()).decode()

def _decrypt(text):
    if not text: return None
    return _fernet.decrypt(text.encode()).decode()
```

**`get_gmail_client(account_id)`:**
1. Load account from DB
2. Decrypt tokens
3. Build `google.oauth2.credentials.Credentials` with token, refresh_token, client_id, client_secret, token_uri
4. If expired, refresh and update DB
5. Return `googleapiclient.discovery.build('gmail', 'v1', credentials=creds)`

**`list_accounts(owner_type=None, owner_id=None)`:** Query google_accounts, return list (without tokens).

**`disconnect_account(account_id, owner_type, owner_id)`:** Verify ownership, DELETE cascade.

- [ ] **Step 2: Verify import**

```bash
docker exec archie_platform python3 -c "from tools.google_work_suite.services.google_api_service import get_auth_url, handle_callback, get_gmail_client; print('OK')"
```

Note: This may fail if google-auth packages aren't installed yet (Docker rebuild needed). The import test should pass after rebuild.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/google_work_suite/services/google_api_service.py
git commit -m "feat(google-work-suite): add Google API service — OAuth + encrypted token storage"
```

---

## Task 3: Gmail Service — Inbox + Send + Agent Processing

**Files:**
- Create: `platform_v2/tools/google_work_suite/services/gmail_service.py`

**Dependencies:** Task 2

- [ ] **Step 1: Write Gmail service (~200 lines)**

```python
"""Gmail service — inbox sync, read, send, draft, agent processing.

Public API:
- sync_inbox(account_id, max_results)  — sync from Gmail API to cache
- get_inbox(account_id, page, per_page, label) — read from cache
- get_email(account_id, gmail_id)      — fetch full email body
- send_email(account_id, to, subject, body, reply_to_id) — send or draft
- create_draft(account_id, to, subject, body, reply_to_id)
- search_emails(account_id, query)
- process_agent_inbox(account_id)      — auto-process for agents
"""
```

**`sync_inbox(account_id, max_results=50)`:**
1. `get_gmail_client(account_id)`
2. `service.users().messages().list(userId='me', maxResults=max_results, labelIds=['INBOX'])`
3. For each message ID: `service.users().messages().get(userId='me', id=msg_id, format='metadata', metadataHeaders=['Subject', 'From', 'To', 'Date'])`
4. Extract: subject, sender (From header), recipients (To), snippet, labelIds, date
5. Check `payload.get('parts', [])` for attachments
6. UPSERT into `google_email_cache` with `ON CONFLICT (account_id, gmail_id) DO UPDATE`
7. Update `google_accounts.last_sync_at`
8. Return count

**`get_inbox(account_id, page=1, per_page=20, label=None)`:**
Query cache with OFFSET/LIMIT, optional label filter (JSONB `@>` operator). Return list of email summaries.

**`get_email(account_id, gmail_id)`:**
Fetch full message via API with `format='full'`. Parse MIME: walk parts, find `text/plain` and `text/html`. Return `{subject, sender, recipients, body_text, body_html, date, labels, attachments: [{filename, mimeType, size}]}`.

**`send_email(account_id, to, subject, body, reply_to_id=None)`:**
1. Load account, check `permission_level`
2. If `'draft_only'`: call `create_draft()` instead, return `{status: 'drafted'}`
3. Build MIME message (`email.mime.text.MIMEText`)
4. If `reply_to_id`: fetch original, set `In-Reply-To` + `References` headers, prepend `Re:` to subject
5. Base64url encode, send via `service.users().messages().send()`
6. Return `{status: 'sent', message_id}`

**`create_draft(account_id, to, subject, body, reply_to_id=None)`:**
Same MIME building, use `service.users().drafts().create()`. Return `{status: 'drafted', draft_id}`.

**`search_emails(account_id, query)`:**
`service.users().messages().list(userId='me', q=query)`. Return matching IDs, fetch from cache or API.

**`process_agent_inbox(account_id)`:**
1. Sync inbox
2. Query unread from cache: `WHERE account_id=%s AND is_read=false`
3. For each unread:
   a. Load rules: `SELECT * FROM google_email_rules WHERE account_id=%s AND is_active=true`
   b. Check conditions: match `from`, `subject_contains`, `body_contains`
   c. If rule matches: execute actions (auto_reply via send_email, forward, apply label)
   d. If no rule: dispatch to Bridge AI for classification
4. Mark processed as read in cache + via API: `service.users().messages().modify(userId='me', id=gmail_id, body={'removeLabelIds': ['UNREAD']})`

**Bridge dispatch (no matching rule):**
```python
from ai_bridge.archie_bridge import archie_bridge as ai_bridge
system_prompt = f"You are an email assistant for agent {agent_name}. Analyze this email and respond with JSON: {{\"action\": \"reply\"|\"ignore\"|\"flag\", \"draft_reply\": \"...\", \"priority\": \"high\"|\"normal\"|\"low\"}}"
result = ai_bridge(prompt=f"From: {sender}\nSubject: {subject}\n\n{body[:2000]}", system_prompt=system_prompt, user_id=owner_id, enable_memory=False)
```
Parse response JSON. If action=reply → send_email. If action=flag → star + notify.

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/google_work_suite/services/gmail_service.py
git commit -m "feat(google-work-suite): add Gmail service — inbox sync, send, agent processing"
```

---

## Task 4: APScheduler Job

**Files:**
- Modify: `ai_bridge/agent_loop.py`

- [ ] **Step 1: Read agent_loop.py to find insertion point**

Find last scheduler.add_job call and stop() job ID list.

- [ ] **Step 2: Add agent email processing job**

After the last job (currently #22 media_analytics_snapshot):
```python
self.scheduler.add_job(
    with_app_context(self._process_agent_emails),
    trigger=IntervalTrigger(minutes=5),
    id="agent_email_processing",
    name="Agent Loop: Gmail Processing",
    replace_existing=True,
)
```

- [ ] **Step 3: Add the method**

```python
def _process_agent_emails(self):
    """Process inboxes for all agent Gmail accounts."""
    try:
        from database import get_db_cursor
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT id FROM google_accounts WHERE owner_type = 'agent'")
            accounts = cur.fetchall()
        if not accounts:
            return
        from tools.google_work_suite.services.gmail_service import process_agent_inbox
        for acc in accounts:
            try:
                process_agent_inbox(acc['id'])
            except Exception as e:
                logger.warning(f"Agent email processing failed for account {acc['id']}: {e}")
    except Exception as e:
        logger.error(f"Agent email job failed: {e}")
```

- [ ] **Step 4: Update job count (22→23) and add to stop() list**

- [ ] **Step 5: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(google-work-suite): add agent email processing APScheduler job (#23)"
```

---

## Task 5: API Routes

**Files:**
- Create: `platform_v2/tools/google_work_suite/routes.py`

- [ ] **Step 1: Write routes.py (~200 lines) with 12 endpoints**

```python
"""Google Work Suite routes — OAuth, inbox, email, rules."""

from flask import request, jsonify, redirect, session
from flask_login import login_required, current_user
from . import google_work_suite_bp


@google_work_suite_bp.route("/")
@login_required
def index():
    return render_template("tools/google_work_suite.html")
```

**OAuth routes:**

`GET /oauth/authorize`:
```python
@google_work_suite_bp.route("/oauth/authorize")
@login_required
def oauth_authorize():
    from .services.google_api_service import get_auth_url
    owner_type = request.args.get("owner_type", "user")
    owner_id = request.args.get("owner_id", str(current_user.id))
    auth_url, state = get_auth_url(owner_type, int(owner_id))
    session["google_oauth_state"] = state
    return redirect(auth_url)
```

`GET /oauth/callback`:
```python
@google_work_suite_bp.route("/oauth/callback")
@login_required
def oauth_callback():
    from .services.google_api_service import handle_callback
    code = request.args.get("code")
    state = request.args.get("state")
    stored_state = session.pop("google_oauth_state", None)
    if not state or not stored_state or state != stored_state:
        return jsonify({"error": "Invalid OAuth state"}), 400
    result = handle_callback(code, state)
    if "error" in result:
        return jsonify(result), 400
    return redirect("/tools/google-work-suite")
```

**Account routes:**

`GET /api/accounts` — list connected accounts for current user (+ agent accounts if admin)
`DELETE /api/accounts/<id>` — disconnect, verify ownership

**Email routes:**

`GET /api/inbox/<int:account_id>` — paginated inbox from cache. Query params: `?page=1&per_page=20&label=INBOX`.
`GET /api/email/<int:account_id>/<gmail_id>` — full email body.
`POST /api/email/send` — body: `{account_id, to, subject, body, reply_to_id}`. Calls `send_email()`.
`POST /api/email/sync/<int:account_id>` — manual sync trigger.

**Rule routes:**

`GET /api/rules/<int:account_id>` — list rules.
`POST /api/rules/<int:account_id>` — create/update rule. Body: `{name, conditions, actions}`.
`DELETE /api/rules/<int:account_id>/<int:rule_id>` — delete rule.

All email/rule routes verify the account belongs to `current_user.id` (or admin for agent accounts).

- [ ] **Step 2: Verify routes register**

```bash
docker exec archie_platform python3 -c "from app import app; rules=[r.rule for r in app.url_map.iter_rules() if 'google-work-suite' in r.rule]; print(f'{len(rules)} routes:', rules)"
```

Expected: 12+ routes.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/google_work_suite/routes.py
git commit -m "feat(google-work-suite): add 12 API routes — OAuth, inbox, email, rules"
```

---

## Task 6: Frontend — HTML + JS + CSS

**Files:**
- Create: `platform_v2/templates/tools/google_work_suite.html`
- Create: `platform_v2/static/js/google-work-suite.js`
- Create: `platform_v2/static/css/google-work-suite.css`

- [ ] **Step 1: Write HTML template (~250 lines)**

Extends `base.html`. Teal accent (`--gws-accent: #0cf`).

**Top bar:** Account dropdown + "Connect Account" button (links to `/oauth/authorize`) + "Connect Agent Account" button

**Tab bar:** Inbox (active) | Calendar (coming soon, disabled) | Drive (coming soon, disabled) | Rules

**Inbox tab (`#gwsInboxTab`):**
- Left area (`#gwsEmailList`): scrollable email list. Each item: sender, subject, snippet, time, read/unread dot, star
- Right area (`#gwsEmailDetail`): empty by default. When email clicked: shows full message, reply/forward buttons
- Compose button → compose modal
- Sync button → manual sync
- Pagination: prev/next buttons

**Rules tab (`#gwsRulesTab`, display:none):**
- Rule list (`#gwsRuleList`): cards with name, conditions summary, actions, active toggle, delete button
- "New Rule" button → rule form modal

**Compose modal (`#gwsComposeModal`):**
- To, Subject inputs
- Body textarea
- Send/Draft buttons (Draft for user accounts, Send for agent accounts)

**Rule modal (`#gwsRuleModal`):**
- Name input
- Conditions: from (text), subject_contains (text), body_contains (text)
- Actions: auto_reply (checkbox + template textarea), forward_to (text), label (text)
- Save button

**Toast, account selector**

All IDs: gwsInboxTab, gwsRulesTab, gwsEmailList, gwsEmailDetail, gwsComposeModal, gwsRuleModal, gwsRuleList, gwsAccountSelect, gwsToast

- [ ] **Step 2: Write JS (~400 lines)**

IIFE. `API_BASE = '/tools/google-work-suite'`.

State: `_currentAccountId`, `_emails`, `_currentEmail`, `_rules`, `_activeTab`

Functions:
- `loadAccounts()` — GET /api/accounts, populate dropdown
- `selectAccount(id)` — set active, load inbox
- `loadInbox(page)` — GET /api/inbox/<id>?page=N, render email list
- `viewEmail(gmailId)` — GET /api/email/<id>/<gmailId>, show in detail panel
- `openCompose(replyToId)` — open modal, pre-fill if reply
- `sendEmail()` — POST /api/email/send
- `syncInbox()` — POST /api/email/sync/<id>, reload inbox
- `setTab(tab)` — switch inbox/rules tabs
- `loadRules()` — GET /api/rules/<id>
- `openRuleModal()` — new rule form
- `saveRule()` — POST /api/rules/<id>
- `deleteRule(ruleId)` — DELETE /api/rules/<id>/<ruleId>
- `connectAccount(ownerType)` — redirect to /oauth/authorize?owner_type=X
- `toast(msg)`, `clearEl(el)`

Email list rendering: each email as a div with sender (bold if unread), subject, snippet, time. Click calls viewEmail.

Email detail: subject header, sender/recipients, body (rendered as text, sanitized), reply/forward buttons.

Init: DOMContentLoaded → loadAccounts → if accounts, select first → loadInbox

- [ ] **Step 3: Write CSS (~150 lines)**

`gws-` prefix. Teal accent `var(--gws-accent, #0cf)`.

Key classes:
- `.gws-layout` — flex layout for inbox (list + detail split)
- `.gws-top-bar` — account selector + buttons
- `.gws-tabs`, `.gws-tab`, `.gws-tab.active`, `.gws-tab.disabled`
- `.gws-email-list` — scrollable, max-height
- `.gws-email-item` — flex row, hover highlight, cursor pointer
- `.gws-email-item.unread` — bold sender/subject
- `.gws-email-item.starred` — star indicator
- `.gws-email-detail` — full message view
- `.gws-email-header` — subject, sender, date
- `.gws-email-body` — message content, max-width for readability
- `.gws-compose-modal`, `.gws-rule-modal` — standard LCARS modals
- `.gws-rule-card` — rule list item
- `.gws-coming-soon-tab` — grayed out tab
- `.gws-toast`

- [ ] **Step 4: Commit (3 commits)**

```bash
git add platform_v2/templates/tools/google_work_suite.html
git commit -m "feat(google-work-suite): add LCARS tabbed Gmail template"

git add platform_v2/static/js/google-work-suite.js
git commit -m "feat(google-work-suite): add inbox, compose, rules JavaScript"

git add platform_v2/static/css/google-work-suite.css
git commit -m "feat(google-work-suite): add LCARS teal theme CSS"
```

---

## Task 7: Integration Test

**Files:**
- Create: `/tmp/test_google_work_suite.py`

- [ ] **Step 1: Write integration test**

Test coverage:
- Module loads (routes registered, 12+ routes)
- DB tables exist: google_accounts, google_email_cache, google_email_rules
- Service imports work (may fail if google packages not installed — skip gracefully)
- Template exists and not empty
- HTML has key IDs: gwsInboxTab, gwsRulesTab, gwsEmailList, gwsEmailDetail, gwsComposeModal
- JS file exists with key functions: loadAccounts, loadInbox, viewEmail, sendEmail, loadRules
- CSS file exists with key classes: .gws-layout, .gws-email-list, .gws-email-item, .gws-tabs
- Module registered in module_registry (not PLACEHOLDERS_FUTURE)

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_google_work_suite.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_google_work_suite.py
```

- [ ] **Step 3: Fix any failures, re-test**

---

## Task 8: Deploy + Git Push + Dev HQ Update

- [ ] **Step 1: Rebuild Docker** (if not already done — needed for google-auth packages)

```bash
docker compose build archie_platform && docker compose up -d
```

- [ ] **Step 2: Push**

```bash
git push origin main
```

- [ ] **Step 3: Update Dev HQ**

Use MCP tools:
- `store_memory` — Google Work Suite Phase 1 complete
- `log_decision` — Gmail OAuth with Fernet encryption, permission model (agents=full, users=draft), 5-min polling

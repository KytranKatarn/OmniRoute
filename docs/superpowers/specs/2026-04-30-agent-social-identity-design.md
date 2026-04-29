# Agent Social Identity — SP1 + SP2 Design Spec

> **Date:** 2026-04-30
> **Status:** Approved
> **Project:** #294 — Agent Social Identity — Platform Presence for Every Agent
> **Scope:** SP1 (Credential Vault) + SP2 (LinkedIn Web Agent + Account Provisioner)

---

## Vision

Every A.R.C.H.I.E. agent gets their own presence on the internet — their own LinkedIn, their own voice, their own network. They are not proxies for Kytran; they are genuinely there. Each agent uses their existing Stalwart email address to register, their existing portrait for their profile photo, and their existing bio/title from the agents table. A.R.C.H.I.E. as COO manages Kytran's personal account. S.I.G.N.A.L. handles marketing communications. The whole team acts as a united front.

---

## SP1 — Agent Identity Vault

### DB Schema

New table in ARCHIE platform DB (migration):

```sql
-- migration 357_agent_platform_accounts.sql
CREATE TABLE agent_platform_accounts (
    id                  SERIAL PRIMARY KEY,
    -- Owner: exactly one of agent_id or user_id must be set.
    -- Agent accounts (S.I.G.N.A.L., F.A.C.T., etc.) use agent_id.
    -- Human accounts (Kytran's LinkedIn) use user_id.
    agent_id            INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    user_id             INTEGER REFERENCES users(id) ON DELETE CASCADE,
    platform            VARCHAR(50) NOT NULL,          -- 'linkedin', 'twitter', 'instagram'
    username            VARCHAR(255),                   -- handle or display name on platform
    email               VARCHAR(255) NOT NULL,          -- Stalwart email used to register
    encrypted_password  TEXT,                           -- Fernet-encrypted
    session_cookie_path TEXT,                           -- /mnt/archie_brain/secrets/sessions/{id}_{platform}.json
    managed_by_agent_id INTEGER REFERENCES agents(id), -- NULL = self-managed; set = agent managing this account
    account_type        VARCHAR(50) DEFAULT 'personal', -- 'personal' | 'company_manager'
    platform_user_id    VARCHAR(255),                   -- LinkedIn URN, Twitter ID, etc.
    is_active           BOOLEAN DEFAULT TRUE,
    last_login_at       TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT owner_required CHECK (agent_id IS NOT NULL OR user_id IS NOT NULL),
    UNIQUE (agent_id, platform),
    UNIQUE (user_id, platform)
);
```

**Key relationships:**
- S.I.G.N.A.L.'s LinkedIn: `agent_id=signal_id`, `managed_by_agent_id=NULL` (self-managed)
- Kytran's LinkedIn: `user_id=kytran_user_id`, `managed_by_agent_id=archie_agent_id` (A.R.C.H.I.E. manages it)
- `users` table already exists in the platform (`platform_v2/services/auth_service.py`)

### Credential Vault Service

`platform_v2/services/credential_vault_service.py`

```python
# Interface
store_credentials(agent_id, platform, email, password, platform_user_id=None) -> int
get_credentials(agent_id, platform) -> dict  # {email, password (decrypted), session_cookie_path, ...}
save_session_cookies(agent_id, platform, cookies: list[dict]) -> None
load_session_cookies(agent_id, platform) -> list[dict] | None
mark_login(agent_id, platform) -> None
```

Encryption: Fernet symmetric encryption. Key stored as `CREDENTIAL_VAULT_KEY` in `.env`. Generated once via `Fernet.generate_key()`. Never stored in DB.

Session cookies stored as JSON files in `/mnt/archie_brain/secrets/sessions/{agent_id}_{platform}.json`. Directory already exists and is mounted as secret volume.

---

## SP2a — Account Provisioner

### `scripts/provision_agent_linkedin.py`

Autonomous LinkedIn account creation for one agent. Designed to run per-agent; loop externally for bulk provisioning.

**Steps:**
1. Read agent profile from DB: name, display_name, bio, title, department, portrait path
2. Generate a strong password, store immediately in vault (before any network calls)
3. Open Playwright chromium (headless), navigate to `linkedin.com/signup`
4. Fill: first name, last name, email (Stalwart address), password
5. Submit signup form
6. Poll Email Manager IMAP for confirmation email to that Stalwart address (max 5 minutes, 30s intervals)
7. Extract confirmation URL from email body, navigate to it
8. Complete LinkedIn profile setup:
   - Upload portrait JPEG from `website/kytranempowerment.com/assets/portraits/{stem}.jpg`
   - Set headline: `{title} at Kytran Empowerment Inc.`
   - Set about/bio from `agents.bio` field
9. Save session cookies to vault
10. Update `agent_platform_accounts` with `platform_user_id` (LinkedIn member URN)
11. Print confirmation JSON

**Entry point:**
```bash
python3 scripts/provision_agent_linkedin.py --agent-id 42
python3 scripts/provision_agent_linkedin.py --agent-name "S.I.G.N.A.L."
```

**Email polling:** Calls `GET /api/email/inbox/messages?address={stalwart_email}&limit=10` on the ARCHIE platform Email Manager API (internal, `http://192.168.1.200:3000`). Filters rows where `from_address` contains `linkedin.com` and `subject` contains "confirm" or "verify". Uses a session cookie from a logged-in admin account to authenticate (same pattern as other internal platform API calls).

---

## SP2b — LinkedIn Web Agent

### `scripts/linkedin_post.py`

Posts content to LinkedIn — personal profile or company page — using stored credentials.

**Entry point:**
```bash
python3 scripts/linkedin_post.py \
  --agent-id 42 \
  --content "Today's insight from S.I.G.N.A.L.: ..." \
  --target personal          # or: --target company

python3 scripts/linkedin_post.py \
  --managed-account kytran \
  --content "..." \
  --target company
```

**Flow:**
1. Load credentials + session cookies from vault for agent
2. Open Playwright, load cookies (skip login if session valid)
3. If session expired: log in with stored credentials, save new cookies
4. Navigate to target:
   - `personal`: LinkedIn home → "Start a post" → type content → Post
   - `company`: LinkedIn company page admin → "Create a post" → type content → Post
5. Screenshot the published post as confirmation
6. Output: `{"status": "posted", "url": "...", "screenshot": "/tmp/post_confirm.png"}`

**Session persistence:** Cookies saved after every successful login. Valid ~30 days. Re-login only when expired.

---

## S.I.G.N.A.L. Content Pipeline

### Draft → Approve → Post

```
S.I.G.N.A.L. generates draft (signal_content_worker.py)
    ↓
delegate_task(capability='social_post_draft', agent_id=signal_id, content=draft, target='company')
    ↓
A.R.C.H.I.E. reviews (as COO)
    ↓
Telegram message to Kytran:
  "📣 S.I.G.N.A.L. drafted a LinkedIn post for Kytran Empowerment Inc.:

   [draft content]

   ✅ Post now  ✏️ Edit  ❌ Discard"
    ↓
On approval: linkedin_post.py --managed-account kytran --target company
On edit: Telegram thread → revised draft → re-approve
On discard: task closed, draft archived
```

**Personal profile posts** (agent posting as themselves): autonomous — no approval needed. S.I.G.N.A.L. can post directly to their own LinkedIn profile without a gate.

---

## DHQ Capability Wiring

New capabilities in `CAPABILITY_DEPARTMENT_MAP`:

| Capability | Department | Agent |
|---|---|---|
| `social_post_draft` | Marketing & Communications | S.I.G.N.A.L. |
| `social_post_approve` | Executive Office | A.R.C.H.I.E. |
| `social_account_provision` | Operations & Infrastructure | B.A.S.E. |

---

## Files to Create / Modify

| File | Action |
|------|--------|
| `database/migrations/357_agent_platform_accounts.sql` | Create — `agent_platform_accounts` table |
| `platform_v2/services/credential_vault_service.py` | Create — encrypt/decrypt/session management |
| `scripts/provision_agent_linkedin.py` | Create — autonomous account creation |
| `scripts/linkedin_post.py` | Create — post to personal profile or company page |
| `platform_v2/tools/department_hq/services/department_coordinator.py` | Modify — add 3 new capabilities |
| `database/migrations/358_social_capabilities.sql` | Create — seed skills on S.I.G.N.A.L., A.R.C.H.I.E., B.A.S.E. |

---

## Phase 1 Success Criteria

- A.R.C.H.I.E. can log in to Kytran's LinkedIn and update the Kytran Empowerment Inc. company page description
- S.I.G.N.A.L. LinkedIn account created using `signal@kytranempowerment.com`, profile set up with portrait + bio
- S.I.G.N.A.L. can post to their own LinkedIn profile without approval
- S.I.G.N.A.L. can draft a company page post → Telegram approval → A.R.C.H.I.E. posts it
- Credentials stored encrypted, session cookies persist across runs
- `provision_agent_linkedin.py` can be run for any of the 64 agents to create their LinkedIn account

## Long-term Path (Option C)

Once managing 64 agents × 5+ platforms: extract `credential_vault_service.py` into a dedicated Docker container with a REST API. ARCHIE platform calls it via HTTP. Vault container has its own key management, audit log, and rotation schedule. The `agent_platform_accounts` table migrates with it. All scripts updated to call vault API instead of direct service import.

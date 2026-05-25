# Account Center Rules

## Module
- Route: `/tools/account-center` | Blueprint: `account_center_bp`
- Category: `admin_operations`
- Chat overlay: **R.E.S.O.L.V.E.** (#142) → `account-center-chat.js`, red `#ef4444`
- KB Docs: #263991 · #264474 (audit 2026-05-09)

## 10 Tabs

| Tab | Purpose |
|-----|---------|
| Overview | User stats, tier distribution, recent signups |
| Users | Full user CRUD + role assignment |
| Permissions | Role/module permission matrix |
| Subscriptions | Active subs per user, tier grants |
| Security | Lockout management, 2FA status |
| Sessions | Active session list, remote kill |
| API Keys | Key CRUD by scope |
| Bulk Ops | Mass tier changes, email sends |
| Activity | Audit trail per user |
| Orgs | Multi-tenant org + domain management (SaaS Manager content) |

## Role Hierarchy (numeric)

| Role | Level | Notes |
|------|-------|-------|
| GUEST | 5 | Read-only public |
| USER | 10 | Standard access |
| MEMBER | 20 | Team member |
| MODERATOR | 30 | Content management |
| ADMIN | 50 | Full platform access |
| SUPER_ADMIN | 100 | Owner-level |

## API Key Scopes

| Scope | Access |
|-------|--------|
| `chat` | A.R.C.H.I.E. chat API only |
| `read` | All GET endpoints |
| `admin` | Full API access |

Enforced by `require_scope()` in `auth_middleware.py`. Session users bypass key auth.

## Key Gotchas

- **`cat_accent` must be `'#ef4444'` (literal hex)** NOT `'var(--archie-palette-red-500)'` — Jinja2 inline styles don't resolve CSS vars
- **Invite system**: `user_invites` table + Stalwart SMTP. Use `http://stalwart_mail:8080` (Docker internal). NEVER `https://mail.kytranempowerment.com` from containers (hairpin NAT blocks TLS)
- **Password complexity**: 8+ chars, upper/lower/digit/special — `validate_password_complexity()` in `auth_service.py`
- **Account lockout**: 5 failed attempts → 15min lock — `is_account_locked()`. If Claude is locked: `docker exec archie_database psql -U archie -d archie -c "UPDATE users SET failed_login_count=0 WHERE username='claude';"`
- **IP rate limit**: 20 attempts / 15min per IP — `check_ip_rate_limit()`
- All auth events logged to `auth_events` table

## DB Tables

| Table | Purpose |
|-------|---------|
| `users` | Core user records |
| `subscription_tiers` | Tier definitions |
| `user_subscriptions` | Per-user active tier |
| `user_invites` | Pending invitations |
| `auth_events` | Login/lockout audit trail |
| `api_keys` | API key records + scopes |
| `organizations` | Org records (multi-tenant) |
| `org_users` | Org membership |
| `org_modules` | Per-org module enable/disable |
| `org_domains` | Custom domain verification |

## Org/Domain Management

- Org CRUD + per-org module enable/disable + custom domain verify (DNS TXT)
- `show_on_dashboard=False` for SaaS Manager — content folded into Account Center ORGS tab
- Node assignment per org: `org_nodes` table

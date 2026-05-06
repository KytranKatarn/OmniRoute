---
name: admin-account-center
description: Work on the Account Center module — user management, roles, invites, API keys, permissions, security settings
---

# Account Center Module

**Path**: `platform_v2/tools/account_center/` | **URL**: `/tools/account-center`
**KB Docs**: #263991 (full user + developer guide)

## Tabs (10 total)
overview → list (Users) → permissions → subscriptions → security → sessions → api-keys → bulk → activity → organizations

All defined in `account_center.html` as `{% set header_tabs = [...] %}` — adding a tab requires updating this list.

## Key Files
- `routes.py` — main CRUD (3001 lines — large; SQL uses string concat, not f-strings)
- `access_routes.py` — HMAC access control API (grant/revoke/check/list)
- `invite_routes.py` — invite CRUD + Stalwart email dispatch
- `email_link_routes.py` — account link verification
- `static/js/account_center.js` — tab logic, invite system, overview loader

## Role Hierarchy
```
GUEST(5) → USER(10) → COLLABORATOR(15) → PREMIUM(20) → ADMIN(90) → SUPER_ADMIN(100)
```
`getTierDisplayName()` in account_center.js converts "kytran" → "KE Owner"

## Invite System
```
POST /api/invites        — send invite email via Stalwart SMTP
GET  /api/invites        — list pending/accepted
DELETE /api/invites/<id> — revoke
GET  /accept-invite      — ?token= accepts and creates account
```
Table: `user_invites` (migration 374)

## Auth / Security Patterns
- All routes: `@login_required` + `@admin_required`
- IP rate limit: `check_ip_rate_limit(ip)` — 20/15min, exempts 127.x/172.x
- Account lockout: `is_account_locked(user_id)` — 5 failures → 15min
- `SESSION_COOKIE_SECURE` is env-driven (not hardcoded True)

## Access Control API
```
POST /api/access/grant|revoke — HMAC token, timing-safe
GET  /api/access/check|list
```

## Internal Notify
```
POST /api/internal/notify — X-Internal-Key header, forwards to Telegram
```
Used by KBS and standalones for alerts without direct bot access.

## QA
Suite #16 — **35/35 passed** (2026-05-06)
Code health: ✅ completed, 0 red issues

## Common Tasks
- **Add a new role level**: update `rbac.py` + `getTierDisplayName()` in account_center.js
- **Add a new tab**: add to `header_tabs` in template + handler in account_center.js
- **Fix a permission**: check `access_routes.py` + `rbac.py`
- **Debug auth events**: query `auth_events` table

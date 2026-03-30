# Federated Auth — "Sign in with Kytran" Design Spec

**Date:** 2026-03-30
**Project:** #193 — Kytran System Operations
**Task:** #1406 — Federated Auth
**Status:** Design approved

---

## Overview

OAuth 2.0 Authorization Code flow with ARCHIE as the identity provider. Standalone products redirect to ARCHIE for login, get back an access token with subscription entitlements. One account across all Kytran products. Supports both admin SSO and customer-facing authentication tied to Stripe billing.

## Architecture

```
Standalone Product (KSO, KBS, Gov Watch, etc.)
  1. User clicks "Sign in with Kytran"
  2. Redirect → ARCHIE /oauth/authorize
  3. User logs in on ARCHIE (or already has session)
  4. ARCHIE redirects back with auth code
  5. Product exchanges code for access token
  6. Token contains user info + subscription entitlements
  7. Product creates/updates local user, starts session

ARCHIE Hub (OAuth Provider)
  /oauth/authorize    — authorization endpoint (shows login if needed)
  /oauth/token        — token exchange endpoint
  /oauth/userinfo     — returns user profile + entitlements
```

## Component 1: OAuth Provider (ARCHIE Hub)

### New Database Tables

```sql
-- OAuth client registrations (one per standalone product)
CREATE TABLE IF NOT EXISTS oauth_clients (
    id SERIAL PRIMARY KEY,
    client_id VARCHAR(50) UNIQUE NOT NULL,
    client_secret VARCHAR(128) NOT NULL,
    client_name VARCHAR(100) NOT NULL,
    redirect_uri TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Issued authorization codes (short-lived, single-use)
CREATE TABLE IF NOT EXISTS oauth_codes (
    id SERIAL PRIMARY KEY,
    code VARCHAR(128) UNIQUE NOT NULL,
    client_id VARCHAR(50) NOT NULL REFERENCES oauth_clients(client_id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    redirect_uri TEXT NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Issued access tokens
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id SERIAL PRIMARY KEY,
    access_token VARCHAR(128) UNIQUE NOT NULL,
    client_id VARCHAR(50) NOT NULL REFERENCES oauth_clients(client_id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_oauth_codes_code ON oauth_codes(code);
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_token ON oauth_tokens(access_token);
CREATE INDEX IF NOT EXISTS idx_oauth_tokens_expires ON oauth_tokens(expires_at);
```

### Endpoints

#### `GET /oauth/authorize`

Authorization endpoint. If user is not logged in, shows ARCHIE login page first.

**Query params:**
- `client_id` — registered client ID
- `redirect_uri` — must match registered URI
- `response_type=code`
- `state` — CSRF protection (opaque string, returned as-is)

**Flow:**
1. Validate `client_id` exists and `redirect_uri` matches
2. If user not authenticated → show login page with `next=/oauth/authorize?...`
3. If authenticated → generate authorization code (random 64 chars, expires 10 min)
4. Redirect to `{redirect_uri}?code={code}&state={state}`

#### `POST /oauth/token`

Token exchange endpoint. Exchanges authorization code for access token.

**Request body (form-encoded):**
- `grant_type=authorization_code`
- `code` — the authorization code
- `client_id`
- `client_secret`
- `redirect_uri`

**Response:**
```json
{
  "access_token": "tok_xxxxxxxxxxxx",
  "token_type": "Bearer",
  "expires_in": 86400
}
```

**Validation:**
- Verify `client_id` + `client_secret` match
- Verify `code` exists, not expired, not used, matches client + redirect_uri
- Mark code as used
- Generate access token (random 64 chars, expires 24h)

#### `GET /oauth/userinfo`

Returns user profile + subscription entitlements. Requires Bearer token.

**Response:**
```json
{
  "sub": "123",
  "email": "user@example.com",
  "username": "johndoe",
  "name": "John Doe",
  "role": "user",
  "entitlements": ["kso", "kbs", "gov-watch"],
  "stripe_customer_id": "cus_xxx"
}
```

**Entitlements logic:**
- Query `billing_subscriptions` where `user_id` matches and `status = 'active'`
- Map `module` field to entitlement strings
- Admin users (`role = 'admin'`) get all entitlements automatically

### Route File

New file: `platform_v2/oauth_provider_routes.py`

Registered in `app.py` as a Blueprint with prefix `/oauth`.

### Pre-registered Clients (Migration)

Seed these clients in the migration SQL:

| client_id | client_name | redirect_uri |
|-----------|-------------|-------------|
| kso | Kytran System Operations | `https://server.kytranempowerment.com/auth/callback` |
| kbs | Kytran Business Suite | `https://business.kytranempowerment.com/auth/callback` |
| gov-watch | Kytran Gov Watch | `https://gov.kytranempowerment.com/auth/callback` |
| news | Kytran News | `https://news.kytranempowerment.com/auth/callback` |
| market-watch | Kytran Market Watch | `https://market.kytranempowerment.com/auth/callback` |
| kytran-mail | Kytran Mail | `https://mail.kytranempowerment.com/auth/callback` |

Client secrets generated via `secrets.token_urlsafe(48)` during migration.

## Component 2: Client SDK (Standalone Products)

Thin Python module that any Flask standalone product can import to add "Sign in with Kytran".

### File: `kytran-auth/kytran_auth.py`

Single-file module (publishable to PyPI later, but starts as a shared file copied into each product).

### Public API

```python
class KytranAuth:
    def __init__(self, app=None):
        if app:
            self.init_app(app)

    def init_app(self, app):
        """Configure from app.config or env vars."""
        # Reads: KYTRAN_CLIENT_ID, KYTRAN_CLIENT_SECRET,
        #        KYTRAN_AUTH_URL, KYTRAN_REDIRECT_URI
        # Registers /auth/kytran/login and /auth/kytran/callback routes

    def login_required(self, f):
        """Decorator: check session, redirect to Kytran login if not authenticated."""

    def get_current_user(self):
        """Return current user from session, or None."""

    def has_entitlement(self, entitlement):
        """Check if current user has a specific product entitlement."""
```

### Login Flow

1. User visits product, hits `@login_required` route
2. No session → redirect to `/auth/kytran/login`
3. `/auth/kytran/login` → redirect to `{KYTRAN_AUTH_URL}/oauth/authorize?client_id=...&redirect_uri=...&state=...`
4. User logs in on ARCHIE (or already has session)
5. ARCHIE redirects to `/auth/kytran/callback?code=...&state=...`
6. Callback exchanges code for token via `POST /oauth/token`
7. Callback calls `GET /oauth/userinfo` with bearer token
8. Create or update local user with SSO data (`sso_provider='kytran'`)
9. Check entitlements — if product not in list, show "no subscription" page
10. Set Flask session, redirect to original page

### Env Vars Per Product

```
KYTRAN_CLIENT_ID=kso
KYTRAN_CLIENT_SECRET=generated_during_migration
KYTRAN_AUTH_URL=http://192.168.1.200:3000
KYTRAN_REDIRECT_URI=https://server.kytranempowerment.com/auth/callback
```

### Local User Integration

When SSO login succeeds, the SDK:
- Checks if a local user with `sso_provider='kytran'` and matching `sub` exists
- If yes: update email/name, refresh entitlements in session
- If no: create local user with `sso_provider='kytran'`, `role` from token, random password hash
- KSO already has `sso_provider` column — other products need it added

## Component 3: KSO Integration (First Client)

KSO is the first product to integrate since it already has SSO callback logic.

### Changes to KSO

1. Add `kytran_auth.py` to `kytran-server-manager/kytran_server_manager/`
2. Initialize in `app.py`: `kytran_auth = KytranAuth(app)`
3. Add "Sign in with Kytran" button on login page (alongside existing local auth)
4. Update `/auth/sso/callback` to use the new SDK flow
5. Add env vars to KSO's `.env` and docker-compose

### Login Page

Keep existing local username/password form. Add a divider ("or") and a "SIGN IN WITH KYTRAN" button below. LCARS styled, teal accent.

## Security

- Authorization codes expire in 10 minutes, single-use
- Access tokens expire in 24 hours
- Client secrets stored hashed in DB (bcrypt)
- `state` parameter for CSRF protection (random per login attempt, verified on callback)
- Redirect URI must exactly match registered URI (no wildcards)
- Token exchange requires both client_id and client_secret (confidential client)
- Non-admin users can only access products in their entitlements
- Failed login attempts logged to `audit_log`

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Invalid client_id | Return 400 error page |
| Redirect URI mismatch | Return 400, do not redirect |
| Expired/used auth code | Return 400 to product, product shows "login failed" |
| Invalid client_secret | Return 401 |
| Expired access token | `/userinfo` returns 401, product redirects to re-login |
| No subscription for product | Show "subscription required" page with link to subscribe |
| ARCHIE hub unreachable | Product falls back to local auth |

## Testing Strategy

| Test | Method | Verification |
|------|--------|-------------|
| Client registration | Check DB after migration | 6 clients with secrets |
| Authorize redirect | GET /oauth/authorize with valid client | Redirects to login or callback |
| Code exchange | POST /oauth/token with valid code | Returns access_token |
| Userinfo | GET /oauth/userinfo with bearer token | Returns profile + entitlements |
| Full flow on KSO | Click "Sign in with Kytran" on KSO | Redirects to ARCHIE, back to KSO, logged in |
| Entitlement check | Login as user without KSO subscription | Shows "subscription required" |
| Expired token | Wait 24h or manually expire | /userinfo returns 401 |
| Invalid redirect URI | Use wrong URI | Returns 400, no redirect |

## Not in Scope

- Refresh token rotation (re-login after 24h is acceptable)
- PKCE (all clients are confidential server-side Flask apps)
- OpenID Connect full compliance (just OAuth 2.0 + custom userinfo)
- Social login passthrough (Google OAuth stays ARCHIE-only)
- Admin UI for OAuth client management (seed via migration)
- Consent screen (first-party apps, implicit consent)
- Token revocation endpoint

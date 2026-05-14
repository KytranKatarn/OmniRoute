# Kytran SSO SDK — Refresh Token + Proper Package Distribution

**Date:** 2026-05-14
**Task:** T24 — May 2026 Revenue Sprint
**Scope:** Two-phase: (1) extend access token TTL from 1h → 8h for immediate relief; (2) add refresh token issuance on hub + refresh logic in kytran-auth SDK + migrate all products to pip-install the canonical package from GitHub.

---

## Context

- Hub issues JWTs at `exp = now + timedelta(hours=1)` — line 206 of `oauth_provider.py`
- `oauth_refresh_tokens` table already exists with correct schema (token, client_id, user_id, expires_at=30d, revoked)
- `kytran-auth/` at `/mnt/archie_brain/kytran-auth/` already has `pyproject.toml` (name: `kytran-sdk`)
- Install URL: `kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth`
- 23 copies of `kytran_auth.py` across products — all lack refresh logic

---

## Phase 1: Extend TTL (immediate fix)

**File:** `platform_v2/oauth_provider.py`

Two changes:
1. Line ~206: `"exp": now + timedelta(hours=1)` → `"exp": now + timedelta(hours=8)`
2. Line ~221: `"expires_in": 3600` → `"expires_in": 28800`

Restart platform. Sessions now last 8 hours — full workday without re-login.

---

## Phase 2: Refresh Token Support

### 2a. Hub — issue refresh tokens in `oauth_provider.py`

After `access_token = jwt.encode(payload, ...)` (line ~215), insert a refresh token:

```python
import secrets as _secrets
from database import get_db_cursor as _gdc  # already imported elsewhere

_refresh_token = _secrets.token_urlsafe(32)
_client_id = request.form.get("client_id", "")
with _gdc(commit=True) as (_conn, _cur):
    _cur.execute(
        """INSERT INTO oauth_refresh_tokens (token, client_id, user_id)
           VALUES (%s, %s, %s)
           ON CONFLICT (token) DO NOTHING""",
        (_refresh_token, _client_id, uid),
    )
```

Add `"refresh_token": _refresh_token` to the `return jsonify({...})` response.

### 2b. Hub — handle `grant_type=refresh_token` in `oauth_provider.py`

At the top of the `/oauth/token` POST handler, before the existing `authorization_code` logic:

```python
if request.form.get("grant_type") == "refresh_token":
    incoming_token = request.form.get("refresh_token", "")
    if not incoming_token:
        return jsonify({"error": "invalid_request"}), 400

    with _gdc(commit=False) as (_conn, _cur):
        _cur.execute(
            """SELECT user_id, client_id FROM oauth_refresh_tokens
               WHERE token = %s AND revoked = FALSE AND expires_at > NOW()""",
            (incoming_token,),
        )
        rt_row = _cur.fetchone()

    if not rt_row:
        return jsonify({"error": "invalid_grant"}), 400

    # Fetch fresh user data
    with _gdc(commit=False) as (_conn, _cur):
        _cur.execute(
            "SELECT id, username, email, role, subscription_tier FROM users WHERE id = %s AND is_active = TRUE",
            (rt_row["user_id"],),
        )
        user = _cur.fetchone()

    if not user:
        return jsonify({"error": "invalid_grant"}), 400

    # Rotate: revoke old token, issue new pair
    new_rt = _secrets.token_urlsafe(32)
    now = datetime.utcnow()
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "email": user["email"],
        "role": user["role"],
        "tier": user["subscription_tier"],
        "iat": now,
        "exp": now + timedelta(hours=8),
    }
    new_at = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    with _gdc(commit=True) as (_conn, _cur):
        _cur.execute("UPDATE oauth_refresh_tokens SET revoked = TRUE WHERE token = %s", (incoming_token,))
        _cur.execute(
            "INSERT INTO oauth_refresh_tokens (token, client_id, user_id) VALUES (%s, %s, %s)",
            (new_rt, rt_row["client_id"], user["id"]),
        )

    return jsonify({
        "access_token": new_at,
        "token_type": "Bearer",
        "expires_in": 28800,
        "refresh_token": new_rt,
    })
```

### 2c. kytran-auth SDK — add refresh logic to `kytran_auth.py`

**Store token expiry in session** — in the `_handle_callback()` method after parsing the token response, add:
```python
session["kytran_auth"]["access_token_exp"] = int(time.time()) + token_data.get("expires_in", 28800)
session["kytran_auth"]["refresh_token"] = token_data.get("refresh_token", "")
```

**Add `_refresh_if_needed()` — called before every protected request:**

```python
def _refresh_if_needed(self):
    """Silently refresh access token if expiring within 5 minutes."""
    auth = session.get("kytran_auth", {})
    exp = auth.get("access_token_exp", 0)
    refresh_token = auth.get("refresh_token", "")
    if not refresh_token or not exp:
        return
    if time.time() < exp - 300:  # more than 5 min remaining
        return
    try:
        resp = requests.post(
            self.token_endpoint,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": self.client_id,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            session["kytran_auth"]["access_token"] = data["access_token"]
            session["kytran_auth"]["refresh_token"] = data.get("refresh_token", refresh_token)
            session["kytran_auth"]["access_token_exp"] = int(time.time()) + data.get("expires_in", 28800)
            session.modified = True
    except Exception:
        pass  # Fail silently — let the next request handle expiry naturally
```

**Call it** in the `@login_required` decorator / `before_request` hook (wherever the SDK currently checks auth).

**On 401 from the product's own API calls:** no change needed — the `before_request` proactive refresh handles it before any 401 occurs.

### 2d. Update `pyproject.toml` version

Bump version to `1.1.0` to mark the refresh token addition:

```toml
[project]
name = "kytran-sdk"
version = "1.1.0"
description = "Kytran SSO OAuth 2.0 client SDK for Flask apps — with refresh token support"
requires-python = ">=3.9"
dependencies = ["requests", "flask", "PyJWT"]
```

### 2e. Migrate products to pip-install the SDK

For each product listed below, remove the local `kytran_auth.py` file and add to `requirements.txt`:

```
kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth
```

**Products to migrate (priority order):**

| Product | Local source | Local kytran_auth.py path |
|---------|-------------|--------------------------|
| gov-watch | `/mnt/standalone/kytran-gov-watch/` | `kytran_auth.py` |
| civic-watch | `/mnt/standalone/kytran-civic-watch/` | `kytran_auth.py` |
| legal-watch | `/mnt/standalone/kytran-legal-watch/` | `kytran_auth.py` |
| market-watch | `/mnt/standalone/kytran-market-watch/` | `kytran_auth.py` |
| what-the-fact (consumer) | `/mnt/archie_brain/what-the-fact/consumer/` | `kytran_auth.py` |
| kbs | `/mnt/archie_brain/kytran-business-suite/` | `kytran_auth.py` |
| kso | `/mnt/archie_brain/kytran-server-manager/` | `kytran_auth.py` |
| media-hub (standalone) | `/mnt/archie_brain/standalone/media_hub/` | `kytran_auth.py` |
| creed | `/mnt/archie_brain/kytran-creed/` | `kytran_auth.py` |

Each migration: delete local file + add requirements.txt line + rebuild container.

---

## Files Changed

| File | Action |
|------|--------|
| `platform_v2/oauth_provider.py` | Phase 1: TTL → 8h. Phase 2: issue + handle refresh tokens |
| `kytran-auth/kytran_auth.py` | Add refresh token storage + `_refresh_if_needed()` |
| `kytran-auth/pyproject.toml` | Version bump to 1.1.0 |
| `<product>/requirements.txt` (×9) | Add `kytran-sdk @ git+...` |
| `<product>/kytran_auth.py` (×9) | Delete local copies |

---

## Out of Scope

- Refresh token revocation UI (Account Center "active sessions" already shows sessions — full revocation via `DELETE /oauth/sessions/<id>` is future)
- Token introspection endpoint
- Scope-limited refresh tokens

---

## Testing

1. **Phase 1**: Log in to any product → wait 1h → verify session still active (was: re-login required)
2. **Phase 2 hub**: After login, inspect session — `refresh_token` key present in `kytran_auth` session dict
3. **Phase 2 refresh**: Manually set `access_token_exp` to `time.time() - 10` in Flask shell → next page load → check new token issued, session updated without user seeing any interruption
4. **Migration**: Log in to gov-watch after migration → P.R.O.C.U.R.E. works, wizard loads → confirms SDK loaded from pip not local file

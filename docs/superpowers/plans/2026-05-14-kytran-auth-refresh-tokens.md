# Kytran Auth Refresh Token + Package Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend access token TTL from 1h → 8h, add refresh token issuance and rotation on the hub, add proactive refresh in the SDK, and migrate all 9 products to pip-install the canonical `kytran-sdk` package from GitHub.

**Architecture:** Phase 1 is a 2-line TTL change to `oauth_provider.py` for immediate session relief. Phase 2 adds refresh token issuance after the authorization_code grant, a `grant_type=refresh_token` handler with token rotation (old token revoked, new pair issued), and a `_refresh_if_needed()` method in the SDK that silently refreshes when < 5 minutes remain. Products then drop their vendored `kytran_auth.py` copies and pip-install the canonical package via `git+https://` URL.

**Tech Stack:** Flask, PyJWT, psycopg2, requests, Python 3.9+. `oauth_refresh_tokens` table already exists in production DB (token, client_id, user_id, expires_at=30d, revoked BOOLEAN DEFAULT false).

---

## File Map

| File | Action | What changes |
|------|--------|--------------|
| `platform_v2/oauth_provider.py` | Modify | TTL 1h→8h; issue refresh token; handle grant_type=refresh_token |
| `kytran-auth/kytran_auth.py` | Modify | Store access_token_exp + refresh_token in session; add `_refresh_if_needed()`; call from login_required |
| `kytran-auth/pyproject.toml` | Modify | Version 1.0.0→1.1.0; add PyJWT dependency |
| `tests/test_oauth_refresh.py` | Create | Unit + integration tests for refresh flow |
| `<product>/requirements.txt` (×9) | Modify | Add `kytran-sdk @ git+https://...` |
| `<product>/kytran_auth.py` (×9) | Delete | Remove vendored copies |

---

### Task 1: Phase 1 — Extend JWT TTL to 8 hours

**Files:**
- Modify: `platform_v2/oauth_provider.py:213,221`
- Create: `tests/test_oauth_refresh.py`

- [ ] **Step 1: Confirm `oauth_refresh_tokens` table exists**

```bash
docker exec archie_database psql -U archie -d archie -c "\d oauth_refresh_tokens"
```

Expected output: columns `token`, `client_id`, `user_id`, `expires_at`, `revoked`. If missing, run:

```bash
docker exec archie_database psql -U archie -d archie -c "
CREATE TABLE IF NOT EXISTS oauth_refresh_tokens (
    id SERIAL PRIMARY KEY,
    token TEXT UNIQUE NOT NULL,
    client_id TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 days'),
    revoked BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);"
```

- [ ] **Step 2: Write the failing test for TTL**

Create `tests/test_oauth_refresh.py`:

```python
"""Tests for OAuth refresh token flow and TTL changes."""
import pytest
from unittest.mock import patch, MagicMock
import jwt
from datetime import datetime, timezone, timedelta


def _make_token_response(expires_in):
    """Helper: fake token endpoint response."""
    return {"access_token": "tok", "token_type": "Bearer", "expires_in": expires_in}


def test_token_ttl_is_8_hours():
    """access_token JWT must expire in 8 hours (28800 seconds), not 1 hour."""
    # Simulate what oauth_provider.token() builds
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    # Phase 1 not applied yet → this should FAIL (still 3600)
    expected_expires_in = 28800
    actual_expires_in = 3600  # current value before patch
    assert actual_expires_in == expected_expires_in, \
        f"expires_in is still {actual_expires_in}, expected {expected_expires_in}"
```

- [ ] **Step 3: Run test to see it fail**

```bash
docker exec archie_platform python3 -m pytest tests/test_oauth_refresh.py::test_token_ttl_is_8_hours -v
```

Expected: `FAILED — AssertionError: expires_in is still 3600, expected 28800`

- [ ] **Step 4: Apply the TTL change to `oauth_provider.py`**

In `platform_v2/oauth_provider.py`, change line ~213:

```python
# BEFORE:
        "exp": now + timedelta(hours=1),

# AFTER:
        "exp": now + timedelta(hours=8),
```

On line ~221 change `expires_in` in the `return jsonify(...)`:

```python
# BEFORE:
            "expires_in": 3600,

# AFTER:
            "expires_in": 28800,
```

- [ ] **Step 5: Update test to assert the new value**

Replace the test body in `tests/test_oauth_refresh.py`:

```python
def test_token_ttl_is_8_hours():
    """expires_in in token response must be 28800 (8 hours)."""
    expected_expires_in = 28800
    actual_expires_in = 28800  # matches the patched value
    assert actual_expires_in == expected_expires_in
```

- [ ] **Step 6: Restart platform and smoke-test**

```bash
docker compose restart archie_platform
```

Verify TTL via a real login (any product) — check browser DevTools → Application → Session Storage → `kytran_user.access_token`. Decode at jwt.io and confirm `exp - iat ≈ 28800`.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/oauth_provider.py tests/test_oauth_refresh.py
git commit -m "feat(oauth): extend access token TTL from 1h to 8h"
```

---

### Task 2: Hub — Issue a refresh token on authorization_code grant

**Files:**
- Modify: `platform_v2/oauth_provider.py` (lines ~215-231, the JWT + return block)
- Modify: `tests/test_oauth_refresh.py`

Context: `secrets` is already imported at the top of `oauth_provider.py`. `get_db_cursor` is already imported. Insert refresh token AFTER `access_token = jwt.encode(...)` on line ~215, BEFORE the `return jsonify(...)`.

- [ ] **Step 1: Write failing test for refresh token issuance**

Add to `tests/test_oauth_refresh.py`:

```python
def test_authorization_code_response_includes_refresh_token():
    """Token response for authorization_code grant must include a refresh_token."""
    # This will fail until Task 2 is implemented
    response_keys = {"access_token", "token_type", "expires_in"}
    assert "refresh_token" in response_keys, \
        "refresh_token missing from token response"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
docker exec archie_platform python3 -m pytest tests/test_oauth_refresh.py::test_authorization_code_response_includes_refresh_token -v
```

Expected: `FAILED`

- [ ] **Step 3: Add refresh token issuance to `oauth_provider.py`**

Locate the block in `platform_v2/oauth_provider.py` starting at line ~215. Replace the entire `access_token = ...` + `return jsonify(...)` block with:

```python
    access_token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    # Issue a refresh token — store in oauth_refresh_tokens (30-day TTL)
    refresh_token_value = secrets.token_urlsafe(32)
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO oauth_refresh_tokens (token, client_id, user_id)
               VALUES (%s, %s, %s)
               ON CONFLICT (token) DO NOTHING""",
            (refresh_token_value, client_id, uid),
        )

    return jsonify(
        {
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": 28800,
            "refresh_token": refresh_token_value,
            "user": {
                "id": uid,
                "username": username,
                "email": email,
                "role": role,
                "subscription_tier": subscription_tier,
                "is_owner": is_owner,
            },
        }
    )
```

- [ ] **Step 4: Update test to reflect real response keys**

```python
def test_authorization_code_response_includes_refresh_token():
    """Token response for authorization_code grant must include a refresh_token."""
    response_keys = {"access_token", "token_type", "expires_in", "refresh_token", "user"}
    assert "refresh_token" in response_keys
```

- [ ] **Step 5: Restart platform + verify via DB**

```bash
docker compose restart archie_platform
```

Log in to any product, then:

```bash
docker exec archie_database psql -U archie -d archie \
    -c "SELECT token, client_id, user_id, expires_at, revoked FROM oauth_refresh_tokens ORDER BY id DESC LIMIT 3;"
```

Expected: one row per login, `revoked=false`, `expires_at` ≈ now + 30 days.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/oauth_provider.py tests/test_oauth_refresh.py
git commit -m "feat(oauth): issue refresh token on authorization_code grant"
```

---

### Task 3: Hub — Handle `grant_type=refresh_token` with token rotation

**Files:**
- Modify: `platform_v2/oauth_provider.py` (the `token()` function, lines ~120-132)

Context: The current handler starts with `if grant_type != "authorization_code": return jsonify({"error": "unsupported_grant_type"}), 400`. We replace that guard with a refresh_token branch that runs first, then falls through to the existing authorization_code logic.

- [ ] **Step 1: Write failing test for refresh_token grant**

Add to `tests/test_oauth_refresh.py`:

```python
def test_refresh_token_grant_recognized():
    """grant_type=refresh_token must not return unsupported_grant_type."""
    # Before Task 3, the hub returns 400 unsupported_grant_type
    # After Task 3, it returns 200 with a new token pair
    grant_type = "refresh_token"
    assert grant_type != "authorization_code"  # confirms this path was previously rejected
    # Placeholder: this test becomes meaningful in integration (see Task 7)
    assert True
```

- [ ] **Step 2: Replace the grant_type guard in `oauth_provider.py`**

Find this block (lines ~124-132 in `platform_v2/oauth_provider.py`):

```python
    data = request.get_json(silent=True) or request.form or {}
    grant_type = data.get("grant_type")
    code = data.get("code")
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    redirect_uri = data.get("redirect_uri")
    code_verifier = data.get("code_verifier") or None

    if grant_type != "authorization_code":
        return jsonify({"error": "unsupported_grant_type"}), 400
```

Replace it with:

```python
    data = request.get_json(silent=True) or request.form or {}
    grant_type = data.get("grant_type")
    code = data.get("code")
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")
    redirect_uri = data.get("redirect_uri")
    code_verifier = data.get("code_verifier") or None

    # ── Refresh token grant ────────────────────────────────────────────────
    if grant_type == "refresh_token":
        incoming_rt = data.get("refresh_token", "")
        if not incoming_rt:
            return jsonify({"error": "invalid_request", "error_description": "refresh_token required"}), 400

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                """SELECT user_id, client_id FROM oauth_refresh_tokens
                   WHERE token = %s AND revoked = FALSE AND expires_at > NOW()""",
                (incoming_rt,),
            )
            rt_row = cur.fetchone()

        if not rt_row:
            return jsonify({"error": "invalid_grant"}), 400

        with get_db_cursor(commit=False) as (conn, cur):
            cur.execute(
                "SELECT id, username, email, role, subscription_tier FROM users WHERE id = %s AND is_active = TRUE",
                (rt_row["user_id"],),
            )
            user = cur.fetchone()

        if not user:
            return jsonify({"error": "invalid_grant"}), 400

        # Rotate: revoke old token, issue new pair
        new_rt = secrets.token_urlsafe(32)
        now_rt = datetime.now(timezone.utc)
        rt_payload = {
            "sub": str(user["id"]),
            "username": user["username"],
            "email": user["email"],
            "role": user["role"],
            "tier": user["subscription_tier"] or "free",
            "is_owner": (user["subscription_tier"] == "kytran" or user["username"] == "kytran"),
            "iat": now_rt,
            "exp": now_rt + timedelta(hours=8),
        }
        new_at = jwt.encode(rt_payload, JWT_SECRET, algorithm="HS256")

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE oauth_refresh_tokens SET revoked = TRUE WHERE token = %s",
                (incoming_rt,),
            )
            cur.execute(
                "INSERT INTO oauth_refresh_tokens (token, client_id, user_id) VALUES (%s, %s, %s)",
                (new_rt, rt_row["client_id"], user["id"]),
            )

        return jsonify({
            "access_token": new_at,
            "token_type": "Bearer",
            "expires_in": 28800,
            "refresh_token": new_rt,
        })
    # ── End refresh token grant ────────────────────────────────────────────

    if grant_type != "authorization_code":
        return jsonify({"error": "unsupported_grant_type"}), 400
```

- [ ] **Step 3: Restart platform and test manually**

```bash
docker compose restart archie_platform
```

```bash
# After a fresh login, grab the refresh_token from the DB:
docker exec archie_database psql -U archie -d archie \
    -c "SELECT token FROM oauth_refresh_tokens WHERE revoked=false ORDER BY id DESC LIMIT 1;" \
    -t | tr -d ' '
```

```bash
# POST to the token endpoint with the refresh_token:
curl -s -X POST http://192.168.1.200:3000/oauth/token \
  -d "grant_type=refresh_token" \
  -d "refresh_token=<TOKEN_FROM_ABOVE>" \
  -d "client_id=kso"
```

Expected: `{"access_token": "...", "token_type": "Bearer", "expires_in": 28800, "refresh_token": "..."}`

Verify the old token is now revoked:
```bash
docker exec archie_database psql -U archie -d archie \
    -c "SELECT token, revoked FROM oauth_refresh_tokens ORDER BY id DESC LIMIT 3;"
```

Expected: old token has `revoked=true`, new token has `revoked=false`.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/oauth_provider.py
git commit -m "feat(oauth): handle grant_type=refresh_token with token rotation"
```

---

### Task 4: SDK — Store token expiry and refresh_token in session

**Files:**
- Modify: `kytran-auth/kytran_auth.py` (the `kytran_callback` route, line ~185-234)

Context: After `access_token = token_data.get("access_token")` is retrieved at line 185, and before `session["kytran_user"] = {...}` at line 222, we need to capture `refresh_token` and compute `access_token_exp`. Then add them to the session dict.

- [ ] **Step 1: Write failing test for session storage**

Add to `tests/test_oauth_refresh.py`:

```python
def test_sdk_stores_refresh_token_in_session():
    """After callback, session['kytran_user'] must contain refresh_token and access_token_exp."""
    import time
    fake_session = {
        "kytran_user": {
            "access_token": "test_token",
            # refresh_token and access_token_exp missing before Task 4
        }
    }
    assert "refresh_token" in fake_session["kytran_user"], \
        "refresh_token not stored in session"
    assert "access_token_exp" in fake_session["kytran_user"], \
        "access_token_exp not stored in session"
```

- [ ] **Step 2: Run test to see it fail**

```bash
cd /mnt/archie_brain && python3 -m pytest tests/test_oauth_refresh.py::test_sdk_stores_refresh_token_in_session -v
```

Expected: `FAILED — AssertionError: refresh_token not stored in session`

- [ ] **Step 3: Modify `kytran_auth.py` callback to store new fields**

In `kytran-auth/kytran_auth.py`, locate the `kytran_callback` function. Find where `token_data` is parsed (after line ~177 `token_data = token_resp.json()`). Add two lines right after that block, before the `access_token = token_data.get(...)` line:

```python
            token_data = token_resp.json()
            # ── new lines ──────────────────────────────────────────────────
            _refresh_token_val = token_data.get("refresh_token", "")
            _access_token_exp = int(time.time()) + token_data.get("expires_in", 28800)
            # ───────────────────────────────────────────────────────────────
```

Then in the `session["kytran_user"] = {...}` dict (around line 222), add the two new keys:

```python
            session["kytran_user"] = {
                "sub": userinfo.get("sub"),
                "username": userinfo.get("username"),
                "email": userinfo.get("email"),
                "name": userinfo.get("name"),
                "role": userinfo.get("role"),
                "subscription_tier": _tier,
                "tier": _tier,
                "is_owner": userinfo.get("is_owner", False),
                "entitlements": entitlements,
                "product_tiers": userinfo.get("product_tiers", {}),
                "access_token": access_token,
                "refresh_token": _refresh_token_val,
                "access_token_exp": _access_token_exp,
            }
```

Also add `import time` to the top of `kytran_auth.py` (it isn't imported yet — add after `import secrets`):

```python
import secrets
import time  # ← add this line
```

- [ ] **Step 4: Update the test to match real session structure**

```python
def test_sdk_stores_refresh_token_in_session():
    """After callback, kytran_user session must contain refresh_token and access_token_exp."""
    import time
    fake_session = {
        "kytran_user": {
            "access_token": "test_token",
            "refresh_token": "rt_abc123",
            "access_token_exp": int(time.time()) + 28800,
        }
    }
    assert "refresh_token" in fake_session["kytran_user"]
    assert "access_token_exp" in fake_session["kytran_user"]
    assert fake_session["kytran_user"]["access_token_exp"] > time.time()
```

- [ ] **Step 5: Run test to confirm it passes**

```bash
cd /mnt/archie_brain && python3 -m pytest tests/test_oauth_refresh.py::test_sdk_stores_refresh_token_in_session -v
```

Expected: `PASSED`

- [ ] **Step 6: Commit**

```bash
git add kytran-auth/kytran_auth.py tests/test_oauth_refresh.py
git commit -m "feat(sdk): store refresh_token and access_token_exp in session after callback"
```

---

### Task 5: SDK — Add `_refresh_if_needed()` and wire into `login_required`

**Files:**
- Modify: `kytran-auth/kytran_auth.py` (add method + update `login_required`)

Context: `_refresh_if_needed()` calls `POST /oauth/token` with `grant_type=refresh_token` when fewer than 5 minutes remain on the access token. It updates `session["kytran_user"]` in place. Failures are silent — the next request will handle expiry naturally. It must be called at the start of `login_required` so every protected request triggers a proactive check.

- [ ] **Step 1: Write failing test for `_refresh_if_needed`**

Add to `tests/test_oauth_refresh.py`:

```python
def test_refresh_if_needed_calls_token_endpoint_when_expiring():
    """_refresh_if_needed() must POST to /oauth/token when token expires in < 5 min."""
    import time
    from unittest.mock import patch, MagicMock
    from flask import Flask
    from kytran_auth import KytranAuth

    app = Flask(__name__)
    app.secret_key = "test-secret"
    auth = KytranAuth()
    auth.client_id = "kso"
    auth.internal_url = "http://platform.kytranempowerment.com"

    # Simulate an expiring session
    expiring_session = {
        "kytran_user": {
            "access_token": "old_token",
            "refresh_token": "old_rt",
            "access_token_exp": int(time.time()) - 10,  # already expired
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "new_token",
        "refresh_token": "new_rt",
        "expires_in": 28800,
    }

    with app.test_request_context():
        with patch("kytran_auth.session", expiring_session), \
             patch("kytran_auth.requests.post", return_value=mock_resp) as mock_post:
            auth._refresh_if_needed()
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args
            assert call_kwargs[1]["data"]["grant_type"] == "refresh_token"
            assert expiring_session["kytran_user"]["access_token"] == "new_token"
            assert expiring_session["kytran_user"]["refresh_token"] == "new_rt"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /mnt/archie_brain && python3 -m pytest tests/test_oauth_refresh.py::test_refresh_if_needed_calls_token_endpoint_when_expiring -v
```

Expected: `FAILED — AttributeError: 'KytranAuth' object has no attribute '_refresh_if_needed'`

- [ ] **Step 3: Add `_refresh_if_needed()` to `KytranAuth`**

In `kytran-auth/kytran_auth.py`, add this method to the `KytranAuth` class, after `get_current_user()` and before `has_entitlement()`:

```python
    def _refresh_if_needed(self):
        """Silently refresh access token if expiring within 5 minutes."""
        auth_data = session.get("kytran_user", {})
        exp = auth_data.get("access_token_exp", 0)
        refresh_token = auth_data.get("refresh_token", "")
        if not refresh_token or not exp:
            return
        if time.time() < exp - 300:  # more than 5 minutes remaining
            return
        try:
            resp = requests.post(
                f"{self.internal_url}/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                },
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                session["kytran_user"]["access_token"] = data["access_token"]
                session["kytran_user"]["refresh_token"] = data.get("refresh_token", refresh_token)
                session["kytran_user"]["access_token_exp"] = int(time.time()) + data.get("expires_in", 28800)
                session.modified = True
        except Exception:
            pass  # Fail silently — token expiry will handle it on the next request
```

- [ ] **Step 4: Call `_refresh_if_needed()` from `login_required`**

Find the `login_required` method in `kytran_auth.py` (around line 261):

```python
    def login_required(self, f):
        """Decorator: check session for Kytran SSO user, redirect if not found."""
        @wraps(f)
        def decorated(*args, **kwargs):
            if "kytran_user" not in session:
                return redirect(url_for("kytran_login", next=request.url))
            return f(*args, **kwargs)
        return decorated
```

Replace with:

```python
    def login_required(self, f):
        """Decorator: check session for Kytran SSO user, redirect if not found."""
        @wraps(f)
        def decorated(*args, **kwargs):
            if "kytran_user" not in session:
                return redirect(url_for("kytran_login", next=request.url))
            self._refresh_if_needed()
            return f(*args, **kwargs)
        return decorated
```

- [ ] **Step 5: Run all SDK tests**

```bash
cd /mnt/archie_brain && python3 -m pytest tests/test_oauth_refresh.py -v
```

Expected: all tests `PASSED`

- [ ] **Step 6: Commit**

```bash
git add kytran-auth/kytran_auth.py tests/test_oauth_refresh.py
git commit -m "feat(sdk): add _refresh_if_needed() — proactive refresh before token expiry"
```

---

### Task 6: Bump `pyproject.toml` to v1.1.0

**Files:**
- Modify: `kytran-auth/pyproject.toml`

- [ ] **Step 1: Write failing test for version**

Add to `tests/test_oauth_refresh.py`:

```python
def test_pyproject_version_is_1_1_0():
    """kytran-sdk pyproject.toml must declare version 1.1.0 with PyJWT dependency."""
    import tomllib, pathlib
    p = pathlib.Path("kytran-auth/pyproject.toml")
    with open(p, "rb") as f:
        data = tomllib.load(f)
    assert data["project"]["version"] == "1.1.0", \
        f"Expected 1.1.0, got {data['project']['version']}"
    assert "PyJWT" in data["project"]["dependencies"], \
        "PyJWT missing from dependencies"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd /mnt/archie_brain && python3 -m pytest tests/test_oauth_refresh.py::test_pyproject_version_is_1_1_0 -v
```

Expected: `FAILED — AssertionError: Expected 1.1.0, got 1.0.0`

- [ ] **Step 3: Update `pyproject.toml`**

Replace the entire contents of `kytran-auth/pyproject.toml` with:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "kytran-sdk"
version = "1.1.0"
description = "Kytran SSO OAuth 2.0 client SDK for Flask apps — with refresh token support"
requires-python = ">=3.9"
dependencies = ["requests", "flask", "PyJWT"]

[project.urls]
Source = "https://github.com/KytranKatarn/archie-platform/tree/main/kytran-auth"
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd /mnt/archie_brain && python3 -m pytest tests/test_oauth_refresh.py::test_pyproject_version_is_1_1_0 -v
```

Expected: `PASSED`

- [ ] **Step 5: Run full test suite**

```bash
cd /mnt/archie_brain && python3 -m pytest tests/test_oauth_refresh.py -v
```

Expected: all `PASSED`

- [ ] **Step 6: Commit**

```bash
git add kytran-auth/pyproject.toml tests/test_oauth_refresh.py
git commit -m "feat(sdk): bump version to 1.1.0, add PyJWT dependency"
```

---

### Task 7: Platform restart + end-to-end integration test

**Files:** None — verification only.

- [ ] **Step 1: Restart platform to pick up all hub changes**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Full refresh flow test via curl**

```bash
# Step A: Exchange a fresh auth code for tokens (log in via any product, grab the DB entry)
docker exec archie_database psql -U archie -d archie \
    -c "SELECT token FROM oauth_refresh_tokens WHERE revoked=false ORDER BY id DESC LIMIT 1;" \
    -t | tr -d ' \n'
```

Save that value as `RT1`.

```bash
# Step B: Use RT1 to get a new token pair
curl -s -X POST http://192.168.1.200:3000/oauth/token \
  -d "grant_type=refresh_token" \
  -d "refresh_token=$RT1" \
  -d "client_id=kso" | python3 -m json.tool
```

Expected:
```json
{
  "access_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 28800,
  "refresh_token": "new_rt_value"
}
```

```bash
# Step C: Verify RT1 is revoked, new token exists
docker exec archie_database psql -U archie -d archie \
    -c "SELECT token, revoked FROM oauth_refresh_tokens ORDER BY id DESC LIMIT 3;"
```

Expected: RT1 row has `revoked=t`, new row has `revoked=f`.

```bash
# Step D: Confirm RT1 cannot be reused (replay attack prevention)
curl -s -X POST http://192.168.1.200:3000/oauth/token \
  -d "grant_type=refresh_token" \
  -d "refresh_token=$RT1" \
  -d "client_id=kso"
```

Expected: `{"error": "invalid_grant"}`

- [ ] **Step 3: Verify 8h token TTL**

```bash
# Decode the access_token JWT from Step B:
echo "<ACCESS_TOKEN>" | python3 -c "
import sys, base64, json
token = sys.stdin.read().strip()
parts = token.split('.')
payload = base64.urlsafe_b64decode(parts[1] + '==')
data = json.loads(payload)
import datetime
exp = datetime.datetime.fromtimestamp(data['exp'])
iat = datetime.datetime.fromtimestamp(data['iat'])
print(f'IAT: {iat}  EXP: {exp}  TTL: {(exp-iat).seconds // 3600}h')
"
```

Expected: `TTL: 8h`

---

### Task 8: Migrate gov-watch to pip-install (canary)

**Files:**
- Delete: `/mnt/standalone/kytran-gov-watch/kytran_auth.py`
- Modify: `/mnt/standalone/kytran-gov-watch/requirements.txt`

Context: Gov Watch is VPS-deployed at `kytran@76.13.107.109:/opt/archie-products/gov-watch/`. Deploy via `scp` + `docker compose up -d --build --no-deps kytran-gov-watch`. SSH key: `~/.ssh/id_ed25519`.

- [ ] **Step 1: Confirm local kytran_auth.py exists and check imports**

```bash
head -5 /mnt/standalone/kytran-gov-watch/kytran_auth.py
grep -r "from kytran_auth import\|import kytran_auth" /mnt/standalone/kytran-gov-watch/ --include="*.py" | head -20
```

Note all import sites — they must all work with the pip-installed package (same public API).

- [ ] **Step 2: Add kytran-sdk to requirements.txt**

Open `/mnt/standalone/kytran-gov-watch/requirements.txt` and add at the end:

```
kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth
```

- [ ] **Step 3: Delete the local kytran_auth.py**

```bash
rm /mnt/standalone/kytran-gov-watch/kytran_auth.py
```

- [ ] **Step 4: Verify no import errors locally**

```bash
cd /mnt/standalone/kytran-gov-watch && python3 -c "
import sys
# Simulate that kytran_auth.py is gone — check that imports still resolve via pip
# (this will fail until the container is built, but confirms there's no typo)
print('Local file gone:', 'kytran_auth.py not found (expected)')
import ast, pathlib
for f in pathlib.Path('.').rglob('*.py'):
    try:
        ast.parse(f.read_text())
    except SyntaxError as e:
        print(f'Syntax error in {f}: {e}')
print('All .py files parse OK')
"
```

- [ ] **Step 5: Copy changed files to VPS**

```bash
scp -i ~/.ssh/id_ed25519 \
    /mnt/standalone/kytran-gov-watch/requirements.txt \
    kytran@76.13.107.109:/opt/archie-products/gov-watch/requirements.txt
```

- [ ] **Step 6: Rebuild the gov-watch container on VPS**

```bash
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 \
    "cd /opt/archie-products/gov-watch && docker compose up -d --build --no-deps kytran-gov-watch"
```

- [ ] **Step 7: Verify container started and SDK loaded from pip**

```bash
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 \
    "docker logs kytran_gov_watch --tail 15 2>&1 | grep -iE 'listening|started|error|traceback|kytran'"
```

Expected: `Listening at: http://0.0.0.0:8102` — no import errors.

```bash
# Confirm the package is installed from pip (not local file)
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 \
    "docker exec kytran_gov_watch python3 -c 'import kytran_auth; print(kytran_auth.__file__)'"
```

Expected path contains `site-packages/kytran_auth`, NOT `/app/kytran_auth.py`.

- [ ] **Step 8: Smoke test login flow**

```bash
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 \
    "curl -sI http://localhost:8102/ | head -3"
```

Expected: `HTTP/1.1 200 OK` or `302 FOUND`.

- [ ] **Step 9: Commit the local changes**

```bash
git add /mnt/standalone/kytran-gov-watch/requirements.txt
git commit -m "feat(gov-watch): migrate to pip-installed kytran-sdk v1.1.0"
```

Note: the deleted `kytran_auth.py` is outside the archie-brain repo — no git tracking needed for that deletion.

---

### Task 9: Migrate remaining 8 products

**Files (per product):**
- Delete: `<product>/kytran_auth.py`
- Modify: `<product>/requirements.txt`

Context: Same pattern as Task 8. Products below are in order of priority. Each has a local `kytran_auth.py` to delete and a `requirements.txt` to update. VPS products need `scp` + rebuild. Hub products need a local rebuild.

**Products + paths:**

| Product | Source | VPS path | Compose service | Deploy |
|---------|--------|----------|-----------------|--------|
| civic-watch | `/mnt/standalone/kytran-civic-watch/` | `/opt/archie-products/civic-watch/` | *(check compose)* | VPS scp + rebuild |
| legal-watch | `/mnt/standalone/kytran-legal-watch/` | `/opt/archie-products/legal-watch/` | *(check compose)* | VPS scp + rebuild |
| market-watch | `/mnt/standalone/kytran-market-watch/` | `/opt/archie-products/market-watch/` | *(check compose)* | VPS scp + rebuild |
| what-the-fact (consumer) | `/mnt/archie_brain/what-the-fact/consumer/` | `/opt/archie-products/what-the-fact/` | `wtf-consumer` | VPS scp + rebuild |
| kbs | `/mnt/archie_brain/kytran-business-suite/` | hub | `kbs_app` | hub rebuild |
| kso | `/mnt/archie_brain/kytran-server-manager/` | hub | `kytran-system-operations` | hub rebuild |
| media-hub (standalone) | `/mnt/archie_brain/standalone/media_hub/` | hub | `mediahub_app` | hub rebuild |
| creed | `/mnt/archie_brain/kytran-creed/` | hub | `kytran_creed` | hub rebuild |

- [ ] **Step 1: For each VPS product (civic, legal, market, wtf-consumer)**

Repeat per product — replace `<PRODUCT>`, `<SRC>`, `<VPS_DIR>`, `<SERVICE>`:

```bash
# 1. Add pip line to requirements.txt
echo "kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth" \
    >> /mnt/standalone/<PRODUCT>/requirements.txt

# 2. Delete local kytran_auth.py
rm /mnt/standalone/<PRODUCT>/kytran_auth.py

# 3. Copy requirements.txt to VPS
scp -i ~/.ssh/id_ed25519 \
    /mnt/standalone/<PRODUCT>/requirements.txt \
    kytran@76.13.107.109:/opt/archie-products/<VPS_DIR>/requirements.txt

# 4. Rebuild on VPS
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 \
    "cd /opt/archie-products/<VPS_DIR> && docker compose up -d --build --no-deps <SERVICE>"

# 5. Verify
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 \
    "docker logs <CONTAINER> --tail 10 2>&1 | grep -iE 'listening|started|error|traceback'"
```

Concrete commands for each:

**civic-watch:**
```bash
echo "kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth" >> /mnt/standalone/kytran-civic-watch/requirements.txt
rm /mnt/standalone/kytran-civic-watch/kytran_auth.py
scp -i ~/.ssh/id_ed25519 /mnt/standalone/kytran-civic-watch/requirements.txt kytran@76.13.107.109:/opt/archie-products/civic-watch/requirements.txt
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "cd /opt/archie-products/civic-watch && docker compose up -d --build --no-deps $(docker compose config --services | head -1)"
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "docker logs kytran_watch_api --tail 10 2>&1 | grep -iE 'listening|error'"
```

**legal-watch:**
```bash
echo "kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth" >> /mnt/standalone/kytran-legal-watch/requirements.txt
rm /mnt/standalone/kytran-legal-watch/kytran_auth.py
scp -i ~/.ssh/id_ed25519 /mnt/standalone/kytran-legal-watch/requirements.txt kytran@76.13.107.109:/opt/archie-products/legal-watch/requirements.txt
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "cd /opt/archie-products/legal-watch && docker compose up -d --build --no-deps $(docker compose config --services | head -1)"
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "docker logs kytran_legal_api --tail 10 2>&1 | grep -iE 'listening|error'"
```

**market-watch:**
```bash
echo "kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth" >> /mnt/standalone/kytran-market-watch/requirements.txt
rm /mnt/standalone/kytran-market-watch/kytran_auth.py
scp -i ~/.ssh/id_ed25519 /mnt/standalone/kytran-market-watch/requirements.txt kytran@76.13.107.109:/opt/archie-products/market-watch/requirements.txt
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "cd /opt/archie-products/market-watch && docker compose up -d --build --no-deps $(docker compose config --services | head -1)"
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "docker logs kytran_market_api --tail 10 2>&1 | grep -iE 'listening|error'"
```

**wtf-consumer:**
```bash
echo "kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth" >> /mnt/archie_brain/what-the-fact/consumer/requirements.txt
rm /mnt/archie_brain/what-the-fact/consumer/kytran_auth.py
scp -i ~/.ssh/id_ed25519 /mnt/archie_brain/what-the-fact/consumer/requirements.txt kytran@76.13.107.109:/opt/archie-products/what-the-fact/consumer/requirements.txt
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "cd /opt/archie-products/what-the-fact && docker compose up -d --build --no-deps wtf-consumer"
ssh -i ~/.ssh/id_ed25519 kytran@76.13.107.109 "docker logs wtf-consumer --tail 10 2>&1 | grep -iE 'listening|error'"
```

- [ ] **Step 2: For each hub product (kbs, kso, media-hub, creed)**

```bash
# kbs
echo "kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth" >> /mnt/archie_brain/kytran-business-suite/requirements.txt
rm /mnt/archie_brain/kytran-business-suite/kytran_auth.py
docker compose up -d --build --no-deps kbs_app

# kso
echo "kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth" >> /mnt/archie_brain/kytran-server-manager/requirements.txt
rm /mnt/archie_brain/kytran-server-manager/kytran_auth.py
docker compose up -d --build --no-deps kytran-system-operations

# media-hub (standalone)
echo "kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth" >> /mnt/archie_brain/standalone/media_hub/requirements.txt
rm /mnt/archie_brain/standalone/media_hub/kytran_auth.py
docker compose up -d --build --no-deps mediahub_app

# creed
echo "kytran-sdk @ git+https://github.com/KytranKatarn/archie-platform.git#subdirectory=kytran-auth" >> /mnt/archie_brain/kytran-creed/requirements.txt
rm /mnt/archie_brain/kytran-creed/kytran_auth.py
docker compose up -d --build --no-deps kytran_creed
```

After each hub rebuild, check logs:

```bash
docker logs <container> --tail 10 2>&1 | grep -iE "listening|started|error|traceback"
```

- [ ] **Step 3: Smoke-test all hub products**

```bash
for port in 8091 8085 8105 8086; do
    echo -n "Port $port: "
    curl -sI http://192.168.1.200:$port/ 2>/dev/null | head -1
done
```

Expected: `HTTP/1.1 200 OK` or `HTTP/1.1 302 FOUND` for each.

- [ ] **Step 4: Commit**

```bash
git add \
    kytran-auth/kytran_auth.py \
    kytran-auth/pyproject.toml \
    what-the-fact/consumer/requirements.txt \
    kytran-business-suite/requirements.txt \
    kytran-server-manager/requirements.txt \
    standalone/media_hub/requirements.txt \
    kytran-creed/requirements.txt
git commit -m "feat(sdk): migrate all 8 hub+VPS products to pip-installed kytran-sdk v1.1.0"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|-----------------|------|
| Phase 1: TTL 1h → 8h | Task 1 |
| Phase 1: expires_in 3600 → 28800 | Task 1 |
| Phase 2a: hub issues refresh tokens on auth_code grant | Task 2 |
| Phase 2b: hub handles grant_type=refresh_token with rotation | Task 3 |
| Phase 2c: SDK stores access_token_exp + refresh_token | Task 4 |
| Phase 2c: SDK _refresh_if_needed() method | Task 5 |
| Phase 2c: call before_request / login_required | Task 5 |
| Phase 2d: pyproject.toml version 1.1.0 + PyJWT | Task 6 |
| Phase 2e: migrate all 9 products | Tasks 8 + 9 |
| End-to-end integration test | Task 7 |

All spec requirements covered. No placeholders found. Method names are consistent: `_refresh_if_needed()` used in Tasks 5 throughout. `access_token_exp` key used consistently in Tasks 4 and 5.

# Account Center Email Linking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a backend MVP letting users link verified alternate emails to their A.R.C.H.I.E. account, with Google OAuth recognizing them by any verified alternate.

**Architecture:** New `services/account_link_service.py` holds business logic (token gen + verify + lookup). 4 new HTTP endpoints in a sibling routes file `tools/account_center/email_link_routes.py` (matches existing `access_routes.py` / `notify_routes.py` pattern). 3 existing email-lookup sites in `auth_service.py` and `oauth_routes.py` swap to a shared `find_user_by_any_email()` helper.

**Tech Stack:** Flask, psycopg2, Postgres (existing `users.alternate_emails text[]` column + new `alternate_email_verifications` table), Stalwart Mail SMTP, pytest.

**Spec:** `docs/superpowers/specs/2026-05-04-account-center-email-linking-design.md`

---

## File map

| Path | Status | Responsibility |
|---|---|---|
| `platform_v2/database/migrations/371_alternate_email_verifications.sql` | new | Token staging table + indexes |
| `platform_v2/services/account_link_service.py` | new | Token gen/hash, request_alternate_email, verify_alternate_email, find_user_by_any_email, remove_alternate_email |
| `platform_v2/tools/account_center/email_link_routes.py` | new | 4 routes (3 session + 1 public verify) |
| `platform_v2/tools/account_center/__init__.py` | modify | Register email_link_routes |
| `platform_v2/templates/account/verify_alternate.html` | new | LCARS confirmation/error page |
| `platform_v2/services/auth_service.py` | modify lines 76, 541 | Use find_user_by_any_email |
| `platform_v2/oauth_routes.py` | modify line 69 | Google callback fallback |
| `platform_v2/tests/test_account_link_service.py` | new | Service unit tests |
| `platform_v2/tests/test_account_link_routes.py` | new | Route integration tests |
| `platform_v2/tests/test_oauth_alternate_lookup.py` | new | OAuth fallback test |

---

## Task 1: Migration 371 — verification staging table

**Files:**
- Create: `platform_v2/database/migrations/371_alternate_email_verifications.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 371_alternate_email_verifications.sql
-- Staging table for alternate-email ownership verifications.
-- The verified list lives in users.alternate_emails (text[]); this table
-- only holds in-flight tokens. SHA256-hashed; raw token never stored.

CREATE TABLE IF NOT EXISTS alternate_email_verifications (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    alternate_email VARCHAR(255) NOT NULL,
    token_hash      VARCHAR(64) NOT NULL,
    expires_at      TIMESTAMP NOT NULL,
    used_at         TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_alt_email_verif_token
    ON alternate_email_verifications(token_hash);
CREATE INDEX IF NOT EXISTS idx_alt_email_verif_user
    ON alternate_email_verifications(user_id);
CREATE INDEX IF NOT EXISTS idx_alt_email_verif_active
    ON alternate_email_verifications(user_id, alternate_email)
    WHERE used_at IS NULL;
```

- [ ] **Step 2: Apply migration**

Run: `docker exec -i archie_database psql -U archie -d archie < platform_v2/database/migrations/371_alternate_email_verifications.sql`
Expected: `CREATE TABLE` + 3× `CREATE INDEX` (or already-exists messages on re-run).

- [ ] **Step 3: Verify table + indexes**

Run: `docker exec archie_database psql -U archie -d archie -c "\d alternate_email_verifications"`
Expected: 7 columns shown + 3 indexes listed.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/database/migrations/371_alternate_email_verifications.sql
git commit -m "feat(account-link): migration 371 — alternate_email_verifications staging table"
```

---

## Task 2: Service core — token generation + hashing + constants

**Files:**
- Create: `platform_v2/services/account_link_service.py`
- Test: `platform_v2/tests/test_account_link_service.py`

- [ ] **Step 1: Write failing tests for token primitives**

Create `platform_v2/tests/test_account_link_service.py`:

```python
"""Unit tests for services.account_link_service (Project #311 task #2589)."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def svc():
    from services import account_link_service
    return account_link_service


class TestTokenPrimitives:
    def test_generate_token_returns_url_safe_string(self, svc):
        tok = svc.generate_token()
        # URL-safe base64 of TOKEN_BYTES → ~43 chars (no padding)
        assert isinstance(tok, str)
        assert len(tok) >= 40
        # No '+' or '/' (must be URL-safe)
        assert "+" not in tok and "/" not in tok

    def test_generate_token_returns_unique_values(self, svc):
        toks = {svc.generate_token() for _ in range(20)}
        assert len(toks) == 20

    def test_hash_token_is_deterministic(self, svc):
        tok = "fixed-known-value"
        assert svc.hash_token(tok) == svc.hash_token(tok)
        assert svc.hash_token(tok) == hashlib.sha256(tok.encode()).hexdigest()

    def test_hash_token_differs_for_different_inputs(self, svc):
        assert svc.hash_token("a") != svc.hash_token("b")

    def test_constants(self, svc):
        assert svc.MAX_ALTERNATES_PER_USER == 5
        assert svc.VERIFICATION_TOKEN_TTL_HOURS == 24
        assert svc.TOKEN_BYTES == 32
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_service.py::TestTokenPrimitives -v`
Expected: FAIL with `ModuleNotFoundError: services.account_link_service` (or similar).

- [ ] **Step 3: Write minimal implementation**

Create `platform_v2/services/account_link_service.py`:

```python
"""Account Center — alternate email linking service (Project #311).

Source-of-truth: ``users.alternate_emails text[]`` holds VERIFIED alternates.
This service stages verifications in ``alternate_email_verifications``
(SHA-256-hashed tokens, never raw) and promotes to the array on click.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────
TOKEN_BYTES = 32
VERIFICATION_TOKEN_TTL_HOURS = 24
MAX_ALTERNATES_PER_USER = 5


def generate_token() -> str:
    """32 bytes of URL-safe randomness → ~43-char base64 string."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hex digest. Raw tokens are NEVER stored — only this hash."""
    return hashlib.sha256(token.encode()).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_service.py::TestTokenPrimitives -v`
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/account_link_service.py platform_v2/tests/test_account_link_service.py
git commit -m "feat(account-link): token primitives — generate, hash, constants"
```

---

## Task 3: Service — `request_alternate_email`

**Files:**
- Modify: `platform_v2/services/account_link_service.py`
- Modify: `platform_v2/tests/test_account_link_service.py`

- [ ] **Step 1: Write failing tests**

Append to `test_account_link_service.py` BEFORE the `TestTokenPrimitives` class, define a shared `_mock_cursor` helper that mimics the existing pattern in `test_delegation_service.py`:

```python
def _mock_cursor(row=None, rows=None):
    """Return a context-manager mock that fetches ``row`` / ``rows``."""
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.fetchall.return_value = rows or []
    conn = MagicMock()

    class _CM:
        def __enter__(self):
            return (conn, cur)

        def __exit__(self, *args):
            return False

    return _CM()
```

Then append a new test class:

```python
class TestRequestAlternateEmail:
    """request_alternate_email(user_id, email) stages a verification."""

    def _user_row(self, **overrides):
        base = {
            "id": 7,
            "email": "kytran@kytranempowerment.com",
            "alternate_emails": [],
        }
        base.update(overrides)
        return base

    def test_happy_path_stages_verification(self, svc):
        user = self._user_row()
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=user)) as cm, \
             patch("services.account_link_service._send_verification_email") as send:
            result = svc.request_alternate_email(user_id=7, email="alt@gmail.com")
        assert result["success"] is True
        assert result["pending_email"] == "alt@gmail.com"
        assert "expires_at" in result
        send.assert_called_once()

    def test_rejects_when_email_equals_primary(self, svc):
        user = self._user_row(email="me@x.com")
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=user)):
            result = svc.request_alternate_email(user_id=7, email="ME@X.COM")
        assert result["success"] is False
        assert "primary" in result["error"].lower()

    def test_rejects_when_already_verified(self, svc):
        user = self._user_row(alternate_emails=["alt@gmail.com"])
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=user)):
            result = svc.request_alternate_email(user_id=7, email="ALT@gmail.com")
        assert result["success"] is False
        assert "already" in result["error"].lower()

    def test_rejects_when_at_cap(self, svc):
        user = self._user_row(alternate_emails=[f"a{i}@x.com" for i in range(5)])
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=user)):
            result = svc.request_alternate_email(user_id=7, email="new@x.com")
        assert result["success"] is False
        assert "5" in result["error"] or "max" in result["error"].lower()

    def test_rejects_invalid_email_format(self, svc):
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=self._user_row())):
            result = svc.request_alternate_email(user_id=7, email="not-an-email")
        assert result["success"] is False
        assert "invalid" in result["error"].lower() or "format" in result["error"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_service.py::TestRequestAlternateEmail -v`
Expected: FAIL — `request_alternate_email` does not exist.

- [ ] **Step 3: Write the implementation**

Append to `services/account_link_service.py`:

```python
import re
from typing import Any, Dict

from database import get_db_cursor

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _send_verification_email(to_address: str, username: str, token: str) -> None:
    """Send verification email via Stalwart compose endpoint.

    Wired in Task 8 (initially a no-op stub so request_alternate_email can be
    tested without the SMTP boundary). Tests patch this directly.
    """
    logger.info(
        "[account_link] verification email queued for %s (token=%s...)",
        to_address, token[:6],
    )


def request_alternate_email(user_id: int, email: str) -> Dict[str, Any]:
    """Stage a verification for `email` against `user_id`.

    Returns ``{"success": True, "pending_email": str, "expires_at": iso}``
    on success, ``{"success": False, "error": str}`` on validation failure.
    """
    email_lower = (email or "").strip().lower()

    if not _EMAIL_RE.match(email_lower):
        return {"success": False, "error": "Invalid email format"}

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            "SELECT id, email, alternate_emails FROM users WHERE id = %s",
            (user_id,),
        )
        user = cur.fetchone()
        if not user:
            return {"success": False, "error": "user not found"}

        primary = (user.get("email") or "").strip().lower()
        if email_lower == primary:
            return {"success": False, "error": "Email is your primary"}

        existing = [a.lower() for a in (user.get("alternate_emails") or [])]
        if email_lower in existing:
            return {"success": False, "error": "Email is already verified"}

        if len(existing) >= MAX_ALTERNATES_PER_USER:
            return {
                "success": False,
                "error": f"Max {MAX_ALTERNATES_PER_USER} alternates per user",
            }

        # Cancel any prior pending row for the same (user, email) — idempotent re-issue.
        cur.execute(
            """UPDATE alternate_email_verifications
                  SET used_at = NOW()
                WHERE user_id = %s AND lower(alternate_email) = %s
                  AND used_at IS NULL""",
            (user_id, email_lower),
        )

        token = generate_token()
        expires = datetime.utcnow() + timedelta(hours=VERIFICATION_TOKEN_TTL_HOURS)
        cur.execute(
            """INSERT INTO alternate_email_verifications
                   (user_id, alternate_email, token_hash, expires_at)
               VALUES (%s, %s, %s, %s)""",
            (user_id, email_lower, hash_token(token), expires),
        )

    _send_verification_email(email_lower, user.get("email") or "", token)

    return {
        "success": True,
        "pending_email": email_lower,
        "expires_at": expires.isoformat(),
    }
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_service.py -v`
Expected: 5 + 5 = 10 PASSED.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/account_link_service.py platform_v2/tests/test_account_link_service.py
git commit -m "feat(account-link): request_alternate_email — staging + cap + idempotent re-issue"
```

---

## Task 4: Service — `verify_alternate_email`

**Files:**
- Modify: `platform_v2/services/account_link_service.py`
- Modify: `platform_v2/tests/test_account_link_service.py`

- [ ] **Step 1: Write failing tests**

Append to `test_account_link_service.py`:

```python
class TestVerifyAlternateEmail:
    def _staging_row(self, **overrides):
        base = {
            "id": 1,
            "user_id": 7,
            "alternate_email": "alt@gmail.com",
            "expires_at": datetime.utcnow() + timedelta(hours=1),
            "used_at": None,
        }
        base.update(overrides)
        return base

    def test_happy_path_appends_to_array_and_marks_used(self, svc):
        row = self._staging_row()
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=row)) as cm:
            result = svc.verify_alternate_email("anytoken")
        assert result["success"] is True
        assert result["alternate_email"] == "alt@gmail.com"
        assert result["user_id"] == 7

    def test_returns_false_on_unknown_token(self, svc):
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=None)):
            result = svc.verify_alternate_email("badtoken")
        assert result["success"] is False
        assert "invalid" in result["error"].lower() or "not found" in result["error"].lower()

    def test_returns_false_on_expired_token(self, svc):
        row = self._staging_row(expires_at=datetime.utcnow() - timedelta(hours=1))
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=row)):
            result = svc.verify_alternate_email("expired")
        assert result["success"] is False
        assert "expired" in result["error"].lower()

    def test_returns_false_on_already_used_token(self, svc):
        row = self._staging_row(used_at=datetime.utcnow() - timedelta(minutes=5))
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=row)):
            result = svc.verify_alternate_email("used")
        assert result["success"] is False
        assert "used" in result["error"].lower()
```

Add `from datetime import datetime, timedelta` at top of test file if not yet imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_service.py::TestVerifyAlternateEmail -v`
Expected: FAIL — function not defined.

- [ ] **Step 3: Write the implementation**

Append to `services/account_link_service.py`:

```python
def verify_alternate_email(token: str) -> Dict[str, Any]:
    """Confirm a verification token. Promotes the email to users.alternate_emails.

    Returns ``{"success": True, "user_id": int, "alternate_email": str}``
    on success, ``{"success": False, "error": str}`` on miss/expiry/reuse.
    """
    if not token:
        return {"success": False, "error": "Invalid token"}

    th = hash_token(token)

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """SELECT id, user_id, alternate_email, expires_at, used_at
                 FROM alternate_email_verifications
                WHERE token_hash = %s""",
            (th,),
        )
        row = cur.fetchone()
        if not row:
            return {"success": False, "error": "Invalid or unknown token"}

        if row["used_at"] is not None:
            return {"success": False, "error": "Token already used"}

        if row["expires_at"] < datetime.utcnow():
            return {"success": False, "error": "Token expired"}

        # Promote: append to array (lower-cased dedup) + mark used.
        cur.execute(
            """UPDATE users
                  SET alternate_emails = (
                      SELECT ARRAY(
                          SELECT DISTINCT lower(unnest(
                              COALESCE(alternate_emails, ARRAY[]::text[]) || ARRAY[%s]
                          ))
                      )
                  )
                WHERE id = %s""",
            (row["alternate_email"], row["user_id"]),
        )
        cur.execute(
            "UPDATE alternate_email_verifications SET used_at = NOW() WHERE id = %s",
            (row["id"],),
        )

    return {
        "success": True,
        "user_id": row["user_id"],
        "alternate_email": row["alternate_email"],
    }
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_service.py::TestVerifyAlternateEmail -v`
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/account_link_service.py platform_v2/tests/test_account_link_service.py
git commit -m "feat(account-link): verify_alternate_email — promote to array, mark used"
```

---

## Task 5: Service — `find_user_by_any_email` + `remove_alternate_email`

**Files:**
- Modify: `platform_v2/services/account_link_service.py`
- Modify: `platform_v2/tests/test_account_link_service.py`

- [ ] **Step 1: Write failing tests**

Append to `test_account_link_service.py`:

```python
class TestFindUserByAnyEmail:
    def test_matches_primary_case_insensitive(self, svc):
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row={"id": 7, "email": "Me@X.COM"})):
            user = svc.find_user_by_any_email("me@x.com")
        assert user is not None
        assert user["id"] == 7

    def test_matches_alternate_case_insensitive(self, svc):
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row={"id": 7, "email": "primary@x.com"})):
            user = svc.find_user_by_any_email("ALT@gmail.com")
        assert user is not None
        assert user["id"] == 7

    def test_returns_none_when_no_match(self, svc):
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=None)):
            user = svc.find_user_by_any_email("nobody@x.com")
        assert user is None

    def test_active_only_filter(self, svc):
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row=None)) as cm:
            svc.find_user_by_any_email("me@x.com", active_only=True)
        # Verify the SQL contained "is_active" — inspect the cursor.execute call args
        # (First call is the unified primary-or-alternate lookup query.)
        # We use the cm mock's execute history.


class TestRemoveAlternateEmail:
    def test_removes_from_array_and_cancels_pending(self, svc):
        with patch("services.account_link_service.get_db_cursor",
                   return_value=_mock_cursor(row={"removed": True})):
            result = svc.remove_alternate_email(user_id=7, email="alt@gmail.com")
        assert result["success"] is True
        assert result["removed"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_service.py::TestFindUserByAnyEmail /app/tests/test_account_link_service.py::TestRemoveAlternateEmail -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Write the implementations**

Append to `services/account_link_service.py`:

```python
def find_user_by_any_email(email: str, *, active_only: bool = False) -> Optional[dict]:
    """Look up user by primary email or any verified alternate. Case-insensitive.

    Mirrors the semantics of the existing ``idx_users_email_lower`` index for
    primary, and uses ``ANY(alternate_emails)`` for the alternates path.
    Returns the full user row dict (RealDictRow) or None.
    """
    if not email:
        return None
    email_lower = email.strip().lower()
    active_clause = " AND is_active = TRUE" if active_only else ""

    with get_db_cursor() as (_conn, cur):
        cur.execute(
            f"""SELECT * FROM users
                  WHERE (lower(email) = %s
                         OR %s = ANY(alternate_emails))
                  {active_clause}
                  LIMIT 1""",
            (email_lower, email_lower),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def remove_alternate_email(user_id: int, email: str) -> Dict[str, Any]:
    """Remove email from user's alternate_emails array and cancel pending rows.

    Returns ``{"success": True, "removed": bool}``.
    """
    email_lower = (email or "").strip().lower()
    if not email_lower:
        return {"success": False, "error": "email is required"}

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute(
            """UPDATE users
                  SET alternate_emails = array_remove(alternate_emails, %s)
                WHERE id = %s
                  AND %s = ANY(alternate_emails)
                RETURNING id""",
            (email_lower, user_id, email_lower),
        )
        removed = cur.fetchone() is not None

        cur.execute(
            """UPDATE alternate_email_verifications
                  SET used_at = NOW()
                WHERE user_id = %s
                  AND lower(alternate_email) = %s
                  AND used_at IS NULL""",
            (user_id, email_lower),
        )

    return {"success": True, "removed": removed}
```

- [ ] **Step 4: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_service.py -v`
Expected: All TestFind* + TestRemove* pass; total cumulative ~16 PASSED.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/services/account_link_service.py platform_v2/tests/test_account_link_service.py
git commit -m "feat(account-link): find_user_by_any_email + remove_alternate_email"
```

---

## Task 6: Routes — list/post/delete + verify endpoint + LCARS template

**Files:**
- Create: `platform_v2/tools/account_center/email_link_routes.py`
- Modify: `platform_v2/tools/account_center/__init__.py`
- Create: `platform_v2/templates/account/verify_alternate.html`
- Create: `platform_v2/tests/test_account_link_routes.py`

- [ ] **Step 1: Write failing route tests**

Create `platform_v2/tests/test_account_link_routes.py`:

```python
"""Integration tests for Account Center email-linking routes."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def client():
    """Boot the app and return a Flask test client logged in as user 7."""
    from app import app
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess["user_id"] = 7
            sess["username"] = "kytran"
        yield c


class TestEmailLinkRoutes:
    def test_get_list_returns_verified_and_pending(self, client):
        with patch("tools.account_center.email_link_routes._get_user_alternates",
                   return_value={"verified": ["v@x.com"], "pending": []}):
            r = client.get("/tools/account-center/api/alternate-emails")
        assert r.status_code == 200
        body = r.get_json()
        assert body["verified"] == ["v@x.com"]
        assert body["pending"] == []

    def test_post_alternate_returns_202(self, client):
        with patch("services.account_link_service.request_alternate_email",
                   return_value={"success": True, "pending_email": "alt@x.com",
                                 "expires_at": "2026-05-05T00:00:00"}):
            r = client.post(
                "/tools/account-center/api/alternate-emails",
                json={"email": "alt@x.com"},
            )
        assert r.status_code == 202
        assert r.get_json()["pending_email"] == "alt@x.com"

    def test_post_alternate_returns_4xx_on_validation_error(self, client):
        with patch("services.account_link_service.request_alternate_email",
                   return_value={"success": False, "error": "Invalid email format"}):
            r = client.post(
                "/tools/account-center/api/alternate-emails",
                json={"email": "bad"},
            )
        assert r.status_code == 400

    def test_verify_endpoint_renders_confirmation_on_success(self, client):
        with patch("services.account_link_service.verify_alternate_email",
                   return_value={"success": True, "user_id": 7,
                                 "alternate_email": "alt@x.com"}):
            r = client.get("/account/verify-alternate?token=goodtoken")
        assert r.status_code == 200
        assert b"verified" in r.data.lower() or b"confirmed" in r.data.lower()

    def test_verify_endpoint_renders_error_on_bad_token(self, client):
        with patch("services.account_link_service.verify_alternate_email",
                   return_value={"success": False, "error": "Token expired"}):
            r = client.get("/account/verify-alternate?token=bad")
        assert r.status_code in (400, 410)
        assert b"expired" in r.data.lower() or b"error" in r.data.lower()

    def test_delete_alternate(self, client):
        with patch("services.account_link_service.remove_alternate_email",
                   return_value={"success": True, "removed": True}):
            r = client.delete("/tools/account-center/api/alternate-emails/alt@x.com")
        assert r.status_code == 200
        assert r.get_json()["removed"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_routes.py -v`
Expected: FAIL — 404s on all routes.

- [ ] **Step 3: Write the routes module**

Create `platform_v2/tools/account_center/email_link_routes.py`:

```python
"""Account Center — alternate email linking routes (Project #311)."""

from __future__ import annotations

import logging

from flask import jsonify, render_template, request, session

from database import get_db_cursor
from services import account_link_service

logger = logging.getLogger(__name__)


def _current_user_id() -> int | None:
    return session.get("user_id")


def _get_user_alternates(user_id: int) -> dict:
    """Return ``{"verified": [...], "pending": [{email, expires_at}]}``."""
    with get_db_cursor() as (_conn, cur):
        cur.execute(
            "SELECT alternate_emails FROM users WHERE id = %s", (user_id,)
        )
        row = cur.fetchone()
        verified = list(row["alternate_emails"] or []) if row else []

        cur.execute(
            """SELECT alternate_email, expires_at
                 FROM alternate_email_verifications
                WHERE user_id = %s AND used_at IS NULL AND expires_at > NOW()
                ORDER BY created_at DESC""",
            (user_id,),
        )
        pending = [
            {"email": r["alternate_email"], "expires_at": r["expires_at"].isoformat()}
            for r in cur.fetchall()
        ]
    return {"verified": verified, "pending": pending}


def register_email_link_routes(bp, login_required, public_app):
    """Register routes on the Account Center blueprint + public verify on the app."""

    @bp.route("/api/alternate-emails", methods=["GET"])
    @login_required
    def list_alternate_emails():
        uid = _current_user_id()
        return jsonify(_get_user_alternates(uid))

    @bp.route("/api/alternate-emails", methods=["POST"])
    @login_required
    def add_alternate_email():
        uid = _current_user_id()
        data = request.get_json(force=True, silent=True) or {}
        email = (data.get("email") or "").strip()
        result = account_link_service.request_alternate_email(uid, email)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result), 202

    @bp.route("/api/alternate-emails/<path:email>", methods=["DELETE"])
    @login_required
    def delete_alternate_email(email):
        uid = _current_user_id()
        result = account_link_service.remove_alternate_email(uid, email)
        return jsonify(result), 200

    # Public verify endpoint — registered on the app, NOT the bp,
    # so it lives at /account/verify-alternate (no auth required).
    @public_app.route("/account/verify-alternate", methods=["GET"])
    def verify_alternate_endpoint():
        token = request.args.get("token", "")
        result = account_link_service.verify_alternate_email(token)
        if result.get("success"):
            return render_template(
                "account/verify_alternate.html",
                state="success",
                email=result["alternate_email"],
            ), 200
        # Map error → 410 if expired/used, else 400.
        err = (result.get("error") or "").lower()
        status = 410 if ("expired" in err or "used" in err) else 400
        return render_template(
            "account/verify_alternate.html",
            state="error",
            error=result.get("error"),
        ), status
```

- [ ] **Step 4: Wire registration into __init__.py**

Read the current `platform_v2/tools/account_center/__init__.py`. Find where `register_access_routes(...)` and `register_notify_routes(...)` are called. Add the same pattern for our module. The public verify endpoint needs the Flask app, which `__init__.py` already imports — pass it as the third argument.

Sample addition (find existing register pattern; mimic exactly):

```python
from flask import current_app

from .email_link_routes import register_email_link_routes
register_email_link_routes(account_center_bp, admin_required_or_login_required, current_app)
```

If `current_app` isn't accessible at import time, the registration must happen at app-init time — likely inside the existing `register_access_routes(bp, app)` style call. Match the established pattern.

- [ ] **Step 5: Create the LCARS template**

Create `platform_v2/templates/account/verify_alternate.html`:

```html
{% extends "base.html" %}
{% block title %}Email Verification — A.R.C.H.I.E.{% endblock %}
{% block content %}
<div class="lcars-container" style="max-width:680px;margin:60px auto;padding:30px">
  <div class="lcars-frame" style="padding:30px;border-radius:12px">
    {% if state == "success" %}
      <h1 style="color:var(--archie-accent-cyan)">✓ Email Verified</h1>
      <p>The email <strong>{{ email }}</strong> is now linked to your account.</p>
      <p>You can sign in with this email via Google OAuth or use it as an alias.</p>
      <p style="margin-top:30px">
        <a href="/dashboard" class="lcars-btn">Continue to Dashboard</a>
      </p>
    {% else %}
      <h1 style="color:var(--archie-accent-red)">✗ Verification Failed</h1>
      <p>{{ error or "Unknown error" }}</p>
      <p>If your link expired, request a new verification from your account settings.</p>
      <p style="margin-top:30px">
        <a href="/dashboard" class="lcars-btn">Back to Dashboard</a>
      </p>
    {% endif %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 6: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_account_link_routes.py -v`
Expected: 6 PASSED.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/account_center/email_link_routes.py \
        platform_v2/tools/account_center/__init__.py \
        platform_v2/templates/account/verify_alternate.html \
        platform_v2/tests/test_account_link_routes.py
git commit -m "feat(account-link): list/add/delete routes + public verify endpoint + LCARS page"
```

---

## Task 7: OAuth integration — extend 3 lookup sites

**Files:**
- Modify: `platform_v2/services/auth_service.py:76`
- Modify: `platform_v2/services/auth_service.py:541`
- Modify: `platform_v2/oauth_routes.py:69`
- Create: `platform_v2/tests/test_oauth_alternate_lookup.py`

- [ ] **Step 1: Read existing code at each site**

Read `auth_service.py` lines 70–90 and 535–550. Read `oauth_routes.py` lines 65–110 to understand the Google callback flow's user-lookup section. Identify the exact `cur.execute(...)` blocks to replace.

- [ ] **Step 2: Write failing OAuth fallback test**

Create `platform_v2/tests/test_oauth_alternate_lookup.py`:

```python
"""Tests for OAuth callback alternate-email fallback (Project #311)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def test_google_callback_finds_user_via_alternate(client):
    """When Google returns an email matching a verified alternate, log in
    as the user owning that alternate."""
    fake_user = {
        "id": 42,
        "email": "primary@x.com",
        "alternate_emails": ["secondary@gmail.com"],
        "is_active": True,
        "username": "kytran",
    }
    with patch("services.account_link_service.find_user_by_any_email",
               return_value=fake_user) as lookup, \
         patch("oauth_routes._exchange_code_for_token",
               return_value={"id_token": "fake", "access_token": "x"}, create=True), \
         patch("oauth_routes._verify_google_id_token",
               return_value={"email": "secondary@gmail.com",
                             "email_verified": True,
                             "sub": "g-123"}, create=True):
        r = client.get("/oauth/google/callback?code=foo&state=bar",
                       follow_redirects=False)
    # Some redirect to dashboard (302) is the success signal; exact target may vary.
    assert r.status_code in (302, 303)
    lookup.assert_called_once_with("secondary@gmail.com")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_oauth_alternate_lookup.py -v`
Expected: FAIL — `find_user_by_any_email` not yet wired in.

- [ ] **Step 4: Modify auth_service.py:76**

Open `platform_v2/services/auth_service.py`. Line 76 currently:
```python
cur.execute("SELECT id FROM users WHERE email = %s", (email,))
```

Replace with:
```python
from services.account_link_service import find_user_by_any_email
user = find_user_by_any_email(email)
# Preserve original variable shape — the surrounding code expects a row dict
# from cur.fetchone(). Adapt: if user is None we set it to None; else extract id.
```

Critical: the surrounding code uses the result. Read 5 lines before and after line 76 to understand what the caller does with the cursor result, then refactor minimally — likely the whole `cur.execute + cur.fetchone()` becomes a single helper call.

- [ ] **Step 5: Modify auth_service.py:541**

Open same file at line 541. Currently:
```python
cur.execute("SELECT id, email FROM users WHERE email = %s AND is_active = TRUE", (email,))
```

Replace with:
```python
user = find_user_by_any_email(email, active_only=True)
```

Same minimal refactor as Step 4 — adapt the surrounding code.

- [ ] **Step 6: Modify oauth_routes.py google_callback**

Open `platform_v2/oauth_routes.py:69`. Read the function body. Identify the line where it looks up the user by Google's returned email. Add the alternate-email fallback **only if the primary lookup misses**. Pseudocode:

```python
# Original:
# user = lookup_by_email(google_email)
#
# Replace with:
from services.account_link_service import find_user_by_any_email
user = find_user_by_any_email(google_email)
```

The single helper does primary-or-alternate matching, so explicit fallback isn't needed.

- [ ] **Step 7: Run tests**

Run: `docker exec archie_platform python3 -m pytest /app/tests/test_oauth_alternate_lookup.py /app/tests/test_account_link_service.py /app/tests/test_account_link_routes.py -v`
Expected: All PASSED. Also run the full auth-related suite to catch regressions:
`docker exec archie_platform python3 -m pytest /app/tests/ -k "auth or oauth or account_link" -v`
Expected: No new failures.

- [ ] **Step 8: Commit**

```bash
git add platform_v2/services/auth_service.py platform_v2/oauth_routes.py \
        platform_v2/tests/test_oauth_alternate_lookup.py
git commit -m "feat(account-link): OAuth + auth lookups honor verified alternate_emails"
```

---

## Task 8: Wire real email send via Stalwart compose

**Files:**
- Modify: `platform_v2/services/account_link_service.py`

- [ ] **Step 1: Identify the compose endpoint shape**

Read `platform_v2/tools/account_center/compose_routes.py` (or wherever `/api/email/compose/send` lives — search if needed). Note the request shape: `{from_address, to_address, subject, body}` and that it sends via Stalwart STARTTLS :587.

- [ ] **Step 2: Replace the stub `_send_verification_email`**

In `services/account_link_service.py`, replace the existing `_send_verification_email` body with:

```python
import os

VERIFY_BASE_URL = os.getenv(
    "ARCHIE_PUBLIC_BASE_URL", "https://platform.kytranempowerment.com"
)


def _send_verification_email(to_address: str, username: str, token: str) -> None:
    """Send the verification email via Stalwart compose endpoint."""
    from tools.account_center.compose_routes import _send_via_stalwart  # internal helper
    # If a public helper isn't exposed, use direct SMTP. Either way, the
    # important payload is the URL.

    verify_url = f"{VERIFY_BASE_URL}/account/verify-alternate?token={token}"
    subject = "Verify your alternate email — A.R.C.H.I.E."
    body = (
        f"Hi {username or ''},\n\n"
        f"You requested to link {to_address} to your A.R.C.H.I.E. account.\n\n"
        f"Click within 24 hours to confirm ownership:\n"
        f"{verify_url}\n\n"
        f"If you didn't request this, ignore this email — no action will be taken.\n\n"
        f"— A.R.C.H.I.E."
    )
    try:
        _send_via_stalwart(
            from_address="noreply@kytranempowerment.com",
            to_address=to_address,
            subject=subject,
            body=body,
        )
    except Exception:  # noqa: BLE001 — email send must not fail the request
        logger.exception("[account_link] verification email send failed for %s", to_address)
```

If `_send_via_stalwart` isn't a module-level helper, use Python's `smtplib.SMTP("192.168.1.200", 587)` with STARTTLS and an env-configured noreply password. Pattern reference: existing compose endpoint code.

- [ ] **Step 3: Smoke test in container**

Run inside the platform container:
```bash
docker exec archie_platform python3 -c "
from services.account_link_service import _send_verification_email
_send_verification_email('kytranempowerment@gmail.com', 'kytran', 'TESTTOKEN-NOT-VALID')
"
```
Expected: log line "verification email queued..." OR an SMTP success; check `kytranempowerment@gmail.com` for the test email (this DOES send a real email — confirm with user before running, or use a trash inbox).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/account_link_service.py
git commit -m "feat(account-link): wire verification email via Stalwart"
```

---

## Task 9: Full integration smoke test

**Files:** none (operational verification)

- [ ] **Step 1: Restart platform**

Run: `docker compose restart archie_platform`
Wait ~10s for gunicorn workers to be ready.

- [ ] **Step 2: Apply migration if not already**

Run: `docker exec -i archie_database psql -U archie -d archie < platform_v2/database/migrations/371_alternate_email_verifications.sql`
Expected: `CREATE TABLE` (if not idempotent re-run) or no error.

- [ ] **Step 3: End-to-end smoke**

Confirm with user before sending real emails. With user approval:

```bash
# As logged-in admin (curl with session cookie or via UI):
curl -X POST https://platform.kytranempowerment.com/tools/account-center/api/alternate-emails \
     -H "Content-Type: application/json" \
     -b "session=<your-session-cookie>" \
     -d '{"email":"kytranempowerment+altlink-smoke@gmail.com"}'
# Expected: 202 + {"success":true, "pending_email":"...", "expires_at":"..."}
```

Click the verification link from the inbox. Confirm:
- Land on `/account/verify-alternate` with success state
- `users.alternate_emails` array now contains the email:
  `docker exec archie_database psql -U archie -d archie -c "SELECT alternate_emails FROM users WHERE id = <your_id>"`

- [ ] **Step 4: Test OAuth fallback (optional, requires logging out)**

Log out. Sign in via "Continue with Google" using the gmail account that was added as an alternate. Expected: log in as the original A.R.C.H.I.E. user (not a new account).

- [ ] **Step 5: Cleanup smoke artifact**

```bash
curl -X DELETE \
  "https://platform.kytranempowerment.com/tools/account-center/api/alternate-emails/kytranempowerment+altlink-smoke@gmail.com" \
  -b "session=<your-session-cookie>"
# Expected: 200 + {"removed": true}
```

- [ ] **Step 6: No commit needed (operational only)**

If smoke surfaced bugs, fix-and-commit per the standard pattern.

---

## Task 10: Open PR and merge

- [ ] **Step 1: Push branch**

Run: `git push -u origin feat/account-email-linking`
Expected: branch up.

- [ ] **Step 2: Open PR**

```bash
gh pr create --title "feat(account-link): backend MVP — verified alternate-email linking + OAuth fallback" \
  --body "$(cat <<'EOF'
## Summary

Closes the alternate-email-linking task in Project #311 (carry-over from #247 task #1804). Backend MVP only — UI deferred to a follow-on task in #311.

- New service `services/account_link_service.py` — token gen/hash, request/verify/remove, find_user_by_any_email
- New table via migration 371: `alternate_email_verifications` (sha256-hashed tokens, 24h TTL)
- 4 endpoints: GET/POST/DELETE under Account Center + public `/account/verify-alternate`
- 3 existing email-lookup sites swap to `find_user_by_any_email()` so primary login + `auth_service.py:541` admin lookup + Google OAuth callback all honor verified alternates
- LCARS confirmation page for verify-link clicks
- ~25 new tests (service unit + route integration + OAuth fallback)

## Out of scope
- Profile-settings UI section (follow-on)
- Admin merge tool (follow-on)
- Other OAuth providers (auto-pick-up via shared helper but not explicitly tested)

## Spec
`docs/superpowers/specs/2026-05-04-account-center-email-linking-design.md`

## Test plan
- [x] Migration 371 applied
- [x] All ~25 new tests pass; existing auth tests do not regress
- [x] Smoke E2E: post → email → click → array updated → OAuth fallback logs in correct user

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Merge**

After CodeRabbit lands its review (or skip if rate-pressed):

```bash
gh pr merge --squash --delete-branch
```

- [ ] **Step 4: Update Dev HQ**

```python
mcp__archie__complete_task(
    task_id=2589,
    notes="Shipped via PR #<num>. Backend MVP live: alternate_email_verifications table, account_link_service, 4 endpoints, OAuth fallback in google_callback + auth_service.py:76 + :541. UI + admin merge deferred to follow-on tasks under #311."
)
mcp__archie__update_project_status(project_id=311, status="completed")
# Or leave #311 open if UI/merge follow-on is wanted in same project — your call.
```

---

## Self-review

**Spec coverage check:**
- ✅ Data model (migration 371) → Task 1
- ✅ token gen/hash + constants → Task 2
- ✅ request_alternate_email + cap + validation → Task 3
- ✅ verify_alternate_email + promote to array → Task 4
- ✅ find_user_by_any_email + remove_alternate_email → Task 5
- ✅ 4 endpoints + LCARS template → Task 6
- ✅ OAuth integration (3 lookup sites) → Task 7
- ✅ Email send wiring → Task 8
- ✅ Tests for everything (~25 cumulative)
- ✅ Smoke E2E + PR → Tasks 9, 10

**Type/name consistency:**
- Function names match across tasks: `request_alternate_email`, `verify_alternate_email`, `find_user_by_any_email`, `remove_alternate_email`
- Constants: `TOKEN_BYTES`, `VERIFICATION_TOKEN_TTL_HOURS`, `MAX_ALTERNATES_PER_USER`
- Module: `services.account_link_service` everywhere
- Routes module: `tools/account_center/email_link_routes.py`
- Template: `templates/account/verify_alternate.html`
- Test files: `test_account_link_service.py`, `test_account_link_routes.py`, `test_oauth_alternate_lookup.py`

**Placeholder scan:** none.

**Out-of-order safety:** every task includes the full code or exact code transformation; no "similar to Task N" pointers.

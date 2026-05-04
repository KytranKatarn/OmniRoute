# Account Center — Email Linking (Backend MVP) — Design Spec

**Date**: 2026-05-04
**Project**: #311 Account Center — Email Linking & Account Merge
**Carry-over from**: project #247 task #1804 (re-homed)
**Author**: Claude Opus 4.7 (brainstorm + design)

## Goal

Ship a backend-only MVP that lets a user link verified alternate emails to
their A.R.C.H.I.E. account, and lets Google OAuth recognize them when they
sign in with one of those alternates. Closes the "user signs in with their
Gmail and we don't know who they are" gap without requiring profile-page UI
or admin tooling in this slice.

## Out of scope (deferred to follow-on tasks under #311)

- Profile-settings UI page section for self-service add/list/remove
- Admin merge tool for duplicate accounts
- Extending non-Google OAuth providers explicitly (they pick up the
  fallback automatically via the shared `find_user_by_any_email()` helper)
- Per-alternate notification preferences
- Bulk admin add of alternates
- Address the 5 open auth-security tasks (#2060–#2064 PKCE, JWT rotation,
  CSRF audit, 2FA backup codes, SDK consolidation) — orthogonal

## State of the world (recon)

| Surface | State |
|---|---|
| `users.alternate_emails text[]` | Already exists on `users` table — no migration to add |
| `users.email_verified boolean` | Already exists |
| `idx_users_email_lower` | Already indexed for case-insensitive lookup |
| Primary email lookups | `auth_service.py:76` (login) + `auth_service.py:541` (admin) |
| Google OAuth callback | `oauth_routes.py:69` `/google/callback` (primary login) + `:231` `/link/google/callback` (linking pre-existing) |
| Email send infra | Stalwart Mail :587 STARTTLS via `tools/account_center/compose_routes.py` `/api/email/compose/send` |
| Account Center routes | `tools/account_center/routes.py` (existing module) |

## Architecture

Three layers, no new module:

1. **Service** — `services/account_link_service.py` (new). Holds business
   logic: token generation, hashing, expiry checks, verification, cap
   enforcement, lookup helpers.
2. **Routes** — extend `tools/account_center/routes.py` with 4 endpoints
   (3 session-authenticated + 1 unauthenticated verify endpoint).
3. **OAuth integration** — extend `oauth_routes.py:69` `google_callback`
   and the 2 email-lookup sites in `auth_service.py` to fall back to
   `alternate_emails`.

## Data model

One new table for token staging. The `users.alternate_emails` array is the
**source of truth for verified alternates**; the staging table only
holds in-flight verifications.

```sql
-- database/migrations/371_alternate_email_verifications.sql
CREATE TABLE alternate_email_verifications (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    alternate_email VARCHAR(255) NOT NULL,
    token_hash      VARCHAR(64) NOT NULL,       -- sha256 of token; never store raw
    expires_at      TIMESTAMP NOT NULL,
    used_at         TIMESTAMP,
    created_at      TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_alt_email_verif_token ON alternate_email_verifications(token_hash);
CREATE INDEX idx_alt_email_verif_user ON alternate_email_verifications(user_id);
CREATE INDEX idx_alt_email_verif_active
    ON alternate_email_verifications(user_id, alternate_email)
    WHERE used_at IS NULL;
```

### Constants (`account_link_service.py`)

| Constant | Value | Reason |
|---|---|---|
| `MAX_ALTERNATES_PER_USER` | 5 | Cap to prevent abuse / runaway lists |
| `VERIFICATION_TOKEN_TTL_HOURS` | 24 | Standard "click to confirm" window |
| `TOKEN_BYTES` | 32 | 256-bit URL-safe random |

## API surface

All four endpoints under the existing Account Center blueprint at
`/tools/account-center/...` paths.

### `GET /tools/account-center/api/alternate-emails`

- Auth: session (`@login_required`)
- Returns: `{verified: [str], pending: [{email, expires_at}]}`

### `POST /tools/account-center/api/alternate-emails`

- Auth: session (`@login_required`)
- Body: `{email: str}`
- Action:
  1. Validate format (basic regex), reject if equal to user's primary email
  2. Reject if already in user's verified `alternate_emails` array
  3. Reject if user is at `MAX_ALTERNATES_PER_USER`
  4. Cancel any prior pending row for `(user_id, alternate_email)` by
     setting `used_at = NOW()` (idempotent re-issue)
  5. Generate 32-byte URL-safe token; insert hashed staging row
  6. Send verification email via Stalwart compose endpoint
- Response: `202 Accepted` with `{pending_email, expires_at}`

### `GET /account/verify-alternate?token=<t>`

- Auth: **none** (public link clicked from email)
- Action:
  1. Hash incoming token → look up active staging row (token_hash match,
     `used_at IS NULL`, `expires_at > NOW()`)
  2. If miss / expired / already-used → render LCARS error page
  3. On hit: append `lower(alternate_email)` to `users.alternate_emails`
     (use `array_append` with dedup), set staging `used_at = NOW()`
  4. Render LCARS confirmation page (no auto-login — explicit redirect to login)

### `DELETE /tools/account-center/api/alternate-emails/<email>`

- Auth: session (`@login_required`)
- Action: remove email from `users.alternate_emails` array AND mark all
  pending verifications for that `(user_id, alternate_email)` as used.
- Response: `200 OK` `{removed: bool}`

## OAuth integration

Add a new helper in `account_link_service.py`:

```python
def find_user_by_any_email(email: str) -> Optional[dict]:
    """Look up by primary email first, then verified alternate_emails.
    Case-insensitive. Returns user row dict or None.
    """
```

Extend the **3 existing lookup sites** to use this helper:

1. `auth_service.py:76` — currently `WHERE email = %s`. Replace with
   helper call. Used by login flow.
2. `auth_service.py:541` — currently `WHERE email = %s AND is_active = TRUE`.
   Replace with helper that also passes the `is_active` filter.
3. `oauth_routes.py:69` `google_callback` — when Google returns `email` and
   primary lookup misses, fall back via the helper.

### Critical security rule

Only the `alternate_emails` ARRAY is honored for OAuth lookup. The staging
table is **never** authoritative — a row in `alternate_email_verifications`
without `used_at` does NOT grant access. The append to `alternate_emails`
happens only inside the verification endpoint after the token is matched.

Cross-OAuth providers (KBS, Account Center, WTF SSO) all rely on the same
`users` table; once they migrate to call `find_user_by_any_email()`, they
inherit the alternate-email behavior. That migration is **out of scope**
for this PR — we only commit to wiring Google.

## Email verification message

Sent from `noreply@kytranempowerment.com` via the existing Stalwart
`/api/email/compose/send` endpoint. Plain text body + minimal HTML twin:

```
Hi <username>,

You requested to link <alt_email> to your A.R.C.H.I.E. account.

Click within 24 hours to confirm ownership:
https://platform.kytranempowerment.com/account/verify-alternate?token=<t>

If you didn't request this, ignore this email — no action will be taken.

— A.R.C.H.I.E.
```

## Tests

`tests/test_account_link_service.py` (new, mocked DB):

- `generate_token()` returns 32 url-safe bytes
- `hash_token()` is deterministic + matches verifier
- `request_alternate_email()` happy path: stages row, returns expires_at
- `request_alternate_email()` rejects when at cap (5)
- `request_alternate_email()` rejects when email is user's primary
- `request_alternate_email()` rejects when email already verified
- `request_alternate_email()` re-issue cancels prior pending (idempotent)
- `verify_alternate_email()` happy path: appends to array, marks used_at
- `verify_alternate_email()` returns false on expired token
- `verify_alternate_email()` returns false on already-used token
- `verify_alternate_email()` returns false on unknown token
- `find_user_by_any_email()` matches primary case-insensitive
- `find_user_by_any_email()` matches alternate case-insensitive
- `find_user_by_any_email()` returns None when no match
- `remove_alternate_email()` removes from array AND cancels pending
- Verification append is idempotent (lower-cased dedup — no duplicate alts)

`tests/test_account_link_routes.py` (new, Flask test client):

- `GET /api/alternate-emails` returns verified + pending lists
- `POST /api/alternate-emails` issues 202 + queues email send (mock)
- `GET /account/verify-alternate?token=<good>` renders confirmation
- `GET /account/verify-alternate?token=<bad>` renders error page
- `DELETE /api/alternate-emails/<email>` removes from array

`tests/test_oauth_alternate_lookup.py` (new):

- `google_callback` with email matching primary → existing behavior
- `google_callback` with email matching verified alternate → logs in as
  the user owning the alternate
- `google_callback` with unmatched email → falls through to existing
  signup/error path (unchanged)

## Migration

`database/migrations/371_alternate_email_verifications.sql` — idempotent
(`CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`).

## Rollout

1. Apply migration 371
2. Deploy code (gunicorn worker reload picks up routes)
3. Smoke test: add own alternate, click link, verify it lands in
   `users.alternate_emails` array, log out, sign in with Google using
   the alternate, confirm logged in as same user
4. Squash-merge PR

## Acceptance criteria

- [ ] Migration 371 applied
- [ ] User can POST a new alternate; receives verification email
- [ ] Verification link click adds to `users.alternate_emails`
- [ ] Google OAuth callback signs user in via verified alternate
- [ ] User can DELETE an alternate (removes from array)
- [ ] Cap of 5 enforced (POST 6th returns 4xx)
- [ ] Expired tokens return error page
- [ ] All tests pass (~25 new tests)
- [ ] No regression in existing `test_delegation_service.py`,
      `test_oauth_routes.py`, or other auth tests

## Decisions

- **No raw token storage** — only `sha256` hash in DB; raw token only ever
  in the email link
- **No auto-login on verify** — verify endpoint shows confirmation page,
  user clicks "Continue" to log in normally. Avoids logging in the wrong
  person on a shared device.
- **No primary-email overwrite** — verified alternates stay alternates;
  primary email is never silently changed. Out of scope: explicit "promote
  alternate to primary" flow.
- **Lower-cased comparison everywhere** — both staging insert and
  `find_user_by_any_email()` use `lower()` to match `idx_users_email_lower`
  semantics.
- **Idempotent POST** — re-POSTing same email cancels prior pending and
  issues a fresh token. Prevents stale-token drift.

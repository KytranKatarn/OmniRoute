# Phase 1 — Auth Resilience (survive a hub blip) — SCOPING RESULT
*2026-06-01. Read-only investigation of the Watch products' Kytran SSO. No changes made.*

## Good news: steady-state auth is ALREADY local
- Session = **signed Flask cookie** (`app.secret_key`, `SESSION_COOKIE_HTTPONLY`, `PERMANENT_SESSION_LIFETIME=7d`, `session.permanent=True`). No server-side store, no per-request DB/Redis. The user (`session["kytran_user"]`) rides in the cookie.
- Per-request decorator `login_required` (kytran_auth.py:279) just checks `"kytran_user" in session` → **local**, no hub call for already-logged-in users.
- **Entitlements + tier are fetched at LOGIN only** (`/oauth/userinfo`) and cached in the session → tier gating survives a hub outage. No change needed.
- New logins need the hub IdP (`/oauth/token` + `/oauth/userinfo`) — acceptable degradation (can't issue new sessions while hub is down).

## The ONE hub dependency in the request path (the bug to fix)
`login_required` → `_refresh_if_needed()` (kytran_auth.py:295):
```python
if not refresh_token or time.time() < exp - 300:
    return True                      # token still valid >5min → NO hub call (most requests)
try:
    resp = requests.post(f"{internal_url}/oauth/token", {grant_type: refresh_token,...}, timeout=10)
except Exception:
    return False                     # ← hub unreachable → returns False
if resp.status_code != 200:
    return False                     # ← any non-200 → returns False
```
And the caller:
```python
if not self._refresh_if_needed():
    session.clear()                  # ← LOGS THE USER OUT
    return redirect(url_for("kytran_login", ...))
```

**Failure mode:** access token lives 8h. When the hub is down AND a logged-in user's token is within 5 min of its 8h expiry, the refresh POST throws → `_refresh_if_needed()` returns False → **session cleared, user logged out** — even though they hold a valid 30-day refresh token and were just working. Users with fresh tokens keep working for up to 8h; the unlucky ones in their refresh window get bounced.

## The fix (this IS "auth caching"/resilience)
Make `_refresh_if_needed()` distinguish **hub-unreachable** from **token-rejected**:
- `except (ConnectionError, Timeout)` (or any network error) → **hub down → keep the session** (return True), don't clear. Extend `access_token_exp` by a bounded **grace window** (e.g. +6h) so it doesn't re-hammer the hub every request, and so the ride is time-limited.
- `resp.status_code in (401, 400 invalid_grant)` → refresh token genuinely rejected → **return False (real logout).**
- `resp.status_code` 5xx / 502 (hub up but erroring) → transient → keep session (return True), retry next window.
- Add a hard ceiling: if the hub has been unreachable past the grace window (track `grace_until`), then force re-auth. The 30-day refresh token gives ample runway; a 6–24h grace is reasonable.

Net: a hub outage no longer logs anyone out; sessions ride locally until the hub returns (bounded), and a *revoked/expired* token still logs out promptly when the hub is reachable.

## Blast radius — files & deploy
**Each Watch product carries its OWN divergent copy** of `kytran_auth.py` (different md5s — they are NOT a single shared import):
| Product | File | Hub source path |
|---|---|---|
| gov_watch | `kytran_auth.py` | `/mnt/standalone/kytran-gov-watch/` |
| legal | `kytran-auth-pkg/kytran_auth.py` | `/mnt/standalone/kytran-legal-watch/` |
| market | `kytran_auth.py` | `/mnt/standalone/kytran-market-watch/` |
| civic | `kytran_auth.py` | `/mnt/standalone/kytran-civic-watch/` |
- WTF + civic-transparency: no `kytran_auth.py` (WTF uses its own OAuth — separate scope if needed).
- **The fix must be applied to all 4 copies** (ideally re-converged on the `kytran-auth-pkg` template — optional cleanup, see Follow-ups).
- **Deploy:** per VPS pattern — `rsync --exclude=.env` each product to outpost-boston (`kytran@76.13.107.109:/opt/archie-products/<product>/`) + `docker compose up -d --build`. 4 separate product deploys.

## Risk & security note
- **Risk:** it's production auth across 4 live products — a bug could lock users out OR keep sessions alive too long.
- **Security tradeoff:** during a hub outage, a user whose access was revoked at the hub could retain access for up to the grace window. Acceptable as outage-resilience (bounded, only on connectivity errors, token still expires) — but document it. Tighten the grace window if the threat model demands.
- **Mitigation:** grace ONLY on connectivity/5xx errors, NEVER on 401/invalid_grant; bounded `grace_until`; unit-test both paths.

## Test plan (must pass before claiming done)
1. Unit: token fresh → no hub call (return True). Token expiring + hub 401 → return False (logout). Token expiring + hub unreachable → return True (keep) within grace; past grace → False.
2. Live (staging or one product first): log in, then block the VPS→hub path (firewall 100.64.0.4 or point `internal_url` at a dead port), exercise a near-expiry session → confirm the user **stays logged in** instead of being bounced; restore hub → confirm normal refresh resumes.
3. Confirm a real logout still happens when the refresh token is actually invalid.

## Recommended rollout
1. Implement on **gov_watch first (canary)**, branch + test (unit + live block-the-hub) → deploy gov only → verify.
2. Then propagate the identical change to legal/market/civic, deploy each, verify.
3. (Follow-up, optional) re-converge the 4 divergent `kytran_auth.py` copies onto one `kytran-auth-pkg` so future auth fixes are one-place.

## Follow-ups / out of scope
- WTF's own OAuth resilience (separate auth code) — scope later if WTF needs the same.
- Converging the 4 auth copies into one shared package.

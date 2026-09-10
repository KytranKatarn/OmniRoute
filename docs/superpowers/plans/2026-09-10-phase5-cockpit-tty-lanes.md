# Phase 5 — TTY lanes in the cockpit: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth **Terminal** pane to the cockpit that embeds the two existing coder lanes (claude, codex) and lets the owner work in them without leaving the page.

**Architecture:** The cockpit mints a short-lived, **lane-bound** one-time token; the pane iframes the *existing* `ttyd_auth_proxy.py`, which remains the only gate for shell bytes. The proxy gains a signed 15-minute sliding cookie so the document, its assets, and its websocket all authenticate (today only the first request does). No terminal bytes ever pass through comms.

**Tech Stack:** Python 3.11 (asyncio raw-socket proxy, Flask/Jinja on comms), PostgreSQL, vanilla JS + CSS grid, systemd, ttyd.

**Spec:** `docs/superpowers/specs/2026-09-10-phase5-cockpit-tty-lanes-design.md` — read it, **including §11**, which corrects four things the body still states loosely.

---

## Global Constraints

Copy these values verbatim; every task's requirements implicitly include this section.

- **Two lanes only.** `claude` → proxy `:7681` → ttyd `127.0.0.1:17681` (host tmux `claude-code`, no container boundary). `codex` → proxy `:7683` → `127.0.0.1:17682` (containerised, `--max-clients 1`). **The engine is not a lane** (`:9090` is a bearer-auth websocket API with no shell) — do not add it.
- **Cookie attributes are exactly:** `HttpOnly; Path=/; Secure; SameSite=None`, signed with a host-side secret. **Never `SameSite=Strict` or `Lax`** — see spec §11.3; the iframe is cross-site and a Strict cookie is never sent.
- **`SameSite=None` ships only together with** `Content-Security-Policy: frame-ancestors` restricting embedders. Never one without the other.
- **Cookie lifetime: 15 minutes, sliding** — renewed on each accepted request.
- **Fail closed everywhere.** Unset signing secret ⇒ accept no cookies. NULL or mismatched `lane` ⇒ refuse. Unset `PROXY_LANE` ⇒ refuse.
- **Basic Auth fallback stays.** It is how the terminal is reached outside the cockpit and over plain-HTTP LAN, where a `Secure` cookie cannot travel.
- **Token minting stays one-time.** The cookie, not the token, carries the session.
- **Secrets are never committed and never printed.** New secrets go in `/mnt/archie_brain/.env` + a dedicated systemd `EnvironmentFile`, mode 0600, root-owned.
- **`docker compose up -d --no-deps <svc>`, never `restart`** — `restart` does not re-read `env_file`.
- **comms is image-baked** (`COPY . .`) ⇒ `docker compose up -d --build --no-deps archie_comms`, **from `main` only**.
- **Never `docker compose up` while a feature branch touching `platform_v2` is checked out** (bind mount).
- Branch + PR, never `main`. Merge only on a clean F.O.R.G.E. APPROVE. A coverage-only demotion is discharged by **reading** the dropped files, never by `coverage_ack`.
- Absolute paths in `git add`; never `--no-verify`.

---

## File Structure

| File | Responsibility |
|---|---|
| `database/migrations/NNN_terminal_token_lane.sql` | adds `lane` to `terminal_auth_tokens` (+ index) |
| `scripts/ttyd_auth_proxy.py` | **modified** — lane-bound token validation, signed sliding cookie, `frame-ancestors` header |
| `scripts/ttyd-auth-proxy.service`, `scripts/ttyd-codex-auth-proxy.service` | **modified** — `PROXY_LANE`, `TTYD_COOKIE_SECRET`, `TTYD_FRAME_ANCESTORS` |
| `archie-comms/services/terminal_lanes.py` | **new** — the single mint helper + lane registry + reachability probe |
| `archie-comms/app_comms.py` | **modified** — legacy `/api/terminal/token` delegates to the helper |
| `archie-comms/cockpit_routes.py` | **modified** — 19 rules → 21 (mint, lane status) |
| `archie-comms/templates/cockpit.html` | **modified** — fifth pane + tab + lane switcher |
| `archie-comms/static/js/cockpit.js` | **modified** — lane mount, reconnect, states |
| `archie-comms/static/css/cockpit.css` | **modified** — `#pane-terminal` grid-cell invariant |
| `platform_v2/tests/test_ttyd_proxy_lane_and_cookie.py` | **new** — proxy unit tests |
| `archie-comms/tests/test_cockpit_terminal.py` | **new** — mint gate, lane list, CSS invariant |

Tasks 1–3 are the security floor and land as one PR **before** any UI work; a pane pointed at an ungated proxy is the failure mode Phase 5 exists to avoid.

---

### Task 1: Bind a token to its lane

A token minted for the sandboxed codex lane is currently accepted by the claude host-shell proxy. Fix this **first** — it is live today (spec §11.4).

**Files:**
- Create: `database/migrations/NNN_terminal_token_lane.sql` (use the next free number)
- Modify: `scripts/ttyd_auth_proxy.py` (`validate_token`, config block, `handle_connection`)
- Modify: `scripts/ttyd-auth-proxy.service`, `scripts/ttyd-codex-auth-proxy.service`
- Test: `platform_v2/tests/test_ttyd_proxy_lane_and_cookie.py`

**Interfaces:**
- Consumes: `terminal_auth_tokens(id, user_id, token, created_at, expires_at, used)`
- Produces: `validate_token(token: str, lane: str) -> bool`; env `PROXY_LANE`; column `terminal_auth_tokens.lane TEXT`

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_ttyd_proxy_lane_and_cookie.py
import importlib.util, sys
import pytest
from tests.repo_root import repo_path

PROXY = repo_path("scripts", "ttyd_auth_proxy.py")
pytestmark = pytest.mark.skipif(not PROXY.exists(), reason=f"not reachable at {PROXY}")

def _load():
    spec = importlib.util.spec_from_file_location("_ttyd_proxy_under_test", PROXY)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m

@pytest.fixture(scope="module")
def proxy():
    m = _load()
    yield m
    sys.modules.pop("_ttyd_proxy_under_test", None)

def test_validate_token_requires_a_matching_lane(proxy, monkeypatch):
    """A codex token must never open the claude host shell."""
    rows = {"tok-codex": (1, 7, "codex")}
    def _fake_lookup(token):
        return rows.get(token)
    monkeypatch.setattr(proxy, "_lookup_token_row", _fake_lookup)
    monkeypatch.setattr(proxy, "_consume_token", lambda token_id: None)

    assert proxy.validate_token("tok-codex", "codex") is True
    assert proxy.validate_token("tok-codex", "claude") is False

def test_a_null_lane_fails_closed(proxy, monkeypatch):
    monkeypatch.setattr(proxy, "_lookup_token_row", lambda t: (1, 7, None))
    monkeypatch.setattr(proxy, "_consume_token", lambda token_id: None)
    assert proxy.validate_token("legacy", "claude") is False

def test_an_unset_proxy_lane_fails_closed(proxy, monkeypatch):
    monkeypatch.delenv("PROXY_LANE", raising=False)
    assert proxy.configured_lane() == ""
    monkeypatch.setattr(proxy, "_lookup_token_row", lambda t: (1, 7, "claude"))
    monkeypatch.setattr(proxy, "_consume_token", lambda token_id: None)
    assert proxy.validate_token("tok", proxy.configured_lane()) is False
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `docker exec -i archie_platform python3 -m pytest /app/tests/test_ttyd_proxy_lane_and_cookie.py -q -p no:cacheprovider`
Expected: FAIL — `AttributeError: module has no attribute '_lookup_token_row'`.

- [ ] **Step 3: Write the migration**

```sql
-- database/migrations/NNN_terminal_token_lane.sql
ALTER TABLE terminal_auth_tokens ADD COLUMN IF NOT EXISTS lane TEXT;
CREATE INDEX IF NOT EXISTS idx_term_tokens_lane ON terminal_auth_tokens (lane);
COMMENT ON COLUMN terminal_auth_tokens.lane IS
  'Lane this token may open (claude|codex). NULL fails closed: both proxies share one table and one script, so an unbound token would open either lane.';
```

Apply: `docker exec -i archie_database psql -U archie -d archie < database/migrations/NNN_terminal_token_lane.sql`

- [ ] **Step 4: Split the DB access out, then gate on lane**

In `scripts/ttyd_auth_proxy.py`, add near the config block:

```python
PROXY_LANE = os.environ.get("PROXY_LANE", "").strip()

def configured_lane() -> str:
    """The lane this proxy instance serves. Empty means unconfigured — refuse everything."""
    return os.environ.get("PROXY_LANE", "").strip()
```

Split the existing body of `validate_token` into two seams the tests can replace:

```python
def _lookup_token_row(token: str):
    """(id, user_id, lane) for a live, unused token, else None."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, lane FROM terminal_auth_tokens "
                "WHERE token = %s AND used = FALSE AND expires_at > NOW()",
                (token,),
            )
            return cur.fetchone()
    finally:
        conn.close()

def _consume_token(token_id: int) -> None:
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE terminal_auth_tokens SET used = TRUE WHERE id = %s", (token_id,))
        conn.commit()
    finally:
        conn.close()

def validate_token(token: str, lane: str) -> bool:
    """Consume a one-time token, but ONLY for the lane it was minted for.

    Both proxies run this same script against the same table, so without the lane check a
    token minted for the sandboxed codex lane opens the claude HOST shell. Fails closed on
    an unconfigured lane and on legacy NULL-lane rows.
    """
    if not lane:
        logger.error("Refusing token auth: PROXY_LANE is not configured (fail-closed).")
        return False
    try:
        row = _lookup_token_row(token)
        if row is None:
            return False
        token_id, user_id, token_lane = row
        if token_lane != lane:
            logger.warning(
                "Refusing token auth: token minted for lane=%r presented to lane=%r",
                token_lane, lane,
            )
            return False
        _consume_token(token_id)
        logger.info("Token auth OK token_id=%s user_id=%s lane=%s", token_id, user_id, lane)
        return True
    except Exception:
        logger.exception("Token validation DB error")
        return False
```

In `handle_connection`, change the call site to `if validate_token(token, configured_lane()):`.

- [ ] **Step 5: Add `PROXY_LANE` to both units**

`scripts/ttyd-auth-proxy.service` → `Environment=PROXY_LANE=claude`
`scripts/ttyd-codex-auth-proxy.service` → `Environment=PROXY_LANE=codex`

- [ ] **Step 6: Run the tests — expect PASS**

Run the same pytest command. Expected: 3 passed.

- [ ] **Step 7: Prove the guard by hand (authoring-time only, never bake into a test)**

Temporarily return `True` from the lane comparison, re-run, confirm `test_validate_token_requires_a_matching_lane` fails, then revert.

- [ ] **Step 8: Commit**

```bash
git add /mnt/archie_brain/database/migrations/NNN_terminal_token_lane.sql \
        /mnt/archie_brain/scripts/ttyd_auth_proxy.py \
        /mnt/archie_brain/scripts/ttyd-auth-proxy.service \
        /mnt/archie_brain/scripts/ttyd-codex-auth-proxy.service \
        /mnt/archie_brain/platform_v2/tests/test_ttyd_proxy_lane_and_cookie.py
git commit -m "fix(security): a terminal token was not bound to its lane, so a sandbox token opened the host shell"
```

---

### Task 2: A signed 15-minute sliding cookie

The one-time token authenticates exactly one request (measured, spec §3.1). A ttyd page is a document, then assets, then a websocket — so without this the pane sits empty or prompts for a password inside the cockpit.

**Files:**
- Modify: `scripts/ttyd_auth_proxy.py`
- Modify: both `.service` files (`TTYD_COOKIE_SECRET`)
- Test: `platform_v2/tests/test_ttyd_proxy_lane_and_cookie.py` (append)

**Interfaces:**
- Consumes: `configured_lane()` from Task 1
- Produces: `mint_cookie(user_id, lane) -> str`, `verify_cookie(value, lane) -> int | None`, `parse_cookie_header(raw) -> str | None`, `COOKIE_NAME = "archie_tty"`, `COOKIE_TTL_SECONDS = 900`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_valid_cookie_round_trips(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_COOKIE_SECRET", "test-secret")
    v = proxy.mint_cookie(7, "claude")
    assert proxy.verify_cookie(v, "claude") == 7

def test_a_cookie_is_rejected_for_a_different_lane(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_COOKIE_SECRET", "test-secret")
    v = proxy.mint_cookie(7, "codex")
    assert proxy.verify_cookie(v, "claude") is None

def test_a_tampered_cookie_is_rejected(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_COOKIE_SECRET", "test-secret")
    v = proxy.mint_cookie(7, "claude")
    body, sig = v.rsplit(".", 1)
    assert proxy.verify_cookie(body + ".dead" + sig[4:], "claude") is None

def test_a_cookie_signed_with_another_secret_is_rejected(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_COOKIE_SECRET", "secret-a")
    v = proxy.mint_cookie(7, "claude")
    monkeypatch.setenv("TTYD_COOKIE_SECRET", "secret-b")
    assert proxy.verify_cookie(v, "claude") is None

def test_an_expired_cookie_is_rejected(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_COOKIE_SECRET", "test-secret")
    monkeypatch.setattr(proxy.time, "time", lambda: 1_000_000.0)
    v = proxy.mint_cookie(7, "claude")
    monkeypatch.setattr(proxy.time, "time", lambda: 1_000_000.0 + proxy.COOKIE_TTL_SECONDS + 1)
    assert proxy.verify_cookie(v, "claude") is None

def test_an_unset_secret_accepts_no_cookie(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_COOKIE_SECRET", "test-secret")
    v = proxy.mint_cookie(7, "claude")
    monkeypatch.delenv("TTYD_COOKIE_SECRET", raising=False)
    assert proxy.verify_cookie(v, "claude") is None

def test_set_cookie_attributes_are_exactly_the_spec(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_COOKIE_SECRET", "test-secret")
    header = proxy.build_set_cookie(7, "claude")
    assert "HttpOnly" in header and "Secure" in header
    assert "SameSite=None" in header          # Strict/Lax is never sent in the iframe
    assert "SameSite=Strict" not in header
    assert f"Max-Age={proxy.COOKIE_TTL_SECONDS}" in header

def test_the_cookie_is_parsed_out_of_a_raw_request(proxy):
    raw = b"GET / HTTP/1.1\r\nHost: x\r\nCookie: a=1; archie_tty=abc.def; b=2\r\n\r\n"
    assert proxy.parse_cookie_header(raw) == "abc.def"
```

- [ ] **Step 2: Run to confirm they fail**

Expected: FAIL — `module has no attribute 'mint_cookie'`.

- [ ] **Step 3: Implement the cookie**

Add `import base64, hmac, hashlib, time` and:

```python
COOKIE_NAME = "archie_tty"
COOKIE_TTL_SECONDS = 900  # 15 minutes, sliding — renewed on every accepted request

def _cookie_secret() -> bytes:
    return os.environ.get("TTYD_COOKIE_SECRET", "").strip().encode()

def _sign(payload: bytes) -> str:
    return hmac.new(_cookie_secret(), payload, hashlib.sha256).hexdigest()

def mint_cookie(user_id: int, lane: str) -> str:
    """`<b64(user_id:lane:expiry)>.<hmac>`; empty when unconfigured."""
    if not _cookie_secret():
        logger.error("TTYD_COOKIE_SECRET is not set — cannot mint (fail-closed).")
        return ""
    raw = f"{user_id}:{lane}:{int(time.time()) + COOKIE_TTL_SECONDS}".encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{body}.{_sign(body.encode())}"

def verify_cookie(value: str, lane: str):
    """user_id when the cookie is valid FOR THIS LANE and unexpired, else None."""
    if not value or not _cookie_secret() or not lane:
        return None
    try:
        body, sig = value.rsplit(".", 1)
    except ValueError:
        return None
    # compare_digest on bytes so a non-ASCII cookie can never raise instead of returning None
    if not hmac.compare_digest(_sign(body.encode()).encode(), sig.encode()):
        return None
    try:
        pad = "=" * (-len(body) % 4)
        user_id, cookie_lane, expiry = base64.urlsafe_b64decode(body + pad).decode().split(":")
        if cookie_lane != lane or int(expiry) < int(time.time()):
            return None
        return int(user_id)
    except Exception:
        return None

def build_set_cookie(user_id: int, lane: str) -> str:
    """Secure + SameSite=None: the cockpit iframe is CROSS-SITE, so Strict/Lax is never sent.
    Paired with frame-ancestors (Task 3) — None alone lets any site embed us."""
    v = mint_cookie(user_id, lane)
    if not v:
        return ""
    return (f"{COOKIE_NAME}={v}; Max-Age={COOKIE_TTL_SECONDS}; Path=/; "
            "HttpOnly; Secure; SameSite=None")

def parse_cookie_header(raw_request: bytes):
    for line in raw_request.split(b"\r\n"):
        if line.lower().startswith(b"cookie:"):
            for part in line.split(b":", 1)[1].split(b";"):
                k, _, v = part.strip().partition(b"=")
                if k == COOKIE_NAME.encode():
                    return v.decode("utf-8", errors="replace")
    return None
```

- [ ] **Step 4: Inject `Set-Cookie` into the upstream response**

`proxy_http` currently streams bytes through untouched, so add an opt-in header injection:

```python
async def proxy_http(reader, writer, raw_request: bytes, set_cookie: str = ""):
    """Forward to ttyd; optionally inject one Set-Cookie into the response head."""
    try:
        upstream_r, upstream_w = await asyncio.open_connection(TTYD_HOST, TTYD_PORT)
        upstream_w.write(raw_request)
        await upstream_w.drain()

        if set_cookie:
            head = await upstream_r.readuntil(b"\r\n\r\n")
            head = head[:-2] + f"Set-Cookie: {set_cookie}\r\n".encode() + b"\r\n"
            writer.write(head)
            await writer.drain()

        while True:
            chunk = await upstream_r.read(65536)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()
        upstream_w.close()
    except Exception:
        logger.exception("HTTP proxy error")
    finally:
        writer.close()
```

⚠️ The websocket upgrade is a `101` and cannot reliably carry `Set-Cookie` — it does not need to. The document is fetched first, so the cookie is already set by the time the socket opens.

- [ ] **Step 5: Wire it into `handle_connection`**

Order: token (mints the cookie) → cookie → Basic Auth. On a valid token, remember the `user_id`; on a valid cookie, re-issue a fresh one (this is what makes it sliding).

```python
    lane = configured_lane()

    token, stripped_request = parse_token_from_request(raw_request)
    if token:
        if validate_token(token, lane):
            user_id = _last_token_user_id  # returned by validate_token; see Step 6
            sc = build_set_cookie(user_id, lane)
            if is_websocket_upgrade(stripped_request):
                await proxy_websocket(reader, writer, stripped_request)
            else:
                await proxy_http(reader, writer, stripped_request, set_cookie=sc)
            return
        raw_request = stripped_request

    cookie_uid = verify_cookie(parse_cookie_header(raw_request) or "", lane)
    if cookie_uid is not None:
        if is_websocket_upgrade(raw_request):
            await proxy_websocket(reader, writer, raw_request)
        else:
            await proxy_http(reader, writer, raw_request,
                             set_cookie=build_set_cookie(cookie_uid, lane))
        return
    # ...existing Basic Auth fallback unchanged...
```

- [ ] **Step 6: Return the user id from `validate_token`**

Change it to return `int | None` (the `user_id`) instead of `bool`, update the Task 1 tests to assert on the id (`== 7` / `is None`), and update both call sites. A bool cannot tell the caller whose cookie to mint.

- [ ] **Step 7: Add the secret**

```bash
printf '\nTTYD_COOKIE_SECRET=%s\n' "$(openssl rand -hex 32)" >> /mnt/archie_brain/.env
```
Add `Environment=TTYD_COOKIE_SECRET=` via a dedicated `EnvironmentFile=-/etc/ttyd-proxy.env` (0600, root-owned) on **both** units — the same shape as `/etc/claude-proxy.env` in #3284, and for the same reason: do not load the whole platform `.env` into a process fronting a shell. **Never print the value.**

- [ ] **Step 8: Run tests, then commit**

```bash
git add /mnt/archie_brain/scripts/ttyd_auth_proxy.py \
        /mnt/archie_brain/scripts/ttyd-auth-proxy.service \
        /mnt/archie_brain/scripts/ttyd-codex-auth-proxy.service \
        /mnt/archie_brain/platform_v2/tests/test_ttyd_proxy_lane_and_cookie.py
git commit -m "feat(terminal): a signed 15-minute sliding cookie so the whole ttyd page authenticates, not just its first request"
```

---

### Task 3: `frame-ancestors` — who may embed the terminal

`SameSite=None` means any site can embed the terminal and the browser will attach the cookie. This is the other half; it does not ship separately.

**Files:** Modify `scripts/ttyd_auth_proxy.py`, both `.service` files. Test: append to the same file.

**Interfaces:** Produces `frame_ancestors() -> str`, env `TTYD_FRAME_ANCESTORS`.

- [ ] **Step 1: Write the failing tests**

```python
def test_frame_ancestors_defaults_to_none_when_unset(proxy, monkeypatch):
    """Unset must mean 'nobody may embed', not 'anybody'."""
    monkeypatch.delenv("TTYD_FRAME_ANCESTORS", raising=False)
    assert proxy.frame_ancestors() == "'none'"

def test_frame_ancestors_passes_through_the_allowlist(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_FRAME_ANCESTORS", "https://archie.kytranempowerment.com http://192.168.1.200:3002")
    assert "archie.kytranempowerment.com" in proxy.frame_ancestors()

def test_the_csp_header_is_injected_into_the_response(proxy, monkeypatch):
    monkeypatch.setenv("TTYD_FRAME_ANCESTORS", "https://archie.kytranempowerment.com")
    head = proxy.inject_response_headers(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n", set_cookie="")
    assert b"Content-Security-Policy: frame-ancestors https://archie.kytranempowerment.com" in head
```

- [ ] **Step 2: Run to confirm they fail.**

- [ ] **Step 3: Implement**

```python
def frame_ancestors() -> str:
    """Who may embed this terminal. Fails CLOSED: unset means nobody.

    Required because the session cookie is SameSite=None — without this, any page on the
    internet could iframe the terminal and the browser would attach the owner's cookie.
    """
    return os.environ.get("TTYD_FRAME_ANCESTORS", "").strip() or "'none'"

def inject_response_headers(head: bytes, set_cookie: str = "") -> bytes:
    extra = f"Content-Security-Policy: frame-ancestors {frame_ancestors()}\r\n"
    if set_cookie:
        extra += f"Set-Cookie: {set_cookie}\r\n"
    return head[:-2] + extra.encode() + b"\r\n"
```

Refactor `proxy_http` to always read the head and call `inject_response_headers` (so the CSP is present on every response, cookie or not).

- [ ] **Step 4: Set the allowlist on both units**

`Environment=TTYD_FRAME_ANCESTORS=https://archie.kytranempowerment.com http://192.168.1.200:3002`

- [ ] **Step 5: Run tests, commit, open the PR for Tasks 1–3**

```bash
git commit -m "feat(terminal): frame-ancestors allowlist, the required other half of SameSite=None"
```
Then `/commit-push-pr`, F.O.R.G.E. review, merge on a clean APPROVE.

- [ ] **Step 6: Deploy the proxies and prove the three properties live**

```bash
sudo cp /mnt/archie_brain/scripts/ttyd-auth-proxy.service /mnt/archie_brain/scripts/ttyd-codex-auth-proxy.service /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/ttyd-auth-proxy.service
sudo systemctl daemon-reload && sudo systemctl restart ttyd-auth-proxy ttyd-codex-auth-proxy
systemctl is-active ttyd-auth-proxy ttyd-codex-auth-proxy
```
Then, with a freshly minted **codex** token, confirm against `:7681`: **401**. Against `:7683`: **200**, with `Set-Cookie` and `frame-ancestors` present. A second request carrying only the cookie: **200**. (`curl` is blocked in this environment — probe with a small `urllib` script under `$CLAUDE_JOB_DIR/tmp`.)

---

### Task 4: One mint helper, admin-gated, lane-aware

**Files:**
- Create: `archie-comms/services/terminal_lanes.py`
- Modify: `archie-comms/app_comms.py` (the existing `/api/terminal/token` at ~:1243)
- Test: `archie-comms/tests/test_cockpit_terminal.py`

**Interfaces:**
- Produces: `LANES` (ordered registry), `mint_token(user_id, lane) -> dict`, `lane_status() -> list[dict]`, `UnknownLane`
- Consumes: `terminal_auth_tokens.lane` (Task 1)

- [ ] **Step 1: Write the failing tests**

```python
def test_unknown_lane_is_refused():
    from services import terminal_lanes as tl
    with pytest.raises(tl.UnknownLane):
        tl.mint_token(4, "engine")   # the engine is NOT a lane (spec §2)

def test_mint_records_the_lane(monkeypatch):
    from services import terminal_lanes as tl
    seen = {}
    monkeypatch.setattr(tl, "_insert_token", lambda tok, uid, exp, lane: seen.update(lane=lane))
    tl.mint_token(4, "codex")
    assert seen["lane"] == "codex"

def test_lane_urls_are_distinct_and_https():
    from services import terminal_lanes as tl
    urls = {n: c["url"] for n, c in tl.LANES.items()}
    assert len(set(urls.values())) == len(urls)
    assert all(u.startswith("https://") for u in urls.values())

def test_the_claude_lane_is_marked_unsandboxed():
    from services import terminal_lanes as tl
    assert tl.LANES["claude"]["sandboxed"] is False
    assert tl.LANES["codex"]["sandboxed"] is True
```

- [ ] **Step 2: Run to confirm they fail.**

- [ ] **Step 3: Write the helper**

```python
"""The two coder lanes and the one place a terminal token is minted.

ONE mint path on purpose: two routes minting into terminal_auth_tokens with different
gates is the second shell gate the design exists to avoid (spec §11.1).
"""
LANES = {
    "claude": {
        "label": "Claude",
        "url": "https://terminal.kytranempowerment.com",
        "sandboxed": False,   # the HOST shell — no container boundary (spec §2)
        "probe": "http://127.0.0.1:7681/",
    },
    "codex": {
        "label": "Codex",
        "url": "https://codex.kytranempowerment.com",   # confirm against the live Caddyfile
        "sandboxed": True,
        "probe": "http://127.0.0.1:7683/",
    },
}
TOKEN_TTL_SECONDS = 300

class UnknownLane(ValueError):
    pass
```

`mint_token(user_id, lane)` raises `UnknownLane` for anything not in `LANES`, inserts `(token, user_id, expires_at, lane)`, and returns `{"token", "url": f"{cfg['url']}?token={token}", "expires_in": TOKEN_TTL_SECONDS, "lane": lane, "sandboxed": cfg["sandboxed"]}`.

`lane_status()` returns one dict per lane: `{lane, label, reachable, sandboxed, busy}`, where `reachable` is a **real probe** of the proxy (2s timeout, exceptions ⇒ `reachable=False`), never a guess.

- [ ] **Step 4: Point the legacy route at the helper**

Rewrite `/api/terminal/token` to call `mint_token(user_id, "claude")` — same response shape, so the existing chat drawer keeps working. This is what stops a second minting path existing.

- [ ] **Step 5: Run tests, commit**

```bash
git commit -m "refactor(terminal): one lane-aware mint helper, so there is exactly one place a shell token is created"
```

---

### Task 5: The two cockpit routes

**Files:** Modify `archie-comms/cockpit_routes.py` (19 rules → **21**). Test: append to `archie-comms/tests/test_cockpit_terminal.py`.

**Interfaces:** Consumes `terminal_lanes`. Produces `POST /api/cockpit/terminal/<lane>/token`, `GET /api/cockpit/terminal/lanes`.

- [ ] **Step 1: Write the failing tests**

```python
def test_mint_requires_a_session(client):
    assert client.post("/api/cockpit/terminal/claude/token").status_code == 401

def test_mint_requires_an_admin_role(client):
    with client.session_transaction() as s:
        s["user_id"] = 4
        s["role"] = "user"          # today unreachable; the check must be local, not implied
    r = client.post("/api/cockpit/terminal/claude/token")
    assert r.status_code == 403
    assert "admin" in r.get_json()["error"].lower()

def test_an_unknown_lane_is_404_not_500(client):
    with client.session_transaction() as s:
        s["user_id"] = 4; s["role"] = "admin"
    assert client.post("/api/cockpit/terminal/engine/token").status_code == 404

def test_lane_list_shape(client):
    with client.session_transaction() as s:
        s["user_id"] = 4; s["role"] = "admin"
    body = client.get("/api/cockpit/terminal/lanes").get_json()
    assert {l["lane"] for l in body["lanes"]} == {"claude", "codex"}
    for l in body["lanes"]:
        assert set(l) >= {"lane", "label", "reachable", "sandboxed", "busy"}

def test_the_blueprint_has_exactly_21_rules(app):
    rules = [r for r in app.url_map.iter_rules() if r.endpoint.startswith("cockpit.")]
    assert len(rules) == 21
```

- [ ] **Step 2: Run to confirm they fail.**

- [ ] **Step 3: Implement**

```python
def _require_admin(fn):
    """Admin, checked HERE and not inferred from the login path.

    Every comms user is an admin today (app_comms.py:131 rejects role != "admin"), so this
    is currently redundant — and required anyway: without it the terminal's protection would
    rest on a property of the SSO path rather than on anything the terminal code states
    (spec §3.3).
    """
    @wraps(fn)
    def _wrapped(*a, **k):
        if not session.get("user_id"):
            return jsonify({"error": "Not authenticated"}), 401
        if session.get("role") != "admin":
            return jsonify({"error": "A terminal needs an admin account"}), 403
        return fn(*a, **k)
    return _wrapped

@cockpit_bp.route("/api/cockpit/terminal/<lane>/token", methods=["POST"])
@_require_admin
def cockpit_terminal_token(lane):
    try:
        return jsonify(tl.mint_token(session["user_id"], lane)), 200
    except tl.UnknownLane:
        return jsonify({"error": f"Unknown lane: {lane}"}), 404

@cockpit_bp.route("/api/cockpit/terminal/lanes", methods=["GET"])
@_require_admin
def cockpit_terminal_lanes():
    return jsonify({"lanes": tl.lane_status()}), 200
```

Log every mint with the requesting user id and lane, and rate-limit per user.

- [ ] **Step 4: Run tests, commit**

```bash
git commit -m "feat(cockpit): admin-gated terminal mint + lane status routes"
```

---

### Task 6: The fifth pane

**Files:** Modify `archie-comms/templates/cockpit.html`, `static/js/cockpit.js`, `static/css/cockpit.css`. Test: append.

**Interfaces:** Consumes the two routes from Task 5.

- [ ] **Step 1: Write the failing CSS-invariant test**

```python
def test_pane_terminal_is_hidden_by_default_in_the_desktop_block():
    """The Phase 4b grid-cell hazard: two panes in one cell after a resize."""
    css = (COMMS / "static" / "css" / "cockpit.css").read_text()
    block = css.split("@media (min-width: 768px)", 1)[1]
    assert "#pane-terminal { display: none; }" in block
    assert "body.ck-left-terminal #pane-terminal { display: flex; }" in block

def test_the_terminal_pane_and_tab_exist():
    html = (COMMS / "templates" / "cockpit.html").read_text()
    assert 'id="pane-terminal"' in html
    assert 'data-pane="terminal"' in html
```

- [ ] **Step 2: Run to confirm they fail.**

- [ ] **Step 3: Template — fifth section + tab**

Add `<section id="pane-terminal" class="ck-pane" aria-label="Terminal">` after `#pane-approvals`, holding a lane switcher and one iframe slot (only the selected lane mounted), plus a `<button type="button" data-pane="terminal">Terminal</button>` in `#ck-tabs`.

- [ ] **Step 4: CSS — extend the grid-cell invariant**

In the `@media (min-width: 768px)` block, beside the existing `#pane-work` rules:

```css
  /* Bare-id form (0,1,0,0) on purpose — do NOT "tidy" this into a :not() selector.
     A grid ITEM with a non-auto z-index paints as if positioned even at position:static,
     so an uncovered #pane-terminal shares a cell with #pane-crew after a resize. */
  #pane-terminal { display: none; }
  body.ck-left-terminal #pane-terminal { display: flex; }
```

- [ ] **Step 5: JS — mount, states, reconnect**

`mountLane(lane)` POSTs the mint route, sets `iframe.src` to the returned URL, and mounts only the selected lane. Render each state from §6 as **explicit text, never a blank frame**: proxy unreachable (+ when last reachable), codex seat taken, session lapsed (an inline **reconnect** control that mints a fresh token — no silent reload), mint refused (the honest "a terminal needs an admin account"), tmux session absent. Render the claude lane's **persistent host marker** next to codex's sandbox marker.

- [ ] **Step 6: Run tests, commit, PR, merge, rebuild comms from main**

```bash
git commit -m "feat(cockpit): Terminal pane — both lanes, honest states, host-vs-sandbox marker"
# after merge, from main:
docker compose up -d --build --no-deps archie_comms
```

---

### Task 7: The live drive — the only thing that settles this phase

Static tests cannot show that a terminal renders. Do this in a real browser at `http://192.168.1.200:3002/cockpit`.

- [ ] **Step 1:** A non-admin cockpit session cannot mint a token (403, with the honest reason on screen).
- [ ] **Step 2:** A minted token loads the pane **and its assets and its websocket** — the failure §3.1 documents. Confirm in devtools that the cookie is set and that asset requests carry it.
- [ ] **Step 3:** Typing in the claude pane reaches the shared session, and the same session is visible from the standalone terminal URL.
- [ ] **Step 4:** A **codex** token presented to the claude proxy is refused (Task 1, in the browser this time).
- [ ] **Step 5:** The session lapses after 15 idle minutes and the reconnect control recovers it. Confirm it does **not** lapse during continuous use (sliding).
- [ ] **Step 6:** Codex reports its seat as busy when it is.
- [ ] **Step 7:** Both widths — **390 and 1280** — exactly one pane visible, no horizontal scroll.
- [ ] **Step 8:** With the pane closed, confirm an outside origin cannot embed the terminal (`frame-ancestors` refuses).

---

### Task 8: Close out

- [ ] **Step 1:** `complete_task` for the Phase 5 tasks; `log_decision` for the lane-binding rule and the `SameSite=None` + `frame-ancestors` pairing.
- [ ] **Step 2:** `store_memory` a `mistake_learned` for the unbound-token gap — a token that names no scope is a token that grants every scope.
- [ ] **Step 3:** Rewrite the session handoff; delete the SDD workspace for this plan.

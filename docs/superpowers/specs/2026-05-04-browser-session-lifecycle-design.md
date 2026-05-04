# Browser Session Lifecycle Management — Layer A — Design Spec

**Date**: 2026-05-04
**Sequence**: Layer A of a 4-layer multi-agent web automation foundation. B (multi-agent isolation), C (agent provisioning), D (Archie hands-on-internet) follow.
**Triggered by**: 2026-05-04 09:00 EDT outage. The 33-skill LinkedIn Playwright pipeline silently failed for ~3 days because the chromium browser session inside `archie_browser` aged out. No detection. No alert. No re-auth UX. The same outage will recur on every other Playwright-driven platform once we expand to Twitter/Facebook.

## Goal

Build a foundation that ensures every Playwright skill across `archie_browser` has a **detectable, refreshable, queryable** browser session backing it. Specifically:

1. **Detect** session staleness within 6 hours (proactive probe + reactive in-skill detection)
2. **Surface** session status to Kytran via Telegram + DHQ visibility (no more silent failures)
3. **Re-authenticate** via a canonical noVNC sidecar that scales to any agent / any platform
4. **Recover** automatically — skill calls deferred during stale window auto-replay once session restored
5. **Unblock today** — cookie-paste emergency provider gets the existing 33 skills working tonight

## Explicit non-goals (forward references)

| Out of scope | Layer | Why deferred |
|---|---|---|
| Per-agent identity isolation (each AI agent has their own LinkedIn) | **B** | Schema accommodates it (`agent_id` keyed), but provisioning UX + agent persona config is a separate spec |
| Agent account provisioning (Archie creates email + LinkedIn from scratch) | **C** | Builds on Layer A primitives + adds new account-creation skills + uses Stalwart email pipeline already in place |
| Archie hands-on-internet (general goal-driven web actions) | **D** (Project #320) | Reuses Layer A for state persistence; different flow on top |
| Twitter / Facebook / Instagram probe modules | follow-on | Schema is generic; probe URL + stale-signature regex are LinkedIn-specific MVP. Add per platform |
| Multi-account same platform (e.g., 2 LinkedIn accounts for same agent) | follow-on | Schema enforces `UNIQUE(agent_id, platform)`. Extend with `slot` column if/when needed |

## State of the world (recon)

| Component | Current state |
|---|---|
| `archie-browser/session_manager.py` | Encrypted JSON files on disk, keyed `(agent_id, platform)`. No metadata, no DHQ visibility. Loaded by `skill_runner.py:60`. |
| `archie-browser/app.py` | Flask app with `POST /session/setup` (headless username/password login) + `POST /session/<agent>/<platform>/refresh`. No re-auth UI, no probe. |
| `BROWSER_ENCRYPTION_KEY` env var | Already set; reused for new ciphertext column |
| 33 LinkedIn skills | All Playwright-based, all depend on the single shared session. Current state: ALL FAILING because session expired between May 1 and 2026-05-04. |
| KBS `social_accounts` table | OAuth-based (LinkedIn API path) — orthogonal to this spec. Layer A is the Playwright-side equivalent. |
| `autonomy_approval_queue` | Already used for Telegram approvals. Reused for `skill_failure` alerts in Layer A. |
| `dispatch_pending_queue` | Cold-model dispatch deferral pattern. Layer A's `browser_skill_queue` mirrors this pattern. |

## Architecture

```
┌──────────────────────── Layer A: Browser Sessions ───────────────────────┐
│                                                                          │
│  ┌─────────────────┐    ┌──────────────────┐   ┌──────────────────┐     │
│  │ Probe Job (6h)  │───▶│ browser_sessions │◀──│ Reactive layer   │     │
│  │ per (agent,plt) │    │ (DB table)       │   │ in skill_runner  │     │
│  └─────────────────┘    │  status:         │   │  catches:        │     │
│                         │   active         │   │   timeout        │     │
│                         │   stale          │   │   "Page          │     │
│                         │   reauth_pending │   │    isn't avail"  │     │
│                         │   reauth_active  │   │   /login redirect│     │
│                         └──────┬───────────┘   └──────┬───────────┘     │
│                                │                      │                 │
│                                ▼                      ▼                 │
│  ┌──────────────────────────────────────────────────────────┐           │
│  │ Status transition: active ──[probe miss/skill fail]──▶   │           │
│  │ stale ──[Telegram alert sent]──▶                         │           │
│  │ reauth_pending ──[Kytran clicks link]──▶                 │           │
│  │ reauth_active ──[noVNC complete]──▶ active               │           │
│  └──────────────────────────────────────────────────────────┘           │
│                                                                          │
│  When session = stale | reauth_pending:                                  │
│    skill calls deferred to browser_skill_queue (DB table)                │
│    when session → active: defer worker auto-replays                      │
│                                                                          │
│  Re-auth providers:                                                      │
│  ┌───────────────────────────────────┐  ┌───────────────────────────┐   │
│  │ noVNC sidecar (canonical)         │  │ Cookie paste (emergency)  │   │
│  │  archie_browser_vnc container     │  │  POST /api/sessions/      │   │
│  │  Kytran clicks signed link →      │  │   <agent>/<platform>/     │   │
│  │  views chromium → logs in →       │  │   import-cookies          │   │
│  │  state captured → DB updated      │  │  body: {cookies: [...]}   │   │
│  └───────────────────────────────────┘  └───────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

### Container topology after Layer A ships

| Container | Role | Change |
|---|---|---|
| `archie_browser` | Runs Playwright skills | `skill_runner.py` reads/writes `browser_sessions` table instead of on-disk JSON |
| **NEW**: `archie_browser_vnc` | Xvfb + x11vnc + noVNC web server | Connects to `archie_browser`'s chromium via shared X display socket. Exposes only via NPM proxy with admin auth + signed-token check |
| `archie_database` | Postgres | New tables: `browser_sessions`, `browser_skill_queue` |
| `archie_platform` | Flask app | New routes under `/tools/department-hq/api/sessions/...` + DHQ "Connected Accounts" tab |

## Components (detailed)

### 3.1 Schema — `database/migrations/372_browser_sessions.sql`

```sql
BEGIN;

CREATE TABLE IF NOT EXISTS browser_sessions (
    id                  SERIAL PRIMARY KEY,
    agent_id            INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    platform            VARCHAR(50) NOT NULL,
    status              VARCHAR(30) NOT NULL DEFAULT 'unverified',
                        -- unverified | active | stale | reauth_pending | reauth_active | disabled
    encrypted_state     BYTEA,                  -- AES-encrypted cookies+localStorage JSON
    last_used_at        TIMESTAMP,
    last_probe_at       TIMESTAMP,
    last_probe_ok       BOOLEAN,
    last_failure_reason TEXT,
    reauth_token        VARCHAR(64),
    reauth_expires_at   TIMESTAMP,
    deferred_count      INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(agent_id, platform)
);

CREATE INDEX IF NOT EXISTS idx_browser_sessions_status ON browser_sessions(status);
CREATE INDEX IF NOT EXISTS idx_browser_sessions_probe ON browser_sessions(last_probe_at);

CREATE TABLE IF NOT EXISTS browser_skill_queue (
    id                  SERIAL PRIMARY KEY,
    skill_name          VARCHAR(100) NOT NULL,
    agent_id            INTEGER NOT NULL,
    platform            VARCHAR(50) NOT NULL,
    params              JSONB NOT NULL,
    status              VARCHAR(30) NOT NULL DEFAULT 'queued',
                        -- queued | running | completed | failed | abandoned
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMP,
    source_approval_id  INTEGER  -- FK to autonomy_approval_queue.id when applicable
);

CREATE INDEX IF NOT EXISTS idx_browser_skill_queue_pickup
    ON browser_skill_queue(agent_id, platform, status)
    WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS idx_browser_skill_queue_age
    ON browser_skill_queue(created_at)
    WHERE status IN ('queued', 'running');

COMMIT;
```

Encryption uses existing `BROWSER_ENCRYPTION_KEY`. Encrypt-on-write helper in `services/browser_session_service.py` (new) — single source of truth for encrypt/decrypt.

### 3.2 Probe job — `agent_loop_browser_session_probe`

- **Cadence**: 6h cron (`CronTrigger(hour='*/6')`)
- **Per row** in `browser_sessions WHERE status IN ('active', 'stale')`:
  1. Load `encrypted_state` → decrypt → Playwright context
  2. Goto a known-good URL (LinkedIn: `https://www.linkedin.com/feed/`)
  3. `wait_for_load_state('networkidle', timeout=15000)`
  4. Check for selector `[data-test-global-nav]` OR `nav.global-nav` (verifies logged-in state)
  5. **Pass**: `last_probe_ok=true`, `last_probe_at=NOW()`. If transitioning `stale→active`: clear `last_failure_reason`, send Telegram "✅ LinkedIn restored".
  6. **Fail**: `last_probe_ok=false`, `last_failure_reason=<details>`. If transitioning `active→stale`: send Telegram alert (3.5).
- **Per platform**: probe URL + selector live in `services/browser_session_probes.py` (one function per platform). MVP: LinkedIn only.

### 3.3 Reactive layer — wraps `skill_runner.run_skill_sync`

After every skill execution, classify result:

```python
STALE_SIGNATURES = {
    "linkedin": [
        "This LinkedIn Page isn't available",
        "linkedin.com/login",
        "challenge",
    ],
}

def _classify_for_session_health(platform, result):
    err = (result.get("error") or "").lower()
    if "timeout" in err or "could not find" in err:
        return "stale"
    return None
```

If classified as stale → mark `browser_sessions.status='stale'` + fire Telegram (3.5).

### 3.4 noVNC sidecar — `archie_browser_vnc` container

- **Base image**: `consol/ubuntu-xfce-vnc:1.x` or `dorowu/ubuntu-desktop-lxde-vnc` (Xvfb + x11vnc + noVNC + minimal desktop)
- **Connection**: shared volume mount with `archie_browser` for X11 socket OR remote Chrome DevTools Protocol over network
- **Web server**: noVNC on internal port 6901; not WAN-exposed
- **Access path**: NPM proxy adds `/tools/department-hq/sessions/reauth/<token>`:
  1. Validates platform admin session
  2. Validates `token` against `browser_sessions.reauth_token` + not-expired
  3. Sets `status='reauth_active'`
  4. Reverse-proxies to `archie_browser_vnc:6901`
- **On exit**: sidecar polls until Kytran closes tab OR clicks "Done" button injected on the LinkedIn page → captures `context.storage_state()` → encrypts → writes to DB → `status='active'` → fires Telegram "✅ Reconnected".
- **Token lifecycle**: 30-minute TTL; one-shot (cleared after use).

### 3.5 Telegram alert flow

Three alert types, all routed through `briefing_service` → unified comms (A.R.C.H.I.E. voice):

| Trigger | Format | Inline buttons |
|---|---|---|
| Session detected stale (probe or reactive) | "🔌 LinkedIn (KE Inc.) session expired. {N} posts deferred." | `[Reconnect]` (opens signed URL) · `[Snooze 6h]` · `[Disable Pipeline]` |
| Skill execution failure | "❌ {skill_name} failed: {error_class}. Approval #{N} marked failed. {screenshot link}." | `[Retry]` · `[Mark Won't Fix]` |
| Deferred-queue backup (>3 items, oldest >1h) | "⏳ {N} LinkedIn posts waiting on re-auth (oldest {Xh})." | `[Reconnect]` · `[Drop Queue]` |

Buttons map to `/api/sessions/...` callback endpoints in DHQ.

### 3.6 Defer worker — `agent_loop_browser_skill_replay`

- **Cadence**: 30s cron, `max_instances=1`, `coalesce=True`
- **Logic**:
  1. `SELECT * FROM browser_skill_queue q JOIN browser_sessions s ON (q.agent_id=s.agent_id AND q.platform=s.platform) WHERE q.status='queued' AND s.status='active' ORDER BY q.created_at LIMIT 5`
  2. For each row:
     - Mark `status='running'`
     - Call original skill via `run_skill_sync(skill_name, params)`
     - On success: `status='completed', completed_at=NOW()`
     - On failure: `attempts += 1, last_error=<...>`. If `attempts >= 3`: `status='abandoned'` + Telegram alert.
  3. Skipping if session re-stales mid-replay → row goes back to `queued`.

### 3.7 DHQ "Connected Accounts" tab (small UI addition)

In DHQ → new sub-tab OR Fleet tab section. Read-only initially:

- Table: `agent_name | platform | status | last_used | last_probe | deferred | [Reconnect]`
- Status colored: green=active, amber=stale, red=disabled, blue=reauth_active
- `[Reconnect]` button: hits `POST /api/sessions/<agent>/<platform>/init-reauth` → server generates signed token → opens noVNC URL in new tab.

Frontend: extend `tools/department_hq/static/js/department-hq.js` with `loadConnectedAccounts()`.

### 3.8 Cookie-paste endpoint (emergency provider)

`POST /tools/department-hq/api/sessions/<agent_id>/<platform>/import-cookies`

```json
{
  "cookies": [
    {"name": "li_at", "value": "...", "domain": ".linkedin.com", "path": "/", "expires": ..., "httpOnly": true, "secure": true},
    ...
  ]
}
```

Validates schema (Chrome extension cookie format), packages as Playwright `storage_state` JSON, encrypts via existing key, UPSERTs row in `browser_sessions` with `status='active'`. Fires confirmation Telegram. Admin-only auth.

### 3.9 New service module — `services/browser_session_service.py`

Single source of truth for:
- `encrypt_state(state_dict) -> bytes`
- `decrypt_state(ciphertext) -> dict`
- `load_session(agent_id, platform) -> Optional[dict]` — replaces `archie-browser/session_manager.load_session` (DB-backed)
- `save_session(agent_id, platform, state_dict, status='active') -> None`
- `mark_stale(agent_id, platform, reason) -> None`
- `mark_active(agent_id, platform) -> None`
- `generate_reauth_token(agent_id, platform, ttl_minutes=30) -> str`
- `consume_reauth_token(token) -> Optional[(agent_id, platform)]`

Used by: skill_runner, probe job, reactive layer, defer worker, cookie-paste endpoint, DHQ routes.

## Day-1 path (today's repair, fits within Layer A)

The cookie-paste path is Layer A's emergency provider. Today's repair = ship a minimal slice of Layer A in one PR:

```
Day-1 minimal slice (4-6 hours):
  ✓ Migration 372: browser_sessions table only (skip queue, skip skill_runner refactor for now)
  ✓ services/browser_session_service.py: encrypt + DB read/write helpers
  ✓ Cookie-paste endpoint
  ✓ archie-browser/session_manager.py: refactor load_session() to call platform service via HTTP
    (GET http://archie_platform:3000/api/sessions/<agent>/<platform>/state — admin-key auth).
    Reverse direction matches existing pattern (platform calls archie_browser at :4242).
  ✓ Manual repair workflow:
      1. Kytran exports cookies from her browser (Chrome cookie editor extension)
      2. POSTs to import-cookies endpoint
      3. browser_sessions row inserted
      4. Re-fire linkedin_company_post test → should succeed
  ✓ Failure-alert patch (silent-failure fix — fires on execution_result.success=false)

Day-2+ (full Layer A — separate PRs):
  ☐ Probe job (6h)
  ☐ Reactive layer wrap
  ☐ browser_skill_queue + defer worker
  ☐ noVNC sidecar
  ☐ DHQ "Connected Accounts" tab
  ☐ Telegram inline-button callback handlers
```

## Test plan

| Layer | Test |
|---|---|
| Unit | `encrypt_state` / `decrypt_state` round-trip preserves payload; mismatched key fails |
| Unit | Stale-signature regex matchers cover all 3 LinkedIn signatures |
| Unit | Status transition state machine: only valid transitions allowed |
| Unit | Reauth token generation + consumption (happy + expired + double-use) |
| Integration | Cookie-import endpoint validates schema, encrypts, persists, returns 200 |
| Integration | Probe job marks `stale` when nav-selector missing; restores `active` on success |
| Integration | `skill_runner` defers when `status≠active`; defer worker replays when status→active |
| E2E (manual) | Today's repair: cookie paste → linkedin_company_post test on #1111 content → real LinkedIn post lands → screenshots verified |
| Telegram | Skill execution failure → alert fires within 30s → button replies route correctly |
| Security | NPM proxy refuses `/sessions/reauth/<bad-token>`; refuses non-admin platform sessions; refuses expired tokens |

## Acceptance criteria

### Day-1 slice (must ship same PR)
- [ ] Migration 372 applied
- [ ] Kytran-personal session row in DB with `status='active'`
- [ ] KE Inc. session row in DB with `status='active'`
- [ ] `linkedin_company_post` E2E test succeeds against `#1111` content (or new fresh content)
- [ ] `linkedin_post` (personal) E2E test succeeds
- [ ] Skill execution failure (forced via mock) fires a Telegram alert

### Full Layer A (across follow-on PRs)
- [ ] Probe job catches a synthetically-staled session within 6h + sends Telegram
- [ ] Reactive layer marks session `stale` on a real skill timeout (verified via skill output classification)
- [ ] Deferred posts auto-replay when status flips to `active`
- [ ] noVNC sidecar accessible via signed URL; 30-min TTL enforced; new-account cookies persisted
- [ ] DHQ "Connected Accounts" tab lists all sessions with correct status colors

## Decisions / trade-offs

| Decision | Chosen | Why |
|---|---|---|
| Re-auth UX | noVNC canonical + cookie paste emergency | noVNC scales to all 38 future agents; cookie paste unblocks today |
| Detection | Probe (6h) + Reactive | Defense-in-depth; probe catches expiry within 6h, reactive catches edge cases the probe misses |
| Storage | DB-backed (BYTEA) | Survives container rebuilds; queryable for DHQ + monitoring; DB has backups |
| Skill behavior on stale | Defer + auto-retry (mirrors cold-model dispatch) | Today's #1111 would have eventually shipped; survives container restarts |
| noVNC infra | Sidecar container | Clean separation; archie_browser stays single-purpose; standard pattern |
| Failure alerts | Rolled into Layer A | Today's silent-failure was the EXACT bug Layer A solves — bundling them keeps the fix coherent |
| Probe cadence | 6h | Balance responsiveness vs LinkedIn rate-pressure |

## References

- Layer B/C/D placeholder projects: TBD — created post-Layer-A
- Project #320 — Archie Hands-on-Internet (Layer D)
- Project #316 — Agent Social Identity SP3+SP4 (depends on Layer A for multi-platform expansion)
- KB #261583+ — S.I.G.N.A.L. Command tab implementation
- Existing pattern: `dispatch_pending_queue` cold-model deferral (model-affinity dispatch queue)
- Existing pattern: `autonomy_approval_queue` Telegram approvals

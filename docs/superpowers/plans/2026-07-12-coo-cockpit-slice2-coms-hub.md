# COO Cockpit Slice 2 — COMs / Telegram Hub — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the Department HQ **COMs** tab (Telegram message feed + config + migration status) into the cockpit as a read-only **COMs tab** — A.R.C.H.I.E.'s comms command center where she works.

**Architecture:** Thin cockpit + platform internal endpoints (the Slice-1 pattern). One platform read service reproduces the DHQ COMs read logic over `telegram_message_log`; one internal endpoint (`@_require_internal_key`) exposes it; a session-authed cockpit proxy fetches it; a new `panel-coms` tab renders it. Read-only — mutations (test-send, triage policies) stay in DHQ (its tab is the thin mirror). Slice 2 of `docs/superpowers/specs/2026-07-12-archie-coo-command-surface-design.md`.

**Tech Stack:** Flask (both apps), psycopg2 (`get_db_cursor`, RealDict rows), the LCARS tab system (`header_tabs` + `.comms-panel` + `onLcarsTabSwitch`), vanilla JS (`_mk`/textContent).

## Global Constraints

- Thin cockpit → platform internal endpoints behind `@_require_internal_key` (Bearer `INTERNAL_API_KEY`); the key NEVER reaches the browser (cockpit proxy calls the platform server-side).
- **Read-only.** The COMs feed is `telegram_message_log` (the outbound ops log). Do NOT expose the mutating COMs routes (test-send, triage-policy CRUD, director-report ack) — those stay in DHQ.
- Distinct from the chat stream: the cockpit chat renders `unified_messages` (`channel='telegram'`); this panel reads `telegram_message_log`. **Different table — no duplication.**
- XSS: all dynamic DOM via `_mk(tag, cls)` + `.textContent`. Never `innerHTML`.
- Fail-soft: a degraded COMs lane never breaks the cockpit — the tab shows an empty/"unavailable" state.
- `PLATFORM_URL` (default `http://archie_platform:3000`) is the cockpit→platform base (mirror `coo_consult.py`, NOT `PLATFORM_INTERNAL_URL`).
- In `app.py`, import platform services directly inside the handler (the Slice-1 pattern); no `_ensure_import_paths()`.
- Timezone: stringify `created_at` server-side; the JS shows it via existing `ArchieTime` if available, else raw.

## File Structure

**Platform (`platform_v2/`)**
- `services/coms_hub_service.py` — CREATE. `list_messages()` + `config_summary()` + `migration_summary()` + `overview()` — reproduces the DHQ COMs READ logic (`telegram_message_log` SELECT, env/`CATEGORIES` config, `KNOWN_SENDERS` migration). DRY: imports `KNOWN_SENDERS` from `coms_routes`.
- `app.py` — MODIFY. Add `GET /api/internal/coms/overview` beside the Slice-1 coo endpoints (~line 4540).
- `tests/test_coms_hub.py` — CREATE.

**Cockpit (`archie-comms/`)**
- `services/coms_hub.py` — CREATE. `overview(...)` proxy (mirror `coo_consult.py`).
- `app_comms.py` — MODIFY. Session-authed `GET /api/coms/overview`.
- `templates/chat.html` — MODIFY. Add `("coms", "COMs", "radio")` to `header_tabs` + a `panel-coms` div.
- `static/js/archie-chat.js` — MODIFY. `loadComs()` + `onLcarsTabSwitch` wiring.
- `static/css/archie-chat.css` — MODIFY. COMs panel styles.
- `tests/test_coms_hub.py` — CREATE.

---

### Task 1: Platform — COMs read service

**Files:**
- Create: `platform_v2/services/coms_hub_service.py`
- Test: `platform_v2/tests/test_coms_hub.py`

**Interfaces:**
- Produces: `list_messages(limit=50, category=None, source_agent=None, status=None) -> list[dict]`; `config_summary() -> dict`; `migration_summary() -> dict`; `overview(...) -> {messages, config, migration}`.

- [ ] **Step 1: Write the failing test**

```python
# platform_v2/tests/test_coms_hub.py
def test_list_messages_builds_filtered_query(monkeypatch):
    import services.coms_hub_service as svc
    seen = {}

    class _Cur:
        def execute(self, q, params=None):
            seen["q"] = q
            seen["params"] = params

        def fetchall(self):
            return [{"id": 1, "category": "system", "message": "hi", "source_agent": "V.I.G.I.L.",
                     "status": "sent", "created_at": "2026-07-12"}]

    import contextlib

    @contextlib.contextmanager
    def _fake_cursor(commit=False):
        yield (None, _Cur())

    monkeypatch.setattr(svc, "_get_cursor", lambda: _fake_cursor)
    rows = svc.list_messages(limit=10, category="system", source_agent="V.I.G.I.L.")
    assert rows[0]["source_agent"] == "V.I.G.I.L."
    assert "telegram_message_log" in seen["q"] and "category = %s" in seen["q"] and "source_agent = %s" in seen["q"]
    assert seen["params"][-1] == 10  # LIMIT last


def test_config_summary_shape(monkeypatch):
    import services.coms_hub_service as svc
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "999")
    c = svc.config_summary()
    assert c["bot_token_set"] is True and c["chat_id"] == "999" and isinstance(c["categories"], dict)


def test_overview_combines(monkeypatch):
    import services.coms_hub_service as svc
    monkeypatch.setattr(svc, "list_messages", lambda **k: [{"id": 1}])
    monkeypatch.setattr(svc, "config_summary", lambda: {"bot_token_set": True})
    monkeypatch.setattr(svc, "migration_summary", lambda: {"progress": {"percentage": 50}})
    o = svc.overview()
    assert o["messages"] == [{"id": 1}] and o["config"]["bot_token_set"] and o["migration"]["progress"]["percentage"] == 50
```

- [ ] **Step 2: Run — expect FAIL (module missing).**

- [ ] **Step 3: Implement the service**

```python
# platform_v2/services/coms_hub_service.py
"""COO command surface — COMs/Telegram hub read layer (Slice 2). Reproduces the DHQ COMs
tab's READ logic (telegram_message_log feed + config + migration) so the cockpit can surface
it read-only. Mutations stay in DHQ. DRY: reuses coms_routes.KNOWN_SENDERS."""
from __future__ import annotations

import os

_MSG_COLS = (
    "id, category, title, message, source_agent, source_department, "
    "source_module, priority, status, created_at"
)


def _get_cursor():
    from database import get_db_cursor

    return get_db_cursor


def list_messages(limit=50, category=None, source_agent=None, status=None):
    q = f"SELECT {_MSG_COLS} FROM telegram_message_log WHERE 1=1"
    params = []
    if category:
        q += " AND category = %s"
        params.append(category)
    if source_agent:
        q += " AND source_agent = %s"
        params.append(source_agent)
    if status:
        q += " AND status = %s"
        params.append(status)
    q += " ORDER BY created_at DESC LIMIT %s"
    params.append(int(limit))
    get_db_cursor = _get_cursor()
    with get_db_cursor(commit=False) as (_conn, cur):
        cur.execute(q, params)
        rows = cur.fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("created_at") is not None:
            d["created_at"] = str(d["created_at"])
        out.append(d)
    return out


def config_summary():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    categories = {}
    try:
        from services.telegram_service import CATEGORIES

        for name, meta in (CATEGORIES or {}).items():
            categories[name] = {
                "icon": (meta or {}).get("icon", ""),
                "label": (meta or {}).get("label", name),
                "priority": (meta or {}).get("priority", ""),
            }
    except Exception:
        pass
    return {"bot_token_set": bool(token), "chat_id": chat_id, "categories": categories}


def migration_summary():
    try:
        from tools.department_hq.coms_routes import KNOWN_SENDERS
    except Exception:
        KNOWN_SENDERS = []
    seen = set()
    try:
        get_db_cursor = _get_cursor()
        with get_db_cursor(commit=False) as (_conn, cur):
            cur.execute("SELECT DISTINCT source_module FROM telegram_message_log WHERE source_module IS NOT NULL")
            for r in cur.fetchall():
                seen.add(dict(r).get("source_module"))
    except Exception:
        pass
    senders = []
    migrated = 0
    for s in KNOWN_SENDERS:
        mod = s.get("module")
        st = "migrated" if mod in seen else "pending"
        if st == "migrated":
            migrated += 1
        senders.append(
            {"module": mod, "location": s.get("location"), "purpose": s.get("purpose"),
             "agent": s.get("agent"), "status": st}
        )
    total = len(KNOWN_SENDERS)
    pct = round(migrated / total * 100) if total else 0
    return {"senders": senders, "progress": {"migrated": migrated, "total": total, "percentage": pct}}


def overview(limit=50, category=None, source_agent=None, status=None):
    return {
        "messages": list_messages(limit=limit, category=category, source_agent=source_agent, status=status),
        "config": config_summary(),
        "migration": migration_summary(),
    }
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit.**

```bash
git add platform_v2/services/coms_hub_service.py platform_v2/tests/test_coms_hub.py
git commit -m "feat(coo): platform COMs hub read service (feed + config + migration) (Slice 2)"
```

---

### Task 2: Platform — COMs internal endpoint

**Files:**
- Modify: `platform_v2/app.py` (add `GET /api/internal/coms/overview` after the coo endpoints)
- Test: `platform_v2/tests/test_coms_hub.py`

**Interfaces:**
- Consumes: `coms_hub_service.overview(...)` (Task 1).
- Produces: `GET /api/internal/coms/overview?limit&category&source_agent&status` → `{success, messages, config, migration}`; unauth → 401; fail-soft 200 on error.

- [ ] **Step 1: Write the failing test**

```python
def test_coms_overview_requires_key(client):
    r = client.get("/api/internal/coms/overview")
    assert r.status_code == 401


def test_coms_overview_ok(client, monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    import services.coms_hub_service as svc
    monkeypatch.setattr(
        svc, "overview",
        lambda **k: {"messages": [{"id": 1, "message": "hi"}], "config": {"bot_token_set": True},
                     "migration": {"progress": {"percentage": 42}}},
    )
    r = client.get("/api/internal/coms/overview?limit=5&category=system", headers={"Authorization": "Bearer k"})
    assert r.status_code == 200
    b = r.get_json()
    assert b["success"] and b["messages"][0]["id"] == 1 and b["migration"]["progress"]["percentage"] == 42
```

- [ ] **Step 2: Run — expect FAIL (404).**

- [ ] **Step 3: Add the endpoint in `app.py`** (after `api_internal_coo_consult`)

```python
@app.route("/api/internal/coms/overview", methods=["GET"])
@_require_internal_key
def api_internal_coms_overview():
    """COMs/Telegram hub read view (feed + config + migration) for the cockpit COMs tab.

    Read-only (Slice 2 of the COO command surface). Fail-soft: 200 with empties on error.
    """
    try:
        from services.coms_hub_service import overview

        data = overview(
            limit=int(request.args.get("limit", 50) or 50),
            category=(request.args.get("category") or "").strip() or None,
            source_agent=(request.args.get("source_agent") or "").strip() or None,
            status=(request.args.get("status") or "").strip() or None,
        )
        return jsonify({"success": True, **data})
    except Exception as e:
        logger.warning(f"coms/overview failed: {e}")
        return jsonify({"success": False, "messages": [], "config": {}, "migration": {}}), 200
```

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit.**

```bash
git add platform_v2/app.py platform_v2/tests/test_coms_hub.py
git commit -m "feat(coo): platform /api/internal/coms/overview endpoint (Slice 2)"
```

---

### Task 3: Cockpit — COMs proxy + route

**Files:**
- Create: `archie-comms/services/coms_hub.py`
- Modify: `archie-comms/app_comms.py` (add `GET /api/coms/overview`)
- Test: `archie-comms/tests/test_coms_hub.py`

**Interfaces:**
- Produces: `overview(limit=50, category=None, source_agent=None, status=None) -> dict` (platform JSON or fail-soft empties).

- [ ] **Step 1: Write the failing test**

```python
# archie-comms/tests/test_coms_hub.py
import services.coms_hub as ch


def test_overview_proxies_with_filters(monkeypatch):
    seen = {}

    class _R:
        status_code = 200

        def json(self):
            return {"success": True, "messages": [{"id": 1}], "config": {"bot_token_set": True},
                    "migration": {"progress": {"percentage": 10}}}

    import requests as rq
    monkeypatch.setattr(rq, "get", lambda url, headers=None, params=None, timeout=None: seen.update(url=url, params=params) or _R())
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    out = ch.overview(limit=5, category="system")
    assert out["messages"][0]["id"] == 1
    assert seen["url"].endswith("/api/internal/coms/overview")
    assert seen["params"]["limit"] == 5 and seen["params"]["category"] == "system"


def test_overview_failsoft(monkeypatch):
    import requests as rq

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(rq, "get", boom)
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    assert ch.overview() == {"messages": [], "config": {}, "migration": {}}
```

- [ ] **Step 2: Run — expect FAIL (module missing).**

- [ ] **Step 3: Implement the proxy** (mirror `coo_consult.py`)

```python
# archie-comms/services/coms_hub.py
"""Cockpit-side proxy to the platform COMs hub read endpoint. Server-side only —
INTERNAL_API_KEY never reaches the browser. Read-only. Slice 2 of the COO command surface."""
import os

import requests


def _platform_url():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _headers():
    return {"Authorization": "Bearer " + os.getenv("INTERNAL_API_KEY", "")}


def overview(limit=50, category=None, source_agent=None, status=None):
    """COMs feed + config + migration; fail-soft to empties."""
    params = {"limit": limit}
    if category:
        params["category"] = category
    if source_agent:
        params["source_agent"] = source_agent
    if status:
        params["status"] = status
    try:
        r = requests.get(
            f"{_platform_url()}/api/internal/coms/overview", headers=_headers(), params=params, timeout=15
        )
        if r.status_code == 200:
            d = r.json()
            return {"messages": d.get("messages", []), "config": d.get("config", {}), "migration": d.get("migration", {})}
    except Exception:
        pass
    return {"messages": [], "config": {}, "migration": {}}
```

- [ ] **Step 4: Add the session route in `app_comms.py`** (after `api_coo_agents`)

```python
@app.route("/api/coms/overview", methods=["GET"])
def api_coms_overview():
    """COMs/Telegram hub read view for the cockpit COMs tab. Session-gated; the internal
    key is applied server-side in the proxy. Slice 2 (COO command surface)."""
    from flask import request as flask_request
    from flask import session as flask_session

    if not flask_session.get("user_id"):
        return jsonify({"error": "Not authenticated"}), 401
    from services.coms_hub import overview

    return jsonify(
        overview(
            limit=int(flask_request.args.get("limit", 50) or 50),
            category=(flask_request.args.get("category") or "").strip() or None,
            source_agent=(flask_request.args.get("source_agent") or "").strip() or None,
            status=(flask_request.args.get("status") or "").strip() or None,
        )
    )
```

- [ ] **Step 5: Run — expect PASS. Commit.**

```bash
git add archie-comms/services/coms_hub.py archie-comms/app_comms.py archie-comms/tests/test_coms_hub.py
git commit -m "feat(coo): cockpit COMs hub proxy + session route (Slice 2)"
```

---

### Task 4: Cockpit — the COMs tab (frontend)

**Files:**
- Modify: `archie-comms/templates/chat.html` (add tab tuple + `panel-coms`)
- Modify: `archie-comms/static/js/archie-chat.js` (`loadComs()` + `onLcarsTabSwitch`)
- Modify: `archie-comms/static/css/archie-chat.css`

**Interfaces:**
- Consumes: `GET /api/coms/overview` (Task 3); `_mk`/textContent (js:7); the `onLcarsTabSwitch` lazy-load pattern (js:901).

- [ ] **Step 1: Add the tab tuple + panel in `chat.html`**

Add to `header_tabs` (after the `terminal` tuple, ~line 26):
```html
    ("coms", "COMs", "radio")
```
Add the panel (after `panel-terminal` closes, ~line 174+; place beside the other `.comms-panel` divs):
```html
<div id="panel-coms" class="comms-panel">
  <div class="ac-coms-wrap">
    <div class="ac-coms-header" id="ac-coms-header">Loading COMs…</div>
    <div class="ac-coms-feed" id="ac-coms-feed"></div>
  </div>
</div>
```

- [ ] **Step 2: Add `loadComs()` + wire the tab in `archie-chat.js`**

Extend the `onLcarsTabSwitch` wrapper (js:901-905) — add a branch:
```javascript
    if (tabId === 'coms') loadComs();
```
Define `loadComs` (standalone function, near `loadApprovals` ~js:633; uses `_mk`/textContent):
```javascript
async function loadComs() {
  const header = document.getElementById('ac-coms-header');
  const feed = document.getElementById('ac-coms-feed');
  if (!header || !feed) return;
  try {
    const r = await fetch('/api/coms/overview?limit=60', { credentials: 'same-origin' });
    const d = r.ok ? await r.json() : { messages: [], config: {}, migration: {} };
    // Header: bot status + migration progress
    header.textContent = '';
    const status = _mk('span', 'ac-coms-status');
    status.textContent = d.config && d.config.bot_token_set ? '● Telegram connected' : '○ Telegram not configured';
    header.appendChild(status);
    if (d.migration && d.migration.progress) {
      const mig = _mk('span', 'ac-coms-mig');
      mig.textContent = '  ·  ' + (d.migration.progress.migrated || 0) + '/' + (d.migration.progress.total || 0) +
        ' senders migrated (' + (d.migration.progress.percentage || 0) + '%)';
      header.appendChild(mig);
    }
    // Feed rows
    feed.textContent = '';
    const msgs = Array.isArray(d.messages) ? d.messages : [];
    if (!msgs.length) {
      const empty = _mk('div', 'ac-coms-empty');
      empty.textContent = 'No Telegram messages logged yet.';
      feed.appendChild(empty);
      return;
    }
    msgs.forEach((m) => {
      const row = _mk('div', 'ac-coms-row');
      const meta = _mk('div', 'ac-coms-meta');
      meta.textContent = (m.source_agent || m.source_module || 'system') + ' · ' + (m.category || '') +
        ' · ' + (m.status || '');
      const body = _mk('div', 'ac-coms-body');
      body.textContent = m.title ? (m.title + ' — ' + (m.message || '')) : (m.message || '');
      const time = _mk('div', 'ac-coms-time');
      time.textContent = m.created_at || '';
      row.appendChild(meta);
      row.appendChild(body);
      row.appendChild(time);
      feed.appendChild(row);
    });
  } catch (e) {
    header.textContent = 'COMs unavailable right now.';
  }
}
```

- [ ] **Step 3: Style in `archie-chat.css`** (append; match the LCARS panels)

```css
/* COMs tab (Slice 2) — Telegram ops feed + config/migration header */
#panel-coms { padding: 12px 16px; overflow-y: auto; }
.ac-coms-header { font-family: "IBM Plex Mono", ui-monospace, monospace; font-size: 12px;
  color: var(--ac-text-dim, #7f95a8); padding: 6px 0 10px; border-bottom: 1px solid var(--ac-line, #24405c); }
.ac-coms-status { color: var(--ac-accent, #00e5ff); }
.ac-coms-feed { display: flex; flex-direction: column; gap: 6px; padding-top: 10px; }
.ac-coms-row { background: var(--ac-panel, #10151c); border: 1px solid var(--ac-line, #24405c);
  border-radius: 6px; padding: 8px 10px; }
.ac-coms-meta { font-size: 10px; color: var(--ac-accent, #00e5ff); font-family: "IBM Plex Mono", ui-monospace, monospace; }
.ac-coms-body { font-size: 13px; color: var(--ac-text, #cfe3ff); margin: 3px 0; }
.ac-coms-time { font-size: 10px; color: var(--ac-text-dim, #556677); }
.ac-coms-empty { color: var(--ac-text-dim, #556677); font-size: 12px; padding: 12px 0; }
```

- [ ] **Step 4: Verify** `node --check archie-comms/static/js/archie-chat.js` — clean.

- [ ] **Step 5: Commit.**

```bash
git add archie-comms/templates/chat.html archie-comms/static/js/archie-chat.js archie-comms/static/css/archie-chat.css
git commit -m "feat(coo): COMs tab in the cockpit — Telegram ops feed + config/migration (Slice 2)"
```

---

## Deploy & verify (after all tasks green)

- Platform: `docker restart archie_platform` (new route).
- Cockpit: `docker compose -f /mnt/archie_brain/docker-compose.yml up -d --build archie_comms`.
- Live: `GET /api/internal/coms/overview` (internal key) returns `{messages, config, migration}`; open the cockpit → **COMs** tab shows the Telegram feed + connected status + migration %.

## Self-Review

- **Spec coverage:** migrate COMs tab (feed + config + migration) into the cockpit as a panel ✓ (Tasks 1-4); read-only, DHQ keeps its tab as the thin mirror ✓ (no DHQ change, no mutating routes exposed); reuses `telegram_message_log` + `KNOWN_SENDERS` (DRY) ✓; thin-cockpit + internal-endpoint + session-proxy pattern ✓; distinct from the chat stream ✓ (different table, called out).
- **Placeholder scan:** none — every step has concrete code/anchors.
- **Type consistency:** `overview()` returns `{messages, config, migration}` (produced Task 1, exposed Task 2, proxied Task 3, rendered Task 4); the message row keys (`source_agent`/`category`/`status`/`title`/`message`/`created_at`) match `_MSG_COLS` throughout.

# Phase 8: Settings, Search & Mobile — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add mobile sidebar drawer, user settings/preferences UI, and conversation search to the ARCHIE chat interface.

**Architecture:** Replace the CSS-only sidebar hide at <900px with a slide-in drawer + hamburger toggle. Add a `user_chat_settings` table for JSONB preferences. Add a search endpoint with ILIKE + snippet extraction. All UI added to the existing sidebar and status bar areas.

**Tech Stack:** Flask, PostgreSQL, vanilla JS (createElement + textContent), `--archie-*` CSS tokens, existing `get_db()` + `RealDictCursor` pattern.

---

## Context for All Tasks

**Design spec:** `docs/plans/2026-02-18-phase8-settings-search-mobile-design.md`

**Key files:**
- `platform_v2/templates/tools/archie_chat.html` — 4,608 lines
  - CSS block: lines 5-2761 (insert new CSS before line 2761 `{% endblock %}`)
  - Sidebar CSS `.sidebar`: lines 44-52 (width: 280px, flex column)
  - `@media (max-width: 900px)`: line 2439 (currently `display: none`)
  - `@media (max-width: 600px)`: line 2481
  - Analytics panel HTML: lines 2853-2867
  - Memory panel HTML: lines 2870-2879
  - Sidebar closes: line 2880 (`</aside>`)
  - Status bar `.status-right`: lines 2912-2938
  - Notification bar: lines 2942-2947
  - Solo chat container starts: line 2949
  - Main `<script>` ends: line 4605
  - `showToast()`: line 4598
- `platform_v2/tools/archie_core/routes.py` — 2,490 lines, all imports present (jsonify, request, current_user, RealDictCursor, Response, datetime, os, json, psycopg2)
  - Append new routes after line 2490

**DB connection:** `get_db()` (NOT `get_db_connection()`)
**DOM pattern:** `document.createElement()` + `textContent` (NO innerHTML)
**CSS pattern:** `--archie-*` design tokens with fallbacks
**JS pattern:** `function` keyword, no arrow functions, no template literals

---

### Task 1: Create Migration 112

**Files:**
- Create: `database/migrations/112_user_chat_settings.sql`

**Step 1: Write the migration file**

Create `/mnt/archie_brain/database/migrations/112_user_chat_settings.sql`:

```sql
-- Migration 112: User chat settings
-- Phase 8: Settings, Search & Mobile

CREATE TABLE IF NOT EXISTS user_chat_settings (
    user_id INTEGER PRIMARY KEY,
    settings JSONB DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT NOW()
);

COMMENT ON TABLE user_chat_settings IS 'Per-user chat UI preferences (theme, font size, default mode, etc.)';
```

Note: No FK to `users(id)` to avoid issues if users table structure varies. `user_id` is the PK itself.

**Step 2: Run the migration**

```bash
docker cp database/migrations/112_user_chat_settings.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/112_user_chat_settings.sql
```

**Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "\d user_chat_settings"
```

**Step 4: Commit**

```bash
git add database/migrations/112_user_chat_settings.sql
git commit -m "feat(db): migration 112 — user_chat_settings table for Phase 8"
```

---

### Task 2: Settings API Endpoints

**Files:**
- Modify: `platform_v2/tools/archie_core/routes.py` (append after line 2490)

**Step 1: Verify users table has id column**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT id FROM users LIMIT 1;"
```

**Step 2: Add settings endpoints**

Append after the last route in routes.py:

```python
# ============================================================
# Phase 8: Settings Endpoints
# ============================================================

SETTINGS_DEFAULTS = {
    "theme": "dark",
    "fontSize": "medium",
    "voiceAutoSpeak": True,
    "notifSound": True,
    "defaultMode": "solo",
    "thinkingAutoOpen": False,
    "defaultModel": None,
    "maxMemoryInject": 10,
    "briefingDelivery": "chat",
    "notifPollInterval": 30,
}


@archie_chat_bp.route("/api/settings")
@login_required
def get_settings():
    """Get current user's chat settings (merged with defaults)."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT settings FROM user_chat_settings WHERE user_id = %s",
            (current_user.id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        stored = row["settings"] if row else {}
        merged = dict(SETTINGS_DEFAULTS)
        merged.update(stored)
        return jsonify({"settings": merged})
    except Exception as e:
        logger.error("get_settings error: %s", e)
        return jsonify({"settings": dict(SETTINGS_DEFAULTS)})


@archie_chat_bp.route("/api/settings", methods=["POST"])
@login_required
def update_settings():
    """Update user's chat settings (partial merge)."""
    data = request.get_json() or {}
    updates = data.get("settings", {})
    if not updates:
        return jsonify({"error": "No settings provided"}), 400
    # Only allow known keys
    valid = {k: v for k, v in updates.items() if k in SETTINGS_DEFAULTS}
    if not valid:
        return jsonify({"error": "No valid settings keys"}), 400
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_chat_settings (user_id, settings, updated_at)
            VALUES (%s, %s::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE
            SET settings = user_chat_settings.settings || %s::jsonb,
                updated_at = NOW()
            """,
            (current_user.id, json.dumps(valid), json.dumps(valid)),
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"ok": True, "updated": list(valid.keys())})
    except Exception as e:
        logger.error("update_settings error: %s", e)
        return jsonify({"error": str(e)}), 500
```

**Step 3: Verify**

```bash
docker exec archie_platform python3 -c "from tools.archie_core.routes import archie_chat_bp; print('OK')"
```

**Step 4: Commit**

```bash
git add platform_v2/tools/archie_core/routes.py
git commit -m "feat(chat): settings API endpoints — get and update user preferences"
```

---

### Task 3: Search API Endpoint

**Files:**
- Modify: `platform_v2/tools/archie_core/routes.py` (append after settings endpoints)

**Step 1: Add search endpoint**

```python
# ============================================================
# Phase 8: Conversation Search Endpoint
# ============================================================


@archie_chat_bp.route("/api/conversations/search")
@login_required
def conversation_search():
    """Search across all conversations by keyword."""
    q = request.args.get("q", "").strip()
    if len(q) < 3:
        return jsonify({"results": [], "total": 0})
    range_days = request.args.get("range", 0, type=int)
    limit = min(request.args.get("limit", 20, type=int), 50)
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Build query
        params = [current_user.id, "%" + q + "%", "%" + q + "%"]
        date_filter = ""
        if range_days > 0:
            date_filter = "AND c.created_at > NOW() - make_interval(days => %s)"
            params.append(range_days)
        params.append(limit)
        sql = """
            SELECT DISTINCT ON (c.conversation_id)
                c.conversation_id,
                t.title as thread_title,
                CASE
                    WHEN c.message ILIKE %s THEN 'message'
                    ELSE 'response'
                END as matched_in,
                CASE
                    WHEN c.message ILIKE %s THEN c.message
                    ELSE c.response
                END as matched_text,
                c.created_at,
                c.metadata->>'model' as model
            FROM ai_conversations c
            LEFT JOIN ai_conversation_threads t
                ON t.conversation_id = c.conversation_id
            WHERE c.user_id = %s
            AND (c.message ILIKE %s OR c.response ILIKE %s)
            {date_filter}
            ORDER BY c.conversation_id, c.created_at DESC
            LIMIT %s
        """.format(date_filter=date_filter)
        # Reorder params for query: ILIKE1, ILIKE2, user_id, ILIKE3, ILIKE4, [range], limit
        like_param = "%" + q + "%"
        query_params = [like_param, like_param, current_user.id, like_param, like_param]
        if range_days > 0:
            query_params.append(range_days)
        query_params.append(limit)
        cur.execute(sql, query_params)
        rows = cur.fetchall()
        # Build snippets
        results = []
        q_lower = q.lower()
        for r in rows:
            text = r["matched_text"] or ""
            idx = text.lower().find(q_lower)
            if idx >= 0:
                start = max(0, idx - 30)
                end = min(len(text), idx + len(q) + 30)
                snippet = ("..." if start > 0 else "") + text[start:end] + ("..." if end < len(text) else "")
            else:
                snippet = text[:60] + ("..." if len(text) > 60 else "")
            results.append({
                "conversation_id": r["conversation_id"],
                "thread_title": r["thread_title"] or "Untitled",
                "snippet": snippet,
                "matched_in": r["matched_in"],
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "model": r["model"],
            })
        cur.close()
        conn.close()
        return jsonify({"results": results, "total": len(results)})
    except Exception as e:
        logger.error("conversation_search error: %s", e)
        return jsonify({"results": [], "total": 0, "error": str(e)})
```

**Step 2: Verify**

```bash
docker exec archie_platform python3 -c "from tools.archie_core.routes import archie_chat_bp; print('OK')"
```

**Step 3: Commit**

```bash
git add platform_v2/tools/archie_core/routes.py
git commit -m "feat(chat): conversation search endpoint with snippet extraction"
```

---

### Task 4: Mobile Sidebar Drawer — CSS

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Read lines 2439-2445 (existing @media 900px) and lines 44-52 (.sidebar definition)**

Verify the exact content to edit.

**Step 2: Add drawer CSS**

Insert BEFORE line 2761 (`{% endblock %}` closing the styles block):

```css
/* === Phase 8: Mobile Sidebar Drawer === */
.sidebar-hamburger{display:none;background:none;border:none;color:var(--archie-text,#e2e8f0);font-size:1.4rem;cursor:pointer;padding:4px 8px;line-height:1}
.sidebar-backdrop{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.4);z-index:998}
.sidebar-backdrop.open{display:block}
.sidebar-close{display:none;position:absolute;top:8px;right:8px;background:none;border:none;color:var(--archie-muted,#6b7280);font-size:1.2rem;cursor:pointer;z-index:1000;padding:4px}
.sidebar-close:hover{color:var(--archie-text,#e2e8f0)}
```

**Step 3: Replace the existing @media (max-width: 900px) rule for .sidebar**

Find the existing rule at line 2439:
```css
@media (max-width: 900px) {
    .sidebar {
        display: none;
    }
```

Replace with:
```css
@media (max-width: 900px) {
    .sidebar-hamburger{display:inline-flex;align-items:center}
    .sidebar-close{display:block}
    .sidebar{position:fixed;top:0;left:0;bottom:0;width:280px;z-index:999;transform:translateX(-100%);transition:transform .3s ease;overflow-y:auto}
    .sidebar.drawer-open{transform:translateX(0)}
```

IMPORTANT: Read the actual file first to see the complete @media (max-width: 900px) block — it may contain more rules than just `.sidebar { display: none; }`. Preserve any other rules inside the block.

**Step 4: Verify template parses**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
```

**Step 5: Commit**

```bash
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): mobile sidebar drawer CSS — slide-in overlay at <900px"
```

---

### Task 5: Mobile Sidebar Drawer — HTML + JS

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add hamburger button to status bar**

In `.status-right` (line 2912), insert BEFORE the first existing button (the activity badge at line 2913):

```html
        <button class="sidebar-hamburger" onclick="toggleSidebar()" title="Menu">&#9776;</button>
```

**Step 2: Add close button inside sidebar**

At the very beginning of the sidebar content (right after the opening `<aside class="sidebar">` tag), add:

```html
        <button class="sidebar-close" onclick="toggleSidebar()" title="Close">&times;</button>
```

**Step 3: Add backdrop div**

Insert right before the `<div class="chat-main">` (or right after the sidebar `</aside>` at line 2880):

```html
<div class="sidebar-backdrop" id="sidebar-backdrop" onclick="toggleSidebar()"></div>
```

**Step 4: Add sidebar JS**

Insert before line 4605 (`</script>`):

```javascript
// ============================================================
// Phase 8: Mobile Sidebar Drawer
// ============================================================
function toggleSidebar() {
    var sidebar = document.querySelector('.sidebar');
    var backdrop = document.getElementById('sidebar-backdrop');
    if (!sidebar || !backdrop) return;
    var isOpen = sidebar.classList.contains('drawer-open');
    if (isOpen) {
        sidebar.classList.remove('drawer-open');
        backdrop.classList.remove('open');
    } else {
        sidebar.classList.add('drawer-open');
        backdrop.classList.add('open');
    }
}

// Close sidebar on Escape key
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        var sidebar = document.querySelector('.sidebar');
        if (sidebar && sidebar.classList.contains('drawer-open')) {
            toggleSidebar();
        }
    }
});
```

**Step 5: Verify and commit**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): mobile sidebar drawer — hamburger toggle, backdrop, escape-to-close"
```

---

### Task 6: Settings Panel — CSS + HTML

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add settings CSS**

Insert before `{% endblock %}` (line 2761), after the drawer CSS:

```css
/* === Phase 8: Settings Panel === */
.settings-panel{padding:8px 12px;border-top:1px solid var(--archie-border,#2a3a4a)}
.settings-toggle{display:flex;justify-content:space-between;align-items:center;cursor:pointer;padding:6px 0;font-size:.8rem;font-weight:600;color:var(--archie-accent,#60a5fa)}
.settings-body{display:none;padding-top:8px}
.settings-body.open{display:block}
.set-row{display:flex;justify-content:space-between;align-items:center;padding:4px 0;font-size:.8rem}
.set-row label{color:var(--archie-text,#e2e8f0)}
.set-toggle{position:relative;width:36px;height:20px;cursor:pointer}
.set-toggle input{opacity:0;width:0;height:0}
.set-toggle .slider{position:absolute;top:0;left:0;right:0;bottom:0;background:var(--archie-border,#2a3a4a);border-radius:10px;transition:.3s}
.set-toggle input:checked + .slider{background:var(--archie-accent,#60a5fa)}
.set-toggle .slider::before{content:'';position:absolute;height:16px;width:16px;left:2px;bottom:2px;background:#fff;border-radius:50%;transition:.3s}
.set-toggle input:checked + .slider::before{transform:translateX(16px)}
.set-select{padding:2px 6px;border:1px solid var(--archie-border,#2a3a4a);border-radius:4px;background:var(--archie-card-bg,#0a1628);color:var(--archie-text,#e2e8f0);font-size:.75rem}
.set-more{display:block;text-align:center;margin-top:8px;font-size:.75rem;color:var(--archie-accent,#60a5fa);cursor:pointer;text-decoration:underline;background:none;border:none;width:100%}
/* Settings modal */
.settings-modal-overlay{display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:1100}
.settings-modal-overlay.open{display:flex;align-items:center;justify-content:center}
.settings-modal{background:var(--archie-card-bg,#0a1628);border:1px solid var(--archie-border,#2a3a4a);border-radius:8px;padding:20px;width:90%;max-width:480px;max-height:80vh;overflow-y:auto}
.settings-modal h3{margin:0 0 16px;font-family:'Orbitron',monospace;font-size:.9rem;color:var(--archie-accent,#60a5fa)}
.settings-modal .set-section{margin-bottom:12px}
.settings-modal .set-section-title{font-size:.7rem;color:var(--archie-muted,#6b7280);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}
.settings-modal .set-actions{display:flex;gap:8px;margin-top:16px;justify-content:flex-end}
.settings-modal .set-actions button{padding:6px 14px;border:1px solid var(--archie-border,#2a3a4a);border-radius:4px;background:none;color:var(--archie-text,#e2e8f0);cursor:pointer;font-size:.8rem}
.settings-modal .set-actions button.primary{background:var(--archie-accent,#60a5fa);color:#0a1628;border-color:var(--archie-accent,#60a5fa)}
/* Font size classes */
body.font-small .messages-container{font-size:.82rem}
body.font-large .messages-container{font-size:1.05rem}
```

**Step 2: Add settings HTML in sidebar**

Insert AFTER the memory panel (line 2879, before `</aside>` at line 2880):

```html
<!-- Settings Panel -->
<div class="settings-panel">
    <div class="settings-toggle" onclick="toggleSettings()">
        <span>Settings</span>
        <span id="set-arrow">&#9654;</span>
    </div>
    <div class="settings-body" id="settings-body">
        <div class="set-row">
            <label>Dark Theme</label>
            <label class="set-toggle"><input type="checkbox" id="set-theme" onchange="updateSetting('theme', this.checked ? 'dark' : 'light')"><span class="slider"></span></label>
        </div>
        <div class="set-row">
            <label>Voice Auto-Speak</label>
            <label class="set-toggle"><input type="checkbox" id="set-voice" onchange="updateSetting('voiceAutoSpeak', this.checked)"><span class="slider"></span></label>
        </div>
        <div class="set-row">
            <label>Notification Sound</label>
            <label class="set-toggle"><input type="checkbox" id="set-notif-sound" onchange="updateSetting('notifSound', this.checked)"><span class="slider"></span></label>
        </div>
        <div class="set-row">
            <label>Default Mode</label>
            <select class="set-select" id="set-mode" onchange="updateSetting('defaultMode', this.value)">
                <option value="solo">Solo</option>
                <option value="side-by-side">Side-by-Side</option>
                <option value="collab">Collaborate</option>
            </select>
        </div>
        <button class="set-more" onclick="openSettingsModal()">More Settings...</button>
    </div>
</div>

<!-- Settings Modal -->
<div class="settings-modal-overlay" id="settings-modal-overlay">
    <div class="settings-modal">
        <h3>Chat Settings</h3>
        <div class="set-section">
            <div class="set-section-title">Appearance</div>
            <div class="set-row">
                <label>Font Size</label>
                <select class="set-select" id="set-font" onchange="updateSetting('fontSize', this.value)">
                    <option value="small">Small</option>
                    <option value="medium">Medium</option>
                    <option value="large">Large</option>
                </select>
            </div>
            <div class="set-row">
                <label>Auto-open Thinking Panel</label>
                <label class="set-toggle"><input type="checkbox" id="set-thinking" onchange="updateSetting('thinkingAutoOpen', this.checked)"><span class="slider"></span></label>
            </div>
        </div>
        <div class="set-section">
            <div class="set-section-title">Notifications</div>
            <div class="set-row">
                <label>Briefing Delivery</label>
                <select class="set-select" id="set-briefing" onchange="updateSetting('briefingDelivery', this.value)">
                    <option value="chat">Chat Only</option>
                    <option value="chat+telegram">Chat + Telegram</option>
                </select>
            </div>
            <div class="set-row">
                <label>Poll Interval</label>
                <select class="set-select" id="set-poll" onchange="updateSetting('notifPollInterval', parseInt(this.value))">
                    <option value="15">15 seconds</option>
                    <option value="30">30 seconds</option>
                    <option value="60">60 seconds</option>
                </select>
            </div>
        </div>
        <div class="set-section">
            <div class="set-section-title">Chat</div>
            <div class="set-row">
                <label>Max Memories Injected</label>
                <select class="set-select" id="set-memory-inject" onchange="updateSetting('maxMemoryInject', parseInt(this.value))">
                    <option value="5">5</option>
                    <option value="10">10</option>
                    <option value="15">15</option>
                    <option value="20">20</option>
                </select>
            </div>
        </div>
        <div class="set-actions">
            <button onclick="closeSettingsModal()">Close</button>
        </div>
    </div>
</div>
```

**Step 3: Verify and commit**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): settings panel CSS + HTML — quick toggles and modal"
```

---

### Task 7: Settings Panel — JavaScript

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add settings JS functions**

Insert before line 4605 (`</script>`), after the sidebar drawer JS:

```javascript
// ============================================================
// Phase 8: Settings Panel
// ============================================================
var _chatSettings = {};

function toggleSettings() {
    var body = document.getElementById('settings-body');
    var arrow = document.getElementById('set-arrow');
    if (!body) return;
    if (body.classList.contains('open')) {
        body.classList.remove('open');
        arrow.textContent = '\u25B6';
    } else {
        body.classList.add('open');
        arrow.textContent = '\u25BC';
    }
}

function openSettingsModal() {
    var overlay = document.getElementById('settings-modal-overlay');
    if (overlay) overlay.classList.add('open');
}

function closeSettingsModal() {
    var overlay = document.getElementById('settings-modal-overlay');
    if (overlay) overlay.classList.remove('open');
}

function loadSettings() {
    fetch('/tools/archie-chat/api/settings')
        .then(function(r) { return r.json(); })
        .then(function(d) {
            _chatSettings = d.settings || {};
            applySettings(_chatSettings);
        }).catch(function() {});
}

function applySettings(s) {
    // Theme
    var themeCheck = document.getElementById('set-theme');
    if (themeCheck) themeCheck.checked = (s.theme !== 'light');
    // Voice auto-speak
    var voiceCheck = document.getElementById('set-voice');
    if (voiceCheck) voiceCheck.checked = (s.voiceAutoSpeak !== false);
    // Notification sound
    var notifCheck = document.getElementById('set-notif-sound');
    if (notifCheck) notifCheck.checked = (s.notifSound !== false);
    // Default mode
    var modeSelect = document.getElementById('set-mode');
    if (modeSelect && s.defaultMode) modeSelect.value = s.defaultMode;
    // Font size
    var fontSelect = document.getElementById('set-font');
    if (fontSelect && s.fontSize) fontSelect.value = s.fontSize;
    document.body.classList.remove('font-small', 'font-large');
    if (s.fontSize === 'small') document.body.classList.add('font-small');
    if (s.fontSize === 'large') document.body.classList.add('font-large');
    // Thinking auto-open
    var thinkCheck = document.getElementById('set-thinking');
    if (thinkCheck) thinkCheck.checked = !!s.thinkingAutoOpen;
    // Briefing delivery
    var briefSelect = document.getElementById('set-briefing');
    if (briefSelect && s.briefingDelivery) briefSelect.value = s.briefingDelivery;
    // Poll interval
    var pollSelect = document.getElementById('set-poll');
    if (pollSelect && s.notifPollInterval) pollSelect.value = String(s.notifPollInterval);
    // Max memory inject
    var memSelect = document.getElementById('set-memory-inject');
    if (memSelect && s.maxMemoryInject) memSelect.value = String(s.maxMemoryInject);
}

function updateSetting(key, value) {
    _chatSettings[key] = value;
    // Apply immediately
    if (key === 'fontSize') {
        document.body.classList.remove('font-small', 'font-large');
        if (value === 'small') document.body.classList.add('font-small');
        if (value === 'large') document.body.classList.add('font-large');
    }
    if (key === 'theme') {
        // Trigger existing theme toggle if available
        if (typeof toggleTheme === 'function') toggleTheme();
    }
    // Persist to server
    var payload = {};
    payload[key] = value;
    fetch('/tools/archie-chat/api/settings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({settings: payload})
    }).catch(function() {});
}

// Load settings on page init
loadSettings();

// Close settings modal on Escape
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeSettingsModal();
    }
});

// Close settings modal on backdrop click
document.getElementById('settings-modal-overlay').addEventListener('click', function(e) {
    if (e.target === this) closeSettingsModal();
});
```

NOTE: The Escape key handler for the settings modal can be combined with the sidebar one — but keeping them separate is fine (both check specific conditions).

**Step 2: Verify and commit**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): settings JS — load, apply, update, modal toggle"
```

---

### Task 8: Search Panel — CSS + HTML

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add search CSS**

Insert before `{% endblock %}` in the styles block:

```css
/* === Phase 8: Conversation Search === */
.search-panel{padding:8px 12px;border-top:1px solid var(--archie-border,#2a3a4a)}
.search-input-wrap{position:relative}
.search-input{width:100%;padding:6px 8px 6px 28px;border:1px solid var(--archie-border,#2a3a4a);border-radius:4px;background:var(--archie-card-bg,#0a1628);color:var(--archie-text,#e2e8f0);font-size:.8rem}
.search-input:focus{border-color:var(--archie-accent,#60a5fa);outline:none}
.search-icon{position:absolute;left:8px;top:50%;transform:translateY(-50%);font-size:.75rem;color:var(--archie-muted,#6b7280)}
.search-clear{position:absolute;right:6px;top:50%;transform:translateY(-50%);background:none;border:none;color:var(--archie-muted,#6b7280);cursor:pointer;font-size:.8rem;display:none;padding:2px}
.search-clear.visible{display:block}
.search-filters{display:flex;gap:4px;margin-top:6px;flex-wrap:wrap}
.search-chip{padding:2px 8px;border:1px solid var(--archie-border,#2a3a4a);border-radius:12px;font-size:.65rem;cursor:pointer;background:none;color:var(--archie-muted,#6b7280)}
.search-chip.active{border-color:var(--archie-accent,#60a5fa);color:var(--archie-accent,#60a5fa)}
.search-results{margin-top:8px;max-height:300px;overflow-y:auto}
.search-result{padding:6px 8px;border:1px solid var(--archie-border,#2a3a4a);border-radius:4px;margin-bottom:4px;cursor:pointer;font-size:.8rem}
.search-result:hover{border-color:var(--archie-accent,#60a5fa)}
.search-result .sr-title{font-weight:600;color:var(--archie-text,#e2e8f0);font-size:.75rem}
.search-result .sr-snippet{color:var(--archie-muted,#6b7280);font-size:.72rem;margin-top:2px}
.search-result .sr-snippet mark{background:rgba(96,165,250,0.2);color:var(--archie-accent,#60a5fa);padding:0 2px;border-radius:2px}
.search-result .sr-meta{font-size:.65rem;color:var(--archie-muted,#6b7280);margin-top:2px}
.search-empty{text-align:center;padding:12px;color:var(--archie-muted,#6b7280);font-size:.8rem}
```

**Step 2: Add search HTML in sidebar**

Insert BEFORE the analytics panel (line 2853), since search should be near the top of the sidebar:

```html
<!-- Search Panel -->
<div class="search-panel">
    <div class="search-input-wrap">
        <span class="search-icon">&#128269;</span>
        <input class="search-input" id="conv-search" placeholder="Search conversations..." oninput="onSearchInput(this.value)">
        <button class="search-clear" id="search-clear" onclick="clearSearch()">&#10005;</button>
    </div>
    <div class="search-filters" id="search-filters">
        <button class="search-chip active" data-range="0" onclick="setSearchRange(this, 0)">All Time</button>
        <button class="search-chip" data-range="7" onclick="setSearchRange(this, 7)">This Week</button>
        <button class="search-chip" data-range="30" onclick="setSearchRange(this, 30)">This Month</button>
    </div>
    <div class="search-results" id="search-results"></div>
</div>
```

**Step 3: Verify and commit**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): search panel CSS + HTML — input, filters, results container"
```

---

### Task 9: Search Panel — JavaScript

**Files:**
- Modify: `platform_v2/templates/tools/archie_chat.html`

**Step 1: Add search JS**

Insert before `</script>` (line 4605), after settings JS:

```javascript
// ============================================================
// Phase 8: Conversation Search
// ============================================================
var _searchTimeout = null;
var _searchRange = 0;

function onSearchInput(value) {
    var clearBtn = document.getElementById('search-clear');
    if (clearBtn) {
        if (value.length > 0) {
            clearBtn.classList.add('visible');
        } else {
            clearBtn.classList.remove('visible');
            clearSearchResults();
        }
    }
    if (value.length < 3) {
        clearSearchResults();
        return;
    }
    if (_searchTimeout) clearTimeout(_searchTimeout);
    _searchTimeout = setTimeout(function() {
        searchConversations(value);
    }, 300);
}

function searchConversations(query) {
    var url = '/tools/archie-chat/api/conversations/search?q=' + encodeURIComponent(query) + '&limit=20';
    if (_searchRange > 0) url += '&range=' + _searchRange;
    fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(d) {
            renderSearchResults(d.results || [], query);
        }).catch(function() {
            renderSearchResults([], query);
        });
}

function renderSearchResults(results, query) {
    var container = document.getElementById('search-results');
    if (!container) return;
    container.textContent = '';
    if (results.length === 0) {
        var empty = document.createElement('div');
        empty.className = 'search-empty';
        empty.textContent = 'No conversations match your search.';
        container.appendChild(empty);
        return;
    }
    results.forEach(function(r) {
        var item = document.createElement('div');
        item.className = 'search-result';
        item.onclick = function() { loadSearchResult(r.conversation_id); };

        var title = document.createElement('div');
        title.className = 'sr-title';
        title.textContent = r.thread_title || 'Untitled';

        var snippet = document.createElement('div');
        snippet.className = 'sr-snippet';
        // Highlight the query in the snippet
        var snippetText = r.snippet || '';
        var lowerSnippet = snippetText.toLowerCase();
        var lowerQuery = query.toLowerCase();
        var idx = lowerSnippet.indexOf(lowerQuery);
        if (idx >= 0) {
            var before = document.createTextNode(snippetText.substring(0, idx));
            var match = document.createElement('mark');
            match.textContent = snippetText.substring(idx, idx + query.length);
            var after = document.createTextNode(snippetText.substring(idx + query.length));
            snippet.appendChild(before);
            snippet.appendChild(match);
            snippet.appendChild(after);
        } else {
            snippet.textContent = snippetText;
        }

        var meta = document.createElement('div');
        meta.className = 'sr-meta';
        var metaParts = [];
        if (r.matched_in) metaParts.push('in ' + r.matched_in);
        if (r.model) metaParts.push(r.model);
        if (r.created_at) {
            var d = new Date(r.created_at);
            metaParts.push(d.toLocaleDateString());
        }
        meta.textContent = metaParts.join(' \u00B7 ');

        item.appendChild(title);
        item.appendChild(snippet);
        item.appendChild(meta);
        container.appendChild(item);
    });
}

function loadSearchResult(conversationId) {
    // Try to use existing conversation loading function
    if (typeof loadConversation === 'function') {
        loadConversation(conversationId);
    } else if (typeof switchToConversation === 'function') {
        switchToConversation(conversationId);
    } else {
        // Fallback: reload page with conversation ID
        window.location.hash = conversationId;
        window.location.reload();
    }
    clearSearch();
    // Close mobile drawer if open
    var sidebar = document.querySelector('.sidebar');
    if (sidebar && sidebar.classList.contains('drawer-open')) {
        toggleSidebar();
    }
}

function setSearchRange(chipEl, range) {
    _searchRange = range;
    var chips = document.querySelectorAll('.search-chip');
    for (var i = 0; i < chips.length; i++) {
        chips[i].classList.remove('active');
    }
    chipEl.classList.add('active');
    // Re-run search if there's a query
    var input = document.getElementById('conv-search');
    if (input && input.value.length >= 3) {
        searchConversations(input.value);
    }
}

function clearSearch() {
    var input = document.getElementById('conv-search');
    if (input) input.value = '';
    var clearBtn = document.getElementById('search-clear');
    if (clearBtn) clearBtn.classList.remove('visible');
    clearSearchResults();
}

function clearSearchResults() {
    var container = document.getElementById('search-results');
    if (container) container.textContent = '';
}
```

**Step 2: Check for existing conversation loading function**

Read the file to see what function loads a conversation when clicked in the sidebar. Search for `loadConversation`, `switchToConversation`, `selectConversation`, or similar. The `loadSearchResult` function above tries several names as fallback.

**Step 3: Verify and commit**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('OK')
"
git add platform_v2/templates/tools/archie_chat.html
git commit -m "feat(chat): conversation search JS — debounced input, snippet highlighting, filter chips"
```

---

### Task 10: Deploy and Verify

**Step 1: Restart the platform**

```bash
docker compose restart archie_platform
```

Wait 15 seconds, check logs:
```bash
sleep 15 && docker logs --tail 30 archie_platform
```

**Step 2: Verify migration**

```bash
docker exec archie_database psql -U archie -d archie -c "\d user_chat_settings"
```

**Step 3: Verify routes**

```bash
docker exec archie_platform python3 -c "from tools.archie_core.routes import archie_chat_bp; print('Routes OK')"
```

**Step 4: Verify template**

```bash
docker exec archie_platform python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('/app/templates'))
t = env.get_template('tools/archie_chat.html')
print('Template OK')
"
```

**Step 5: Test settings API**

```bash
docker exec archie_platform python3 -c "
import requests
# This tests the endpoint exists (will 302 to login without auth)
r = requests.get('http://localhost:3000/tools/archie-chat/api/settings', allow_redirects=False)
print('Settings endpoint:', r.status_code)
"
```

**Step 6: Push**

```bash
git push origin main
```

**Step 7: Update Dev HQ**

Use MCP tools to:
1. `store_memory` — Phase 8 deployed with all commits
2. `log_decision` — Settings, Search & Mobile architecture choices
3. Update the master roadmap tracker

---

## Important Notes

- **Black pre-commit hook**: Will reformat Python files. If commit fails, re-stage and commit again.
- **`archie_core/routes.py` uses `get_db()`** (NOT `get_db_connection()` from bridge routes).
- **DOM construction**: All UI uses `document.createElement()` + `textContent`. NO innerHTML.
- **CSS tokens**: All colors use `--archie-*` variables with fallbacks.
- **The `@media (max-width: 900px)` block at line 2439**: Read the full block before modifying — it may contain rules beyond just `.sidebar { display: none }`.
- **Settings modal**: Uses overlay with click-outside-to-close pattern (same as summary modal from Phase 7).
- **Search debounce**: 300ms timeout prevents excessive API calls.
- **archie_chat.html is 4,608 lines**: Each task adds ~50-120 lines. After Phase 8, expect ~5,100 lines.

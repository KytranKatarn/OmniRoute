# Directory Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the employee directory as a professional corporate team page with org chart, AI portraits, live agent chat, and @kytranempowerment.com emails.

**Architecture:** Single Blueprint module at `tools/directory/` with public (`/directory`) and internal (`/tools/directory`) views. Chat dispatches through Bridge to loaded agent models with persistent per-user conversation memory (sliding window + pinned memories). Portraits generated via ComfyUI SDXL.

**Tech Stack:** Flask Blueprint, PostgreSQL, Bridge Dispatcher, Starbase Roster (`get_crew_manifest()`), ComfyUI SDXL, Hostinger Email, Jinja2, vanilla JS

**Spec:** `docs/superpowers/specs/2026-03-20-directory-redesign-design.md`
**Project:** Dev HQ #167 | **Decision:** ADR #236

---

## File Structure

```
platform_v2/tools/directory/
  __init__.py              — Blueprint registration, register_*_routes()
  routes.py                — Public routes: /directory, /api/directory, /api/directory/:id, /api/directory/org-chart
  chat_routes.py           — Auth routes: /api/directory/status, POST /api/directory/chat, GET /api/directory/chat/:agent_id
  helpers.py               — Name derivation, email generation, status mapping, rate limiter

platform_v2/templates/tools/directory/
  directory.html           — Main template (public + internal conditional)

platform_v2/static/css/
  directory.css            — Complete rewrite (existing 401 lines)

platform_v2/static/js/
  directory.js             — Complete rewrite (existing 125 lines)

platform_v2/static/portraits/
  [agent_id].webp          — AI-generated headshots (created by Task 8)

database/migrations/
  NNN_directory_chat.sql   — New tables + agents columns

ai_bridge/
  agent_loop.py            — Add job #47 (conversation memory extraction)
```

**Files modified (not created):**
- `platform_v2/app.py` — Remove directory routes (lines 817-950)
- `platform_v2/module_registry.py` — Add directory module entry
- `platform_v2/rbac.py` — Already has DIRECTORY_VIEW (no change needed)

**Files removed:**
- `platform_v2/templates/business/directory.html` (887 lines — replaced by new template)
- `platform_v2/templates/directory.html` (71 lines — replaced by new template)

---

## Task 1: Database Migration — Chat Tables + Agent Columns
**Dev HQ:** #1160 | **Effort:** Small

**Files:**
- Create: `database/migrations/170_directory_chat.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Migration: 170_directory_chat.sql
-- Directory chat system tables + agent email/hierarchy columns

BEGIN;

-- Agent email addresses
ALTER TABLE agents ADD COLUMN IF NOT EXISTS email VARCHAR(255);

-- Org chart hierarchy
ALTER TABLE agents ADD COLUMN IF NOT EXISTS reports_to_agent_id INTEGER REFERENCES agents(id);

-- Populate emails from display_name
UPDATE agents SET email = LOWER(
  CASE
    WHEN display_name LIKE '% %' THEN
      REPLACE(LOWER(display_name), ' ', '.') || '@kytranempowerment.com'
    ELSE
      LOWER(COALESCE(display_name, name)) || '@kytranempowerment.com'
  END
) WHERE email IS NULL OR email = '';

-- Conversation threads (one per agent-user pair)
CREATE TABLE IF NOT EXISTS directory_conversations (
  id SERIAL PRIMARY KEY,
  agent_id INTEGER NOT NULL REFERENCES agents(id),
  user_id INTEGER NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  message_count INTEGER DEFAULT 0,
  last_message_at TIMESTAMPTZ,
  UNIQUE(agent_id, user_id)
);

-- Individual messages
CREATE TABLE IF NOT EXISTS directory_messages (
  id SERIAL PRIMARY KEY,
  conversation_id INTEGER NOT NULL REFERENCES directory_conversations(id) ON DELETE CASCADE,
  sender_type VARCHAR(10) NOT NULL CHECK (sender_type IN ('user', 'agent')),
  message TEXT NOT NULL,
  timestamp TIMESTAMPTZ DEFAULT NOW(),
  is_pinned BOOLEAN DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_directory_messages_conversation
  ON directory_messages(conversation_id, timestamp DESC);

-- Agent memories about users (summaries + pinned facts)
CREATE TABLE IF NOT EXISTS directory_agent_memories (
  id SERIAL PRIMARY KEY,
  agent_id INTEGER NOT NULL REFERENCES agents(id),
  user_id INTEGER NOT NULL,
  memory_type VARCHAR(20) NOT NULL CHECK (memory_type IN ('summary', 'pinned')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_directory_agent_memories_lookup
  ON directory_agent_memories(agent_id, user_id, memory_type);

COMMIT;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec -it archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/170_directory_chat.sql
```

First copy the file into the container:
```bash
docker cp database/migrations/170_directory_chat.sql archie_database:/docker-entrypoint-initdb.d/migrations/
docker exec -it archie_database psql -U archie -d archie -f /docker-entrypoint-initdb.d/migrations/170_directory_chat.sql
```

Expected: `ALTER TABLE`, `UPDATE 50`, `CREATE TABLE` x3, `CREATE INDEX` x2

- [ ] **Step 3: Verify migration**

```bash
docker exec archie_database psql -U archie -d archie -c "\d directory_conversations"
docker exec archie_database psql -U archie -d archie -c "\d directory_messages"
docker exec archie_database psql -U archie -d archie -c "\d directory_agent_memories"
docker exec archie_database psql -U archie -d archie -c "SELECT display_name, email FROM agents WHERE status='active' LIMIT 10;"
```

Expected: All 3 tables exist, email column populated for all active agents.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/170_directory_chat.sql
git commit -m "feat(directory): add chat tables + agent email/hierarchy columns"
```

---

## Task 2: Extract Directory Blueprint from app.py
**Dev HQ:** #1161 | **Effort:** Medium

**Files:**
- Create: `platform_v2/tools/directory/__init__.py`
- Create: `platform_v2/tools/directory/routes.py`
- Create: `platform_v2/tools/directory/helpers.py`
- Modify: `platform_v2/app.py:817-950` (remove directory routes)
- Modify: `platform_v2/module_registry.py` (add directory entry)

- [ ] **Step 1: Create the directory module folder**

```bash
mkdir -p platform_v2/tools/directory
```

- [ ] **Step 2: Create helpers.py with shared utilities**

`platform_v2/tools/directory/helpers.py`:
```python
"""Directory module helpers — name derivation, email generation, status mapping."""

import time


def derive_full_name(agent):
    """Get display name with fallback chain."""
    if agent.get('first_name') and agent.get('last_name'):
        return f"{agent['first_name']} {agent['last_name']}"
    return agent.get('display_name') or agent.get('name') or 'Unknown'


def derive_email(agent):
    """Get or generate email address."""
    if agent.get('email'):
        return agent['email']
    name = agent.get('display_name') or agent.get('name') or 'agent'
    if ' ' in name:
        return name.lower().replace(' ', '.') + '@kytranempowerment.com'
    return name.lower() + '@kytranempowerment.com'


def map_agent_status(crew_member):
    """Map Starbase roster state to directory status.

    Returns dict with 'status', 'is_online', 'chat_available'.
    """
    if not crew_member:
        return {'status': 'Off Duty', 'is_online': False, 'chat_available': False}

    shift_state = crew_member.get('shift_state', '')
    model_loaded = crew_member.get('model_loaded', False)

    if shift_state == 'active' and model_loaded:
        return {'status': 'Online', 'is_online': True, 'chat_available': True}

    return {'status': 'Off Duty', 'is_online': False, 'chat_available': False}


class RateLimiter:
    """Simple in-memory rate limiter for chat endpoints."""

    def __init__(self, per_user_limit=10, global_limit=50, window=60):
        self.per_user_limit = per_user_limit
        self.global_limit = global_limit
        self.window = window
        self.user_counts = {}  # user_id -> (count, window_start)
        self.global_count = 0
        self.global_window_start = time.time()

    def check(self, user_id):
        """Check if request is allowed. Returns (allowed, error_message)."""
        now = time.time()

        # Reset global window
        if now - self.global_window_start > self.window:
            self.global_count = 0
            self.global_window_start = now

        # Reset user window
        user_data = self.user_counts.get(user_id, (0, now))
        if now - user_data[1] > self.window:
            user_data = (0, now)

        if self.global_count >= self.global_limit:
            return False, "Chat system is busy. Please wait a moment."

        if user_data[0] >= self.per_user_limit:
            return False, "Please wait before sending another message."

        self.global_count += 1
        self.user_counts[user_id] = (user_data[0] + 1, user_data[1])
        return True, None


# Singleton rate limiter
chat_rate_limiter = RateLimiter()
```

- [ ] **Step 3: Create routes.py with public endpoints**

`platform_v2/tools/directory/routes.py`:

Read the existing directory routes from `app.py` (lines 817-950) and move them here. Follow the **starbase pattern**: define `bp` at module level, decorate routes directly on `bp`. No wrapper function for the main routes file.

```python
"""Directory public routes — employee list, profiles, org chart."""

from flask import Blueprint, render_template, request, jsonify, session
from database import get_db_cursor
from .helpers import derive_full_name, derive_email

bp = Blueprint(
    'directory_bp', __name__,
    template_folder='templates',
    url_prefix=''
)


@bp.route('/directory')
def directory_page():
    """Public team directory page."""
    authenticated = 'user_id' in session
    return render_template('tools/directory/directory.html',
                           authenticated=authenticated)


@bp.route('/tools/directory')
def directory_page_internal():
    """Internal team directory (login required, handled by rbac)."""
    return render_template('tools/directory/directory.html',
                           authenticated=True)

    @bp.route('/api/directory')
    def get_employees():
        """List all active employees with optional filters."""
        search = request.args.get('search', '').strip()
        department = request.args.get('department', '').strip()
        employee_type = request.args.get('type', '').strip()

        with get_db_cursor() as (conn, cur):
            query = """
                SELECT id, name, first_name, last_name, display_name,
                       email, phone, title, department, pronouns, bio,
                       avatar_url, worker_type, capabilities, tier,
                       reports_to_agent_id
                FROM agents WHERE status = 'active'
            """
            params = []
            conditions = []

            if search:
                conditions.append("""
                    (LOWER(COALESCE(first_name,'')) || ' ' || LOWER(COALESCE(last_name,''))
                     || ' ' || LOWER(COALESCE(display_name,''))
                     || ' ' || LOWER(COALESCE(title,''))
                     || ' ' || LOWER(COALESCE(department,''))) LIKE %s
                """)
                params.append(f'%{search.lower()}%')

            if department:
                conditions.append("LOWER(department) = %s")
                params.append(department.lower())

            if employee_type:
                if employee_type == 'ai':
                    conditions.append("worker_type IN ('internal', 'contract')")
                else:
                    conditions.append("worker_type NOT IN ('internal', 'contract')")

            if conditions:
                query += ' AND ' + ' AND '.join(conditions)

            query += ' ORDER BY department, display_name'
            cur.execute(query, params)
            rows = cur.fetchall()

        members = []
        by_department = {}
        for row in rows:
            agent = dict(row)
            member = {
                'id': agent['id'],
                'full_name': derive_full_name(agent),
                'first_name': agent.get('first_name') or '',
                'last_name': agent.get('last_name') or '',
                'email': derive_email(agent),
                'phone': agent.get('phone') or '1-877-463-3352',
                'extension': f"x{1000 + agent['id']}",
                'title': agent.get('title') or '',
                'department': agent.get('department') or 'General',
                'pronouns': agent.get('pronouns') or '',
                'bio': agent.get('bio') or '',
                'avatar_url': agent.get('avatar_url') or '',
                'employee_type': 'ai' if agent.get('worker_type') in ('internal', 'contract') else 'human',
                'specialties': [],
                'tools': [],
            }
            # Parse capabilities JSONB
            caps = agent.get('capabilities')
            if caps:
                if isinstance(caps, str):
                    import json
                    try:
                        caps = json.loads(caps)
                    except (json.JSONDecodeError, TypeError):
                        caps = {}
                member['specialties'] = caps.get('specialties', [])[:5]
                member['tools'] = caps.get('tools', [])[:5]

            members.append(member)
            dept = member['department']
            if dept not in by_department:
                by_department[dept] = []
            by_department[dept].append(member)

        departments = sorted(by_department.keys())
        return jsonify({
            'members': members,
            'by_department': by_department,
            'departments': departments,
            'statistics': {
                'total': len(members),
                'departments': len(departments),
                'ai_count': sum(1 for m in members if m['employee_type'] == 'ai'),
                'human_count': sum(1 for m in members if m['employee_type'] == 'human'),
            }
        })

    @bp.route('/api/directory/<int:employee_id>')
    def get_employee(employee_id):
        """Get single employee profile."""
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT id, name, first_name, last_name, display_name,
                       email, phone, title, department, pronouns, bio,
                       avatar_url, worker_type, capabilities, tier,
                       reports_to_agent_id
                FROM agents WHERE id = %s AND status = 'active'
            """, (employee_id,))
            row = cur.fetchone()

        if not row:
            return jsonify({'error': 'Employee not found'}), 404

        agent = dict(row)
        caps = agent.get('capabilities') or {}
        if isinstance(caps, str):
            import json
            try:
                caps = json.loads(caps)
            except (json.JSONDecodeError, TypeError):
                caps = {}

        # Check for portrait
        portrait_url = agent.get('avatar_url') or ''
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT canonical_image_path FROM agent_portraits
                WHERE agent_id = %s AND approved = true
            """, (employee_id,))
            portrait_row = cur.fetchone()
            if portrait_row and portrait_row['canonical_image_path']:
                portrait_url = portrait_row['canonical_image_path']

        return jsonify({
            'id': agent['id'],
            'full_name': derive_full_name(agent),
            'first_name': agent.get('first_name') or '',
            'last_name': agent.get('last_name') or '',
            'email': derive_email(agent),
            'phone': agent.get('phone') or '1-877-463-3352',
            'extension': f"x{1000 + agent['id']}",
            'title': agent.get('title') or '',
            'department': agent.get('department') or 'General',
            'pronouns': agent.get('pronouns') or '',
            'bio': agent.get('bio') or '',
            'avatar_url': portrait_url,
            'employee_type': 'ai' if agent.get('worker_type') in ('internal', 'contract') else 'human',
            'specialties': caps.get('specialties', []),
            'tools': caps.get('tools', []),
            'reports_to_agent_id': agent.get('reports_to_agent_id'),
        })

    @bp.route('/api/directory/org-chart')
    def get_org_chart():
        """Return org chart hierarchy data."""
        with get_db_cursor() as (conn, cur):
            cur.execute("""
                SELECT a.id, a.display_name, a.title, a.department,
                       a.avatar_url, a.reports_to_agent_id, a.worker_type,
                       sa.station_code
                FROM agents a
                LEFT JOIN station_assignments sa ON sa.agent_id = a.id AND sa.is_active = true
                WHERE a.status = 'active'
                ORDER BY a.reports_to_agent_id NULLS FIRST, a.display_name
            """)
            rows = cur.fetchall()

        nodes = []
        for row in rows:
            agent = dict(row)
            nodes.append({
                'id': agent['id'],
                'name': agent.get('display_name') or agent.get('name'),
                'title': agent.get('title') or '',
                'department': agent.get('department') or '',
                'station': agent.get('station_code') or '',
                'avatar_url': agent.get('avatar_url') or '',
                'reports_to': agent.get('reports_to_agent_id'),
                'employee_type': 'ai' if agent.get('worker_type') in ('internal', 'contract') else 'human',
            })

        return jsonify({'nodes': nodes})
```

- [ ] **Step 4: Create __init__.py with Blueprint registration**

Follow the **starbase pattern exactly**: import bp from routes.py, call register functions from sub-route files, export bp. The app dynamically loads this via module_registry.

`platform_v2/tools/directory/__init__.py`:
```python
"""
A.R.C.H.I.E. EMPLOYEE DIRECTORY Module
=======================================
Corporate team page with org chart, profiles, and live agent chat.
"""

from .routes import bp as directory_bp
from flask_login import login_required  # noqa: F401
from rbac import require_permission, Permission

admin_required = require_permission(Permission.ADMIN_ACCESS)

# Chat routes registered in Task 5/6 — uncomment when ready:
# from .chat_routes import register_chat_routes
# register_chat_routes(directory_bp, admin_required)

__all__ = ["directory_bp"]
```

**IMPORTANT:** The Blueprint is defined in `routes.py` and re-exported from `__init__.py`. The app's module loader imports `directory_bp` from this package.

- [ ] **Step 5: Remove directory routes from app.py**

Read `platform_v2/app.py` lines 815-955. Remove the three route functions:
- `@app.route("/directory")`
- `@app.route("/api/directory")`
- `@app.route("/api/directory/<int:employee_id>")`

Do NOT add any manual import/register code — the module registry handles Blueprint loading automatically.

- [ ] **Step 6: Add to module_registry.py and rbac.py**

**module_registry.py** — Add directory module entry. Check existing entries for the exact pattern (look at starbase's entry for reference) and add:
```python
'directory': {
    'name': 'Employee Directory',
    'description': 'Corporate team directory with profiles and live chat',
    'category': 'ADMIN_OPS',
    'icon': 'fa-address-book',
    'route': '/tools/directory',
    'permission': 'directory:view',
    'blueprint_import': 'tools.directory:directory_bp',
},
```

**rbac.py** — Add the DIRECTORY_VIEW permission. Find the Permission class and add:
```python
DIRECTORY_VIEW = "directory:view"
```

Then add it to the PUBLIC role's permissions list (so the public /directory route works without auth). Find the role definitions and add `Permission.DIRECTORY_VIEW` to the PUBLIC role.

The `/tools/directory` internal route should require `login_required` — add this decorator to `directory_page_internal()` in routes.py.

- [ ] **Step 7: Test the Blueprint extraction**

```bash
docker compose restart archie_platform
# Wait 10s for startup
curl -s http://192.168.1.200:3000/directory | head -5
curl -s http://192.168.1.200:3000/api/directory | python3 -m json.tool | head -20
curl -s http://192.168.1.200:3000/api/directory/1 | python3 -m json.tool | head -20
curl -s http://192.168.1.200:3000/api/directory/org-chart | python3 -m json.tool | head -20
```

Expected: All 4 endpoints return data. No 500 errors.

- [ ] **Step 8: Commit**

```bash
git add platform_v2/tools/directory/ platform_v2/app.py platform_v2/module_registry.py
git commit -m "refactor(directory): extract Blueprint module from app.py per ADR-045"
```

---

## Task 3: Directory UI — Hero, Org Chart, Search, Card Grid
**Dev HQ:** #1162 | **Effort:** Large

**Files:**
- Create: `platform_v2/tools/directory/templates/directory.html`
- Rewrite: `platform_v2/static/css/directory.css`
- Rewrite: `platform_v2/static/js/directory.js`

**Reference:** Visual mockups in `.superpowers/brainstorm/3706600-1774012174/`

- [ ] **Step 1: Create directory.html template**

The template must:
- Extend `base.html` for internal view, standalone for public
- Use Jinja2 `{% if authenticated %}` to gate internal features
- Sections: hero (Kytran Empowerment branding + stats), org chart, search/filters, department card grid
- Portrait area on cards: 200px height, branded gradient background
- Department sections with station color accent bars
- Responsive: 3-col desktop, 2-col tablet, 1-col mobile
- Font stack: Orbitron (titles), IBM Plex Mono (code), system sans-serif (body)
- Color palette: navy (#0a1628), teal (#00e5ff), purple (#8b5cf6), station colors for departments

Build this as a complete HTML template following the mockup at `design-section2-ui-flow.html`. Key HTML structure:

```html
<!-- Hero -->
<section class="dir-hero">...</section>

<!-- Org Chart -->
<section class="dir-org-chart">...</section>

<!-- Search + Filters -->
<section class="dir-filters">...</section>

<!-- Department Grid (populated by JS) -->
<section class="dir-departments" id="directoryGrid">...</section>

<!-- Profile Slide-out Panel (hidden by default) -->
<aside class="dir-profile-panel" id="profilePanel">...</aside>

<!-- Chat Panel (hidden, internal only) -->
{% if authenticated %}
<aside class="dir-chat-panel" id="chatPanel">...</aside>
{% endif %}
```

- [ ] **Step 2: Rewrite directory.css**

Complete rewrite of `platform_v2/static/css/directory.css`. Must include:
- `.dir-hero` — gradient background, stats row, Kytran branding
- `.dir-org-chart` — flex layout for hierarchy levels, connector lines via CSS
- `.dir-org-node` — card style for each org chart node with station color border
- `.dir-filters` — search bar, dropdown selects, flex row
- `.dir-card` — employee card (portrait area, info section, status footer)
- `.dir-card.offline` — 65% opacity
- `.dir-status-dot` — green glow (online) or gray (offline)
- `.dir-profile-panel` — slide-out from right, 420px width, z-index overlay
- `.dir-chat-panel` — 360px width, flex column, slide-out adjacent to profile
- `.dir-chat-bubble-agent` / `.dir-chat-bubble-user` — message styles
- `.dir-memory-banner` — purple-tinted banner for pinned memories
- Responsive breakpoints: 360px, 730px, 1024px
- Station colors for department accent bars (use CSS custom properties)

- [ ] **Step 3: Rewrite directory.js**

Complete rewrite of `platform_v2/static/js/directory.js`. Must include:
- `loadDirectory()` — fetch `/api/directory`, render department groups
- `loadOrgChart()` — fetch `/api/directory/org-chart`, render hierarchy
- `renderDepartment(name, members)` — create department section with cards
- `renderCard(member)` — create single employee card HTML
- `openProfile(employeeId)` — fetch `/api/directory/{id}`, populate and show slide-out panel
- `closeProfile()` — hide panel
- Search filtering (client-side filter on already-loaded data)
- Department dropdown filter
- Status filter (All / Online / Off Duty) — requires `/api/directory/status` from Task 5

For now, status indicators can be static placeholders (no green dots yet — that comes in Task 5).

- [ ] **Step 4: Remove old templates**

Delete:
- `platform_v2/templates/business/directory.html` (887 lines)
- `platform_v2/templates/directory.html` (71 lines)

- [ ] **Step 5: Test in browser**

```bash
docker compose restart archie_platform
```

Open `http://192.168.1.200:3000/directory` — verify:
- Hero section renders with stats
- Org chart shows hierarchy
- Employee cards render in grid grouped by department
- Search filters work
- Clicking a card opens profile panel
- Responsive at 360/730/1024px widths

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/directory/templates/ platform_v2/static/css/directory.css platform_v2/static/js/directory.js
git rm platform_v2/templates/business/directory.html platform_v2/templates/directory.html
git commit -m "feat(directory): corporate team page — hero, org chart, card grid, profile panel"
```

---

## Task 4: Profile Slide-Out Panel
**Dev HQ:** #1163 | **Effort:** Medium

**Files:**
- Modify: `platform_v2/static/js/directory.js` (add profile panel logic)
- Modify: `platform_v2/static/css/directory.css` (add profile panel styles)
- Modify: `platform_v2/tools/directory/templates/directory.html` (profile panel HTML)

**Reference:** Visual mockup `design-section3-profile-chat.html`

- [ ] **Step 1: Add profile panel HTML to template**

Inside `directory.html`, the `#profilePanel` aside needs:
- Close button (X)
- Portrait container (180px, rounded square, status badge overlay)
- Name + title + station role
- Status badge (Online/Off Duty)
- Contact card section (email, phone+ext, department)
- About section (full bio)
- Expertise tags (colored pills)
- "Currently Working On" section (internal only, `{% if authenticated %}`)
- "Message [Name]" button (internal only, shown only if online)

- [ ] **Step 2: Add profile panel JS**

In `directory.js`, implement:
- `openProfile(employeeId)` — fetch `/api/directory/{id}`, populate all fields, show panel with slide animation
- `closeProfile()` — hide panel, clear content
- ESC key listener to close
- Backdrop click to close
- Portrait URL: use `avatar_url` from API (portrait or DiceBear fallback)

- [ ] **Step 3: Add profile panel CSS**

In `directory.css`, add:
- Slide-in animation (transform: translateX)
- Backdrop overlay (dark semi-transparent)
- Section styling (contact card, about, expertise)
- Status badge styles (green/gray)
- "Message" button glow effect

- [ ] **Step 4: Test profile panel**

Open `http://192.168.1.200:3000/directory`, click an employee card:
- Panel slides in from right
- Portrait, name, title, contact info all populated
- ESC and backdrop click close the panel
- "Message" button visible when logged in

- [ ] **Step 5: Commit**

```bash
git add platform_v2/static/js/directory.js platform_v2/static/css/directory.css platform_v2/tools/directory/templates/directory.html
git commit -m "feat(directory): profile slide-out panel with contact, bio, expertise"
```

---

## Task 5: Live Status API — Bridge Roster Integration
**Dev HQ:** #1164 | **Effort:** Small

**Files:**
- Create: `platform_v2/tools/directory/chat_routes.py` (start with status endpoint only)
- Modify: `platform_v2/tools/directory/__init__.py` (register chat routes)
- Modify: `platform_v2/static/js/directory.js` (fetch and display status)

- [ ] **Step 1: Create chat_routes.py with status endpoint**

`platform_v2/tools/directory/chat_routes.py`:
```python
"""Directory chat routes — auth-required endpoints for status and messaging."""

from flask import jsonify, request, session
from functools import wraps
import sys
import os

# Add ai_bridge to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'ai_bridge'))


def login_required_api(f):
    """Decorator for API endpoints requiring auth."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated


def register_chat_routes(bp, admin_required):
    """Register auth-gated directory chat routes."""

    @bp.route('/api/directory/status')
    @login_required_api
    def get_agent_status():
        """Get live roster status for all agents."""
        try:
            from bridge_dispatcher import get_crew_manifest
            manifest = get_crew_manifest()
        except Exception:
            manifest = []

        status_map = {}
        for member in manifest:
            agent_id = member.get('agent_id') or member.get('id')
            if agent_id:
                model_loaded = member.get('model_loaded', False)
                shift_state = member.get('shift_state', 'off_duty')
                is_online = shift_state == 'active' and model_loaded
                status_map[agent_id] = {
                    'is_online': is_online,
                    'status': 'Online' if is_online else 'Off Duty',
                    'chat_available': is_online,
                    'shift_state': shift_state,
                }

        return jsonify({'status': status_map})
```

- [ ] **Step 2: Update __init__.py to register chat routes**

Uncomment the chat routes registration in `__init__.py`:
```python
from .chat_routes import register_chat_routes
register_chat_routes(directory_bp, admin_required)
```

- [ ] **Step 3: Add status polling to directory.js**

Add to `directory.js`:
```javascript
async function loadAgentStatus() {
    try {
        const resp = await fetch('/api/directory/status');
        if (!resp.ok) return; // Not logged in or error — skip silently
        const data = await resp.json();
        window.agentStatus = data.status || {};
        updateStatusIndicators();
    } catch (e) {
        // Status is enhancement — don't break page
    }
}

function updateStatusIndicators() {
    document.querySelectorAll('.dir-card').forEach(card => {
        const agentId = card.dataset.agentId;
        const status = window.agentStatus[agentId];
        const dot = card.querySelector('.dir-status-dot');
        const statusText = card.querySelector('.dir-status-text');
        const chatBtn = card.querySelector('.dir-chat-btn');

        if (status && status.is_online) {
            dot?.classList.add('online');
            dot?.classList.remove('offline');
            if (statusText) statusText.textContent = 'Online';
            if (chatBtn) chatBtn.style.display = '';
            card.classList.remove('offline');
        } else {
            dot?.classList.add('offline');
            dot?.classList.remove('online');
            if (statusText) statusText.textContent = 'Off Duty';
            if (chatBtn) chatBtn.style.display = 'none';
            card.classList.add('offline');
        }
    });
}
```

Call `loadAgentStatus()` after `loadDirectory()` completes. Poll every 30 seconds:
```javascript
setInterval(loadAgentStatus, 30000);
```

- [ ] **Step 4: Test status indicators**

```bash
docker compose restart archie_platform
```

Log in to `http://192.168.1.200:3000/tools/directory`:
- Online agents show green dots with glow
- Offline agents show gray dots, cards dimmed
- Chat button only visible on online agents
- Public `/directory` (not logged in) shows no status dots

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/directory/chat_routes.py platform_v2/tools/directory/__init__.py platform_v2/static/js/directory.js
git commit -m "feat(directory): live agent status from Bridge roster"
```

---

## Task 6: Chat System — Slide-Out Panel + Bridge Dispatch
**Dev HQ:** #1165 | **Effort:** Large

**Files:**
- Modify: `platform_v2/tools/directory/chat_routes.py` (add chat endpoints)
- Modify: `platform_v2/static/js/directory.js` (chat UI logic)
- Modify: `platform_v2/static/css/directory.css` (chat panel styles)
- Modify: `platform_v2/tools/directory/templates/directory.html` (chat panel HTML)

- [ ] **Step 1: Add chat endpoints to chat_routes.py**

Add to `chat_routes.py` inside `register_chat_routes()`:

```python
    @bp.route('/api/directory/chat', methods=['POST'])
    @login_required_api
    def send_chat_message():
        """Send a message to an agent via Bridge dispatch."""
        from .helpers import chat_rate_limiter
        from database import get_db_cursor

        user_id = session['user_id']
        data = request.get_json()
        agent_id = data.get('agent_id')
        message = data.get('message', '').strip()

        if not agent_id or not message:
            return jsonify({'error': 'agent_id and message required'}), 400

        if len(message) > 2000:
            return jsonify({'error': 'Message too long (max 2000 chars)'}), 400

        # Rate limiting
        allowed, error_msg = chat_rate_limiter.check(user_id)
        if not allowed:
            return jsonify({'error': error_msg}), 429

        # Check agent is online
        try:
            from bridge_dispatcher import get_crew_manifest
            manifest = get_crew_manifest()
            agent_online = False
            for member in manifest:
                mid = member.get('agent_id') or member.get('id')
                if mid == agent_id:
                    if member.get('shift_state') == 'active' and member.get('model_loaded'):
                        agent_online = True
                    break
        except Exception:
            agent_online = False

        if not agent_online:
            return jsonify({
                'error': 'agent_offline',
                'message': 'This team member is currently off duty. Please try again when they are online.'
            }), 503

        with get_db_cursor(commit=True) as (conn, cur):
            # Get or create conversation
            cur.execute("""
                INSERT INTO directory_conversations (agent_id, user_id)
                VALUES (%s, %s)
                ON CONFLICT (agent_id, user_id) DO UPDATE SET updated_at = NOW()
                RETURNING id
            """, (agent_id, user_id))
            conv_id = cur.fetchone()['id']

            # Store user message
            cur.execute("""
                INSERT INTO directory_messages (conversation_id, sender_type, message)
                VALUES (%s, 'user', %s) RETURNING id, timestamp
            """, (conv_id, message))
            user_msg = cur.fetchone()

            # Load context for dispatch
            # Last 10 messages
            cur.execute("""
                SELECT sender_type, message, timestamp
                FROM directory_messages
                WHERE conversation_id = %s
                ORDER BY timestamp DESC LIMIT 10
            """, (conv_id,))
            recent_msgs = list(reversed(cur.fetchall()))

            # Pinned memories
            cur.execute("""
                SELECT content FROM directory_agent_memories
                WHERE agent_id = %s AND user_id = %s AND memory_type = 'pinned'
                ORDER BY created_at DESC
            """, (agent_id, user_id))
            pinned = [r['content'] for r in cur.fetchall()]

            # Conversation summaries
            cur.execute("""
                SELECT content FROM directory_agent_memories
                WHERE agent_id = %s AND user_id = %s AND memory_type = 'summary'
                ORDER BY created_at DESC LIMIT 5
            """, (agent_id, user_id))
            summaries = [r['content'] for r in cur.fetchall()]

            # Get agent info
            cur.execute("""
                SELECT display_name, name, title, bio, capabilities, department
                FROM agents WHERE id = %s
            """, (agent_id,))
            agent = dict(cur.fetchone())

        # Build system prompt
        agent_name = agent.get('display_name') or agent.get('name')
        system_prompt = f"You are {agent_name}, {agent.get('title', '')} at Kytran Empowerment. {agent.get('bio', '')}\n"
        system_prompt += f"Department: {agent.get('department', '')}\n"

        if pinned:
            system_prompt += "\n## What you remember about this user:\n"
            for p in pinned:
                system_prompt += f"- {p}\n"

        if summaries:
            system_prompt += "\n## Previous conversation summaries:\n"
            for s in summaries:
                system_prompt += f"- {s}\n"

        # Build conversation context
        conv_text = "\n## Current conversation:\n"
        for msg in recent_msgs:
            role = "User" if msg['sender_type'] == 'user' else agent_name
            conv_text += f"{role}: {msg['message']}\n"

        # Dispatch to Bridge
        try:
            from bridge_dispatcher import get_dispatcher
            dispatcher = get_dispatcher()
            result = dispatcher.dispatch(
                prompt=conv_text + f"\n{agent_name}:",
                system_prompt=system_prompt,
                agent_name=agent.get('name'),
                user_id=user_id,
            )
            agent_response = result.get('response', 'I apologize, I had trouble processing that. Could you try again?')
        except Exception as e:
            agent_response = "I'm having a moment — could you try again in a few seconds?"

        # Store agent response
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                INSERT INTO directory_messages (conversation_id, sender_type, message)
                VALUES (%s, 'agent', %s) RETURNING id, timestamp
            """, (conv_id, agent_response))
            agent_msg = cur.fetchone()

            # Update conversation counters
            cur.execute("""
                UPDATE directory_conversations
                SET message_count = message_count + 2,
                    last_message_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s
            """, (conv_id,))

        return jsonify({
            'response': agent_response,
            'timestamp': agent_msg['timestamp'].isoformat(),
            'conversation_id': conv_id,
        })

    @bp.route('/api/directory/chat/<int:agent_id>')
    @login_required_api
    def get_chat_history(agent_id):
        """Get conversation history with an agent."""
        user_id = session['user_id']
        offset = request.args.get('offset', 0, type=int)
        limit = request.args.get('limit', 50, type=int)

        with get_db_cursor() as (conn, cur):
            # Get conversation
            cur.execute("""
                SELECT id, message_count, last_message_at
                FROM directory_conversations
                WHERE agent_id = %s AND user_id = %s
            """, (agent_id, user_id))
            conv = cur.fetchone()

            if not conv:
                return jsonify({'messages': [], 'has_more': False, 'pinned_memories': []})

            # Get messages
            cur.execute("""
                SELECT sender_type, message, timestamp, is_pinned
                FROM directory_messages
                WHERE conversation_id = %s
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s
            """, (conv['id'], limit, offset))
            messages = list(reversed([dict(r) for r in cur.fetchall()]))

            # Serialize timestamps
            for m in messages:
                if m.get('timestamp'):
                    m['timestamp'] = m['timestamp'].isoformat()

            # Get pinned memories for banner
            cur.execute("""
                SELECT content FROM directory_agent_memories
                WHERE agent_id = %s AND user_id = %s AND memory_type = 'pinned'
                ORDER BY created_at DESC LIMIT 3
            """, (agent_id, user_id))
            pinned = [r['content'] for r in cur.fetchall()]

        return jsonify({
            'messages': messages,
            'has_more': len(messages) == limit,
            'total': conv['message_count'],
            'last_message_at': conv['last_message_at'].isoformat() if conv['last_message_at'] else None,
            'pinned_memories': pinned,
        })
```

- [ ] **Step 2: Add chat UI JavaScript**

Add to `directory.js`:
- `openChat(agentId)` — fetch history, show chat panel, render messages
- `sendMessage()` — POST to `/api/directory/chat`, append response
- `renderMessage(msg)` — create bubble HTML (agent left, user right)
- `renderMemoryBanner(memories)` — purple banner with pinned memories
- `showTypingIndicator()` / `hideTypingIndicator()`
- `loadMoreHistory()` — pagination when scrolling up

- [ ] **Step 3: Add chat panel CSS**

Add to `directory.css`:
- `.dir-chat-panel` — slide-in, flex column
- `.dir-chat-header` — agent avatar + name + active status
- `.dir-memory-banner` — purple tint, pinned memories
- `.dir-chat-messages` — scrollable area
- `.dir-chat-bubble-agent` / `.dir-chat-bubble-user` — Teams-style bubbles
- `.dir-typing-indicator` — animated dots
- `.dir-chat-input` — text field + send button

- [ ] **Step 4: Test chat end-to-end**

Log in, find an online agent, click "Message":
- Chat panel slides in next to profile
- History loads if exists
- Memory banner shows pinned memories
- Send a message — typing indicator shows, agent responds
- Messages persist on page reload
- Offline agent returns 503 error gracefully

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/directory/chat_routes.py platform_v2/static/js/directory.js platform_v2/static/css/directory.css platform_v2/tools/directory/templates/directory.html
git commit -m "feat(directory): Teams-style chat with Bridge dispatch + conversation history"
```

---

## Task 7: Chat Memory — Async Summarization + Pinned Memories
**Dev HQ:** #1166 | **Effort:** Medium

**Files:**
- Modify: `ai_bridge/agent_loop.py` (add job #47)

- [ ] **Step 1: Read agent_loop.py to find job registration pattern**

Look for the APScheduler job registration pattern — likely `scheduler.add_job()` calls. Find the highest existing job number to confirm #47 is available.

- [ ] **Step 2: Add job #47 — conversation memory extraction**

Add to `agent_loop.py` following the existing job pattern:

```python
from psycopg2.extras import RealDictCursor  # Add to imports at top of agent_loop.py if not already present

def _process_chat_memories():
    """Job #47: Extract conversation summaries and pinned memories from idle chats."""
    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)  # Must use RealDictCursor for dict access

        # Find conversations idle for 5+ minutes with unsummarized messages
        cur.execute("""
            SELECT dc.id, dc.agent_id, dc.user_id, dc.last_message_at
            FROM directory_conversations dc
            WHERE dc.last_message_at IS NOT NULL
              AND dc.last_message_at < NOW() - INTERVAL '5 minutes'
              AND dc.last_message_at > COALESCE(
                (SELECT MAX(created_at) FROM directory_agent_memories
                 WHERE agent_id = dc.agent_id AND user_id = dc.user_id
                   AND memory_type = 'summary'),
                '1970-01-01'
              )
        """)
        idle_convos = cur.fetchall()

        for convo in idle_convos:
            try:
                _summarize_conversation(cur, conn, convo)
            except Exception as e:
                logging.error(f"Chat memory extraction failed for conv {convo['id']}: {e}")

        conn.close()
    except Exception as e:
        logging.error(f"Job #47 chat memories error: {e}")


def _summarize_conversation(cur, conn, convo):
    """Summarize a single conversation and extract pinned memories."""
    # Get messages since last summary
    cur.execute("""
        SELECT sender_type, message, timestamp
        FROM directory_messages
        WHERE conversation_id = %s
        ORDER BY timestamp ASC
    """, (convo['id'],))
    messages = cur.fetchall()

    if len(messages) < 2:
        return  # Not enough to summarize

    # Get agent info
    cur.execute("SELECT name, display_name, title FROM agents WHERE id = %s", (convo['agent_id'],))
    agent = cur.fetchone()
    agent_name = agent.get('display_name') or agent.get('name')

    # Build conversation text
    conv_text = ""
    for msg in messages:
        role = "User" if msg['sender_type'] == 'user' else agent_name
        conv_text += f"{role}: {msg['message']}\n"

    # Dispatch summarization
    from bridge_dispatcher import get_dispatcher
    dispatcher = get_dispatcher()

    # Summary
    summary_result = dispatcher.dispatch(
        prompt=f"Summarize this conversation in 2-3 sentences:\n\n{conv_text}",
        system_prompt="You are a helpful assistant. Provide a concise summary.",
        agent_name=agent.get('name'),
    )
    summary = summary_result.get('response', '').strip()

    if summary:
        cur.execute("""
            INSERT INTO directory_agent_memories (agent_id, user_id, memory_type, content)
            VALUES (%s, %s, 'summary', %s)
        """, (convo['agent_id'], convo['user_id'], summary))

    # Pinned memories
    pinned_result = dispatcher.dispatch(
        prompt=f"What important facts should you remember about this user from this conversation? List each fact on its own line. Only include facts worth remembering for future conversations.\n\n{conv_text}",
        system_prompt="You are a helpful assistant. Extract key facts about the user.",
        agent_name=agent.get('name'),
    )
    pinned_text = pinned_result.get('response', '').strip()

    if pinned_text:
        for line in pinned_text.split('\n'):
            line = line.strip().lstrip('•-* ')
            if line and len(line) > 10:
                cur.execute("""
                    INSERT INTO directory_agent_memories (agent_id, user_id, memory_type, content)
                    VALUES (%s, %s, 'pinned', %s)
                """, (convo['agent_id'], convo['user_id'], line))

    conn.commit()
```

Register the job with the scheduler (follow existing pattern):
```python
scheduler.add_job(
    _process_chat_memories,
    'interval',
    minutes=2,
    id='job_47_chat_memories',
    name='Chat memory extraction',
)
```

- [ ] **Step 3: Test memory extraction**

1. Have a chat conversation with an agent (at least 3 messages)
2. Wait 5+ minutes
3. Check the database:
```bash
docker exec archie_database psql -U archie -d archie -c "SELECT * FROM directory_agent_memories ORDER BY created_at DESC LIMIT 10;"
```

Expected: Summary and pinned memory records created.

4. Open chat with same agent again — verify memory banner shows pinned memories.

- [ ] **Step 4: Commit**

```bash
git add ai_bridge/agent_loop.py
git commit -m "feat(directory): agent loop job #47 — chat memory extraction"
```

---

## Task 8: Portrait Generation — ComfyUI SDXL Branded Headshots
**Dev HQ:** #1167 | **Effort:** Large

**Files:**
- Create: `platform_v2/static/portraits/` (directory)
- Modify: `agent_portraits` table (populate via ComfyUI)

This task is semi-manual — involves running ComfyUI workflows to generate portraits for all agents.

- [ ] **Step 1: Create portraits directory**

```bash
mkdir -p platform_v2/static/portraits
```

- [ ] **Step 2: Build the portrait generation prompt template**

For each agent, construct a ComfyUI prompt following the brand style guide:

```
Professional corporate headshot portrait of [description based on name/title].
Studio lighting with soft rim light. Dark navy to teal gradient background.
Professional attire with subtle [station_color] accent.
Head and shoulders framing, centered composition.
Photorealistic, high detail, sharp focus.
8k quality, professional photography.
```

Negative prompt:
```
cartoon, anime, illustration, painting, blurry, low quality,
deformed, disfigured, extra limbs, bad anatomy, watermark, text
```

- [ ] **Step 3: Generate portraits for key agents first**

Start with leadership (ARCHIE, Vigil) and department heads. Generate 3-5 variants each at 1024x1024 using SDXL checkpoint. Review and pick best.

Use the existing ComfyUI API or Starbase portrait benchmarking infrastructure if available.

- [ ] **Step 4: Store approved portraits**

For each approved portrait:
1. Save as `/static/portraits/{agent_id}.webp` (convert to WebP for web optimization)
2. Update `agent_portraits` table:
```sql
INSERT INTO agent_portraits (agent_id, canonical_image_path, identity_prompt, face_seed, model_used, approved)
VALUES (?, '/static/portraits/{agent_id}.webp', '{prompt}', {seed}, 'sdxl', true)
ON CONFLICT (agent_id) DO UPDATE SET
  canonical_image_path = EXCLUDED.canonical_image_path,
  identity_prompt = EXCLUDED.identity_prompt,
  face_seed = EXCLUDED.face_seed,
  approved = true,
  updated_at = NOW();
```

- [ ] **Step 5: Generate remaining agent portraits**

Continue for all 50 agents. This can be batched using fan-out dispatch if Task #1152 is complete.

- [ ] **Step 6: Verify all portraits load in directory**

```bash
docker compose restart archie_platform
```

Open `/directory` — verify all agents show photorealistic portraits instead of DiceBear fallbacks.

- [ ] **Step 7: Commit portrait metadata**

```bash
git add platform_v2/static/portraits/
git commit -m "feat(directory): AI-generated branded portraits for all agents"
```

---

## Task 9: Hostinger Email Setup
**Dev HQ:** #1168 | **Effort:** Medium

This task is infrastructure/manual — involves Hostinger admin panel and DNS configuration.

- [ ] **Step 1: Check current Hostinger email plan**

Log into Hostinger panel. Verify the email plan supports enough mailboxes (need 50+). Business Email plan supports 100.

- [ ] **Step 2: Configure DNS records**

In Hostinger DNS management for kytranempowerment.com:
- MX records pointing to Hostinger mail servers
- SPF record: `v=spf1 include:_spf.hostinger.com ~all`
- DKIM: Enable in Hostinger email settings, add TXT record
- DMARC: `v=DMARC1; p=quarantine; rua=mailto:dmarc@kytranempowerment.com`

- [ ] **Step 3: Create agent mailboxes**

Create mailboxes for each agent using the naming convention from the DB:
```bash
docker exec archie_database psql -U archie -d archie -c "SELECT display_name, email FROM agents WHERE status='active' ORDER BY display_name;"
```

Create each mailbox in Hostinger with a generated password. Store credentials securely.

- [ ] **Step 4: Set up catch-all forwarding**

Configure catch-all to forward unmatched addresses to `contactus@kytranempowerment.com`.

- [ ] **Step 5: Test email delivery**

Send test emails to 2-3 agent addresses. Verify:
- Email arrives in Hostinger webmail
- SPF/DKIM/DMARC pass (check headers)
- Catch-all works for nonexistent addresses

- [ ] **Step 6: Document setup**

```bash
# Log to Dev HQ
mcp store_memory "Hostinger email setup complete for @kytranempowerment.com. 50 agent mailboxes created. MX/SPF/DKIM/DMARC configured. Catch-all forwards to contactus@."
```

---

## Task 10: End-to-End Testing
**Dev HQ:** #1169 | **Effort:** Medium

- [ ] **Step 1: Test public directory (no auth)**

Open `http://192.168.1.200:3000/directory` in incognito:
- [ ] Hero section renders with correct stats
- [ ] Org chart shows Kytran → ARCHIE + Vigil → department heads
- [ ] Employee cards render in grid grouped by department
- [ ] Search filters work (name, department)
- [ ] Clicking card opens profile panel
- [ ] No status dots or chat buttons visible
- [ ] All portraits load (or DiceBear fallback)
- [ ] @kytranempowerment.com emails shown on profiles
- [ ] Responsive at 360px, 730px, 1024px

- [ ] **Step 2: Test internal directory (logged in)**

Log in and open `http://192.168.1.200:3000/tools/directory`:
- [ ] Same page as public but with status indicators
- [ ] Online agents show green dots with glow
- [ ] Offline agents show gray dots, cards dimmed
- [ ] "Chat" button visible on online agents only
- [ ] "Currently Working On" section visible in profile panel

- [ ] **Step 3: Test chat system**

- [ ] Click "Message" on online agent — chat panel slides in
- [ ] Memory banner shows pinned memories (if any)
- [ ] Send a message — typing indicator, then response
- [ ] Response is contextual to agent's role/personality
- [ ] Close and reopen chat — history preserved
- [ ] Send to offline agent — 503 error handled gracefully

- [ ] **Step 4: Test rate limiting**

- [ ] Send 11 messages rapidly — 11th should be rejected with 429
- [ ] Wait 60 seconds — rate limit resets

- [ ] **Step 5: Test conversation memory**

- [ ] Have a 5+ message conversation
- [ ] Wait 5 minutes for job #47 to run
- [ ] Check `directory_agent_memories` table for summary + pinned entries
- [ ] Reopen chat — memory banner shows new pinned memories
- [ ] Agent references previous conversation context

- [ ] **Step 6: Final commit + Dev HQ update**

```bash
git push origin main
mcp complete_task 1160 --notes "Migration applied, 3 tables + 2 columns"
mcp complete_task 1161 --notes "Blueprint extracted, routes verified"
mcp complete_task 1162 --notes "Full UI rewrite with org chart"
mcp complete_task 1163 --notes "Profile panel with 180px portraits"
mcp complete_task 1164 --notes "Live status from Bridge roster"
mcp complete_task 1165 --notes "Chat system with Bridge dispatch"
mcp complete_task 1166 --notes "Job #47 memory extraction working"
mcp complete_task 1167 --notes "50 AI portraits generated"
mcp complete_task 1168 --notes "Hostinger email configured"
mcp complete_task 1169 --notes "All flows tested end-to-end"
mcp update_project_status 167 --status completed
```

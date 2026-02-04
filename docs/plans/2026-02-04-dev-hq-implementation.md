# Dev HQ Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build Dev HQ as a header-level admin page replacing Mission Control, unifying project tracking, knowledge, DB schema, API docs, and MCP/Claude integrations into one always-accessible view.

**Architecture:** Standalone Flask Blueprint at `/dev-hq` (not in module registry). Accessed via compass icon in all nav bar includes. Admin-only, Hub-only. 6-tab horizontal layout. Full CRUD for projects/tasks. Reuses Blueprint's DB schema and API docs helper functions. New Integrations tab shows MCP tools, Claude config, and CLAUDE.md content.

**Tech Stack:** Flask Blueprint, Jinja2, vanilla JS (fetch API), existing ARCHIE CSS variables (`theme.css`, `admin-ops.css`), Lucide icons, Orbitron + IBM Plex Mono fonts, PostgreSQL via `database.py`.

**Design doc:** `docs/plans/2026-02-04-dev-hq-design.md`

---

## Task 1: Create Dev HQ Flask Blueprint (skeleton)

**Files:**
- Create: `platform_v2/tools/dev_hq/__init__.py`
- Create: `platform_v2/tools/dev_hq/routes.py`
- Modify: `platform_v2/app.py` (lines ~964-984, add import + register)

**Step 1: Create the blueprint package**

Create `platform_v2/tools/dev_hq/__init__.py`:
```python
"""
A.R.C.H.I.E. Dev HQ - Unified Development Command Center
Admin-only, Hub-only development headquarters.
"""

from flask import Blueprint

dev_hq_bp = Blueprint('dev_hq', __name__, url_prefix='/dev-hq')

from . import routes  # noqa: E402, F401
```

**Step 2: Create minimal routes file**

Create `platform_v2/tools/dev_hq/routes.py`:
```python
"""Dev HQ Routes - Admin Only, Hub Only"""

import os
from flask import render_template, jsonify, abort
from flask_login import login_required, current_user
from . import dev_hq_bp


def admin_hub_only(f):
    """Decorator: require admin role + hub deployment mode."""
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            abort(403)
        if os.getenv("DEPLOYMENT_MODE", "hub") == "business_node":
            abort(404)
        return f(*args, **kwargs)

    return decorated


@dev_hq_bp.route("/")
@login_required
@admin_hub_only
def index():
    """Dev HQ main page."""
    return render_template("dev_hq.html")
```

**Step 3: Register blueprint in app.py**

In `platform_v2/app.py`, after line ~984 (`app.register_blueprint(api_docs_bp)`), add:

```python
# Dev HQ - Unified Development Command Center (not a module - header-level admin tool)
from tools.dev_hq import dev_hq_bp  # noqa: E402

app.register_blueprint(dev_hq_bp)
```

**Step 4: Create minimal template**

Create `platform_v2/templates/dev_hq.html`:
```html
{% extends "base.html" %}

{% block title %}Dev HQ - A.R.C.H.I.E.{% endblock %}

{% block module_name %}dev-hq{% endblock %}

{% block content %}
<div style="padding: 40px; text-align: center; color: var(--archie-text-primary, #c9d1d9); font-family: 'Orbitron', sans-serif;">
    <h1>DEV HQ</h1>
    <p style="font-family: 'IBM Plex Mono', monospace;">Skeleton loaded successfully.</p>
</div>
{% endblock %}
```

**Step 5: Verify**

```bash
docker compose restart archie_platform && sleep 5
docker exec archie_platform curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/dev-hq
```
Expected: `302` (redirect to login) — confirms route is registered.

**Step 6: Commit**

```bash
git add platform_v2/tools/dev_hq/__init__.py platform_v2/tools/dev_hq/routes.py platform_v2/app.py platform_v2/templates/dev_hq.html
git commit -m "feat(dev-hq): create skeleton Flask blueprint with admin-only route"
```

---

## Task 2: Add compass icon to all navigation bars

**Files:**
- Modify: `platform_v2/templates/includes/admin_ops_nav.html` (lines 44-51 — replace Blueprint link with Dev HQ)
- Modify: `platform_v2/templates/includes/admin_tools_nav.html`
- Modify: `platform_v2/templates/includes/creation_tools_nav.html`
- Modify: `platform_v2/templates/includes/business_tools_nav.html`
- Modify: `platform_v2/templates/includes/dev_tools_nav.html`
- Modify: `platform_v2/templates/includes/standalone_apps_nav.html`

**Step 1: Replace Blueprint link in admin_ops_nav.html**

In `admin_ops_nav.html`, find lines 44-51 (the Blueprint nav button after `nav-divider`):

```html
        <div class="nav-divider"></div>
        <a href="{{ url_for('blueprint.index') }}"
           class="nav-module-btn {% if request.endpoint and 'blueprint' in request.endpoint %}active{% endif %}"
           onclick="showTransition(event, this.href)"
           title="A.R.C.H.I.E. Blueprint">
            <i data-lucide="drafting-compass"></i>
            <span>Blueprint</span>
        </a>
```

Replace with:

```html
        <div class="nav-divider"></div>
        {% if current_user.is_authenticated and current_user.is_admin %}
        <a href="{{ url_for('dev_hq.index') }}"
           class="nav-module-btn {% if request.endpoint and 'dev_hq' in request.endpoint %}active{% endif %}"
           onclick="showTransition(event, this.href)"
           title="Dev HQ">
            <i data-lucide="compass"></i>
        </a>
        {% endif %}
```

Note: icon-only (no `<span>` text) — just the compass icon as agreed in design.

**Step 2: Add Dev HQ icon to all other nav includes**

For each of the 5 other nav files (`admin_tools_nav.html`, `creation_tools_nav.html`, `business_tools_nav.html`, `dev_tools_nav.html`, `standalone_apps_nav.html`), find the `nav-right` section's theme controls area and add the Dev HQ icon **before** the `nav-divider` that precedes the module links:

```html
        {% if current_user.is_authenticated and current_user.is_admin %}
        <a href="{{ url_for('dev_hq.index') }}"
           class="nav-module-btn {% if request.endpoint and 'dev_hq' in request.endpoint %}active{% endif %}"
           onclick="showTransition(event, this.href)"
           title="Dev HQ">
            <i data-lucide="compass"></i>
        </a>
        {% endif %}
```

Insert this right after the theme controls `</div>` and before `<div class="nav-divider"></div>` in each file. The compass icon should appear in the nav-right area on every page.

**Step 3: Verify**

```bash
docker compose restart archie_platform
```
Load any module page at http://192.168.1.200:3000 — confirm compass icon appears in nav bar, clicking it navigates to `/dev-hq` skeleton page.

**Step 4: Commit**

```bash
git add platform_v2/templates/includes/
git commit -m "feat(dev-hq): add compass icon to all navigation bars, replace Blueprint link"
```

---

## Task 3: Build the Dev HQ template (6-tab layout + Overview tab)

**Files:**
- Modify: `platform_v2/templates/dev_hq.html` (replace skeleton)

**Step 1: Build the full template with tab structure**

Replace the skeleton `dev_hq.html` with the full template. This task creates the page layout, tab navigation, and the Overview tab content. Other tabs will be added in subsequent tasks.

The template must include:
- `{% extends "base.html" %}` and `{% block content %}`
- Include `admin_ops_nav.html` (same as other admin modules)
- Page header: "DEV HQ" in Orbitron, version badge (v5.24.0), stat chips
- 6 horizontal tabs with Lucide icons: Overview, Projects & Tasks, Knowledge, DB Schema, API Docs, Integrations
- Tab switching via vanilla JS (hide/show divs, no page reload)
- CSS using existing ARCHIE variables from theme.css
- Overview tab content: 4 stat cards, recent activity feed, active project health grid

**CSS approach:**
- `.dev-hq` container: full-height, max-width 1400px, centered
- `.dev-hq-header`: Orbitron title, stat chips row
- `.dev-hq-tabs`: horizontal tab bar with underline-active pattern
- `.dev-hq-tab-btn`: each tab button with icon + label
- `.dev-hq-panel`: tab content panels (display none/block)
- `.dev-hq-stats-row`: 4-column grid of stat cards
- `.dev-hq-activity-feed`: scrollable timeline
- `.dev-hq-project-grid`: card grid for active projects
- Light mode overrides via `body.light-mode .dev-hq-*`
- Responsive: tabs scroll horizontally on mobile (overflow-x auto)

**Tab HTML structure:**
```html
<div class="dev-hq-tabs">
    <button class="dev-hq-tab-btn active" data-tab="overview">
        <i data-lucide="layout-dashboard"></i> Overview
    </button>
    <button class="dev-hq-tab-btn" data-tab="projects">
        <i data-lucide="folder-kanban"></i> Projects & Tasks
    </button>
    <button class="dev-hq-tab-btn" data-tab="knowledge">
        <i data-lucide="book-open"></i> Knowledge
    </button>
    <button class="dev-hq-tab-btn" data-tab="schema">
        <i data-lucide="database"></i> DB Schema
    </button>
    <button class="dev-hq-tab-btn" data-tab="api-docs">
        <i data-lucide="file-code-2"></i> API Docs
    </button>
    <button class="dev-hq-tab-btn" data-tab="integrations">
        <i data-lucide="plug"></i> Integrations
    </button>
</div>

<div class="dev-hq-panel active" id="panel-overview">...</div>
<div class="dev-hq-panel" id="panel-projects">...</div>
<div class="dev-hq-panel" id="panel-knowledge">...</div>
<div class="dev-hq-panel" id="panel-schema">...</div>
<div class="dev-hq-panel" id="panel-api-docs">...</div>
<div class="dev-hq-panel" id="panel-integrations">...</div>
```

**Tab switching JS:**
```javascript
document.querySelectorAll('.dev-hq-tab-btn').forEach(function(btn) {
    btn.addEventListener('click', function() {
        var tab = this.getAttribute('data-tab');
        document.querySelectorAll('.dev-hq-tab-btn').forEach(function(b) { b.classList.remove('active'); });
        document.querySelectorAll('.dev-hq-panel').forEach(function(p) { p.classList.remove('active'); });
        this.classList.add('active');
        document.getElementById('panel-' + tab).classList.add('active');
        // Load tab data on first switch
        loadTabData(tab);
    });
});
```

**Overview tab JS — fetch stats and activity:**
```javascript
function loadOverview() {
    fetch('/dev-hq/api/overview', { credentials: 'same-origin' })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            // Populate stat cards (active projects, open tasks, completed this week, overdue)
            // Populate activity feed
            // Populate project health grid
        });
}
```

**Step 2: Verify**

```bash
docker compose restart archie_platform
```
Load http://192.168.1.200:3000/dev-hq — confirm:
- Page renders with "DEV HQ" header
- 6 tabs visible, clicking each shows/hides panels
- Overview tab shows stat cards (data may be zero — that's fine)
- Compass icon in nav bar links back to this page
- Light/dark mode works
- Mobile layout: tabs scroll horizontally

**Step 3: Commit**

```bash
git add platform_v2/templates/dev_hq.html
git commit -m "feat(dev-hq): build full template with 6-tab layout and Overview tab"
```

---

## Task 4: Overview + Projects API endpoints

**Files:**
- Modify: `platform_v2/tools/dev_hq/routes.py`

**Step 1: Add overview API endpoint**

Add to `routes.py`:

```python
from database import get_db_connection

@dev_hq_bp.route("/api/overview")
@login_required
@admin_hub_only
def api_overview():
    """Dashboard overview: stats + recent activity."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        # Project counts by status
        cur.execute("""
            SELECT status, COUNT(*) as count
            FROM unified_projects
            GROUP BY status
        """)
        project_stats = {row['status']: row['count'] for row in cur.fetchall()}

        # Task counts
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE status NOT IN ('completed', 'cancelled')) as open_tasks,
                COUNT(*) FILTER (WHERE status = 'completed'
                    AND completed_at >= NOW() - INTERVAL '7 days') as completed_this_week,
                COUNT(*) FILTER (WHERE due_date < NOW()
                    AND status NOT IN ('completed', 'cancelled')) as overdue
            FROM unified_tasks
        """)
        task_stats = dict(cur.fetchone())

        # Recent activity
        cur.execute("""
            SELECT pa.*, up.name as project_name
            FROM project_activity pa
            LEFT JOIN unified_projects up ON pa.project_id = up.id
            ORDER BY pa.created_at DESC LIMIT 20
        """)
        activity = [dict(row) for row in cur.fetchall()]

        # Active projects with task progress
        cur.execute("""
            SELECT p.*,
                COUNT(t.id) as total_tasks,
                COUNT(t.id) FILTER (WHERE t.status = 'completed') as completed_tasks
            FROM unified_projects p
            LEFT JOIN unified_tasks t ON t.project_id = p.id
            WHERE p.status = 'active'
            GROUP BY p.id
            ORDER BY p.updated_at DESC LIMIT 12
        """)
        active_projects = [dict(row) for row in cur.fetchall()]

        return jsonify({
            "success": True,
            "project_stats": project_stats,
            "task_stats": task_stats,
            "activity": activity,
            "active_projects": active_projects
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()
```

**Step 2: Add Projects CRUD endpoints**

```python
@dev_hq_bp.route("/api/projects")
@login_required
@admin_hub_only
def api_list_projects():
    """List all projects with optional filters."""
    status = request.args.get('status')
    project_type = request.args.get('type')
    search = request.args.get('search')

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query = """
            SELECT p.*,
                COUNT(t.id) as total_tasks,
                COUNT(t.id) FILTER (WHERE t.status = 'completed') as completed_tasks
            FROM unified_projects p
            LEFT JOIN unified_tasks t ON t.project_id = p.id
            WHERE 1=1
        """
        params = []
        if status:
            query += " AND p.status = %s"
            params.append(status)
        if project_type:
            query += " AND p.project_type = %s"
            params.append(project_type)
        if search:
            query += " AND (p.name ILIKE %s OR p.description ILIKE %s)"
            params.extend([f'%{search}%', f'%{search}%'])
        query += " GROUP BY p.id ORDER BY p.updated_at DESC"

        cur.execute(query, params)
        projects = [dict(row) for row in cur.fetchall()]
        return jsonify({"success": True, "projects": projects})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@dev_hq_bp.route("/api/projects", methods=["POST"])
@login_required
@admin_hub_only
def api_create_project():
    """Create a new project."""
    data = request.get_json()
    if not data or not data.get('name'):
        return jsonify({"success": False, "error": "Name is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            INSERT INTO unified_projects (name, description, project_type, status, priority, target_date, created_by_user)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            data['name'],
            data.get('description', ''),
            data.get('project_type', 'feature'),
            data.get('status', 'active'),
            data.get('priority', 'medium'),
            data.get('target_date'),
            current_user.id
        ))
        project = dict(cur.fetchone())
        conn.commit()
        return jsonify({"success": True, "project": project}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@dev_hq_bp.route("/api/projects/<int:project_id>", methods=["PUT"])
@login_required
@admin_hub_only
def api_update_project(project_id):
    """Update a project."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        fields = []
        params = []
        for key in ['name', 'description', 'project_type', 'status', 'priority', 'target_date']:
            if key in data:
                fields.append(f"{key} = %s")
                params.append(data[key])

        if not fields:
            return jsonify({"success": False, "error": "No valid fields to update"}), 400

        fields.append("updated_at = NOW()")
        params.append(project_id)

        cur.execute(f"""
            UPDATE unified_projects SET {', '.join(fields)}
            WHERE id = %s RETURNING *
        """, params)
        project = cur.fetchone()
        if not project:
            return jsonify({"success": False, "error": "Project not found"}), 404
        conn.commit()
        return jsonify({"success": True, "project": dict(project)})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@dev_hq_bp.route("/api/projects/<int:project_id>", methods=["DELETE"])
@login_required
@admin_hub_only
def api_delete_project(project_id):
    """Delete a project and its tasks."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM unified_tasks WHERE project_id = %s", (project_id,))
        cur.execute("DELETE FROM unified_projects WHERE id = %s RETURNING id", (project_id,))
        if not cur.fetchone():
            return jsonify({"success": False, "error": "Project not found"}), 404
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()
```

**Step 3: Add Tasks CRUD endpoints**

```python
@dev_hq_bp.route("/api/projects/<int:project_id>/tasks")
@login_required
@admin_hub_only
def api_list_tasks(project_id):
    """List tasks for a project."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM unified_tasks
            WHERE project_id = %s
            ORDER BY priority DESC, created_at ASC
        """, (project_id,))
        tasks = [dict(row) for row in cur.fetchall()]
        return jsonify({"success": True, "tasks": tasks})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@dev_hq_bp.route("/api/projects/<int:project_id>/tasks", methods=["POST"])
@login_required
@admin_hub_only
def api_create_task(project_id):
    """Create a task within a project."""
    data = request.get_json()
    if not data or not data.get('title'):
        return jsonify({"success": False, "error": "Title is required"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            INSERT INTO unified_tasks (project_id, title, description, task_type, status, priority, due_date, assigned_to_user)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (
            project_id,
            data['title'],
            data.get('description', ''),
            data.get('task_type', 'implementation'),
            data.get('status', 'pending'),
            data.get('priority', 'medium'),
            data.get('due_date'),
            data.get('assigned_to_user')
        ))
        task = dict(cur.fetchone())
        conn.commit()
        return jsonify({"success": True, "task": task}), 201
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@dev_hq_bp.route("/api/tasks/<int:task_id>", methods=["PUT"])
@login_required
@admin_hub_only
def api_update_task(task_id):
    """Update a task."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No data provided"}), 400

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        fields = []
        params = []
        for key in ['title', 'description', 'task_type', 'status', 'priority', 'due_date', 'assigned_to_user']:
            if key in data:
                fields.append(f"{key} = %s")
                params.append(data[key])

        if not fields:
            return jsonify({"success": False, "error": "No valid fields"}), 400

        # Auto-set completed_at when marking complete
        if data.get('status') == 'completed':
            fields.append("completed_at = NOW()")

        fields.append("updated_at = NOW()")
        params.append(task_id)

        cur.execute(f"""
            UPDATE unified_tasks SET {', '.join(fields)}
            WHERE id = %s RETURNING *
        """, params)
        task = cur.fetchone()
        if not task:
            return jsonify({"success": False, "error": "Task not found"}), 404
        conn.commit()
        return jsonify({"success": True, "task": dict(task)})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@dev_hq_bp.route("/api/tasks/<int:task_id>", methods=["DELETE"])
@login_required
@admin_hub_only
def api_delete_task(task_id):
    """Delete a task."""
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM unified_tasks WHERE id = %s RETURNING id", (task_id,))
        if not cur.fetchone():
            return jsonify({"success": False, "error": "Task not found"}), 404
        conn.commit()
        return jsonify({"success": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()
```

**Step 4: Add required imports at top of routes.py**

Ensure these imports are present at the top:
```python
from flask import render_template, jsonify, request, abort
from flask_login import login_required, current_user
from psycopg2.extras import RealDictCursor
from database import get_db_connection
```

**Step 5: Verify**

```bash
docker compose restart archie_platform && sleep 5
# Test overview endpoint
docker exec archie_platform curl -s http://localhost:5000/dev-hq/api/overview | python3 -m json.tool | head -20
# Test projects list
docker exec archie_platform curl -s http://localhost:5000/dev-hq/api/projects | python3 -m json.tool | head -20
```

Note: These will likely return 302 (login required) when curl'd directly. To test properly, use a session cookie or test via browser. At minimum, confirm no import errors in `docker logs archie_platform`.

**Step 6: Commit**

```bash
git add platform_v2/tools/dev_hq/routes.py
git commit -m "feat(dev-hq): add Overview + Projects + Tasks CRUD API endpoints"
```

---

## Task 5: Knowledge + Activity API endpoints

**Files:**
- Modify: `platform_v2/tools/dev_hq/routes.py`

**Step 1: Add knowledge search endpoint**

```python
@dev_hq_bp.route("/api/knowledge")
@login_required
@admin_hub_only
def api_knowledge():
    """Search/list knowledge base entries."""
    search = request.args.get('search', '')
    category = request.args.get('category', '')
    knowledge_type = request.args.get('type', '')  # knowledge, decision, document
    limit = min(int(request.args.get('limit', 50)), 200)
    offset = int(request.args.get('offset', 0))

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        query = """
            SELECT id, file_name, file_path, primary_category, sub_category,
                   tags, knowledge_type, importance_score, is_documentation,
                   created_at, updated_at,
                   LEFT(content, 300) as snippet
            FROM knowledge_base
            WHERE 1=1
        """
        params = []
        if search:
            query += " AND (content ILIKE %s OR file_name ILIKE %s OR tags::text ILIKE %s)"
            params.extend([f'%{search}%'] * 3)
        if category:
            query += " AND primary_category = %s"
            params.append(category)
        if knowledge_type:
            query += " AND knowledge_type = %s"
            params.append(knowledge_type)

        # Get total count
        count_query = query.replace(
            "SELECT id, file_name, file_path, primary_category, sub_category,\n                   tags, knowledge_type, importance_score, is_documentation,\n                   created_at, updated_at,\n                   LEFT(content, 300) as snippet",
            "SELECT COUNT(*)"
        )
        cur.execute(count_query, params)
        total = cur.fetchone()['count']

        query += " ORDER BY importance_score DESC, updated_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        cur.execute(query, params)
        entries = [dict(row) for row in cur.fetchall()]

        # Get categories for filter
        cur.execute("SELECT DISTINCT primary_category FROM knowledge_base WHERE primary_category IS NOT NULL ORDER BY 1")
        categories = [row['primary_category'] for row in cur.fetchall()]

        return jsonify({
            "success": True,
            "entries": entries,
            "total": total,
            "categories": categories
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@dev_hq_bp.route("/api/knowledge/<int:entry_id>")
@login_required
@admin_hub_only
def api_knowledge_detail(entry_id):
    """Get full content of a knowledge base entry."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM knowledge_base WHERE id = %s", (entry_id,))
        entry = cur.fetchone()
        if not entry:
            return jsonify({"success": False, "error": "Not found"}), 404
        return jsonify({"success": True, "entry": dict(entry)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@dev_hq_bp.route("/api/decisions")
@login_required
@admin_hub_only
def api_decisions():
    """List project decisions (ADRs)."""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT d.*, p.name as project_name
            FROM project_decisions d
            LEFT JOIN unified_projects p ON d.project_id = p.id
            ORDER BY d.created_at DESC
        """)
        decisions = [dict(row) for row in cur.fetchall()]
        return jsonify({"success": True, "decisions": decisions})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()


@dev_hq_bp.route("/api/activity")
@login_required
@admin_hub_only
def api_activity():
    """Recent activity feed."""
    limit = min(int(request.args.get('limit', 30)), 100)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT pa.*, up.name as project_name
            FROM project_activity pa
            LEFT JOIN unified_projects up ON pa.project_id = up.id
            ORDER BY pa.created_at DESC
            LIMIT %s
        """, (limit,))
        activity = [dict(row) for row in cur.fetchall()]
        return jsonify({"success": True, "activity": activity})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cur.close()
        conn.close()
```

**Step 2: Verify**

```bash
docker compose restart archie_platform && sleep 3
docker logs archie_platform --tail 5
```
Expected: no import errors.

**Step 3: Commit**

```bash
git add platform_v2/tools/dev_hq/routes.py
git commit -m "feat(dev-hq): add Knowledge search, Decisions, and Activity API endpoints"
```

---

## Task 6: DB Schema + API Docs endpoints (reuse from Blueprint)

**Files:**
- Modify: `platform_v2/tools/dev_hq/routes.py`

**Step 1: Add schema and docs endpoints that delegate to Blueprint helpers**

```python
# DB Schema and API Docs - reuse Blueprint intelligence functions
try:
    from tools.blueprint.blueprint_intelligence import get_database_schema, get_api_endpoints
    INTELLIGENCE_AVAILABLE = True
except ImportError:
    INTELLIGENCE_AVAILABLE = False


@dev_hq_bp.route("/api/schema")
@login_required
@admin_hub_only
def api_schema():
    """Get database schema information."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"success": False, "error": "Blueprint Intelligence not available"}), 500
    try:
        schema = get_database_schema()
        return jsonify(schema)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@dev_hq_bp.route("/api/docs")
@login_required
@admin_hub_only
def api_docs():
    """Get API endpoint documentation."""
    if not INTELLIGENCE_AVAILABLE:
        return jsonify({"success": False, "error": "Blueprint Intelligence not available"}), 500
    try:
        endpoints = get_api_endpoints()
        return jsonify(endpoints)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 2: Verify**

```bash
docker compose restart archie_platform && sleep 3
docker logs archie_platform --tail 5
```

**Step 3: Commit**

```bash
git add platform_v2/tools/dev_hq/routes.py
git commit -m "feat(dev-hq): add DB Schema and API Docs endpoints reusing Blueprint intelligence"
```

---

## Task 7: Integrations tab API endpoints (MCP + Claude config)

**Files:**
- Modify: `platform_v2/tools/dev_hq/routes.py`

**Step 1: Add MCP status endpoint**

```python
import json as json_module


@dev_hq_bp.route("/api/integrations/mcp")
@login_required
@admin_hub_only
def api_mcp_status():
    """Get MCP server configuration and tool registry."""
    result = {"success": True}

    # Read .mcp.json config
    mcp_config_path = os.path.join(os.getenv("ARCHIE_BRAIN_PATH", "/mnt/archie_brain"), ".mcp.json")
    try:
        with open(mcp_config_path, "r") as f:
            mcp_config = json_module.load(f)
        # Mask passwords in env vars
        for server_name, server in mcp_config.get("mcpServers", {}).items():
            env = server.get("env", {})
            for key in env:
                if "password" in key.lower() or "secret" in key.lower() or "key" in key.lower():
                    env[key] = env[key][:4] + "****" if len(env[key]) > 4 else "****"
        result["mcp_config"] = mcp_config
    except Exception as e:
        result["mcp_config"] = {"error": str(e)}

    # Get tool definitions from database
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT name, category, description, enabled, created_at
            FROM mcp_tool_definitions
            ORDER BY category, name
        """)
        result["mcp_tools_db"] = [dict(row) for row in cur.fetchall()]
    except Exception:
        result["mcp_tools_db"] = []

    # Get tool usage stats
    try:
        cur.execute("""
            SELECT tool_name, COUNT(*) as usage_count, MAX(executed_at) as last_used
            FROM mcp_tool_usage
            GROUP BY tool_name
            ORDER BY usage_count DESC
        """)
        result["tool_usage"] = [dict(row) for row in cur.fetchall()]
    except Exception:
        result["tool_usage"] = []

    cur.close()
    conn.close()
    return jsonify(result)


@dev_hq_bp.route("/api/integrations/claude")
@login_required
@admin_hub_only
def api_claude_config():
    """Get Claude Code configuration details."""
    brain_path = os.getenv("ARCHIE_BRAIN_PATH", "/mnt/archie_brain")
    result = {"success": True}

    # Read CLAUDE.md
    for md_path in [
        os.path.join(brain_path, "CLAUDE.md"),
        os.path.join(brain_path, "platform_v2", ".claude", "CLAUDE.md"),
    ]:
        key = "claude_md_root" if "platform_v2" not in md_path else "claude_md_platform"
        try:
            with open(md_path, "r") as f:
                result[key] = f.read()
        except Exception:
            result[key] = None

    # Read settings.json
    settings_path = os.path.join(brain_path, ".claude", "settings.json")
    try:
        with open(settings_path, "r") as f:
            result["claude_settings"] = json_module.load(f)
    except Exception:
        result["claude_settings"] = None

    # List custom commands
    commands_dir = os.path.join(brain_path, "platform_v2", ".claude", "commands")
    try:
        commands = []
        if os.path.isdir(commands_dir):
            for fn in sorted(os.listdir(commands_dir)):
                if fn.endswith(".md"):
                    cmd_path = os.path.join(commands_dir, fn)
                    with open(cmd_path, "r") as f:
                        first_line = f.readline().strip().lstrip("#").strip()
                    commands.append({"name": fn.replace(".md", ""), "description": first_line})
        result["custom_commands"] = commands
    except Exception:
        result["custom_commands"] = []

    # List hooks
    hooks_dir = os.path.join(brain_path, "platform_v2", "scripts", "hooks")
    try:
        hooks = []
        if os.path.isdir(hooks_dir):
            for fn in sorted(os.listdir(hooks_dir)):
                hooks.append(fn)
        result["hooks"] = hooks
    except Exception:
        result["hooks"] = []

    return jsonify(result)
```

**Step 2: Verify**

```bash
docker compose restart archie_platform && sleep 3
docker logs archie_platform --tail 5
```

**Step 3: Commit**

```bash
git add platform_v2/tools/dev_hq/routes.py
git commit -m "feat(dev-hq): add Integrations API endpoints for MCP tools and Claude config"
```

---

## Task 8: Build Overview tab frontend (JS + rendering)

**Files:**
- Modify: `platform_v2/templates/dev_hq.html`

**Step 1: Implement Overview tab JavaScript**

In the `<script>` section of `dev_hq.html`, implement the `loadOverview()` function using safe DOM methods (createElement, textContent — NO innerHTML with interpolation):

- Fetch `/dev-hq/api/overview`
- Populate 4 stat cards: Active Projects (from `project_stats.active`), Open Tasks (`task_stats.open_tasks`), Completed This Week (`task_stats.completed_this_week`), Overdue (`task_stats.overdue`)
- Render activity feed as a scrollable list of items, each showing: activity type icon, project name, description, timestamp (relative "5m ago" format)
- Render active project health grid as cards showing: project name, progress bar (completed_tasks / total_tasks), status badge

All DOM creation must use `document.createElement()` and `.textContent` — never `innerHTML` with template literals.

**Step 2: Verify**

Load http://192.168.1.200:3000/dev-hq — Overview tab shows real data from database. Stats may be zero or populated depending on existing projects.

**Step 3: Commit**

```bash
git add platform_v2/templates/dev_hq.html
git commit -m "feat(dev-hq): implement Overview tab frontend with stats, activity feed, project health"
```

---

## Task 9: Build Projects & Tasks tab frontend (JS + CRUD UI)

**Files:**
- Modify: `platform_v2/templates/dev_hq.html`

**Step 1: Implement Projects & Tasks tab**

This is the most complex tab. It needs:

- **Project list**: Cards loaded from `/dev-hq/api/projects`. Each card shows name, status badge, priority, progress bar, target date, task count.
- **Expandable tasks**: Clicking a project card expands it to show its tasks (fetched from `/dev-hq/api/projects/{id}/tasks`). Each task row shows title, status, priority, assignee, due date.
- **Filters bar**: Dropdowns for status (all/active/completed/on_hold/archived), priority (all/critical/high/medium/low), text search input.
- **Create Project button**: Opens a modal form with fields: name (required), description (textarea), type (dropdown: feature/bugfix/maintenance/research/infrastructure), priority (dropdown), target date (date input).
- **Create Task button** (per project): Opens modal with fields: title (required), description, type (implementation/review/testing/documentation/research/bugfix), priority, assignee, due date.
- **Inline status update**: Click status badge on task → cycles through pending → in_progress → completed. Calls PUT `/dev-hq/api/tasks/{id}`.
- **Delete**: Small trash icon on projects and tasks, with confirm dialog before calling DELETE.

**Modal pattern:**
```html
<div class="dev-hq-modal-overlay" id="projectModal" style="display:none;">
    <div class="dev-hq-modal">
        <div class="dev-hq-modal-header">
            <span class="dev-hq-modal-title">New Project</span>
            <button onclick="closeModal('projectModal')" class="dev-hq-modal-close">&times;</button>
        </div>
        <div class="dev-hq-modal-body">
            <!-- form fields -->
        </div>
        <div class="dev-hq-modal-footer">
            <button class="dev-hq-btn secondary" onclick="closeModal('projectModal')">Cancel</button>
            <button class="dev-hq-btn primary" onclick="submitProject()">Create</button>
        </div>
    </div>
</div>
```

All DOM creation must use safe methods. Use `fetch` with `method: 'POST'/'PUT'/'DELETE'` and `Content-Type: application/json` for mutations.

**Step 2: Verify**

- Load Dev HQ → Projects & Tasks tab
- See list of projects (may be empty)
- Create a test project → appears in list
- Create a task in that project → appears when project expanded
- Change task status → updates in place
- Delete task and project → removed from list

**Step 3: Commit**

```bash
git add platform_v2/templates/dev_hq.html
git commit -m "feat(dev-hq): implement Projects & Tasks tab with full CRUD, filters, modals"
```

---

## Task 10: Build Knowledge tab frontend

**Files:**
- Modify: `platform_v2/templates/dev_hq.html`

**Step 1: Implement Knowledge tab**

- **Search bar**: Text input that triggers search on Enter or after 500ms debounce. Calls `/dev-hq/api/knowledge?search=...`.
- **Category filter**: Dropdown populated from the `categories` array in the API response.
- **Results list**: Cards showing file_name, primary_category, tags (as chips), snippet (truncated content), importance score, date.
- **Detail view**: Clicking a card fetches `/dev-hq/api/knowledge/{id}` and shows full content in an expanded panel below the card (or a modal). Content rendered as preformatted text (not markdown-rendered — keep it simple).
- **Decisions section**: Below or as a toggle, show project decisions from `/dev-hq/api/decisions`. Each shows: decision number (ADR-xxx), title, status badge (proposed/accepted/deprecated), project name, context snippet.
- **Pagination**: "Load More" button when results exceed the limit (50 per page).

**Step 2: Verify**

- Load Dev HQ → Knowledge tab
- See knowledge entries listed with categories
- Search for a term → results filter
- Click an entry → full content shows
- Decisions section shows ADRs

**Step 3: Commit**

```bash
git add platform_v2/templates/dev_hq.html
git commit -m "feat(dev-hq): implement Knowledge tab with search, filters, and decisions"
```

---

## Task 11: Build DB Schema + API Docs tabs frontend

**Files:**
- Modify: `platform_v2/templates/dev_hq.html`

**Step 1: Implement DB Schema tab**

- Fetch `/dev-hq/api/schema`
- **Table list** (left column or top): All tables sorted alphabetically, each showing name and row count. Clickable.
- **Table detail** (main area): When a table is clicked, show its columns in a table: column name, data type, nullable, default value. Show indexes if available.
- Same visual pattern as the existing Mission Control DB tab (replicating the layout).

**Step 2: Implement API Docs tab**

- Fetch `/dev-hq/api/docs`
- **Endpoint list**: Grouped by blueprint/module name. Each endpoint shows: HTTP method badge (color-coded: GET=green, POST=blue, PUT=amber, DELETE=red), path, description.
- Collapsible groups (click module name to expand/collapse its endpoints).

**Step 3: Verify**

- DB Schema tab shows tables with row counts, clicking shows columns
- API Docs tab shows endpoints grouped by module

**Step 4: Commit**

```bash
git add platform_v2/templates/dev_hq.html
git commit -m "feat(dev-hq): implement DB Schema and API Docs tabs"
```

---

## Task 12: Build Integrations tab frontend

**Files:**
- Modify: `platform_v2/templates/dev_hq.html`

**Step 1: Implement Integrations tab**

Fetch `/dev-hq/api/integrations/mcp` and `/dev-hq/api/integrations/claude` in parallel.

**MCP Server panel:**
- Show server name, command, cwd, transport type
- Environment variables in a key-value table (passwords masked by backend)
- Tool registry: table grouped by category showing name, description, enabled status, usage count, last used

**Claude Configuration panel:**
- Plugins list: show enabled plugins from `claude_settings.enabledPlugins`
- Custom commands: list with name and description
- Hooks: list of hook script filenames

**CLAUDE.md panel:**
- Show rendered content of both CLAUDE.md files (root and platform_v2)
- Use `<pre>` tags with monospace styling for raw markdown display
- Or render as HTML if a markdown library is available (but `<pre>` is fine for simplicity)

**Step 2: Verify**

- Integrations tab shows MCP server config with masked passwords
- Tool registry table populated with categories and usage counts
- Claude configuration shows plugins, commands, hooks
- CLAUDE.md content displayed

**Step 3: Commit**

```bash
git add platform_v2/templates/dev_hq.html
git commit -m "feat(dev-hq): implement Integrations tab with MCP tools and Claude config"
```

---

## Task 13: Remove Blueprint from module registry + move Health to System Ops

**Files:**
- Modify: `platform_v2/module_registry.py` (remove blueprint from AI_COMMAND)
- Modify: `platform_v2/tools/system_operations/routes.py` (add full health endpoint)
- Modify: `platform_v2/tools/blueprint/routes.py` (remove the `/` page route, keep API routes)

**Step 1: Remove blueprint from module_registry.py**

Find the `ModuleDefinition` block for `id="blueprint"` (lines ~407-421) and either remove it entirely or set `enabled=False`. Removing is cleaner — the blueprint Flask routes still work for the API endpoints that Dev HQ consumes.

**Step 2: Remove Blueprint page route**

In `platform_v2/tools/blueprint/routes.py`, find the `index()` function (line ~88-91):
```python
@blueprint_bp.route("/")
def index():
    """Main blueprint dashboard"""
    return render_template("tools/blueprint.html")
```

Replace with a redirect to Dev HQ:
```python
from flask import redirect, url_for

@blueprint_bp.route("/")
def index():
    """Redirect to Dev HQ (Mission Control is now Dev HQ)."""
    return redirect(url_for('dev_hq.index'))
```

This preserves backward compatibility — any old links to `/tools/blueprint` redirect to Dev HQ.

**Step 3: Add full health endpoint to System Operations**

In `platform_v2/tools/system_operations/routes.py`, add a route that reuses the Blueprint health function:

```python
try:
    from tools.blueprint.blueprint_intelligence import get_system_health
    BLUEPRINT_HEALTH_AVAILABLE = True
except ImportError:
    BLUEPRINT_HEALTH_AVAILABLE = False


@system_ops_bp.route("/api/system-health-full")
@login_required
def api_system_health_full():
    """Full system health check (moved from Blueprint)."""
    if not BLUEPRINT_HEALTH_AVAILABLE:
        return jsonify({"error": "Health check not available"}), 500
    try:
        health = get_system_health()
        return jsonify(health)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
```

**Step 4: Verify**

```bash
docker compose restart archie_platform && sleep 5
```
- Load dashboard at http://192.168.1.200:3000 — confirm Blueprint/Mission Control no longer appears in AI Command module grid
- Navigate to `/tools/blueprint` — confirm redirect to `/dev-hq`
- Dev HQ still works (DB Schema and API Docs tabs still function because blueprint API routes are intact)

**Step 5: Commit**

```bash
git add platform_v2/module_registry.py platform_v2/tools/blueprint/routes.py platform_v2/tools/system_operations/routes.py
git commit -m "refactor: remove Blueprint from module grid, redirect to Dev HQ, move health to System Ops"
```

---

## Task 14: Update CLAUDE.md files and nav bar references

**Files:**
- Modify: `CLAUDE.md` (root)
- Modify: `platform_v2/.claude/CLAUDE.md`
- Modify: `platform_v2/templates/includes/admin_ops_nav.html` (update comment)

**Step 1: Update root CLAUDE.md**

Replace references to Mission Control / Blueprint with Dev HQ:

- Architecture section line: `"Mission Control - Unified dashboard..."` → `"Dev HQ - Development command center (/dev-hq), 45+ API endpoints"`
- Quick Reference table: `"Mission Control | http://192.168.1.200:3000/tools/blueprint"` → `"Dev HQ | http://192.168.1.200:3000/dev-hq"`
- Source of Truth table: update access column for Documentation & Knowledge to mention Dev HQ Knowledge tab

**Step 2: Update platform_v2 CLAUDE.md**

Same changes as Step 1, applied to `platform_v2/.claude/CLAUDE.md`.

**Step 3: Update nav bar comment**

In `admin_ops_nav.html`, update the header comment (line 3) from:
```
Shared component for Blueprint, Bridge, Team, Mind, HR, Pool, Goose, Projects
```
to:
```
Shared component for Bridge, Team, Mind, HR, Pool, Goose, Projects (Dev HQ via compass icon)
```

**Step 4: Verify**

Read both CLAUDE.md files to confirm no remaining "Mission Control" or "Blueprint" references (except for the internal code path `tools.blueprint` which is correct — that's the code module, not the user-facing name).

**Step 5: Commit**

```bash
git add CLAUDE.md platform_v2/.claude/CLAUDE.md platform_v2/templates/includes/admin_ops_nav.html
git commit -m "docs: update CLAUDE.md and nav references from Mission Control to Dev HQ"
```

---

## Task 15: Verify everything end-to-end

**Step 1: Full restart and browser verification**

```bash
docker compose restart archie_platform && sleep 8
```

Verify in browser at http://192.168.1.200:3000:

1. **Dashboard**: Blueprint/Mission Control no longer in AI Command grid
2. **Any module page**: Compass icon visible in nav bar (top-right), clicking opens Dev HQ
3. **Dev HQ Overview**: Stats cards populated, activity feed shows entries, active project cards render
4. **Projects & Tasks**: Can create project, create task, change task status, delete both
5. **Knowledge**: Search works, categories populate, clicking entry shows full content, decisions listed
6. **DB Schema**: Tables listed with row counts, clicking shows column details
7. **API Docs**: Endpoints grouped by module, method badges colored
8. **Integrations**: MCP config shown (passwords masked), tool registry table, Claude config with plugins/commands/hooks, CLAUDE.md content displayed
9. **Light/dark mode**: Toggle works on Dev HQ page
10. **Mobile**: Tabs scroll horizontally on narrow viewport
11. **Old URL redirect**: `/tools/blueprint` redirects to `/dev-hq`

**Step 2: Commit if any fixes needed**

```bash
git add -A && git commit -m "fix(dev-hq): end-to-end verification fixes"
```

**Step 3: Store in knowledge base**

Use MCP `store_memory` to document:
- Dev HQ replaces Mission Control
- Route: `/dev-hq`, admin-only, Hub-only
- 6 tabs: Overview, Projects & Tasks, Knowledge, DB Schema, API Docs, Integrations
- Compass icon in all nav bars
- Blueprint module routes still exist for API (DB schema, API docs, health) but page redirects to Dev HQ
- CLAUDE.md updated to reference Dev HQ

---

## Summary

| Task | Description | Key Files |
|------|-------------|-----------|
| 1 | Flask Blueprint skeleton | `tools/dev_hq/__init__.py`, `routes.py`, `app.py`, `dev_hq.html` |
| 2 | Compass icon in all nav bars | 6 nav include files |
| 3 | Full template with 6-tab layout + Overview HTML | `dev_hq.html` |
| 4 | Overview + Projects CRUD API endpoints | `routes.py` |
| 5 | Knowledge + Activity API endpoints | `routes.py` |
| 6 | DB Schema + API Docs API endpoints | `routes.py` |
| 7 | Integrations API endpoints (MCP + Claude) | `routes.py` |
| 8 | Overview tab frontend JS | `dev_hq.html` |
| 9 | Projects & Tasks tab frontend (CRUD UI) | `dev_hq.html` |
| 10 | Knowledge tab frontend | `dev_hq.html` |
| 11 | DB Schema + API Docs tabs frontend | `dev_hq.html` |
| 12 | Integrations tab frontend | `dev_hq.html` |
| 13 | Remove Blueprint from registry, move Health | `module_registry.py`, `blueprint/routes.py`, `system_operations/routes.py` |
| 14 | Update CLAUDE.md and nav references | `CLAUDE.md` (x2), `admin_ops_nav.html` |
| 15 | End-to-end verification | All files |

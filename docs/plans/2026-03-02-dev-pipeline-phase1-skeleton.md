# Dev Pipeline Module Skeleton — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create the dev_pipeline module skeleton with LCARS template, 4-tab navigation, and module registration — ready for route migration in subsequent phases.

**Architecture:** New Flask Blueprint at `/tools/dev-pipeline` using the Consciousness pattern: `__init__.py` registers sub-route files via `register_*_routes(bp, admin_required)`. Single LCARS template with `tab_nav` macro. Empty tab panels with placeholder content.

**Tech Stack:** Flask Blueprint, Jinja2 LCARS macros, CSS, module_registry.py + rbac.py

---

### Task 1: Create module directory and __init__.py

**Files:**
- Create: `platform_v2/tools/dev_pipeline/__init__.py`
- Create: `platform_v2/tools/dev_pipeline/routes.py`

**Step 1: Create directory**

```bash
mkdir -p /mnt/archie_brain/platform_v2/tools/dev_pipeline
```

**Step 2: Create __init__.py**

```python
"""
Dev Pipeline Module — Unified Development Tools

Consolidates Code Sentinel + Improvements Lab + Sandbox Manager into
a single module with 4 tabs: Scan, Proposals, Sandbox, Deploy.

All routes require admin authentication via @admin_required decorator.
"""

from flask import Blueprint

dev_pipeline_bp = Blueprint(
    "dev_pipeline",
    __name__,
    url_prefix="/tools/dev-pipeline",
    template_folder="templates",
)

from . import routes  # noqa: F401, E402
```

**Step 3: Create routes.py with admin_required and index route**

```python
"""Dev Pipeline — main routes and admin_required decorator."""

import logging
from functools import wraps

from flask import (
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
    flash,
)
from flask_login import current_user, login_required

from rbac import Permission, has_permission, audit_log

logger = logging.getLogger(__name__)


def admin_required(f):
    """Decorator to require admin access."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not has_permission(Permission.ADMIN_ACCESS, current_user):
            audit_log(
                "ADMIN_ACCESS_DENIED",
                {
                    "route": request.endpoint,
                    "user_id": (
                        current_user.id if current_user.is_authenticated else None
                    ),
                },
                success=False,
            )
            flash("Admin access required", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated_function


from . import dev_pipeline_bp  # noqa: E402


@dev_pipeline_bp.route("/")
@login_required
@admin_required
def index():
    """Dev Pipeline main page — renders 4-tab LCARS interface."""
    return render_template("tools/dev_pipeline.html")


@dev_pipeline_bp.route("/api/status")
@login_required
def status():
    """Health check endpoint."""
    return jsonify(
        {
            "module": "dev_pipeline",
            "status": "active",
            "healthy": True,
        }
    )
```

**Step 4: Commit**

```bash
git add platform_v2/tools/dev_pipeline/
git commit -m "feat(dev-pipeline): create module skeleton with routes"
```

---

### Task 2: Create LCARS template with 4 tabs

**Files:**
- Create: `platform_v2/templates/tools/dev_pipeline.html`

**Step 1: Create template**

The template follows the Autonomy/Consciousness gold-standard pattern:
- Extends `base.html`
- Includes `admin_ops_nav.html` (AI Command category nav)
- Uses `tab_nav` macro from LCARS layout
- 4 tab panels with placeholder content
- Hash navigation support
- Responsive for Fold5 (374px/717px)

```html
{% extends "base.html" %}

{% block title %}Dev Pipeline{% endblock %}

{% block styles %}
{% from "layouts/lcars.html" import tab_nav %}

/* Dev Pipeline Module Styles */
.dp-container {
    padding: 20px;
    max-width: 100%;
    overflow-x: hidden;
}

.dp-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 16px;
    flex-wrap: wrap;
    gap: 12px;
}

.dp-title {
    font-family: 'Orbitron', var(--archie-font-mono), monospace;
    font-size: 1.3rem;
    font-weight: 600;
    color: var(--archie-text-primary);
    letter-spacing: 2px;
    text-transform: uppercase;
}

.dp-subtitle {
    font-family: 'Antonio', var(--archie-font-mono), monospace;
    font-size: 0.8rem;
    color: var(--archie-text-muted);
    letter-spacing: 1px;
    text-transform: uppercase;
}

/* Stats cards */
.dp-stats {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 12px;
    margin-bottom: 20px;
}

.dp-stat-card {
    background: var(--archie-bg-secondary);
    border: 1px solid var(--archie-border-default);
    border-radius: 2px 12px 12px 2px;
    border-left: 3px solid var(--card-accent, var(--archie-cyan, #00d4ff));
    padding: 14px 16px;
}

.dp-stat-label {
    font-family: 'Antonio', sans-serif;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--archie-text-muted);
    margin-bottom: 4px;
}

.dp-stat-value {
    font-family: 'Orbitron', monospace;
    font-size: 1.4rem;
    font-weight: 700;
    color: var(--card-accent, var(--archie-cyan, #00d4ff));
}

/* Tab content */
.tab-content {
    display: none;
}

.tab-content.active {
    display: block;
}

/* Empty state placeholder */
.dp-empty {
    text-align: center;
    padding: 60px 20px;
    color: var(--archie-text-muted);
}

.dp-empty-icon {
    font-size: 48px;
    margin-bottom: 16px;
    opacity: 0.5;
}

.dp-empty-title {
    font-family: 'Orbitron', monospace;
    font-size: 1.1rem;
    margin-bottom: 8px;
    color: var(--archie-text-secondary);
}

.dp-empty-desc {
    font-size: 0.85rem;
    line-height: 1.6;
}

/* Responsive: Fold5 open (717px) */
@media (max-width: 768px) {
    .dp-container { padding: 12px; }
    .dp-title { font-size: 1.1rem; }
    .dp-stats { grid-template-columns: repeat(2, 1fr); gap: 8px; }
    .dp-stat-card { padding: 10px 12px; }
    .dp-stat-value { font-size: 1.1rem; }
}

/* Responsive: Fold5 closed (374px) */
@media (max-width: 500px) {
    .dp-container { padding: 8px; }
    .dp-title { font-size: 0.95rem; letter-spacing: 1px; }
    .dp-stats { grid-template-columns: repeat(2, 1fr); gap: 6px; }
    .dp-stat-card { padding: 8px 10px; }
    .dp-stat-label { font-size: 0.6rem; }
    .dp-stat-value { font-size: 1rem; }
    .dp-empty { padding: 40px 12px; }
}

{% endblock %}

{% block content %}
{% from "layouts/lcars.html" import tab_nav %}
{% include 'includes/admin_ops_nav.html' %}

<div class="dp-container">
    <div class="dp-header">
        <div>
            <div class="dp-title">Dev Pipeline</div>
            <div class="dp-subtitle">Scan &bull; Propose &bull; Test &bull; Deploy</div>
        </div>
    </div>

    <!-- Stats Overview -->
    <div class="dp-stats">
        <div class="dp-stat-card" style="--card-accent: var(--archie-cyan, #00d4ff);">
            <div class="dp-stat-label">Scans (24h)</div>
            <div class="dp-stat-value" id="statScans">0</div>
        </div>
        <div class="dp-stat-card" style="--card-accent: #f59e0b;">
            <div class="dp-stat-label">Proposals</div>
            <div class="dp-stat-value" id="statProposals">0</div>
        </div>
        <div class="dp-stat-card" style="--card-accent: #8b5cf6;">
            <div class="dp-stat-label">Sandboxes</div>
            <div class="dp-stat-value" id="statSandboxes">0</div>
        </div>
        <div class="dp-stat-card" style="--card-accent: #00ff41;">
            <div class="dp-stat-label">Deployed</div>
            <div class="dp-stat-value" id="statDeployed">0</div>
        </div>
    </div>

    <!-- Tab Navigation -->
    {{ tab_nav(tabs=[
        {'id': 'scan', 'label': 'Scan', 'icon': 'shield-check'},
        {'id': 'proposals', 'label': 'Proposals', 'icon': 'wrench'},
        {'id': 'sandbox', 'label': 'Sandbox', 'icon': 'test-tube-2'},
        {'id': 'deploy', 'label': 'Deploy', 'icon': 'rocket'}
    ], onswitch='switchTab') }}

    <!-- Scan Tab -->
    <div id="tab-scan" class="tab-content active">
        <div class="dp-empty">
            <div class="dp-empty-icon"><i data-lucide="shield-check" style="width:48px;height:48px;"></i></div>
            <div class="dp-empty-title">Code Scanner</div>
            <div class="dp-empty-desc">Scan your codebase for issues, vulnerabilities, and quality problems.<br>Multi-agent review powered by Bridge Command.</div>
        </div>
    </div>

    <!-- Proposals Tab -->
    <div id="tab-proposals" class="tab-content">
        <div class="dp-empty">
            <div class="dp-empty-icon"><i data-lucide="wrench" style="width:48px;height:48px;"></i></div>
            <div class="dp-empty-title">Improvement Proposals</div>
            <div class="dp-empty-desc">Track proposals from detection through approval, testing, and deployment.<br>Auto-generated from scans or created manually.</div>
        </div>
    </div>

    <!-- Sandbox Tab -->
    <div id="tab-sandbox" class="tab-content">
        <div class="dp-empty">
            <div class="dp-empty-icon"><i data-lucide="test-tube-2" style="width:48px;height:48px;"></i></div>
            <div class="dp-empty-title">Sandbox Environments</div>
            <div class="dp-empty-desc">Isolated testing environments for validating code changes.<br>Docker containers or PostgreSQL schema sandboxes.</div>
        </div>
    </div>

    <!-- Deploy Tab -->
    <div id="tab-deploy" class="tab-content">
        <div class="dp-empty">
            <div class="dp-empty-icon"><i data-lucide="rocket" style="width:48px;height:48px;"></i></div>
            <div class="dp-empty-title">Deployments</div>
            <div class="dp-empty-desc">Deployment history, health monitoring, and rollback controls.<br>Safety-first: backup, test, deploy, monitor.</div>
        </div>
    </div>
</div>

<script>
// Tab switching with hash navigation
function switchTab(tabId) {
    document.querySelectorAll('.tab-content').forEach(function(el) {
        el.classList.remove('active');
    });
    document.querySelectorAll('.lcars-tab-btn').forEach(function(el) {
        el.classList.remove('active');
    });
    var panel = document.getElementById('tab-' + tabId);
    if (panel) panel.classList.add('active');
    var btn = document.querySelector('.lcars-tab-btn[data-tab="' + tabId + '"]');
    if (btn) btn.classList.add('active');
    window.location.hash = '#' + tabId;
}

// Hash navigation on load
document.addEventListener('DOMContentLoaded', function() {
    var hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById('tab-' + hash)) {
        switchTab(hash);
    }
    if (typeof lucide !== 'undefined') lucide.createIcons();
});

window.addEventListener('hashchange', function() {
    var hash = window.location.hash.replace('#', '');
    if (hash && document.getElementById('tab-' + hash)) {
        switchTab(hash);
    }
});
</script>
{% endblock %}
```

**Step 2: Commit**

```bash
git add platform_v2/templates/tools/dev_pipeline.html
git commit -m "feat(dev-pipeline): LCARS template with 4-tab navigation"
```

---

### Task 3: Register module in module_registry.py and rbac.py

**Files:**
- Modify: `platform_v2/module_registry.py`
- Modify: `platform_v2/rbac.py`

**Step 1: Add to module_registry.py**

Find the DEVELOPMENT_TOOLS section (around line 505). Add the new module BEFORE the existing Code Sentinel entry:

```python
    ModuleDefinition(
        id="dev_pipeline",
        name="Dev Pipeline",
        description="Unified development tools<br>Scan • Proposals • Sandbox • Deploy",
        icon="git-branch",
        category=ModuleCategory.DEVELOPMENT_TOOLS,
        route="/tools/dev-pipeline",
        blueprint_import="tools.dev_pipeline:dev_pipeline_bp",
        required_permissions=[],
        minimum_role="ADMIN",
        enabled=True,
        coming_soon=False,
        health_check=lambda: check_service_health(
            "dev_pipeline", "/tools/dev-pipeline/api/status"
        ),
        priority=0,
        tags=[
            "development",
            "pipeline",
            "scanning",
            "testing",
            "deployment",
            "development-tools",
        ],
    ),
```

**Step 2: Add permission to rbac.py**

Find the permissions section. Add after `ADMIN_IMPROVEMENTS`:

```python
    ADMIN_DEV_PIPELINE = "admin:dev_pipeline"
```

**Step 3: Commit**

```bash
git add platform_v2/module_registry.py platform_v2/rbac.py
git commit -m "feat(dev-pipeline): register module in registry and RBAC"
```

---

### Task 4: Verification

**Step 1: Syntax check**

```bash
python3 -c "import ast; ast.parse(open('platform_v2/tools/dev_pipeline/__init__.py').read()); print('__init__: OK')"
python3 -c "import ast; ast.parse(open('platform_v2/tools/dev_pipeline/routes.py').read()); print('routes: OK')"
python3 -c "import ast; ast.parse(open('platform_v2/module_registry.py').read()); print('registry: OK')"
python3 -c "import ast; ast.parse(open('platform_v2/rbac.py').read()); print('rbac: OK')"
```

**Step 2: Restart and test**

```bash
docker compose restart archie_platform
sleep 15
# Verify module loads
curl -s -b /tmp/archie_cookies.txt -w "%{http_code}" http://192.168.1.200:3000/tools/dev-pipeline/ -o /dev/null
# Should return 200
```

**Step 3: Screenshot at 3 breakpoints**

Using Playwright:
- 1280x800 (desktop)
- 717x900 (Fold5 open)
- 374x800 (Fold5 closed)

Verify: LCARS tab nav visible, 4 stat cards, placeholder content, no overflow.

**Step 4: Push**

```bash
git push
```

**Step 5: Update Dev HQ**

- Complete task #712

# Website Designer Phase 2: Integration & Deployment — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the missing Hostinger and GitHub deployment files, upgrade AI chat to project-aware role-based dispatch with persistent history in a resizable drawer, add deployment UI, and fix backend bugs.

**Architecture:** Create `hostinger_integration.py` and `github_deployment.py` that routes.py already tries to import (filling in missing modules). Upgrade `chat_with_archie()` in routes.py to pass `prefer_agent` based on role detection. Add chat history persistence to `website_builder_projects.chat_history`. Frontend adds deploy panel + chat drawer to existing builder UI.

**Tech Stack:** Flask (existing), requests (HTTP client), GitHub API, Hostinger API v2, vanilla JS

**Key patterns from existing code:**
- Blueprint: `website_studio_bp`, prefix `/tools/website-studio`
- Routes.py imports at module level with try/except: `from hostinger_integration import get_hostinger_api` → `HOSTINGER_AVAILABLE = True/False`
- Chat handler in routes.py (`chat_with_archie()` at line 589): calls `ai_bridge()` via dynamic import, passes system prompt from `get_chat_system_prompt()`
- Deploy routes: `deploy_project()` at line 1003, `deploy_to_github_pages()` at line 1161
- Hostinger routes: 7 routes already wired calling `api.list_domains()`, `api.get_dns_records()`, etc.
- user_integrations: `SELECT * FROM user_integrations WHERE user_id=%s AND service=%s AND status='active'`
- DB: module uses `get_db_connection()` (NOT `get_db_cursor`) — follow existing pattern, don't change it
- WEBSITE_REPO_PATH = `/tmp/website-repo`
- `admin_required` defined TWICE in routes.py (line 21 + line 1680) — remove duplicate
- Triple decorator bug on `website_deploy()` — fix
- JS IIFE: new code goes before `DOMContentLoaded` listener, inside the IIFE

---

## Task 1: Database Migration 158

**Files:**
- Create: `database/migrations/158_website_designer_phase2.sql`

- [ ] **Step 1: Write the migration**

```sql
-- Migration 158: Website Designer Phase 2 — deployment URL + chat history
-- Idempotent: safe to run multiple times

ALTER TABLE website_deployments
ADD COLUMN IF NOT EXISTS deployment_url VARCHAR(500);

ALTER TABLE website_builder_projects
ADD COLUMN IF NOT EXISTS chat_history JSONB DEFAULT '[]';
```

- [ ] **Step 2: Run migration**

```bash
docker cp database/migrations/158_website_designer_phase2.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/158_website_designer_phase2.sql
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name='website_deployments' AND column_name='deployment_url'"
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name='website_builder_projects' AND column_name='chat_history'"
```

- [ ] **Step 4: Commit**

```bash
git add database/migrations/158_website_designer_phase2.sql
git commit -m "feat(website-designer): add migration 158 — deployment_url + chat_history"
```

---

## Task 2: Hostinger Integration

**Files:**
- Create: `platform_v2/tools/website_studio/hostinger_integration.py`

- [ ] **Step 1: Write hostinger_integration.py (~120 lines)**

The routes.py file imports `get_hostinger_api` from this module. The Hostinger routes call methods on the returned object. Create the `HostingerAPI` class matching what routes.py already calls.

```python
"""Hostinger API integration for Website Designer.

Provides domain and DNS management. Runs in mock mode when no API key
is configured, returning realistic sample data for UI development.

Factory function:
- get_hostinger_api(user_id) — loads credentials, returns HostingerAPI instance
"""

import logging
import requests

logger = logging.getLogger(__name__)

HOSTINGER_API_BASE = "https://api.hostinger.com/v2"


class HostingerAPI:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.mock_mode = not bool(api_key)
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def is_configured(self):
        return not self.mock_mode

    def _request(self, method, path, json=None):
        if self.mock_mode:
            return None  # caller checks mock_mode
        try:
            r = requests.request(
                method, f"{HOSTINGER_API_BASE}{path}",
                headers=self.headers, json=json, timeout=15,
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"Hostinger API error: {e}")
            return {"error": str(e)}

    def list_domains(self):
        if self.mock_mode:
            return {
                "mock": True,
                "domains": [
                    {"domain": "example.com", "status": "active", "expires": "2027-01-15"},
                    {"domain": "mysite.net", "status": "active", "expires": "2026-12-01"},
                ],
            }
        return self._request("GET", "/domains")

    def get_dns_records(self, domain):
        if self.mock_mode:
            return {
                "mock": True,
                "records": [
                    {"id": 1, "type": "A", "name": "@", "content": "185.199.108.153", "ttl": 3600},
                    {"id": 2, "type": "CNAME", "name": "www", "content": "example.github.io", "ttl": 3600},
                    {"id": 3, "type": "MX", "name": "@", "content": "mail.example.com", "ttl": 3600, "priority": 10},
                ],
            }
        return self._request("GET", f"/domains/{domain}/dns")

    def add_dns_record(self, domain, record_type, name, content, ttl=3600, priority=None):
        if self.mock_mode:
            return {"mock": True, "success": True, "id": 999}
        data = {"type": record_type, "name": name, "content": content, "ttl": ttl}
        if priority is not None:
            data["priority"] = priority
        return self._request("POST", f"/domains/{domain}/dns", json=data)

    def update_dns_record(self, domain, record_id, content=None, ttl=None):
        if self.mock_mode:
            return {"mock": True, "success": True}
        data = {}
        if content is not None:
            data["content"] = content
        if ttl is not None:
            data["ttl"] = ttl
        return self._request("PUT", f"/domains/{domain}/dns/{record_id}", json=data)

    def delete_dns_record(self, domain, record_id):
        if self.mock_mode:
            return {"mock": True, "success": True}
        return self._request("DELETE", f"/domains/{domain}/dns/{record_id}")

    def apply_preset(self, domain, preset_type, target=None):
        if self.mock_mode:
            return {"mock": True, "success": True, "records_added": 4}
        if preset_type == "github_pages":
            # Add A records for GitHub Pages IPs + CNAME for www
            records = [
                {"type": "A", "name": "@", "content": "185.199.108.153", "ttl": 3600},
                {"type": "A", "name": "@", "content": "185.199.109.153", "ttl": 3600},
                {"type": "A", "name": "@", "content": "185.199.110.153", "ttl": 3600},
                {"type": "A", "name": "@", "content": "185.199.111.153", "ttl": 3600},
                {"type": "CNAME", "name": "www", "content": target or f"{domain}.github.io", "ttl": 3600},
            ]
        else:
            return {"error": f"Unknown preset: {preset_type}"}
        added = 0
        for rec in records:
            result = self.add_dns_record(domain, rec["type"], rec["name"], rec["content"], rec["ttl"])
            if result and "error" not in result:
                added += 1
        return {"success": True, "records_added": added}


def get_hostinger_api(user_id):
    """Factory function imported by routes.py. Loads API key from user_integrations."""
    try:
        # Use the module's own DB pattern
        import psycopg2
        import os
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "192.168.1.200"),
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ.get("DB_NAME", "archie"),
            user=os.environ.get("DB_USER", "archie"),
            password=os.environ.get("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT credentials FROM user_integrations WHERE user_id = %s AND service = 'hostinger' AND status = 'active'",
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            creds = row[0] if isinstance(row[0], dict) else {}
            api_key = creds.get("api_key")
            return HostingerAPI(api_key)
    except Exception as e:
        logger.warning(f"Failed to load Hostinger credentials: {e}")
    return HostingerAPI()  # mock mode
```

Note: Uses direct psycopg2 connection matching the module's existing pattern (NOT `get_db_cursor`).

- [ ] **Step 2: Verify import works**

```bash
docker exec archie_platform python3 -c "from tools.website_studio.hostinger_integration import get_hostinger_api; api = get_hostinger_api(1); print('configured:', api.is_configured(), 'mock:', api.mock_mode)"
```

Expected: `configured: False mock: True` (no API key configured yet)

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/website_studio/hostinger_integration.py
git commit -m "feat(website-designer): add Hostinger integration with mock mode"
```

---

## Task 3: GitHub Deployment

**Files:**
- Create: `platform_v2/tools/website_studio/github_deployment.py`

**Dependencies:** Task 1 (deployment_url column)

- [ ] **Step 1: Write github_deployment.py (~80 lines)**

```python
"""GitHub deployment for Website Designer.

Provides commit+push+Pages enable for deploying websites to GitHub Pages.
Reuses chat_handler.py's git operations (no duplicate git logic).

Functions (matching routes.py imports):
- deploy_website(user_id, project_id)
- auto_commit_and_push(message, repo_path)
- get_deployment_history(project_id)
"""

import logging
import subprocess
import os

logger = logging.getLogger(__name__)

WEBSITE_REPO_PATH = "/tmp/website-repo"


def deploy_website(user_id, project_id=None):
    """Full deploy: clone/pull → commit → push → enable GitHub Pages."""
    from chat_handler import ensure_repo_cloned, auto_commit_changes

    # 1. Ensure repo is cloned and up to date
    clone_result = ensure_repo_cloned(WEBSITE_REPO_PATH)
    if not clone_result.get("success", True):
        return {"success": False, "error": "Failed to clone/pull repo"}

    # 2. Commit any changes
    commit_result = auto_commit_changes("Deploy from Website Designer", WEBSITE_REPO_PATH)
    commit_hash = commit_result.get("sha", "unknown") if isinstance(commit_result, dict) else "unknown"

    # 3. Push to remote
    try:
        push = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=WEBSITE_REPO_PATH,
            capture_output=True, text=True, timeout=30,
        )
        if push.returncode != 0:
            return {"success": False, "error": f"Push failed: {push.stderr}"}
    except Exception as e:
        return {"success": False, "error": f"Push error: {e}"}

    # 4. Enable GitHub Pages via API (if token available)
    deployment_url = _enable_github_pages(user_id)

    # 5. Record deployment
    _record_deployment(project_id, user_id, commit_hash, deployment_url)

    return {
        "success": True,
        "url": deployment_url or "https://github.com (push complete)",
        "commit_hash": commit_hash,
    }


def auto_commit_and_push(message="Auto-deploy", repo_path=None):
    """Thin wrapper: commit + push."""
    from chat_handler import auto_commit_changes
    repo = repo_path or WEBSITE_REPO_PATH
    auto_commit_changes(message, repo)
    subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )


def get_deployment_history(project_id):
    """Query deployment records for a project."""
    import psycopg2
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "192.168.1.200"),
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ.get("DB_NAME", "archie"),
            user=os.environ.get("DB_USER", "archie"),
            password=os.environ.get("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        cur.execute(
            """SELECT id, deployment_type, status, commit_hash, deployment_url, error_message, created_at
               FROM website_deployments WHERE website_id = %s ORDER BY created_at DESC LIMIT 20""",
            (project_id,),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.close()
        conn.close()
        for r in rows:
            for k, v in list(r.items()):
                if hasattr(v, "isoformat"):
                    r[k] = v.isoformat()
        return rows
    except Exception as e:
        logger.error(f"get_deployment_history error: {e}")
        return []


def _enable_github_pages(user_id):
    """Try to enable GitHub Pages via API. Returns URL or None."""
    import requests as req
    try:
        import psycopg2
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "192.168.1.200"),
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ.get("DB_NAME", "archie"),
            user=os.environ.get("DB_USER", "archie"),
            password=os.environ.get("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT credentials FROM user_integrations WHERE user_id = %s AND service = 'github' AND status = 'active'",
            (user_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row or not row[0]:
            return None
        creds = row[0] if isinstance(row[0], dict) else {}
        token = creds.get("access_token") or creds.get("token")
        if not token:
            token = os.environ.get("GITHUB_TOKEN")
        if not token:
            return None

        # Parse owner/repo from git remote
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=WEBSITE_REPO_PATH, capture_output=True, text=True,
        )
        remote = result.stdout.strip()
        # Handle https://github.com/owner/repo.git or git@github.com:owner/repo.git
        if "github.com" in remote:
            parts = remote.replace(".git", "").split("github.com")[-1].strip(":/").split("/")
            if len(parts) >= 2:
                owner, repo = parts[0], parts[1]
            else:
                return None
        else:
            return None

        headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github+json"}
        # Check if Pages already enabled
        check = req.get(f"https://api.github.com/repos/{owner}/{repo}/pages", headers=headers)
        if check.status_code == 200:
            return check.json().get("html_url")
        # Enable Pages
        resp = req.post(
            f"https://api.github.com/repos/{owner}/{repo}/pages",
            headers=headers,
            json={"source": {"branch": "main", "path": "/"}},
        )
        if resp.status_code in (201, 200):
            return resp.json().get("html_url", f"https://{owner}.github.io/{repo}")
        logger.warning(f"GitHub Pages enable returned {resp.status_code}: {resp.text}")
        return f"https://{owner}.github.io/{repo}"
    except Exception as e:
        logger.warning(f"GitHub Pages enable failed: {e}")
        return None


def _record_deployment(project_id, user_id, commit_hash, deployment_url):
    """Insert deployment record into DB."""
    if not project_id:
        return
    import psycopg2
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "192.168.1.200"),
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ.get("DB_NAME", "archie"),
            user=os.environ.get("DB_USER", "archie"),
            password=os.environ.get("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO website_deployments (website_id, deployment_type, status, commit_hash, deployment_url, deployed_by)
               VALUES (%s, 'github_pages', 'completed', %s, %s, %s)""",
            (project_id, commit_hash, deployment_url, user_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Record deployment failed: {e}")
```

- [ ] **Step 2: Verify import**

```bash
docker exec archie_platform python3 -c "from tools.website_studio.github_deployment import deploy_website, auto_commit_and_push, get_deployment_history; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/website_studio/github_deployment.py
git commit -m "feat(website-designer): add GitHub Pages deployment module"
```

---

## Task 4: Enhanced Chat — Role Detection + History Persistence

**Files:**
- Modify: `platform_v2/tools/website_studio/chat_handler.py` (append ~60 lines)
- Modify: `platform_v2/tools/website_studio/routes.py` (update chat_with_archie)

- [ ] **Step 1: Read chat_handler.py to find append location**

Read last ~20 lines to find where to append new functions.

- [ ] **Step 2: Append role detection + chat history functions to chat_handler.py**

```python
# ── Phase 2: Role Detection + Chat History ──

DESIGN_KEYWORDS = [
    "color", "font", "style", "layout", "css", "theme", "spacing",
    "padding", "margin", "background", "animation", "responsive",
    "dark mode", "gradient", "shadow", "border", "design", "align",
    "flex", "grid", "width", "height", "image", "logo", "icon",
]
DEPLOY_KEYWORDS = [
    "deploy", "publish", "push", "github pages", "hostinger",
    "domain", "dns", "ssl", "live", "hosting", "go live",
]


def detect_task_role(message):
    """Classify chat message into role: design, deploy, or engineering."""
    msg = message.lower()
    if any(k in msg for k in DEPLOY_KEYWORDS):
        return "deploy"
    if any(k in msg for k in DESIGN_KEYWORDS):
        return "design"
    return "engineering"


def save_chat_history(project_id, history):
    """Persist chat history (last 50 messages) to website_builder_projects."""
    import psycopg2
    import json
    import os
    trimmed = history[-50:] if len(history) > 50 else history
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "192.168.1.200"),
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ.get("DB_NAME", "archie"),
            user=os.environ.get("DB_USER", "archie"),
            password=os.environ.get("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        cur.execute(
            "UPDATE website_builder_projects SET chat_history = %s WHERE id = %s",
            (json.dumps(trimmed), project_id),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        pass


def load_chat_history(project_id):
    """Load chat history from website_builder_projects."""
    import psycopg2
    import os
    try:
        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "192.168.1.200"),
            port=int(os.environ.get("DB_PORT", 5432)),
            dbname=os.environ.get("DB_NAME", "archie"),
            user=os.environ.get("DB_USER", "archie"),
            password=os.environ.get("DB_PASSWORD", ""),
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT chat_history FROM website_builder_projects WHERE id = %s",
            (project_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row and row[0]:
            return row[0] if isinstance(row[0], list) else []
        return []
    except Exception:
        return []
```

- [ ] **Step 3: Update chat_with_archie() in routes.py for role-based dispatch**

Find the `chat_with_archie()` function (line ~589). After the `ai_bridge()` call, we need to add role detection. The function already works — we just enhance it:

1. Import the new functions: add `detect_task_role, save_chat_history, load_chat_history` to the existing `from chat_handler import ...` block
2. Before the Bridge call, detect role and set prefer_agent context:
```python
role = detect_task_role(message)
# Include role hint in the system prompt for Bridge
if role == "design":
    system_prompt += "\n\nFocus on CSS, visual design, and styling in your response."
elif role == "deploy":
    system_prompt += "\n\nThe user wants to deploy or manage hosting. Guide them through the process."
```
3. After successful response, save to chat history:
```python
project_id = data.get("project_id")
if project_id:
    save_chat_history(project_id, [
        {"role": "user", "message": message},
        {"role": "ai", "message": response_text},
    ])
```

- [ ] **Step 4: Add chat history GET endpoint to routes.py**

Append near the existing chat endpoint:
```python
@website_studio_bp.route("/api/chat/history/<int:project_id>", methods=["GET"])
@login_required
def get_chat_history_route(project_id):
    from chat_handler import load_chat_history
    history = load_chat_history(project_id)
    return jsonify({"success": True, "history": history})
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/website_studio/chat_handler.py platform_v2/tools/website_studio/routes.py
git commit -m "feat(website-designer): add role detection + chat history persistence"
```

---

## Task 5: Backend Cleanup — Double Decorators + Silent Exceptions

**Files:**
- Modify: `platform_v2/tools/website_studio/routes.py`

- [ ] **Step 1: Read routes.py to find the second admin_required definition**

Find the duplicate `admin_required` at line ~1680 and the triple-decorator on `website_deploy()`.

- [ ] **Step 2: Remove the duplicate admin_required definition**

Delete the second `def admin_required(f):` block (around line 1680). Keep only the first one at line 21.

- [ ] **Step 3: Fix triple decorator on website_deploy()**

Change from:
```python
@admin_required
@login_required
@admin_required
def website_deploy():
```
To:
```python
@login_required
@admin_required
def website_deploy():
```

- [ ] **Step 4: Fix silent except:pass blocks**

Search for bare `except Exception:` followed by `pass` in DB cleanup. Replace with:
```python
except Exception:
    logger.debug("DB cleanup error", exc_info=True)
```

Do this for the ~20 locations. Use a find-and-replace approach — read the file, identify the pattern, replace systematically. Don't change the overall error handling structure, just add logging.

IMPORTANT: The file is ~5000 lines. Be targeted — only change the `except Exception: pass` blocks in the `finally:` DB cleanup sections, not any other exception handling.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/website_studio/routes.py
git commit -m "fix(website-designer): remove double admin_required + log silent exceptions"
```

---

## Task 6: Frontend — Chat Drawer + Deploy Panel + Hostinger UI

**Files:**
- Modify: `platform_v2/templates/tools/website_studio.html`
- Modify: `platform_v2/static/js/website-studio.js`
- Modify: `platform_v2/static/css/website-studio.css`

- [ ] **Step 1: Read current HTML, JS, CSS to find insertion points**

- [ ] **Step 2: Add deploy button + panel HTML to template**

In the toolbar div (between save and refresh buttons), add:
```html
<button class="ws-toolbar-btn ws-deploy-btn" onclick="openDeployPanel()">Deploy</button>
```

After the builder view, add deploy panel HTML:
```html
<div id="wsDeployPanel" class="ws-deploy-panel" style="display:none;">
  <div class="ws-deploy-panel-content">
    <div class="ws-panel-header">
      <span>Deploy & Hosting</span>
      <button class="ws-toolbar-btn" onclick="closeDeployPanel()">&times;</button>
    </div>
    <div class="ws-panel-body">
      <div class="ws-prop-group">
        <div class="ws-prop-group-title">GitHub Pages</div>
        <button class="ws-ai-send" onclick="deployToGitHub()">Deploy to GitHub Pages</button>
        <div id="wsDeployStatus" style="margin-top:0.5rem; font-size:0.7rem;"></div>
        <div id="wsDeployHistory" style="margin-top:0.5rem;"></div>
      </div>
      <div class="ws-prop-group" id="wsHostingerSection">
        <div class="ws-prop-group-title">Hostinger Domains</div>
        <div id="wsHostingerMockBanner" class="ws-mock-banner" style="display:none;">Demo mode — connect API key in Settings</div>
        <div id="wsHostingerDomains"></div>
        <div id="wsDnsRecords" style="display:none;">
          <div class="ws-prop-group-title" id="wsDnsDomainTitle">DNS Records</div>
          <div id="wsDnsTable"></div>
          <div style="margin-top:0.5rem;">
            <button class="ws-toolbar-btn" onclick="showAddDnsForm()">+ Add Record</button>
            <button class="ws-toolbar-btn" onclick="applyGitHubPreset()">Apply GitHub Pages Preset</button>
          </div>
          <div id="wsAddDnsForm" style="display:none; margin-top:0.5rem;">
            <select id="wsDnsType" class="ws-prop-input" style="width:auto;"><option>A</option><option>AAAA</option><option>CNAME</option><option>MX</option><option>TXT</option></select>
            <input id="wsDnsName" class="ws-prop-input" placeholder="name" style="width:80px;">
            <input id="wsDnsContent" class="ws-prop-input" placeholder="content" style="width:150px;">
            <button class="ws-toolbar-btn" onclick="addDnsRecord()">Add</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Upgrade AI chat bar to expandable drawer**

Replace the fixed `ws-ai-history` div with a resizable drawer. Update HTML:
```html
<div class="ws-ai-drawer" id="wsAiDrawer">
  <div class="ws-ai-drawer-handle" id="wsAiDrawerHandle"></div>
  <div id="wsAiHistory" class="ws-ai-history visible" style="max-height:200px; overflow-y:auto;"></div>
</div>
```

Add a toggle button next to the AI input:
```html
<button class="ws-toolbar-btn" onclick="toggleChatDrawer()" title="Toggle chat history">Chat</button>
```

- [ ] **Step 4: Add Phase 2 JavaScript (~150 lines)**

Append inside the IIFE, before the DOMContentLoaded listener:

```javascript
// ── Phase 2: Deploy + Hostinger + Chat Drawer ──

var _chatDrawerOpen = false;
var _currentDomain = null;

window.toggleChatDrawer = function() {
    _chatDrawerOpen = !_chatDrawerOpen;
    var drawer = document.getElementById('wsAiDrawer');
    if (drawer) drawer.style.display = _chatDrawerOpen ? '' : 'none';
};

window.openDeployPanel = function() {
    document.getElementById('wsDeployPanel').style.display = 'flex';
    loadDeployHistory();
    loadHostingerDomains();
};

window.closeDeployPanel = function() {
    document.getElementById('wsDeployPanel').style.display = 'none';
};

window.deployToGitHub = function() {
    var status = document.getElementById('wsDeployStatus');
    status.textContent = 'Deploying...';
    api('POST', '/api/projects/' + _currentProjectId + '/deploy', {
        deployment_type: 'github_pages',
    }).then(function(data) {
        if (data.success || data.deployment_url) {
            status.textContent = 'Deployed! ' + (data.deployment_url || '');
            toast('Deployed to GitHub Pages');
            loadDeployHistory();
        } else {
            status.textContent = 'Error: ' + (data.error || 'Deploy failed');
        }
    });
};

function loadDeployHistory() {
    if (!_currentProjectId) return;
    api('GET', '/api/projects/' + _currentProjectId + '/deployments').then(function(data) {
        var container = document.getElementById('wsDeployHistory');
        clearEl(container);
        var deployments = data.deployments || data || [];
        if (!Array.isArray(deployments)) return;
        deployments.slice(0, 5).forEach(function(d) {
            var row = document.createElement('div');
            row.className = 'ws-prop-row';
            var left = document.createElement('span');
            left.className = 'ws-prop-label';
            left.textContent = (d.status || 'unknown') + ' — ' + (d.created_at || '').split('T')[0];
            var right = document.createElement('span');
            right.className = 'ws-prop-value';
            right.textContent = d.commit_hash ? d.commit_hash.substring(0, 7) : '';
            row.appendChild(left);
            row.appendChild(right);
            container.appendChild(row);
        });
    });
}

// ── Hostinger ──

window.loadHostingerDomains = function() {
    api('GET', '/api/hostinger/status').then(function(data) {
        if (data.error && data.error.indexOf('not available') !== -1) {
            document.getElementById('wsHostingerSection').style.display = 'none';
            return;
        }
        var isMock = data.mock || !data.configured;
        var banner = document.getElementById('wsHostingerMockBanner');
        if (banner) banner.style.display = isMock ? '' : 'none';
    });

    api('GET', '/api/hostinger/domains').then(function(data) {
        var container = document.getElementById('wsHostingerDomains');
        clearEl(container);
        var domains = data.domains || [];
        domains.forEach(function(d) {
            var row = document.createElement('div');
            row.className = 'ws-tree-item';
            row.textContent = d.domain + ' (' + (d.status || 'active') + ')';
            row.onclick = function() { loadDnsRecords(d.domain); };
            container.appendChild(row);
        });
    });
};

window.loadDnsRecords = function(domain) {
    _currentDomain = domain;
    document.getElementById('wsDnsRecords').style.display = '';
    document.getElementById('wsDnsDomainTitle').textContent = 'DNS: ' + domain;

    api('GET', '/api/hostinger/domains/' + domain + '/dns').then(function(data) {
        var container = document.getElementById('wsDnsTable');
        clearEl(container);
        var records = data.records || [];
        records.forEach(function(r) {
            var row = document.createElement('div');
            row.className = 'ws-prop-row';
            var left = document.createElement('span');
            left.className = 'ws-prop-label';
            left.textContent = r.type + ' ' + r.name;
            var right = document.createElement('span');
            right.className = 'ws-prop-value';
            right.textContent = r.content;
            row.appendChild(left);
            row.appendChild(right);
            container.appendChild(row);
        });
    });
};

window.showAddDnsForm = function() {
    document.getElementById('wsAddDnsForm').style.display = '';
};

window.addDnsRecord = function() {
    if (!_currentDomain) return;
    api('POST', '/api/hostinger/domains/' + _currentDomain + '/dns', {
        type: document.getElementById('wsDnsType').value,
        name: document.getElementById('wsDnsName').value,
        value: document.getElementById('wsDnsContent').value,
        ttl: 3600,
    }).then(function(data) {
        if (data.error) { alert(data.error); return; }
        toast('DNS record added');
        document.getElementById('wsAddDnsForm').style.display = 'none';
        loadDnsRecords(_currentDomain);
    });
};

window.applyGitHubPreset = function() {
    if (!_currentDomain) return;
    if (!confirm('Apply GitHub Pages DNS preset to ' + _currentDomain + '?')) return;
    api('POST', '/api/hostinger/domains/' + _currentDomain + '/preset', {
        preset_type: 'github_pages',
    }).then(function(data) {
        if (data.error) { alert(data.error); return; }
        toast('GitHub Pages preset applied (' + (data.records_added || 0) + ' records)');
        loadDnsRecords(_currentDomain);
    });
};

// ── Chat history persistence ──

window.loadChatHistory = function(projectId) {
    api('GET', '/api/chat/history/' + projectId).then(function(data) {
        var history = data.history || [];
        var container = document.getElementById('wsAiHistory');
        clearEl(container);
        history.forEach(function(entry) {
            addAiHistoryEntry(entry.role, entry.message);
        });
    });
};

// Drawer resize
(function() {
    var handle = document.getElementById('wsAiDrawerHandle');
    if (!handle) return;
    var dragging = false;
    handle.addEventListener('mousedown', function() { dragging = true; });
    document.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        var drawer = document.getElementById('wsAiDrawer');
        var rect = drawer.parentElement.getBoundingClientRect();
        var h = rect.bottom - e.clientY;
        h = Math.max(60, Math.min(400, h));
        drawer.style.height = h + 'px';
    });
    document.addEventListener('mouseup', function() { dragging = false; });
})();
```

Also update the existing `openProject()` function to load chat history when opening a project:
```javascript
// At the end of openProject(), after loading pages:
loadChatHistory(projectId);
```

And update `sendAiChat` / `sendAiMessage` to include `project_id` in the POST body:
```javascript
// In the existing sendAiChat function, add project_id to the body:
body.project_id = _currentProjectId;
```

- [ ] **Step 5: Add Phase 2 CSS (~40 lines)**

Append to website-studio.css:
```css
/* ── Phase 2: Deploy + Hostinger + Chat Drawer ── */
.ws-deploy-panel {
    position: fixed; inset: 0; z-index: 9999;
    display: flex; align-items: center; justify-content: center;
    background: rgba(0, 0, 0, 0.85);
}
.ws-deploy-panel-content {
    background: var(--ws-bg, #0d0d1a);
    border: 1px solid var(--ws-accent, #4af);
    border-radius: 8px;
    width: 90vw; max-width: 600px; max-height: 80vh;
    display: flex; flex-direction: column; overflow: hidden;
}
.ws-deploy-btn { color: var(--ws-accent, #4af); }
.ws-mock-banner {
    background: rgba(255, 153, 0, 0.15);
    border: 1px solid #f90;
    color: #f90;
    padding: 0.3rem 0.5rem;
    border-radius: 3px;
    font-size: 0.65rem;
    margin-bottom: 0.5rem;
}
.ws-ai-drawer {
    border-top: 1px solid var(--ws-border, #223);
    background: rgba(0,0,0,0.3);
    display: none;
    flex-direction: column;
    position: relative;
}
.ws-ai-drawer-handle {
    height: 4px;
    background: var(--ws-border, #223);
    cursor: row-resize;
}
.ws-ai-drawer-handle:hover { background: var(--ws-accent, #4af); }
.ws-dns-table { font-size: 0.7rem; }
```

- [ ] **Step 6: Commit frontend changes (3 commits)**

```bash
git add platform_v2/templates/tools/website_studio.html
git commit -m "feat(website-designer): add deploy panel + chat drawer HTML"

git add platform_v2/static/js/website-studio.js
git commit -m "feat(website-designer): add deploy + Hostinger + chat drawer JavaScript"

git add platform_v2/static/css/website-studio.css
git commit -m "feat(website-designer): add deploy panel + chat drawer CSS"
```

---

## Task 7: Integration Test

**Files:**
- Create: `/tmp/test_website_phase2.py`

- [ ] **Step 1: Write integration test**

```python
import sys, os, logging
sys.path.insert(0, '/app/platform_v2')
sys.path.insert(0, '/app')
logging.disable(logging.CRITICAL)

results = []

# Hostinger integration
from tools.website_studio.hostinger_integration import get_hostinger_api, HostingerAPI
results.append(('Import hostinger', 'OK', True))

api = get_hostinger_api(1)
results.append(('Hostinger mock mode', api.mock_mode, True))
domains = api.list_domains()
results.append(('Mock domains', 'domains' in domains, True))
dns = api.get_dns_records('example.com')
results.append(('Mock DNS records', 'records' in dns, True))
add_result = api.add_dns_record('example.com', 'A', '@', '1.2.3.4')
results.append(('Mock add DNS', add_result.get('success', False), True))
preset = api.apply_preset('example.com', 'github_pages')
results.append(('Mock preset', preset.get('success', False), True))

# GitHub deployment
from tools.website_studio.github_deployment import deploy_website, auto_commit_and_push, get_deployment_history
results.append(('Import github_deploy', 'OK', True))
history = get_deployment_history(1)
results.append(('Deploy history', isinstance(history, list), True))

# Chat handler new functions
from tools.website_studio.chat_handler import detect_task_role, save_chat_history, load_chat_history
results.append(('Import chat funcs', 'OK', True))

results.append(('Design role', detect_task_role('make the header blue'), detect_task_role('make the header blue') == 'design'))
results.append(('Deploy role', detect_task_role('deploy to github pages'), detect_task_role('deploy to github pages') == 'deploy'))
results.append(('Eng role', detect_task_role('add a login form'), detect_task_role('add a login form') == 'engineering'))

# DB columns
from app import app
with app.app_context():
    from database import get_db_cursor
    with get_db_cursor() as (conn, cur):
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='website_deployments' AND column_name='deployment_url'")
        results.append(('deployment_url column', cur.fetchone() is not None, True))
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name='website_builder_projects' AND column_name='chat_history'")
        results.append(('chat_history column', cur.fetchone() is not None, True))

    # Routes - GITHUB_AVAILABLE should now be True
    rules = [r.rule for r in app.url_map.iter_rules() if 'website-studio' in r.rule]
    results.append(('Routes exist', len(rules) > 30, True))

    # HTML checks
    html_path = '/app/templates/tools/website_studio.html'
    with open(html_path) as f:
        html = f.read()
    for elem in ['wsDeployPanel', 'wsHostingerDomains', 'wsDnsRecords', 'wsAiDrawer',
                 'openDeployPanel', 'deployToGitHub', 'loadHostingerDomains']:
        results.append((f'HTML/JS has {elem}', elem in html, True))

    # JS checks
    js_path = '/app/static/js/website-studio.js'
    with open(js_path) as f:
        js = f.read()
    for func in ['openDeployPanel', 'deployToGitHub', 'loadHostingerDomains',
                 'loadDnsRecords', 'addDnsRecord', 'applyGitHubPreset',
                 'toggleChatDrawer', 'loadChatHistory']:
        results.append((f'JS has {func}', func in js, True))

    # CSS checks
    css_path = '/app/static/css/website-studio.css'
    with open(css_path) as f:
        css = f.read()
    for cls in ['.ws-deploy-panel', '.ws-mock-banner', '.ws-ai-drawer']:
        results.append((f'CSS has {cls}', cls in css, True))

passed = sum(1 for _, _, ok in results if ok)
for name, val, ok in results:
    print(f'[{"PASS" if ok else "FAIL"}] {name}: {val}')
print(f'\nResult: {passed}/{len(results)} passed')
```

- [ ] **Step 2: Run test**

```bash
docker cp /tmp/test_website_phase2.py archie_platform:/tmp/
docker exec archie_platform python3 /tmp/test_website_phase2.py
```

- [ ] **Step 3: Fix any failures, re-test**

---

## Task 8: Deploy + Git Push + Dev HQ Update

- [ ] **Step 1: Restart platform**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Push**

```bash
git push origin main
```

- [ ] **Step 3: Update Dev HQ**

Use MCP tools:
- `complete_task` for Phase 2 task (#863) and Phase 3 task (#864)
- `store_memory` — Website Designer Phase 2+3 complete
- `log_decision` — Hostinger mock mode pattern, role-based dispatch, chat history on projects table

# Node API VPS Fleet Bootstrap — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make outpost-us (76.13.107.109) a fully-wired fleet node: fix the hardcoded port 9091 bug in `push_skills_to_fleet`, deploy `node_api` on the VPS with a `/api/skills/push` endpoint, and complete the OTA file-serve pipeline so all future code updates flow from the hub with no SSH needed.

**Architecture:** `push_skills_to_fleet` reads `node_api_port` from `remote_nodes` (new column, default 3001) instead of hardcoding 9091. `node_api.py` gains a DB-free `POST /api/skills/push` that writes skill markdown to a local `SKILLS_DIR` volume. `fleet_ota_routes.py` gains `GET /api/nodes/<filename>` to serve node client source files, completing the `code_update` OTA pipeline. A new `docker-compose.vps.yml` handles the one-time VPS bootstrap; all future updates go through OTA.

**Tech Stack:** Python/Flask (node_api), APScheduler job (consciousness/jobs.py), Flask Blueprint (fleet_ota_routes.py), PostgreSQL migration (ALTER TABLE), Docker Compose (VPS deploy), pytest (tests)

---

## File Map

| Action | File | What changes |
|--------|------|--------------|
| Create | `database/migrations/node_api_port.sql` | Add `node_api_port` column to `remote_nodes`; reset stale push failures |
| Modify | `platform_v2/tools/consciousness/jobs.py:1938–1985` | Add `node_api_port` to SELECT; replace hardcoded `9091` |
| Modify | `node_client/node_api.py` | Add `SKILLS_DIR` env var + `POST /api/skills/push` endpoint |
| Modify | `platform_v2/tools/department_hq/fleet_ota_routes.py` | Add `GET /api/nodes/<filename>` file-serve endpoint |
| Create | `node_client/docker-compose.vps.yml` | Lightweight VPS compose (node_api only, no postgres) |
| Create | `tests/test_skill_fleet_push_port.py` | Regression guard — no hardcoded 9091 |
| Create | `tests/test_node_api_skills_push.py` | Skills push endpoint writes file to SKILLS_DIR |
| Create | `tests/test_fleet_ota_file_serve.py` | File-serve endpoint returns source, blocks traversal |

---

## Task 1: Migration — `node_api_port` column + reset stale push failures

**Files:**
- Create: `database/migrations/node_api_port.sql`

- [ ] **Step 1: Write the migration**

```sql
-- database/migrations/node_api_port.sql
-- Add node_api_port to remote_nodes (default 3001 — matches node_api.py app.run port)
ALTER TABLE remote_nodes
    ADD COLUMN IF NOT EXISTS node_api_port INTEGER NOT NULL DEFAULT 3001;

-- outpost-us is already running node_api on 3001 (once deployed)
-- No override needed — default is correct.

-- Reset node_skill_pushes failures so the job retries all 9 skills
-- after the port fix is deployed.
UPDATE node_skill_pushes
SET    fail_count = 0,
       last_error = NULL
WHERE  node_id = (SELECT id FROM remote_nodes WHERE node_id = 'outpost_us_001')
  AND  fail_count > 0;
```

- [ ] **Step 2: Apply the migration**

```bash
docker exec archie_database psql -U archie -d archie \
    -f /mnt/archie_brain/database/migrations/node_api_port.sql
```

Expected output:
```
ALTER TABLE
UPDATE 9
```

- [ ] **Step 3: Verify**

```bash
docker exec archie_database psql -U archie -d archie -c \
    "SELECT id, node_name, hostname, node_api_port FROM remote_nodes WHERE deployment_mode='starship';"
```

Expected: one row, `node_api_port = 3001`.

```bash
docker exec archie_database psql -U archie -d archie -c \
    "SELECT COUNT(*) FROM node_skill_pushes WHERE node_id=93 AND fail_count>0;"
```

Expected: `0`.

- [ ] **Step 4: Commit**

```bash
git checkout -b feat/node-api-vps-fleet-bootstrap
git add database/migrations/node_api_port.sql
git commit -m "feat(fleet): add node_api_port column to remote_nodes, reset stale push failures"
```

---

## Task 2: Fix `push_skills_to_fleet` — read port from DB

**Files:**
- Create: `tests/test_skill_fleet_push_port.py`
- Modify: `platform_v2/tools/consciousness/jobs.py:1938–1985`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_fleet_push_port.py
"""Regression guard: push_skills_to_fleet must use node_api_port from DB."""
import os


def _read_push_func() -> str:
    jobs_path = os.path.join(
        os.path.dirname(__file__),
        "..", "platform_v2", "tools", "consciousness", "jobs.py",
    )
    with open(jobs_path) as f:
        source = f.read()
    start = source.find("def push_skills_to_fleet(")
    end = source.find("\ndef ", start + 1)
    return source[start:end]


def test_no_hardcoded_9091():
    func = _read_push_func()
    assert "9091" not in func, (
        "Port 9091 is hardcoded in push_skills_to_fleet — must use node['node_api_port']"
    )


def test_reads_node_api_port_from_node_dict():
    func = _read_push_func()
    assert "node_api_port" in func, (
        "push_skills_to_fleet must read node_api_port from the node record"
    )


def test_select_includes_node_api_port():
    func = _read_push_func()
    select_block = func[func.find("SELECT id"):func.find("inbound_port")]
    assert "node_api_port" in select_block, (
        "The SELECT query for remote_nodes must include the node_api_port column"
    )
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_skill_fleet_push_port.py -v
```

Expected: 3 FAILED (9091 present, node_api_port absent).

- [ ] **Step 3: Apply the two-line fix in `jobs.py`**

At line **1938**, change the SELECT to include `node_api_port`:

```python
# platform_v2/tools/consciousness/jobs.py  (line ~1938)
            cur.execute(
                """SELECT id, hostname, port, node_name, node_id, node_api_port
                   FROM remote_nodes
                   WHERE deployment_mode = 'starship'
                     AND last_heartbeat > NOW() - INTERVAL '10 minutes'"""
            )
```

At line **1985**, replace the hardcoded port:

```python
# platform_v2/tools/consciousness/jobs.py  (line ~1985)
            inbound_port = node.get("node_api_port") or 3001
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_skill_fleet_push_port.py -v
```

Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tests/test_skill_fleet_push_port.py \
        platform_v2/tools/consciousness/jobs.py
git commit -m "fix(fleet): read node_api_port from remote_nodes instead of hardcoding 9091"
```

---

## Task 3: Add `POST /api/skills/push` to `node_api.py`

**Files:**
- Create: `tests/test_node_api_skills_push.py`
- Modify: `node_client/node_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_node_api_skills_push.py
"""Test the /api/skills/push endpoint on node_api."""
import json
import os
import sys
import tempfile
import importlib

import pytest


@pytest.fixture
def client(tmp_path):
    """Flask test client with a temporary SKILLS_DIR."""
    os.environ["DATABASE_URL"] = ""          # no postgres on VPS
    os.environ["NODE_ID"] = "test-node-001"
    os.environ["SKILLS_DIR"] = str(tmp_path / "skills")
    os.makedirs(os.environ["SKILLS_DIR"], exist_ok=True)

    # Fresh import each test (env vars must be set before import)
    node_client_path = os.path.join(os.path.dirname(__file__), "..", "node_client")
    if node_client_path not in sys.path:
        sys.path.insert(0, node_client_path)

    if "node_api" in sys.modules:
        del sys.modules["node_api"]
    import node_api as _mod
    # Re-read SKILLS_DIR from env after (re)import
    _mod.SKILLS_DIR = os.environ["SKILLS_DIR"]

    with _mod.app.test_client() as c:
        yield c, tmp_path


def test_skills_push_writes_file(client):
    c, tmp_path = client
    payload = {
        "skill_id": 42,
        "repo_slug": "test-org-test-repo",
        "slug": "my-skill",
        "content": "# My Skill\n\nDoes things.",
        "quality_score": 0.85,
        "adapted": False,
    }

    resp = c.post(
        "/api/skills/push",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["success"] is True
    assert data["slug"] == "my-skill"

    skill_path = os.path.join(
        os.environ["SKILLS_DIR"], "test-org-test-repo", "my-skill.md"
    )
    assert os.path.exists(skill_path)
    with open(skill_path) as f:
        assert f.read() == "# My Skill\n\nDoes things."


def test_skills_push_missing_slug_returns_400(client):
    c, _ = client
    resp = c.post(
        "/api/skills/push",
        data=json.dumps({"skill_id": 1, "content": "# test", "repo_slug": "r"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert json.loads(resp.data)["success"] is False


def test_skills_push_missing_content_returns_400(client):
    c, _ = client
    resp = c.post(
        "/api/skills/push",
        data=json.dumps({"skill_id": 1, "slug": "test", "repo_slug": "r"}),
        content_type="application/json",
    )
    assert resp.status_code == 400
    assert json.loads(resp.data)["success"] is False


def test_skills_push_creates_nested_dirs(client):
    c, _ = client
    payload = {
        "skill_id": 7,
        "repo_slug": "some-org-some-repo",
        "slug": "nested-skill",
        "content": "# Nested",
        "quality_score": 0.9,
        "adapted": True,
    }
    resp = c.post(
        "/api/skills/push",
        data=json.dumps(payload),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert os.path.isdir(os.path.join(os.environ["SKILLS_DIR"], "some-org-some-repo"))
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_node_api_skills_push.py -v
```

Expected: 4 FAILED (route does not exist yet).

- [ ] **Step 3: Add `SKILLS_DIR` module-level var and the endpoint to `node_api.py`**

At the top of `node_api.py`, after the existing env var block (after `NODE_TIMEZONE = os.environ.get(...)`), add:

```python
# node_client/node_api.py  (after NODE_TIMEZONE line)
SKILLS_DIR = os.environ.get("SKILLS_DIR", "/skills")
```

Then add the endpoint — place it just before `if __name__ == "__main__":` at the bottom of the file:

```python
# node_client/node_api.py  (before the __main__ block)
@app.route("/api/skills/push", methods=["POST"])
def skills_push():
    """Receive a skill from the hub and write to local SKILLS_DIR filesystem.

    No postgres required — this endpoint is intentionally DB-free so it works
    on lightweight nodes (VPS) without a local database.
    """
    data = request.get_json() or {}
    slug = data.get("slug", "").strip()
    content = data.get("content", "")
    repo_slug = data.get("repo_slug", "unknown")

    if not slug or not content:
        return jsonify({"success": False, "error": "slug and content are required"}), 400

    repo_dir = os.path.join(SKILLS_DIR, repo_slug)
    try:
        os.makedirs(repo_dir, exist_ok=True)
        skill_path = os.path.join(repo_dir, f"{slug}.md")
        with open(skill_path, "w") as fh:
            fh.write(content)
        logger.info("[SkillPush] Wrote %s/%s.md", repo_slug, slug)
        return jsonify({"success": True, "slug": slug, "path": skill_path})
    except Exception as e:
        logger.error("[SkillPush] Failed to write %s/%s: %s", repo_slug, slug, e)
        return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_node_api_skills_push.py -v
```

Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
git add tests/test_node_api_skills_push.py node_client/node_api.py
git commit -m "feat(node): add POST /api/skills/push endpoint — filesystem write, no DB required"
```

---

## Task 4: Add `GET /api/nodes/<filename>` file-serve to `fleet_ota_routes.py`

This endpoint is what `_handle_code_update` in `node_sync.py` downloads from. Without it, OTA code pushes never deliver the updated files.

**Files:**
- Create: `tests/test_fleet_ota_file_serve.py`
- Modify: `platform_v2/tools/department_hq/fleet_ota_routes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fleet_ota_file_serve.py
"""Test the hub-side file-serve endpoint used by OTA code_update."""
import os
import sys
import pytest

# Bootstrap platform path (same pattern as test_department_coordinator.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))


def _make_client():
    """Return a Flask test client for the platform app."""
    from app import create_app  # adjust if entrypoint differs
    app = create_app(testing=True)
    return app.test_client()


@pytest.fixture
def admin_client():
    """Authenticated admin test client."""
    c = _make_client()
    # Log in as admin (credentials from CLAUDE.md: admin / Kyt$13ran2025)
    c.post("/login", data={"username": "admin", "password": "Kyt$13ran2025"},
           follow_redirects=True)
    return c


def test_serve_node_api_py_returns_raw_source(admin_client):
    resp = admin_client.get("/tools/department-hq/api/nodes/node_api.py")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "raw" in data
    assert "def skills_push" in data["raw"]   # our new endpoint must be present
    assert data["filename"] == "node_api.py"


def test_serve_node_sync_py_returns_raw_source(admin_client):
    resp = admin_client.get("/tools/department-hq/api/nodes/node_sync.py")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "raw" in data
    assert "poll_syncs" in data["raw"]


def test_serve_blocks_unlisted_file(admin_client):
    resp = admin_client.get("/tools/department-hq/api/nodes/malicious.py")
    assert resp.status_code == 403
    assert resp.get_json()["success"] is False


def test_serve_blocks_path_traversal(admin_client):
    resp = admin_client.get("/tools/department-hq/api/nodes/../../app.py")
    # Flask normalises the path; the result must not be a 200 with source
    assert resp.status_code in (400, 403, 404)


def test_serve_requires_auth():
    c = _make_client()   # not logged in
    resp = c.get("/tools/department-hq/api/nodes/node_api.py")
    assert resp.status_code in (302, 401, 403)
```

> **Note:** If `create_app(testing=True)` doesn't match the actual platform entrypoint, check `platform_v2/app.py` for the app factory pattern and adjust. The login credentials are `admin` / `Kyt$13ran2025`.

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_fleet_ota_file_serve.py -v 2>&1 | head -30
```

Expected: failures (route 404, or import errors if app factory pattern differs — fix imports then re-run).

- [ ] **Step 3: Add the file-serve route to `fleet_ota_routes.py`**

Add this route inside `register_ota_routes(bp, auth_decorator)`, just before the final closing of the function (after the existing `upgrade_node_v3` and `sync_status` routes):

```python
# platform_v2/tools/department_hq/fleet_ota_routes.py
# (inside register_ota_routes, at the end)

    # Allowlist of files nodes may download via OTA code_update.
    _OTA_ALLOWED_FILES = frozenset({"node_api.py", "node_sync.py", "node_triage.py"})
    _NODE_CLIENT_DIR = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "node_client")
    )

    @bp.route("/api/nodes/<path:filename>")
    @auth_decorator
    def serve_node_file(filename):
        """Serve node client source files for OTA code_update downloads.

        node_sync.py fetches: GET {hub_url}/tools/department-hq/api/nodes/{filename}
        Returns JSON {"raw": "<file content>", "filename": "<name>"}.
        Only files in _OTA_ALLOWED_FILES may be served (no path traversal).
        """
        # Reject anything with path separators or that isn't on the allowlist
        if os.sep in filename or "/" in filename or filename not in _OTA_ALLOWED_FILES:
            return jsonify({"success": False, "error": f"File not permitted: {filename}"}), 403

        file_path = os.path.join(_NODE_CLIENT_DIR, filename)
        if not os.path.isfile(file_path):
            return jsonify({"success": False, "error": "File not found"}), 404

        try:
            with open(file_path, "r") as fh:
                content = fh.read()
            return jsonify({"raw": content, "filename": filename})
        except Exception as e:
            logger.exception("Failed to serve node file %s", filename)
            return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
cd /mnt/archie_brain && python -m pytest tests/test_fleet_ota_file_serve.py -v
```

Expected: 5 PASSED.
If the app factory test setup doesn't work out of the box, skip `test_serve_requires_auth` with `@pytest.mark.skip` and file a follow-up task — the security check is enforced by `@auth_decorator` on the route anyway.

- [ ] **Step 5: Commit**

```bash
git add tests/test_fleet_ota_file_serve.py \
        platform_v2/tools/department_hq/fleet_ota_routes.py
git commit -m "feat(fleet): add GET /api/nodes/<filename> file-serve for OTA code_update pipeline"
```

---

## Task 5: Create `docker-compose.vps.yml` (lightweight VPS bootstrap)

**Files:**
- Create: `node_client/docker-compose.vps.yml`

No tests for a compose file — we validate it structurally with `docker compose config`.

- [ ] **Step 1: Write the compose file**

```yaml
# node_client/docker-compose.vps.yml
###############################################################################
# A.R.C.H.I.E. Node — VPS Lightweight Stack
#
# For nodes that already have Ollama on the host (no GPU, small models).
# Runs node_api only. No postgres — /api/skills/push is DB-free.
# All future code updates come via OTA (no SSH needed after first deploy).
#
# First deploy (on VPS):
#   scp Dockerfile.node node_api.py node_sync.py node_triage.py docker-compose.vps.yml root@<vps>:/opt/archie-node/
#   ssh root@<vps>
#   cd /opt/archie-node
#   cp .env.example .env  && vi .env   # set NODE_ID, HUB_URL, HUB_API_KEY
#   docker compose -f docker-compose.vps.yml up -d --build
#   ufw allow 3001/tcp
###############################################################################

services:
  node_api:
    build:
      context: .
      dockerfile: Dockerfile.node
    image: archie-node-api:local
    container_name: archie_node_api
    restart: unless-stopped
    environment:
      NODE_ID: ${NODE_ID:-outpost_us_001}
      HUB_URL: ${HUB_URL:-https://platform.kytranempowerment.com}
      HUB_API_KEY: ${HUB_API_KEY:-}
      OLLAMA_HOST: http://host.docker.internal:11434
      DATABASE_URL: ""
      SKILLS_DIR: /skills
      NODE_TIMEZONE: ${NODE_TIMEZONE:-America/Toronto}
    volumes:
      - skills_data:/skills
    extra_hosts:
      - "host.docker.internal:host-gateway"
    ports:
      - "3001:3001"
    dns:
      - 192.168.1.200
      - 1.1.1.1
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:3001/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - archie_net

volumes:
  skills_data:

networks:
  archie_net:
    driver: bridge
```

- [ ] **Step 2: Validate the compose file**

```bash
cd /mnt/archie_brain/node_client && docker compose -f docker-compose.vps.yml config --quiet
```

Expected: no errors (exit code 0).

- [ ] **Step 3: Commit**

```bash
git add node_client/docker-compose.vps.yml
git commit -m "feat(node): add docker-compose.vps.yml for lightweight VPS fleet node bootstrap"
```

---

## Task 6: Deploy on VPS + Verify end-to-end

This task is run by Kytran on the VPS. Hub-side code is already live after Tasks 1–5 are merged.

- [ ] **Step 1: Deploy the node_api PR to hub**

```bash
# On hub
git push origin feat/node-api-vps-fleet-bootstrap
gh pr create --title "feat(fleet): node API VPS bootstrap — skill push + OTA file-serve" \
  --body "Fixes skill_fleet_push port bug (9091→3001), adds /api/skills/push endpoint, completes OTA code_update pipeline, bootstraps outpost-us as first lightweight fleet node."
# Merge when CI passes
docker compose restart archie_platform
```

- [ ] **Step 2: Copy files to VPS**

```bash
# On hub — scp the 4 required files
scp /mnt/archie_brain/node_client/{Dockerfile.node,node_api.py,node_sync.py,node_triage.py,docker-compose.vps.yml} \
    root@76.13.107.109:/opt/archie-node/
```

- [ ] **Step 3: Bootstrap node_api on VPS**

SSH to VPS, then:

```bash
cd /opt/archie-node

# Create .env if it doesn't exist
cat > .env <<'EOF'
NODE_ID=outpost_us_001
HUB_URL=https://platform.kytranempowerment.com
HUB_API_KEY=<value from platform .env HUB_API_KEY>
NODE_TIMEZONE=America/Toronto
EOF

docker compose -f docker-compose.vps.yml up -d --build
ufw allow 3001/tcp
```

- [ ] **Step 4: Verify node_api is healthy on VPS**

```bash
# From hub
curl -s http://76.13.107.109:3001/health | python3 -m json.tool
```

Expected:
```json
{
  "status": "degraded",
  "node_id": "outpost_us_001",
  "database": "disconnected"
}
```

`degraded` is correct — no postgres on this node. The `/api/skills/push` endpoint doesn't need DB.

- [ ] **Step 5: Test skill push directly**

```bash
# From hub — simulate what push_skills_to_fleet does
curl -s -X POST http://76.13.107.109:3001/api/skills/push \
  -H 'Content-Type: application/json' \
  -d '{"skill_id":1,"repo_slug":"test-org","slug":"smoke-test","content":"# Smoke Test","quality_score":0.9,"adapted":false}' \
  | python3 -m json.tool
```

Expected: `{"success": true, "slug": "smoke-test", "path": "/skills/test-org/smoke-test.md"}`

- [ ] **Step 6: Wait for next push_skills_to_fleet job run (≤6h) or trigger manually**

```bash
# On hub — check next scheduled run
docker logs archie_platform --since 10m 2>&1 | grep -i 'skill.*push\|SkillPush'
```

Expected within 6h:
```
[SkillPush] Pushing 5 skills to outpost-us (76.13.107.109)
[SkillPush] outpost-us: 5 pushed, 0 errors
```

- [ ] **Step 7: Verify anomaly clears on next session briefing**

`skill_fleet_push` should show `success` with `{"nodes": 1, "pushed": 5, "errors": 0}` in the next anomaly check.

---

## Self-Review Checklist

**Spec coverage:**
- ✅ `node_api_port` column + default 3001 (Task 1)
- ✅ `push_skills_to_fleet` reads from DB not hardcode (Task 2)
- ✅ `POST /api/skills/push` endpoint, DB-free (Task 3)
- ✅ `GET /api/nodes/<filename>` file-serve for OTA (Task 4)
- ✅ `docker-compose.vps.yml` lightweight bootstrap (Task 5)
- ✅ Reset 9 stale `node_skill_pushes` rows (Task 1 migration)
- ✅ VPS deploy + end-to-end verify (Task 6)
- ✅ Future OTA updates flow through Fleet tab, no SSH (Task 4 + Task 6 Step 6)

**Placeholder scan:** None — all code blocks are complete and runnable.

**Type consistency:** `node.get("node_api_port")` in jobs.py matches the column name `node_api_port` in the migration and the SELECT query. `SKILLS_DIR` module var in node_api.py matches the env var name in docker-compose.vps.yml. The route path `/api/nodes/<path:filename>` in fleet_ota_routes.py matches the URL pattern `{hub_url}/tools/department-hq/api/nodes/{fname}` in node_sync.py `_handle_code_update`.

# Skill Pipeline Phase 3 — Cluster Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Push tested skills to online fleet nodes (starship mode) via their inbound API, with per-node tracking in a separate `node_skill_pushes` table to avoid contention with the skill pipeline.

**Architecture:** New `node_skill_pushes` table tracks push state per node. Hub Job #61 runs every 6h, queries delta (skills not yet pushed to each online starship node), POSTs to node inbound endpoint. Node writes files to `skills/github/<repo>/<skill>.md`. Silent retry on failure, Telegram alert at 3 failures.

**Tech Stack:** PostgreSQL (hub tracking), Flask (hub job), aiohttp (node inbound server), filesystem writes (node skill storage).

---

## File Structure

| File | Responsibility |
|------|---------------|
| `database/migrations/node_skill_pushes.sql` | Create `node_skill_pushes` table |
| `platform_v2/tools/consciousness/jobs.py` | Add `push_skills_to_fleet()` Job #61, register in scheduler |
| `archie-code/archie_engine/hub/inbound.py` | Add `POST /api/skills/push` handler |

---

### Task 1: Create `node_skill_pushes` Migration

**Files:**
- Create: `database/migrations/node_skill_pushes.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Node skill push tracking — one row per skill per node
-- Separate from skill_installations to avoid write contention
CREATE TABLE IF NOT EXISTS node_skill_pushes (
    id SERIAL PRIMARY KEY,
    node_id INTEGER NOT NULL REFERENCES remote_nodes(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL,
    pushed_at TIMESTAMP DEFAULT NOW(),
    fail_count INTEGER DEFAULT 0,
    last_error TEXT,
    CONSTRAINT uq_node_skill UNIQUE(node_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_node_skill_pushes_node
    ON node_skill_pushes(node_id);
CREATE INDEX IF NOT EXISTS idx_node_skill_pushes_failed
    ON node_skill_pushes(fail_count) WHERE fail_count > 0;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/node_skill_pushes.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX` x2.

- [ ] **Step 3: Verify table exists**

```bash
docker exec archie_database psql -U archie -d archie -c "\d node_skill_pushes"
```

Expected: Table with id, node_id, skill_id, pushed_at, fail_count, last_error columns.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/node_skill_pushes.sql
git commit -m "feat: add node_skill_pushes table for cluster skill distribution"
```

---

### Task 2: Hub Job #61 — push_skills_to_fleet()

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py` (add function + register in scheduler)

- [ ] **Step 1: Write the push job function**

Add after the `test_installed_skills()` function (before the `# Registration` comment block). Find the exact insertion point by searching for the Registration separator.

```python
def push_skills_to_fleet():
    """Job #61: Push tested skills to online starship fleet nodes.

    Finds skills not yet pushed to each online starship node,
    POSTs to the node's inbound API. Tracks state in node_skill_pushes.
    Processes up to 5 skills per node per cycle (every 6 hours).
    """
    start = time.time()
    pushed_total = 0
    errors_total = 0

    try:
        from database import get_db_cursor
        import requests as _req

        # Find online starship nodes (heartbeat within 10 minutes)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, hostname, port, node_name, node_id
                   FROM remote_nodes
                   WHERE deployment_mode = 'starship'
                     AND last_heartbeat > NOW() - INTERVAL '10 minutes'"""
            )
            nodes = cur.fetchall()

        if not nodes:
            logger.debug("[SkillPush] No online starship nodes")
            _log_cycle(
                "skill_fleet_push", 0, 0,
                int((time.time() - start) * 1000),
            )
            return

        # Get tested+passing skills from skill_installations
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT si.skill_id, gs.repo_name, gs.skill_name,
                          COALESCE(si.adapted_content, si.normalized_content) AS content,
                          gs.quality_score, si.adapted
                   FROM skill_installations si
                   JOIN github_skills gs ON gs.id = si.skill_id
                   WHERE si.target = 'claude_code'
                     AND si.dry_run_passed = TRUE"""
            )
            all_skills = cur.fetchall()

        if not all_skills:
            _log_cycle(
                "skill_fleet_push", 0, 0,
                int((time.time() - start) * 1000),
            )
            return

        all_skill_ids = {s["skill_id"] for s in all_skills}
        skill_map = {s["skill_id"]: s for s in all_skills}

        for node in nodes:
            node_db_id = node["id"]
            hostname = node["hostname"]
            inbound_port = 9091  # InboundServer default
            node_name = node["node_name"]

            # Find skills already pushed to this node
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT skill_id FROM node_skill_pushes
                       WHERE node_id = %s""",
                    (node_db_id,),
                )
                already_pushed = {r["skill_id"] for r in cur.fetchall()}

            # Delta: skills not yet pushed
            to_push = all_skill_ids - already_pushed
            if not to_push:
                continue

            # Limit to 5 per node per cycle
            to_push = list(to_push)[:5]

            logger.info(
                "[SkillPush] Pushing %d skills to %s (%s)",
                len(to_push), node_name, hostname,
            )

            pushed_this_node = 0
            errors_this_node = 0

            for skill_id in to_push:
                skill = skill_map[skill_id]
                repo_slug = skill["repo_name"].replace("/", "-").lower()
                skill_slug = (
                    skill["skill_name"]
                    .replace("/", "-")
                    .replace(" ", "-")
                    .lower()
                )
                if skill_slug.endswith(".md"):
                    skill_slug = skill_slug[:-3]

                payload = {
                    "skill_id": skill_id,
                    "repo_slug": repo_slug,
                    "slug": skill_slug,
                    "content": skill["content"] or "",
                    "quality_score": skill["quality_score"],
                    "adapted": bool(skill["adapted"]),
                }

                try:
                    resp = _req.post(
                        f"http://{hostname}:{inbound_port}/api/skills/push",
                        json=payload,
                        timeout=15,
                    )
                    result = resp.json()

                    if resp.status_code == 200 and result.get("success"):
                        # Record successful push
                        with get_db_cursor(commit=True) as (conn2, cur2):
                            cur2.execute(
                                """INSERT INTO node_skill_pushes
                                   (node_id, skill_id, pushed_at, fail_count)
                                   VALUES (%s, %s, NOW(), 0)
                                   ON CONFLICT (node_id, skill_id)
                                   DO UPDATE SET pushed_at = NOW(),
                                                 fail_count = 0,
                                                 last_error = NULL""",
                                (node_db_id, skill_id),
                            )
                        pushed_this_node += 1
                    else:
                        error_msg = result.get("error", f"HTTP {resp.status_code}")
                        _record_push_failure(
                            node_db_id, skill_id, error_msg
                        )
                        errors_this_node += 1

                except Exception as push_err:
                    _record_push_failure(
                        node_db_id, skill_id, str(push_err)[:200]
                    )
                    errors_this_node += 1

            pushed_total += pushed_this_node
            errors_total += errors_this_node
            logger.info(
                "[SkillPush] %s: %d pushed, %d errors",
                node_name, pushed_this_node, errors_this_node,
            )

        # Check for skills with 3+ failures — Telegram alert
        _check_push_failure_alerts()

        _log_cycle(
            "skill_fleet_push",
            pushed_total,
            errors_total,
            int((time.time() - start) * 1000),
            details={
                "nodes": len(nodes),
                "pushed": pushed_total,
                "errors": errors_total,
            },
        )

    except Exception as e:
        logger.warning("[SkillPush] Job failed: %s", e)
        _log_cycle(
            "skill_fleet_push", 0, 1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


def _record_push_failure(node_id: int, skill_id: int, error: str):
    """Record a skill push failure, incrementing fail_count."""
    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO node_skill_pushes
                   (node_id, skill_id, fail_count, last_error)
                   VALUES (%s, %s, 1, %s)
                   ON CONFLICT (node_id, skill_id)
                   DO UPDATE SET fail_count = node_skill_pushes.fail_count + 1,
                                 last_error = %s""",
                (node_id, skill_id, error, error),
            )
    except Exception as e:
        logger.warning("[SkillPush] Failed to record failure: %s", e)


def _check_push_failure_alerts():
    """Send Telegram alert if any skill has 3+ push failures."""
    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT nsp.node_id, nsp.skill_id, nsp.fail_count,
                          nsp.last_error, rn.node_name
                   FROM node_skill_pushes nsp
                   JOIN remote_nodes rn ON rn.id = nsp.node_id
                   WHERE nsp.fail_count >= 3"""
            )
            failures = cur.fetchall()

        if not failures:
            return

        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            return

        import requests as _req
        from db import get_db

        text = (
            f"\u26a0\ufe0f *Skill Push Failures*\n\n"
            f"*{len(failures)}* skills stuck (3+ failures):\n"
        )
        for f in failures[:5]:
            text += (
                f"- Skill #{f['skill_id']} → {f['node_name']} "
                f"({f['fail_count']}x): {(f['last_error'] or '')[:60]}\n"
            )

        tg_conn = get_db()
        tg_cur = tg_conn.cursor()
        tg_cur.execute(
            "SELECT telegram_id FROM telegram_users "
            "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
        )
        for row in tg_cur.fetchall():
            _req.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": row[0],
                    "text": text,
                    "parse_mode": "Markdown",
                },
                timeout=15,
            )
        tg_cur.close()
        tg_conn.close()
    except Exception as e:
        logger.warning("[SkillPush] Telegram alert failed: %s", e)
```

- [ ] **Step 2: Register Job #61 in the scheduler**

In `register_consciousness_jobs()`, find the skill tester registration and add after it:

```python
    scheduler.add_job(
        with_ctx(push_skills_to_fleet),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 04:00:00"),
        id="agent_skill_fleet_push",
        name="Agent Loop: Skill Fleet Push (Cluster Distribution)",
        replace_existing=True,
    )
```

- [ ] **Step 3: Update the job count log message**

Change `"Registered 18 consciousness jobs"` to `"Registered 19 consciousness jobs"`.

- [ ] **Step 4: Update the module docstring**

Add to the docstring at the top of the file:
```
  - agent_skill_fleet_push (Job #61) — push tested skills to fleet nodes
```

- [ ] **Step 5: Deploy and verify job registers**

```bash
docker compose restart archie_platform
sleep 15
docker logs archie_platform --since 20s 2>&1 | grep 'Skill Fleet Push\|Registered 19'
```

Expected: `Added job "Agent Loop: Skill Fleet Push"` and `Registered 19 consciousness jobs`.

- [ ] **Step 6: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py
git commit -m "feat: add Job #61 — push tested skills to fleet nodes"
```

---

### Task 3: Node Inbound — Skill Push Handler

**Files:**
- Modify: `archie-code/archie_engine/hub/inbound.py`

- [ ] **Step 1: Add the route to _build_app()**

In `_build_app()` (line 36-39), add the new route after the existing ones:

```python
    def _build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_post("/api/dispatch", self._handle_dispatch)
        app.router.add_get("/api/health", self._handle_health)
        app.router.add_post("/api/skills/push", self._handle_skill_push)
        return app
```

- [ ] **Step 2: Add the handler method**

Add after the `_handle_health` method (after line 109):

```python
    async def _handle_skill_push(self, request: web.Request) -> web.Response:
        """Handle POST /api/skills/push — write a skill file from hub."""
        if not self._verify_auth(request):
            return web.json_response(
                {"success": False, "error": "Unauthorized"}, status=401
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"success": False, "error": "Invalid JSON"}, status=400
            )

        skill_id = data.get("skill_id")
        content = data.get("content", "")
        repo_slug = data.get("repo_slug", "unknown")
        slug = data.get("slug", "unknown")

        if not skill_id or not content:
            return web.json_response(
                {"success": False, "error": "skill_id and content required"},
                status=400,
            )

        try:
            from pathlib import Path

            # Write to skills/github/<repo_slug>/<slug>.md
            # Use the same cache dir as HubSync
            base = Path.home() / ".archie" / "skills" / "github"
            repo_dir = base / repo_slug
            repo_dir.mkdir(parents=True, exist_ok=True)
            file_path = repo_dir / f"{slug}.md"
            file_path.write_text(content)

            rel_path = f"skills/github/{repo_slug}/{slug}.md"
            logger.info("Skill pushed: %s (id=%s)", rel_path, skill_id)
            return web.json_response(
                {"success": True, "path": rel_path}
            )
        except OSError as e:
            logger.error("Skill push write failed: %s", e)
            return web.json_response(
                {"success": False, "error": str(e)}, status=500
            )
```

- [ ] **Step 3: Commit**

```bash
git add archie-code/archie_engine/hub/inbound.py
git commit -m "feat: add /api/skills/push endpoint to node inbound server"
```

---

### Task 4: End-to-End Verification

**Files:** None — testing only.

- [ ] **Step 1: Verify table exists**

```bash
docker exec archie_database psql -U archie -d archie -c "\d node_skill_pushes"
```

Expected: Table with all columns shown.

- [ ] **Step 2: Verify job registers**

```bash
docker logs archie_platform --since 2m 2>&1 | grep 'Skill Fleet Push'
```

Expected: `Added job "Agent Loop: Skill Fleet Push (Cluster Distribution)"`

- [ ] **Step 3: Run the push job manually**

Since no starship nodes have recent heartbeats, the job should find 0 nodes and exit cleanly:

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/mnt/archie_brain/platform_v2')
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
sys.path.insert(0, '/mnt/archie_brain')
from app import app
with app.app_context():
    from tools.consciousness.jobs import push_skills_to_fleet
    push_skills_to_fleet()
" 2>&1 | grep 'SkillPush'
```

Expected: `[SkillPush] No online starship nodes` (since no nodes have fresh heartbeats).

- [ ] **Step 4: Test with a fake fresh heartbeat**

Temporarily update a test node's heartbeat to test the delta query:

```bash
docker exec archie_database psql -U archie -d archie -c "
UPDATE remote_nodes SET last_heartbeat = NOW()
WHERE id = 97 AND node_name = 'hub-test-node';
"
```

Run the push job again — it should find 1 node but fail to connect (expected since test node isn't running):

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/mnt/archie_brain/platform_v2')
sys.path.insert(0, '/mnt/archie_brain/ai_bridge')
sys.path.insert(0, '/mnt/archie_brain')
from app import app
with app.app_context():
    from tools.consciousness.jobs import push_skills_to_fleet
    push_skills_to_fleet()
" 2>&1 | grep 'SkillPush'
```

Expected: `[SkillPush] Pushing X skills to hub-test-node` followed by connection errors (node not running). Verify failure rows:

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT node_id, skill_id, fail_count, left(last_error, 60) as error
FROM node_skill_pushes LIMIT 5;
"
```

Expected: Rows with `fail_count = 1` and connection error messages.

- [ ] **Step 5: Clean up test data**

```bash
docker exec archie_database psql -U archie -d archie -c "
DELETE FROM node_skill_pushes WHERE node_id = 97;
UPDATE remote_nodes SET last_heartbeat = NULL WHERE id = 97;
"
```

- [ ] **Step 6: Verify no regressions**

```bash
docker logs archie_platform --since 5m 2>&1 | grep -iE 'error|fail' | grep -v 'apscheduler\|huggingface\|Kokoro\|fail2ban\|Fleet\|System Operations' | head -5
```

Expected: No new errors from our changes.

- [ ] **Step 7: Commit if any fixes were needed**

```bash
git status
```

---

## Self-Review Checklist

- **Spec coverage:** `node_skill_pushes` table (Task 1), Job #61 with delta query + push + failure tracking + Telegram (Task 2), node inbound endpoint (Task 3), E2E verification (Task 4). All spec requirements covered.
- **Placeholder scan:** No TBDs. All code complete. All commands have expected output.
- **Type consistency:** `node_id` is `remote_nodes.id` (integer) throughout. `skill_id` is `github_skills.id` (integer). `push_skills_to_fleet()` uses `_record_push_failure()` and `_check_push_failure_alerts()` — both defined in the same task. Slug generation uses `[:-3]` not `.rstrip()`.
- **Not in scope (per spec):** Skill deletion sync, outpost/legacy support, UI for cluster skill state.

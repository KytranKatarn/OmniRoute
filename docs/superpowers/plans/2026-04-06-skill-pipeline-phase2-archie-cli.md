# Skill Pipeline Phase 2 — Archie CLI Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable Archie CLI instances to sync tested skills from the hub via API, writing them to the same `github/<repo>/<skill>.md` structure as Claude Code, with confirmed install tracking.

**Architecture:** Two new hub API endpoints (sync + confirm) in `github_repo_routes.py`. Extended `HubSync.sync_skills()` in Archie CLI with incremental timestamps, repo-structured writes, and confirmation POST. One-line `SkillLoader` fix for recursive glob. Startup auto-sync when hub is configured.

**Tech Stack:** Flask (hub API), aiohttp (CLI HTTP client), PostgreSQL (`skill_installations` table), YAML frontmatter markdown files.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `platform_v2/tools/consciousness/github_repo_routes.py` | Add `GET /api/github/skills/sync` and `POST /api/github/skills/sync-confirm` endpoints |
| `archie-code/archie_engine/hub/sync.py` | Rewrite `sync_skills()` with incremental fetch, repo-structured writes, confirmation, token persistence |
| `archie-code/archie_engine/hub/connector.py` | Add `sync_skills()` and `confirm_skill_sync()` convenience methods |
| `archie-code/archie_engine/skills/loader.py` | Change `glob("*.md")` to `glob("**/*.md")` for recursive loading |
| `archie-code/archie_engine/__main__.py` | No change needed — startup already calls `hub_sync.sync_all()` which calls `sync_skills()` |

---

### Task 1: Hub API — Skill Sync Endpoint

**Files:**
- Modify: `platform_v2/tools/consciousness/github_repo_routes.py` (after line 1185, the `pipeline-stats` endpoint)

- [ ] **Step 1: Add the GET /api/github/skills/sync endpoint**

Insert after the `api_github_skills_pipeline_stats` function (after line 1185):

```python
    @bp.route("/api/github/skills/sync")
    @login_or_api_key
    def api_github_skills_sync():
        """Return tested+passing skills for CLI sync.

        Params:
            since: ISO timestamp — only return skills newer than this
            limit: int — max skills per response (default 50, max 200)
        """
        try:
            from database import get_db_cursor

            since = request.args.get("since")
            limit = min(int(request.args.get("limit", 50)), 200)

            with get_db_cursor() as (conn, cur):
                # Total available (for pagination awareness)
                cur.execute(
                    """SELECT COUNT(*) as total
                       FROM skill_installations si
                       WHERE si.target = 'claude_code'
                         AND si.dry_run_passed = TRUE"""
                )
                total_available = cur.fetchone()["total"]

                # Fetch skills with optional since filter
                if since:
                    cur.execute(
                        """SELECT si.skill_id, gs.repo_name, gs.skill_name,
                                  COALESCE(si.adapted_content, si.normalized_content) AS content,
                                  gs.quality_score, si.adapted,
                                  si.installed_at::text, si.tested_at::text
                           FROM skill_installations si
                           JOIN github_skills gs ON gs.id = si.skill_id
                           WHERE si.target = 'claude_code'
                             AND si.dry_run_passed = TRUE
                             AND si.installed_at > %s
                           ORDER BY si.installed_at ASC
                           LIMIT %s""",
                        (since, limit),
                    )
                else:
                    cur.execute(
                        """SELECT si.skill_id, gs.repo_name, gs.skill_name,
                                  COALESCE(si.adapted_content, si.normalized_content) AS content,
                                  gs.quality_score, si.adapted,
                                  si.installed_at::text, si.tested_at::text
                           FROM skill_installations si
                           JOIN github_skills gs ON gs.id = si.skill_id
                           WHERE si.target = 'claude_code'
                             AND si.dry_run_passed = TRUE
                           ORDER BY si.installed_at ASC
                           LIMIT %s""",
                        (limit,),
                    )
                rows = cur.fetchall()

            skills = []
            max_installed_at = None
            for row in rows:
                repo_slug = row["repo_name"].replace("/", "-").lower()
                skill_slug = (
                    row["skill_name"]
                    .replace("/", "-")
                    .replace(" ", "-")
                    .lower()
                    .rstrip(".md")
                )
                skills.append(
                    {
                        "skill_id": row["skill_id"],
                        "repo": row["repo_name"],
                        "name": row["skill_name"],
                        "slug": skill_slug,
                        "repo_slug": repo_slug,
                        "content": row["content"] or "",
                        "quality_score": row["quality_score"],
                        "adapted": bool(row["adapted"]),
                        "installed_at": row["installed_at"],
                        "tested_at": row["tested_at"],
                    }
                )
                max_installed_at = row["installed_at"]

            return jsonify(
                {
                    "success": True,
                    "skills": skills,
                    "sync_token": max_installed_at,
                    "total_available": total_available,
                }
            )
        except Exception as e:
            logger.error(f"[GitHub] Skill sync error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 2: Verify `request` is imported**

Check top of `github_repo_routes.py` for `from flask import request`. It should already be imported. If not, add it alongside `jsonify`.

- [ ] **Step 3: Deploy and test the endpoint**

```bash
docker compose restart archie_platform
sleep 15
```

Test via curl or browser: `http://192.168.1.200:3000/tools/consciousness/api/github/skills/sync`

Expected: JSON with `success: true`, `skills` array containing tested+passing skills, `sync_token`, `total_available`.

Test with `since` parameter: `http://192.168.1.200:3000/tools/consciousness/api/github/skills/sync?since=2026-01-01T00:00:00`

Expected: Same result (all skills are newer than 2026-01-01).

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/github_repo_routes.py
git commit -m "feat: add GET /api/github/skills/sync endpoint for Archie CLI"
```

---

### Task 2: Hub API — Sync Confirm Endpoint

**Files:**
- Modify: `platform_v2/tools/consciousness/github_repo_routes.py` (after the sync endpoint from Task 1)

- [ ] **Step 1: Add the POST /api/github/skills/sync-confirm endpoint**

Insert after the `api_github_skills_sync` function:

```python
    @bp.route("/api/github/skills/sync-confirm", methods=["POST"])
    @login_or_api_key
    def api_github_skills_sync_confirm():
        """Record confirmed skill installations from CLI nodes.

        Body: {"skill_ids": [int, ...], "node_id": "hub"}
        Creates skill_installations rows with target='archie_cli'.
        """
        try:
            from database import get_db_cursor
            import json as _json

            data = request.get_json(force=True)
            skill_ids = data.get("skill_ids", [])
            node_id = data.get("node_id", "unknown")

            if not skill_ids:
                return jsonify({"success": True, "confirmed": 0})

            confirmed = 0
            with get_db_cursor(commit=True) as (conn, cur):
                for skill_id in skill_ids:
                    # Build install path from the claude_code installation
                    cur.execute(
                        """SELECT install_path, normalized_content, adapted_content
                           FROM skill_installations
                           WHERE skill_id = %s AND target = 'claude_code'""",
                        (skill_id,),
                    )
                    source = cur.fetchone()
                    if not source:
                        continue

                    # Mirror the path for archie_cli target
                    cli_path = (
                        source["install_path"]
                        .replace(".claude/skills/github/", "skills/github/")
                    )

                    cur.execute(
                        """INSERT INTO skill_installations
                           (skill_id, target, install_path,
                            normalized_content, adapted_content,
                            struct_valid, dry_run_passed,
                            adapted, installed_at)
                           VALUES (%s, 'archie_cli', %s, %s, %s,
                                   TRUE, TRUE, %s, NOW())
                           ON CONFLICT (skill_id, target) DO UPDATE
                           SET install_path = EXCLUDED.install_path,
                               installed_at = NOW()""",
                        (
                            skill_id,
                            cli_path,
                            source["normalized_content"],
                            source["adapted_content"],
                            source["adapted_content"] is not None,
                        ),
                    )
                    confirmed += 1

            logger.info(
                f"[GitHub] Skill sync confirmed: {confirmed} skills "
                f"for node '{node_id}'"
            )
            return jsonify({"success": True, "confirmed": confirmed})
        except Exception as e:
            logger.error(f"[GitHub] Sync confirm error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 2: Deploy and test**

```bash
docker compose restart archie_platform
sleep 15
```

Test with curl (use a known skill_id from the DB):
```bash
curl -X POST http://192.168.1.200:3000/tools/consciousness/api/github/skills/sync-confirm \
  -H "Content-Type: application/json" \
  -d '{"skill_ids": [], "node_id": "test"}'
```

Expected: `{"success": true, "confirmed": 0}`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/github_repo_routes.py
git commit -m "feat: add POST /api/github/skills/sync-confirm for CLI install tracking"
```

---

### Task 3: CLI — Connector Methods

**Files:**
- Modify: `archie-code/archie_engine/hub/connector.py` (add two methods after `get_skills()` at line 138)

- [ ] **Step 1: Add sync_skills and confirm_skill_sync methods**

Add after the existing `get_skills()` method (line 138):

```python
    async def sync_skills(
        self, since: str | None = None, limit: int = 50
    ) -> dict:
        """Fetch tested skills for sync from hub.

        Args:
            since: ISO timestamp — only skills newer than this
            limit: max skills per response
        """
        params = {"limit": str(limit)}
        if since:
            params["since"] = since
        return await self.get(
            "/tools/consciousness/api/github/skills/sync", params=params
        )

    async def confirm_skill_sync(
        self, skill_ids: list[int], node_id: str = "hub"
    ) -> dict:
        """Confirm successful skill installations to hub."""
        return await self.post(
            "/tools/consciousness/api/github/skills/sync-confirm",
            data={"skill_ids": skill_ids, "node_id": node_id},
        )
```

- [ ] **Step 2: Commit**

```bash
git add archie-code/archie_engine/hub/connector.py
git commit -m "feat: add sync_skills() and confirm_skill_sync() to HubConnector"
```

---

### Task 4: CLI — Rewrite sync_skills() in HubSync

**Files:**
- Modify: `archie-code/archie_engine/hub/sync.py` (rewrite `sync_skills()` method, update `get_cached_skills()`)

- [ ] **Step 1: Rewrite sync_skills() method**

Replace the existing `sync_skills()` method (lines 18-33) with:

```python
    async def sync_skills(self) -> int:
        """Sync tested skills from hub with incremental timestamps.

        Downloads skills to cache_dir/skills/github/<repo-slug>/<skill>.md,
        confirms successful writes back to hub.
        Returns count of newly synced skills.
        """
        skills_dir = self.cache_dir / "skills" / "github"
        skills_dir.mkdir(parents=True, exist_ok=True)

        # Read last sync token
        token_file = self.cache_dir / ".skill_sync_token"
        since = None
        if token_file.exists():
            since = token_file.read_text().strip() or None

        total_synced = 0

        while True:
            result = await self.connector.sync_skills(
                since=since, limit=50
            )
            if "error" in result:
                logger.warning("Skill sync failed: %s", result["error"])
                break

            skills = result.get("skills", [])
            if not skills:
                break

            # Write files and collect confirmed IDs
            confirmed_ids = []
            for skill in skills:
                repo_slug = skill.get("repo_slug", "unknown")
                skill_slug = skill.get("slug", "unknown")

                repo_dir = skills_dir / repo_slug
                repo_dir.mkdir(parents=True, exist_ok=True)
                file_path = repo_dir / f"{skill_slug}.md"

                try:
                    content = skill.get("content", "")
                    if content:
                        file_path.write_text(content)
                        confirmed_ids.append(skill["skill_id"])
                except OSError as e:
                    logger.warning(
                        "Failed to write skill %s: %s",
                        skill.get("name", "unknown"),
                        e,
                    )

            # Confirm successful installs to hub
            if confirmed_ids:
                node_id = self._get_node_id()
                confirm_result = await self.connector.confirm_skill_sync(
                    skill_ids=confirmed_ids, node_id=node_id
                )
                if "error" in confirm_result:
                    logger.warning(
                        "Skill sync confirm failed: %s",
                        confirm_result["error"],
                    )

            total_synced += len(confirmed_ids)
            since = result.get("sync_token")

            # If fewer than limit, no more pages
            if len(skills) < 50:
                break

        # Save sync token for next run
        if since:
            token_file.write_text(since)

        if total_synced > 0:
            logger.info("Synced %d skills from hub", total_synced)

        return total_synced

    def _get_node_id(self) -> str:
        """Get this node's ID for sync confirmation."""
        import os

        return os.environ.get("ARCHIE_NODE_ID", "hub")
```

- [ ] **Step 2: Update get_cached_skills() for recursive glob**

Replace the existing `get_cached_skills()` method (lines 67-75) with:

```python
    def get_cached_skills(self) -> list[dict]:
        """Get cached skills (read from disk, including subdirectories)."""
        skills_dir = self.cache_dir / "skills"
        if not skills_dir.exists():
            return []
        skills = []
        for f in skills_dir.glob("**/*.md"):
            skills.append({"name": f.stem, "content": f.read_text()})
        return skills
```

- [ ] **Step 3: Commit**

```bash
git add archie-code/archie_engine/hub/sync.py
git commit -m "feat: incremental skill sync with repo structure and confirmation"
```

---

### Task 5: CLI — SkillLoader Recursive Glob

**Files:**
- Modify: `archie-code/archie_engine/skills/loader.py` (line 21)

- [ ] **Step 1: Change glob to recursive**

Replace line 21:

```python
            for md_file in sorted(directory.glob("*.md")):
```

With:

```python
            for md_file in sorted(directory.glob("**/*.md")):
```

- [ ] **Step 2: Improve source detection for hub-synced skills**

The `source` is currently set to `directory.name` which would be "skills" for hub-synced skills. For better display, extract `source_repo` from the skill's frontmatter. Replace the full `load_all` method:

```python
    def load_all(self) -> list[Skill]:
        """Load all .md skill files from all configured directories."""
        skills = []
        for directory in self.skill_dirs:
            if not directory.exists():
                continue
            default_source = directory.name
            for md_file in sorted(directory.glob("**/*.md")):
                try:
                    raw = md_file.read_text()
                    skill = parse_skill(
                        raw, source=default_source, file_path=str(md_file)
                    )
                    if skill.name:
                        skills.append(skill)
                except Exception as e:
                    logger.warning("Failed to load skill %s: %s", md_file, e)
        return skills
```

- [ ] **Step 3: Commit**

```bash
git add archie-code/archie_engine/skills/loader.py
git commit -m "feat: recursive skill loading — finds github/<repo>/*.md subdirectories"
```

---

### Task 6: End-to-End Verification

**Files:** None — testing only.

- [ ] **Step 1: Test the sync endpoint returns skills**

```bash
curl -s "http://192.168.1.200:3000/tools/consciousness/api/github/skills/sync" | python3 -m json.tool | head -30
```

Expected: JSON with `success: true`, skills array with content, `sync_token`.

- [ ] **Step 2: Test incremental sync with since parameter**

Use the `sync_token` from Step 1:

```bash
curl -s "http://192.168.1.200:3000/tools/consciousness/api/github/skills/sync?since=2099-01-01T00:00:00" | python3 -m json.tool
```

Expected: `skills: []` (no skills newer than 2099).

- [ ] **Step 3: Test the confirm endpoint**

Get a real skill_id from Step 1, then:

```bash
curl -s -X POST "http://192.168.1.200:3000/tools/consciousness/api/github/skills/sync-confirm" \
  -H "Content-Type: application/json" \
  -d '{"skill_ids": [<SKILL_ID>], "node_id": "test-cli"}'
```

Expected: `{"success": true, "confirmed": 1}`

- [ ] **Step 4: Verify archie_cli installation row created**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT skill_id, target, install_path, adapted
FROM skill_installations
WHERE target = 'archie_cli'
ORDER BY installed_at DESC
LIMIT 5;
"
```

Expected: Row(s) with `target='archie_cli'`.

- [ ] **Step 5: Test SkillLoader recursive glob**

```bash
cd /mnt/archie_brain/archie-code && python3 -c "
from pathlib import Path
from archie_engine.skills.loader import SkillLoader

loader = SkillLoader([
    Path('archie_engine/skills/community'),
    Path('/mnt/archie_brain/.claude/skills'),
])
skills = loader.load_all()
print(f'Total skills loaded: {len(skills)}')
for s in skills[:5]:
    print(f'  {s.name} (source={s.source}, path={s.file_path[:60]})')
"
```

Expected: Community skills (6) + Claude Code github skills (~8+) all loaded.

- [ ] **Step 6: Test CLI sync against hub (if hub is running)**

```bash
cd /mnt/archie_brain/archie-code && ARCHIE_HUB_URL=http://192.168.1.200:3000 python3 -c "
import asyncio
from pathlib import Path
from archie_engine.hub.auth import HubAuth
from archie_engine.hub.connector import HubConnector
from archie_engine.hub.sync import HubSync

async def test():
    auth = HubAuth(key_file=Path('/tmp/test_hub_key'))
    connector = HubConnector(hub_url='http://192.168.1.200:3000', auth=auth)
    sync = HubSync(connector=connector, cache_dir=Path('/tmp/archie_cli_test'))
    count = await sync.sync_skills()
    print(f'Synced {count} skills')

    # Check files written
    skills_dir = Path('/tmp/archie_cli_test/skills/github')
    if skills_dir.exists():
        files = list(skills_dir.glob('**/*.md'))
        print(f'Files on disk: {len(files)}')
        if files:
            print(f'Sample: {files[0]}')

asyncio.run(test())
"
```

Expected: Skills synced, files written to `/tmp/archie_cli_test/skills/github/<repo>/`.

- [ ] **Step 7: Verify pipeline-stats now shows archie_cli count**

```bash
curl -s "http://192.168.1.200:3000/tools/consciousness/api/github/skills/pipeline-stats" | python3 -m json.tool
```

Check that `installed` count increased (includes `archie_cli` target).

Note: The pipeline-stats endpoint currently filters `WHERE target = 'claude_code'`. If you want it to show Archie CLI stats too, that's a separate enhancement — not in scope for this plan.

- [ ] **Step 8: Clean up test artifacts**

```bash
rm -rf /tmp/archie_cli_test /tmp/test_hub_key
```

- [ ] **Step 9: Final commit if any verification fixes were needed**

```bash
git status
# Only commit if there are changes from verification fixes
```

---

## Self-Review Checklist

- **Spec coverage:** GET sync endpoint (Task 1), POST confirm endpoint (Task 2), connector methods (Task 3), HubSync rewrite (Task 4), SkillLoader fix (Task 5), E2E verification (Task 6). All spec requirements covered.
- **Placeholder scan:** No TBDs. All code complete. All commands have expected output.
- **Type consistency:** `skill_id` (int) used consistently. `sync_skills()` returns `int` (count) in CLI, returns `dict` (JSON) in connector. `confirm_skill_sync()` takes `list[int]` for `skill_ids`. `slug` and `repo_slug` fields match between hub response and CLI consumer.
- **Not in scope (per spec):** `archie install-skill <name>` (Phase 2b), Skills dashboard UI (Phase 2c), Cluster OTA (Phase 3). No `__main__.py` changes needed — startup already calls `sync_all()` → `sync_skills()`.

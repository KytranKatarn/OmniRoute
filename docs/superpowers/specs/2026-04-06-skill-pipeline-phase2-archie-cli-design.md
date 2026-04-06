# Skill Import Pipeline Phase 2 — Archie CLI Integration

> **Status:** Approved
> **Phase:** 2 of 3 (Phase 1 = Claude Code install/test/adapt, Phase 3 = Cluster OTA)
> **Depends on:** Phase 1 complete (skill_installations table, Jobs #59/#60/#58, pipeline-stats API)

## Goal

Extend the skill pipeline so Archie CLI instances can sync tested skills from the hub, storing them in the same `github/<repo>/<skill>.md` structure as Claude Code. Skills become available to Archie CLI's SkillLoader/SkillExecutor immediately after sync.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Sync approach | Hub API + CLI sync (Approach A) | Uses existing HubConnector/HubSync infrastructure. Works for hub-local and remote fleet nodes. |
| Incremental sync | `since` timestamp parameter | Avoids re-downloading entire library on every sync. First sync gets everything. |
| Skill selection | All tested+passing, with `adapted` flag | CLI gets full library immediately. Adapted skills are highlighted, not gated. |
| Install tracking | CLI confirms via POST after successful writes | Accurate tracking — no false positives from fetch-without-write. |
| File structure | `github/<repo-slug>/<skill-slug>.md` | Same as Claude Code. Consistency across targets. |
| Loader change | `**/*.md` recursive glob | One-line fix. Finds skills in subdirectories. |

## Architecture

```
Hub (192.168.1.200:3000)                    Archie CLI (any node)
========================                    =====================

skill_installations table                   HubSync.sync_skills()
  (target=claude_code,                        |
   dry_run_passed=TRUE)                       | 1. GET /api/github/skills/sync?since=<token>
        |                                     |
        v                                     v
GET /api/github/skills/sync  ──────────>  Receive skills JSON
  - Filters by since timestamp              |
  - Returns content + metadata              | 2. Write to cache_dir/skills/github/<repo>/<skill>.md
  - Returns sync_token                      |
                                            | 3. POST /api/github/skills/sync-confirm
POST /api/github/skills/sync-confirm  <──   {skill_ids: [...], node_id: "hub"}
  - Creates skill_installations               |
    rows (target=archie_cli)                  | 4. Save sync_token to .skill_sync_token
                                              |
                                            SkillLoader.load_all()
                                              glob("**/*.md") finds github/ skills
                                              |
                                            SkillExecutor.execute()
                                              runs skill through Ollama
```

## Hub API: Skill Sync Endpoint

### GET /api/github/skills/sync

**Location:** `platform_v2/tools/consciousness/github_repo_routes.py`
**Auth:** `login_or_api_key`

**Parameters:**
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `since` | ISO timestamp | None | Only return skills installed/updated after this time. Omit for first sync. |
| `limit` | int | 50 | Max skills per response. Max 200. |

**Response:**
```json
{
  "success": true,
  "skills": [
    {
      "skill_id": 230,
      "repo": "obra/superpowers",
      "name": "skills/writing-skills/anthropic-best-practices.md",
      "slug": "skills-writing-skills-anthropic-best-practices",
      "content": "---\nname: ...\n---\n\n# Skill content...",
      "quality_score": 5,
      "adapted": true,
      "installed_at": "2026-04-06T16:00:00Z",
      "tested_at": "2026-04-06T18:00:00Z"
    }
  ],
  "sync_token": "2026-04-06T18:30:00Z",
  "total_available": 8
}
```

**Query logic:**
```sql
SELECT si.skill_id, gs.repo_name, gs.skill_name,
       COALESCE(si.adapted_content, si.normalized_content) AS content,
       gs.quality_score, si.adapted, si.installed_at, si.tested_at
FROM skill_installations si
JOIN github_skills gs ON gs.id = si.skill_id
WHERE si.target = 'claude_code'
  AND si.dry_run_passed = TRUE
  AND ($since IS NULL OR si.installed_at > $since)
ORDER BY si.installed_at ASC
LIMIT $limit
```

- Returns `adapted_content` when available (includes `## Archie CLI` section), falls back to `normalized_content`
- `sync_token` = max `installed_at` from returned results
- `total_available` = count of all passing skills (helps CLI know if more pages exist)

### POST /api/github/skills/sync-confirm

**Location:** `platform_v2/tools/consciousness/github_repo_routes.py`
**Auth:** `login_or_api_key`

**Request body:**
```json
{
  "skill_ids": [230, 231, 245],
  "node_id": "hub"
}
```

**Logic:**
- For each `skill_id`, insert into `skill_installations` with `target='archie_cli'`
- Uses `ON CONFLICT (skill_id, target) DO UPDATE SET installed_at = NOW()`
- `install_path` = `skills/github/<repo-slug>/<skill-slug>.md`
- `node_id` stored in `install_path` prefix or JSONB metadata. Value comes from `ARCHIE_NODE_ID` env var, defaults to `"hub"` if unset.

**Response:**
```json
{
  "success": true,
  "confirmed": 3
}
```

## CLI: Sync Extension

### Modified: `archie_engine/hub/sync.py`

Extend `HubSync.sync_skills()`:

```python
async def sync_skills(self) -> int:
    """Sync tested skills from hub. Returns count of new skills synced."""
    skills_dir = self.cache_dir / "skills" / "github"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Read last sync token
    token_file = self.cache_dir / ".skill_sync_token"
    since = token_file.read_text().strip() if token_file.exists() else None

    total_synced = 0

    while True:
        # Fetch batch
        params = {"limit": 50}
        if since:
            params["since"] = since

        result = await self.connector.get("/api/github/skills/sync", params=params)
        skills = result.get("skills", [])

        if not skills:
            break

        # Write files and collect confirmed IDs
        confirmed_ids = []
        for skill in skills:
            repo_slug = skill["repo"].replace("/", "-").lower()
            skill_slug = skill["slug"] + ".md"

            repo_dir = skills_dir / repo_slug
            repo_dir.mkdir(parents=True, exist_ok=True)

            try:
                (repo_dir / skill_slug).write_text(skill["content"])
                confirmed_ids.append(skill["skill_id"])
            except OSError as e:
                logger.warning("Failed to write skill %s: %s", skill["name"], e)

        # Confirm successful installs
        if confirmed_ids:
            await self.connector.post("/api/github/skills/sync-confirm", {
                "skill_ids": confirmed_ids,
                "node_id": self._get_node_id(),
            })

        total_synced += len(confirmed_ids)
        since = result.get("sync_token")

        # If we got fewer than limit, we're done
        if len(skills) < 50:
            break

    # Save sync token
    if since:
        token_file.write_text(since)

    return total_synced
```

### Modified: `archie_engine/skills/loader.py`

One-line change:

```python
# Before:
for md_file in sorted(directory.glob("*.md")):

# After:
for md_file in sorted(directory.glob("**/*.md")):
```

### Modified: `archie_engine/engine.py`

Add skill sync to startup:

```python
# In __init__, after skill_dirs setup:
if config.hub_url:
    try:
        synced = await self.hub_sync.sync_skills()
        if synced:
            logger.info("Synced %d skills from hub", synced)
    except Exception as e:
        logger.debug("Hub skill sync skipped: %s", e)
```

### New CLI command: `archie sync-skills`

In CLI entry point (likely `__main__.py` or a commands module):

```python
@cli.command()
async def sync_skills():
    """Sync skills from A.R.C.H.I.E. hub."""
    count = await engine.hub_sync.sync_skills()
    print(f"Synced {count} skills from hub")
```

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Hub unreachable during CLI sync | Log warning, use cached skills, skip silently on startup |
| No new skills since last sync | Empty response, CLI does nothing |
| Malformed skill content from hub | CLI validates with `parse_skill()` before writing, skips bad ones, omits from confirmation |
| First sync (no token) | Gets everything in batches of 50 until exhausted |
| Disk full on CLI | Catches `OSError`, logs, omits failed skill from confirmation |
| Confirmation POST fails | Skills on disk but hub doesn't know. Next sync re-fetches same skills (idempotent ON CONFLICT), CLI confirms again. No data loss, no duplicates. |
| Startup sync timeout | 10 second total timeout. Failure is silent — cached skills work offline. |

## File Changes Summary

| Side | File | Change |
|------|------|--------|
| Hub | `consciousness/github_repo_routes.py` | New `GET /api/github/skills/sync` endpoint |
| Hub | `consciousness/github_repo_routes.py` | New `POST /api/github/skills/sync-confirm` endpoint |
| CLI | `archie_engine/hub/sync.py` | Extend `sync_skills()` — incremental fetch, repo-structured writes, confirmation POST, token persistence |
| CLI | `archie_engine/skills/loader.py` | `glob("*.md")` → `glob("**/*.md")` |
| CLI | `archie_engine/__main__.py` | Add `archie sync-skills` command |
| CLI | `archie_engine/engine.py` | Call `sync_skills()` on startup if hub configured |

## Not In Scope

- `archie install-skill <name>` single-skill install (Phase 2b)
- Skills dashboard UI in Archie CLI (Phase 2c)
- Cluster/OTA sync (Phase 3)
- Dry-run testing via Archie CLI executor (deferred — hub tests are sufficient for now)

## Testing Plan

1. Start with loader fix — verify `**/*.md` finds existing Claude Code skills
2. Build hub endpoints — test with curl/direct API calls
3. Extend CLI sync — test against hub with `ARCHIE_HUB_URL=http://192.168.1.200:3000`
4. Verify confirmation tracking — check `skill_installations` rows with `target='archie_cli'`
5. Test startup auto-sync — verify skills load after fresh CLI init
6. Test incremental sync — add new skill, verify only new skill syncs
7. Test error cases — hub down, disk full, malformed content

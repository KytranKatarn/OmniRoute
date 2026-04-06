# Skill Import Pipeline Phase 3 — Cluster Distribution

> **Status:** Approved
> **Phase:** 3 of 3 (Phase 1 = Claude Code install/test/adapt, Phase 2 = Archie CLI sync)
> **Depends on:** Phase 1 (skill_installations table, tested skills), Phase 2 (sync API)

## Goal

Push tested skills to online fleet nodes running Archie CLI (starship mode). Hub pushes delta batches every 6 hours via the node's inbound API. Per-node tracking in a separate table avoids contention with the skill pipeline's hot `skill_installations` table.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Distribution method | Hub pushes via HTTP POST to node inbound API | Matches existing OTA pattern. Nodes don't need to know about the sync API. |
| Pull vs push | Hybrid — CLI nodes can also pull via Phase 2 sync API | Push ensures nodes stay current even if CLI sync isn't configured |
| Tracking table | Separate `node_skill_pushes` (not `skill_installations`) | Avoids write contention with installer/tester/adapter jobs |
| Push frequency | Every 6 hours (Job #61) | Matches fleet health check cadence. Skills aren't urgent. |
| Batch size | 5 skills per node per cycle | Avoids overwhelming nodes |
| Node targeting | Starship only (`deployment_mode='starship'`) | Legacy outpost nodes can't execute skills |
| Failure handling | Silent retry + Telegram at 3 failures | Low noise, admin alerted on persistent issues |

## Architecture

```
Hub (Job #61, every 6h)                     Starship Node
=======================                     ==============

skill_installations                         InboundServer
  (target=claude_code,                        |
   dry_run_passed=TRUE)                       | POST /api/skills/push
        |                                     |   {skill_id, repo_slug, slug, content}
        v                                     v
  Delta query:                              Write to:
  skills NOT IN node_skill_pushes             hub_skills_cache_dir/skills/github/
  for this node_id                            <repo_slug>/<slug>.md
        |                                     |
        v                                     v
  POST to node inbound  ──────────────>     Return {success: true, path: "..."}
        |
        v
  On success:
    INSERT into node_skill_pushes
  On failure:
    UPDATE fail_count++
    If fail_count >= 3: Telegram alert
```

## Database Schema

### New table: `node_skill_pushes`

```sql
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

**Why separate from `skill_installations`:**
- `skill_installations` is written by Jobs #59 (installer), #60 (tester), #58 (adapter), and Phase 2 sync-confirm
- Adding cluster push writes would create a 5th concurrent writer on the same table
- `node_skill_pushes` is only written by Job #61, zero contention

## Hub: Job #61 — push_skills_to_fleet()

**Location:** `platform_v2/tools/consciousness/jobs.py`
**Frequency:** Every 6 hours
**Department:** Documentation & Knowledge

**Logic:**
1. Query `remote_nodes` for online starship nodes (heartbeat within 10 minutes)
2. For each node, find skills to push:
   ```sql
   SELECT si.skill_id, gs.repo_name, gs.skill_name,
          COALESCE(si.adapted_content, si.normalized_content) AS content,
          gs.quality_score, si.adapted
   FROM skill_installations si
   JOIN github_skills gs ON gs.id = si.skill_id
   WHERE si.target = 'claude_code'
     AND si.dry_run_passed = TRUE
     AND si.skill_id NOT IN (
         SELECT skill_id FROM node_skill_pushes
         WHERE node_id = %s
     )
   ORDER BY gs.quality_score DESC
   LIMIT 5
   ```
3. For each skill, POST to `http://<node_hostname>:<node_port>/api/skills/push`
4. On HTTP 200 with `success: true`: INSERT into `node_skill_pushes` (pushed_at = NOW())
5. On failure: UPSERT `node_skill_pushes` with fail_count + 1 and last_error
6. After processing all nodes, if any skill has `fail_count >= 3`: send Telegram alert

**Push payload:**
```json
{
  "skill_id": 230,
  "repo_slug": "obra-superpowers",
  "slug": "skills-writing-skills-anthropic-best-practices",
  "content": "---\nname: ...\n---\n...",
  "quality_score": 5,
  "adapted": true
}
```

**Slug generation:** Uses proper substring removal (`if slug.endswith('.md'): slug[:-3]`), not `.rstrip('.md')`.

## Node: Skill Push Endpoint

**Location:** `archie-code/archie_engine/hub/inbound.py`
**Endpoint:** `POST /api/skills/push`
**Auth:** Node API key (same as other inbound endpoints)

**Request:** Push payload (see above)

**Response:**
```json
{"success": true, "path": "skills/github/obra-superpowers/skills-writing-skills-anthropic-best-practices.md"}
```

**Logic:**
1. Validate: `skill_id` present, `content` non-empty
2. Build path: `hub_skills_cache_dir/skills/github/<repo_slug>/<slug>.md`
3. Create directory if needed
4. Write file
5. Return success + relative path
6. On error: return `{"success": false, "error": "<message>"}`

## Failure Handling

| Scenario | Behavior |
|----------|----------|
| Node offline (stale heartbeat) | Skipped — job only targets nodes with heartbeat < 10 min ago |
| HTTP timeout/connection refused | fail_count++ in `node_skill_pushes`, retry next 6h cycle |
| Node returns `success: false` | fail_count++, store error message in `last_error` |
| fail_count >= 3 for any skill+node | Telegram alert to authorized users |
| Node comes back online | Next cycle picks up all missing skills (delta query) |
| Skill deleted from hub | Not synced (push-only, no deletion sync) |

## File Changes Summary

| Side | File | Change |
|------|------|--------|
| Hub | `database/migrations/node_skill_pushes.sql` | New table + indexes |
| Hub | `platform_v2/tools/consciousness/jobs.py` | Add `push_skills_to_fleet()` Job #61, register in scheduler |
| Node | `archie-code/archie_engine/hub/inbound.py` | Add `/api/skills/push` handler |

## Not In Scope

- Skill deletion/removal sync (push-only)
- Outpost/legacy node support (starship only)
- UI for managing cluster skill state
- Node-initiated pull (already handled by Phase 2 sync)
- Skill execution verification on nodes (trust the file write)

## Testing Plan

1. Run migration — verify `node_skill_pushes` table created
2. Test with hub-test-node entry in `remote_nodes` (mock inbound endpoint)
3. Run Job #61 manually — verify delta query finds skills, attempts push
4. Verify `node_skill_pushes` rows created on success
5. Test failure path — push to offline node, verify fail_count increments
6. Test Telegram alert — set fail_count to 2, trigger one more failure
7. Test idempotency — run Job #61 twice, verify no duplicate pushes

# GitHub Ingestion Bugfix — 3 Bugs in `_reindex_repo_via_tree`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix GitHub repo ingestion so new repos get tracked, re-indexing doesn't wipe sibling repos, and MCP-triggered indexing works.

**Architecture:** All 3 bugs are in `github_routes.py` (the `_reindex_repo_via_tree` function and the `github_index_selective` route). Bug 3 also touches the MCP tool in `knowledge.py`. The root cause is using `repo_type` as a unique identifier when it's actually a shared category (e.g., 7 repos share `ai-tools`).

**Tech Stack:** Python/Flask, PostgreSQL, psycopg2

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `platform_v2/tools/consciousness/github_routes.py` | Modify | Fix delete/update queries (Bug 2), add upsert for tracking row (Bug 1), add API key auth alternative (Bug 3) |
| `platform_v2/mcp_server/tools/knowledge.py` | Modify | Use Bearer auth instead of fake cookie (Bug 3) |

## Key Context

- `github_repositories` table: `repo_name` is UNIQUE (`owner/repo` format), `repo_type` is a shared category
- `knowledge_base` entries: `memory_metadata->>'repo'` stores `owner/repo`, `file_path` stores `owner/repo/path`
- `app.py` line 1350: `require_api_key` decorator uses `ARCHIE_API_KEY` env var with Bearer auth
- ON CONFLICT key for knowledge_base inserts: `(repo_type, file_path)` — this is existing and works fine, don't change it
- 37 repos in `github_repositories`, but 8 more repos exist in `knowledge_base` with no tracking row

---

### Task 1: Fix Bug 2 — Change delete/update from `repo_type` to `repo_name`

**Files:**
- Modify: `platform_v2/tools/consciousness/github_routes.py:494-511` (delete old entries)
- Modify: `platform_v2/tools/consciousness/github_routes.py:637-641` (batch progress update)
- Modify: `platform_v2/tools/consciousness/github_routes.py:643-658` (final sync update)

The function `_reindex_repo_via_tree(owner, repo, repo_type, importance, max_files)` already receives `owner` and `repo` as separate args. We use `memory_metadata->>'repo'` (which stores `owner/repo`) for precise filtering.

- [ ] **Step 1: Fix the DELETE queries (lines 500-511)**

Replace the two DELETE statements that use `repo_type`:

```python
# OLD (lines 500-511) — DELETES ALL repos with same repo_type!
cur.execute(
    """DELETE FROM memory_embeddings WHERE source_type = 'knowledge_base'
       AND source_id IN (
           SELECT id FROM knowledge_base
           WHERE knowledge_type = 'github_file' AND repo_type = %s
       )""",
    (repo_type,),
)
cur.execute(
    "DELETE FROM knowledge_base WHERE knowledge_type = 'github_file' AND repo_type = %s",
    (repo_type,),
)
```

With:

```python
# NEW — only deletes files for THIS specific repo
repo_full = f"{owner}/{repo}"
cur.execute(
    """DELETE FROM memory_embeddings WHERE source_type = 'knowledge_base'
       AND source_id IN (
           SELECT id FROM knowledge_base
           WHERE knowledge_type = 'github_file'
             AND memory_metadata->>'repo' = %s
       )""",
    (repo_full,),
)
cur.execute(
    """DELETE FROM knowledge_base
       WHERE knowledge_type = 'github_file'
         AND memory_metadata->>'repo' = %s""",
    (repo_full,),
)
```

- [ ] **Step 2: Fix the batch progress UPDATE (line 637-641)**

Replace:

```python
cur.execute(
    "UPDATE github_repositories SET indexed_files = %s WHERE repo_type = %s",
    (indexed_count, repo_type),
)
```

With:

```python
repo_full = f"{owner}/{repo}"
cur.execute(
    "UPDATE github_repositories SET indexed_files = %s WHERE repo_name = %s",
    (indexed_count, repo_full),
)
```

Note: `repo_full` is already defined from Step 1 earlier in the function, but since this is inside a loop body that runs per batch, ensure the variable is accessible. It's defined before the loop starts, so it's fine.

- [ ] **Step 3: Fix the final sync UPDATE (lines 643-658)**

Replace:

```python
cur.execute(
    """
    UPDATE github_repositories r
    SET indexed = true,
        indexed_files = COALESCE((
            SELECT count(*) FROM knowledge_base
            WHERE knowledge_type = 'github_file'
              AND memory_metadata->>'repo' = r.repo_name
        ), 0),
        indexed_at = NOW(),
        status = 'indexed', updated_at = NOW()
    WHERE r.repo_type = %s
    """,
    (repo_type,),
)
```

With:

```python
repo_full = f"{owner}/{repo}"
cur.execute(
    """
    UPDATE github_repositories r
    SET indexed = true,
        indexed_files = COALESCE((
            SELECT count(*) FROM knowledge_base
            WHERE knowledge_type = 'github_file'
              AND memory_metadata->>'repo' = r.repo_name
        ), 0),
        indexed_at = NOW(),
        status = 'indexed', updated_at = NOW()
    WHERE r.repo_name = %s
    """,
    (repo_full,),
)
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/github_routes.py
git commit -m "fix(github): use repo_name instead of repo_type for delete/update — prevents cross-repo data loss"
```

---

### Task 2: Fix Bug 1 — Upsert `github_repositories` for new repos

**Files:**
- Modify: `platform_v2/tools/consciousness/github_routes.py` — after the final UPDATE (Task 1 Step 3), add an upsert

Currently, if a repo doesn't already have a row in `github_repositories`, the UPDATE from Task 1 matches zero rows and the repo stays invisible to `github_list_repos`.

- [ ] **Step 1: Add upsert after the final UPDATE**

Right after the final UPDATE query from Task 1 Step 3, add:

```python
# Ensure repo has a tracking row (upsert for new repos)
cur.execute(
    """
    INSERT INTO github_repositories (repo_name, repo_type, local_path, status, indexed, indexed_files, indexed_at, github_url, created_at, updated_at)
    VALUES (%s, %s, %s, 'indexed', true,
        COALESCE((
            SELECT count(*) FROM knowledge_base
            WHERE knowledge_type = 'github_file'
              AND memory_metadata->>'repo' = %s
        ), 0),
        NOW(), %s, NOW(), NOW()
    )
    ON CONFLICT (repo_name) DO UPDATE SET
        indexed = true,
        indexed_files = COALESCE((
            SELECT count(*) FROM knowledge_base
            WHERE knowledge_type = 'github_file'
              AND memory_metadata->>'repo' = EXCLUDED.repo_name
        ), 0),
        indexed_at = NOW(),
        status = 'indexed',
        updated_at = NOW()
    """,
    (
        repo_full,
        repo_type,
        f"/mnt/archie_brain/repos/{repo_type}/{repo}",
        repo_full,
        f"https://github.com/{owner}/{repo}",
    ),
)
conn.commit()
```

This replaces both the previous UPDATE (which can now be removed since the upsert handles both cases) and adds INSERT capability.

- [ ] **Step 2: Remove the now-redundant UPDATE from Task 1 Step 3**

The upsert from Step 1 handles both existing and new repos, so the separate UPDATE is no longer needed. Remove the UPDATE block and keep only the upsert.

- [ ] **Step 3: Backfill the 8 missing repos**

Run a one-time SQL to create tracking rows for repos that are in `knowledge_base` but missing from `github_repositories`:

```sql
INSERT INTO github_repositories (repo_name, repo_type, local_path, status, indexed, indexed_files, indexed_at, github_url, created_at, updated_at)
SELECT
    m.repo_name,
    COALESCE(kb.repo_type, 'unknown'),
    '/mnt/archie_brain/repos/' || COALESCE(kb.repo_type, 'unknown') || '/' || SPLIT_PART(m.repo_name, '/', 2),
    'indexed',
    true,
    m.file_count,
    MAX(kb.created_at),
    'https://github.com/' || m.repo_name,
    MIN(kb.created_at),
    NOW()
FROM (
    SELECT memory_metadata->>'repo' as repo_name, COUNT(*) as file_count
    FROM knowledge_base
    WHERE knowledge_type = 'github_file' AND memory_metadata->>'repo' IS NOT NULL
    GROUP BY memory_metadata->>'repo'
) m
JOIN knowledge_base kb ON kb.knowledge_type = 'github_file' AND kb.memory_metadata->>'repo' = m.repo_name
LEFT JOIN github_repositories gr ON gr.repo_name = m.repo_name
WHERE gr.id IS NULL
GROUP BY m.repo_name, kb.repo_type, m.file_count
ON CONFLICT (repo_name) DO NOTHING;
```

Run via: `docker exec archie_database psql -U archie -d archie -c "<sql>"`

- [ ] **Step 4: Also fix existing repo counts that were corrupted by Bug 2**

```sql
UPDATE github_repositories r
SET indexed_files = COALESCE((
    SELECT count(*) FROM knowledge_base
    WHERE knowledge_type = 'github_file'
      AND memory_metadata->>'repo' = r.repo_name
), 0),
indexed_at = COALESCE(r.indexed_at, NOW()),
updated_at = NOW();
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/github_routes.py
git commit -m "fix(github): upsert github_repositories so new repos get tracked"
```

---

### Task 3: Fix Bug 3 — MCP tool auth for index-selective route

**Files:**
- Modify: `platform_v2/tools/consciousness/github_routes.py:823-826` (route decorator)
- Modify: `platform_v2/mcp_server/tools/knowledge.py:762-787` (MCP tool HTTP call)

The MCP tool sends a fake cookie. The route requires `@login_required @admin_required`. We need either:
- (A) Add API key auth as alternative on the route, OR
- (B) Have MCP call the function directly instead of HTTP

Option A is cleaner — keeps the route reusable. We'll create a combined decorator that accepts either login session OR API key.

- [ ] **Step 1: Add `login_or_api_key` helper to github_routes.py**

Add near the top of `register_github_routes()` (after the existing imports):

```python
def login_or_api_key(f):
    """Allow access via Flask-Login session OR Bearer API key."""
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check API key first
        api_key = request.headers.get("Authorization", "")
        if api_key.startswith("Bearer "):
            valid_key = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")
            if api_key[7:] == valid_key:
                return f(*args, **kwargs)
            return jsonify({"error": "Invalid API key"}), 401
        # Fall back to Flask-Login session
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401
        if not getattr(current_user, 'is_admin', False):
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated
```

- [ ] **Step 2: Replace decorators on the index-selective route**

Change:

```python
@bp.route("/github/index-selective", methods=["POST"])
@login_required
@admin_required
def github_index_selective():
```

To:

```python
@bp.route("/github/index-selective", methods=["POST"])
@login_or_api_key
def github_index_selective():
```

- [ ] **Step 3: Update MCP tool to use Bearer auth**

In `platform_v2/mcp_server/tools/knowledge.py`, replace the HTTP call (lines 769-775):

```python
# OLD
resp = http_requests.post(
    platform_url,
    json=body,
    headers={"Content-Type": "application/json"},
    cookies={"session": "mcp-internal"},
    timeout=300,
)
```

With:

```python
# NEW — use API key auth
api_key = os.getenv("ARCHIE_API_KEY", "dev-api-key-change-in-production")
resp = http_requests.post(
    platform_url,
    json=body,
    headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    },
    timeout=300,
)
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/github_routes.py platform_v2/mcp_server/tools/knowledge.py
git commit -m "fix(github): add API key auth for MCP-triggered repo indexing"
```

---

### Task 4: Deploy and Verify

- [ ] **Step 1: Deploy**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify repo list now shows all repos**

Call `mcp__archie__github_list_repos` — should show 45+ repos (37 original + 8 backfilled).

- [ ] **Step 3: Test MCP indexing works**

Call `mcp__archie__github_index_repo` with a small test repo to verify the full pipeline:
- MCP tool sends Bearer auth
- Route accepts it
- Files get indexed into knowledge_base
- github_repositories gets upserted

- [ ] **Step 4: Verify no cross-repo contamination**

Check that repos sharing `repo_type = 'ai-tools'` each have their own correct file counts:

```sql
SELECT repo_name, indexed_files FROM github_repositories WHERE repo_type = 'ai-tools' ORDER BY repo_name;
```

- [ ] **Step 5: Final commit if any adjustments needed**

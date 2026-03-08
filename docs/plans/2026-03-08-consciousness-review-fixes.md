# Consciousness Module Review Fixes — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all critical bugs, security issues, and dead code found in the Consciousness module code review.

**Architecture:** Surgical fixes across routes.py, knowledge_routes.py, processing_routes.py, consciousness.js, station-ops.js, __init__.py, and consciousness_dashboard.html. No new features — just bug fixes, security hardening, and dead code removal.

**Tech Stack:** Python/Flask, vanilla JS, PostgreSQL, Jinja2 HTML

---

## Phase 1: Critical Bugs (breaking endpoints)

### Task 1: Fix double-close in `get_activity_stats`

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py:1991-1997`

**Step 1:** Remove the inner `finally` block (lines 1995-1997) that closes `cur`/`conn` prematurely. The outer `finally` at ~line 2101 already handles cleanup.

**Step 2:** Verify the outer `finally` block has proper `if cur`/`if conn` guards.

**Step 3:** Commit
```bash
git add platform_v2/tools/consciousness/routes.py
git commit -m "fix(consciousness): remove double-close in get_activity_stats"
```

---

### Task 2: Fix `_tag_content` closing wrong cursor/connection

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py:6437-6441`

**Step 1:** Remove the `finally` block from `_tag_content()` that incorrectly closes outer scope `cur`/`conn`. The inner `cur2`/`conn2` are already closed in the `try` block.

**Step 2:** Commit
```bash
git add platform_v2/tools/consciousness/routes.py
git commit -m "fix(consciousness): _tag_content closing wrong cursor variables"
```

---

### Task 3: Fix `translation_generate` UnboundLocalError

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py:6975-7017`

**Step 1:** Add `conn = None` and `cur = None` initialization before the `if provided_strings` branch.

**Step 2:** Guard the `finally` block: `if cur: cur.close()` / `if conn: conn.close()`

**Step 3:** Commit
```bash
git add platform_v2/tools/consciousness/routes.py
git commit -m "fix(consciousness): guard translation_generate finally for provided_strings path"
```

---

### Task 4: Fix `ingest-directory` writing to dropped table

**Files:**
- Modify: `platform_v2/tools/consciousness/knowledge_routes.py:367-390`

**Step 1:** Change INSERT target from `long_term_memory` to `knowledge_base` with correct column mapping (match `ingest_text`/`create_knowledge` patterns).

**Step 2:** Add path traversal check (same `allowed_bases` guard as `browse_files`).

**Step 3:** Commit
```bash
git add platform_v2/tools/consciousness/knowledge_routes.py
git commit -m "fix(consciousness): retarget ingest-directory to knowledge_base, add path check"
```

---

### Task 5: Fix `_get_backlog_counts` connection leak

**Files:**
- Modify: `platform_v2/tools/consciousness/processing_routes.py:219-303`

**Step 1:** Add `conn = None; cur = None` before the `try` block.

**Step 2:** Guard `finally`: `if cur: cur.close()` / `if conn: conn.close()`

**Step 3:** Commit
```bash
git add platform_v2/tools/consciousness/processing_routes.py
git commit -m "fix(consciousness): guard _get_backlog_counts connection cleanup"
```

---

### Task 6: Fix `_run_embedding_job` missing commits/rollback

**Files:**
- Modify: `platform_v2/tools/consciousness/processing_routes.py:640-690`

**Step 1:** Add `conn.commit()` inside the per-item loop (every 10 items or at end) instead of only at the very end.

**Step 2:** Add `conn.rollback()` in the outer `except` block before closing.

**Step 3:** Commit
```bash
git add platform_v2/tools/consciousness/processing_routes.py
git commit -m "fix(consciousness): batch-commit embeddings, rollback on error"
```

---

## Phase 2: Security Hardening

### Task 7: Add `@admin_required` to `save_conversation`

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py:2246`

**Step 1:** Add `@admin_required` decorator after `@login_required`.

**Step 2:** Commit
```bash
git add platform_v2/tools/consciousness/routes.py
git commit -m "fix(consciousness): add admin_required to save_conversation"
```

---

### Task 8: Validate `memory_type` URL parameter

**Files:**
- Modify: `platform_v2/tools/consciousness/routes.py:2177-2197`

**Step 1:** Add allowlist check at top of both endpoints:
```python
VALID_MEMORY_TYPES = {"knowledge_base", "conversation_memory", "vault_note", "code_snippet"}
if memory_type not in VALID_MEMORY_TYPES:
    return jsonify({"success": False, "error": "Invalid memory type"}), 400
```

**Step 2:** Commit
```bash
git add platform_v2/tools/consciousness/routes.py
git commit -m "fix(consciousness): validate memory_type parameter"
```

---

### Task 9: Fix path traversal in `browse_files` and `ingest-directory`

**Files:**
- Modify: `platform_v2/tools/consciousness/knowledge_routes.py:354, 422`

**Step 1:** In `browse_files`, change `os.walk(directory_path)` to `os.walk(abs_dir)`.

**Step 2:** `ingest-directory` path check already added in Task 4.

**Step 3:** Commit
```bash
git add platform_v2/tools/consciousness/knowledge_routes.py
git commit -m "fix(consciousness): fix path traversal in browse_files"
```

---

### Task 10: Escape `l.code` in consciousness.js

**Files:**
- Modify: `platform_v2/static/js/consciousness.js:1147, 1154-1155`

**Step 1:** Replace all raw `l.code` in HTML string construction with `escHtml(l.code)`.

**Step 2:** Commit
```bash
git add platform_v2/static/js/consciousness.js
git commit -m "fix(consciousness): escape l.code to prevent XSS in language rows"
```

---

## Phase 3: Dead Code Cleanup

### Task 11: Remove team_routes registration

**Files:**
- Modify: `platform_v2/tools/consciousness/__init__.py:25, 37`

**Step 1:** Remove `from .team_routes import register_team_routes` import.

**Step 2:** Remove `register_team_routes(bp, admin_required)` call.

**Step 3:** Commit
```bash
git add platform_v2/tools/consciousness/__init__.py
git commit -m "refactor(consciousness): remove orphaned team_routes registration"
```

---

### Task 12: Remove dead JS functions and fix polling issues

**Files:**
- Modify: `platform_v2/static/js/consciousness.js`

**Step 1:** Remove `loadBrainMap`, `loadEmotionalTimeline`, `switchInsightsSubtab`, `loadSessions`, `loadImprovements`.

**Step 2:** Wrap bare `checkActiveJobs()` calls at lines 687, 713, 742 in `setTimeout(checkActiveJobs, 500)`.

**Step 3:** Add `_stopJobPolling()` in the `.catch` handler at line 747.

**Step 4:** Fix `.catch` handlers (7 spots) to use `(err.message || err)` instead of raw `err`.

**Step 5:** Remove `print()` debug statements in `knowledge_routes.py:46` and `team_routes.py:42,132,137`.

**Step 6:** Commit
```bash
git add platform_v2/static/js/consciousness.js platform_v2/tools/consciousness/knowledge_routes.py platform_v2/tools/consciousness/team_routes.py
git commit -m "refactor(consciousness): remove dead code, fix polling leaks, fix error display"
```

---

## Post-Implementation

- Restart platform: `docker compose restart archie_platform`
- Test endpoints: `/activity-stats`, `/api/translations/tag-module`, `/api/translations/generate`
- Update Dev HQ: `mcp log_decision`, `mcp store_memory`
- Dead CSS cleanup (1,900 lines in template) deferred to separate task — large but low risk

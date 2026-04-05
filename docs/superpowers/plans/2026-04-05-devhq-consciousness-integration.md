# Dev HQ + Consciousness Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand Consciousness Dashboard into a unified command center with automatic project-knowledge linking, knowledge gap analysis, and agent contribution tracking.

**Architecture:** New junction table `project_knowledge_links` for many-to-many project-knowledge relationships. Column additions to `bridge_jobs` (project_id) and `unified_tasks` (assigned_agent). Autonomy job auto-links via embedding cosine similarity. Three new dashboard panels in Consciousness Dashboard tab.

**Tech Stack:** Python/Flask, PostgreSQL, pgvector (768-dim arctic-embed-cpu), APScheduler via JobService, LCARS CSS, vanilla JS.

**Spec:** `docs/superpowers/specs/2026-04-05-devhq-consciousness-integration-design.md`

**Security note:** All JS rendering uses `escHtml()` from consciousness.js to sanitize content before DOM insertion. All API endpoints require `@admin_required`.

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `database/migrations/154_project_knowledge_links.sql` | Schema: new table + column additions |
| Create | `platform_v2/services/knowledge_link_service.py` | Auto-linking logic, gap analysis, CRUD |
| Create | `platform_v2/services/knowledge_link_jobs.py` | Job registration with JobService |
| Create | `platform_v2/static/css/consciousness-dashboard-v2.css` | Styles for 3 new dashboard panels |
| Create | `platform_v2/static/js/consciousness-dashboard-v2.js` | JS for panels: fetch, render, interactions |
| Modify | `platform_v2/tools/consciousness/dashboard_routes.py` | 5 new API endpoints |
| Modify | `platform_v2/tools/consciousness/templates/consciousness_dashboard.html` | 3 new panel HTML sections |
| Modify | `platform_v2/services/project_service.py` | 1 new function: agent contributions |
| Modify | `ai_bridge/bridge_dispatcher.py` | project_id kwarg on dispatch/dispatch_json |
| Modify | `platform_v2/app.py` | Register knowledge_link_jobs at startup |
| Modify | `platform_v2/static/js/consciousness.js` | Hook new panels into tab switch |

---

### Task 1: Database Migration

**Files:**
- Create: `database/migrations/154_project_knowledge_links.sql`

- [ ] **Step 1: Write the migration file**

```sql
-- 154_project_knowledge_links.sql
-- Project-Knowledge linking, bridge job project tracking, task agent assignment

-- Junction table for many-to-many project <-> knowledge
CREATE TABLE IF NOT EXISTS project_knowledge_links (
    id SERIAL PRIMARY KEY,
    project_id INT NOT NULL REFERENCES unified_projects(id) ON DELETE CASCADE,
    knowledge_id INT NOT NULL REFERENCES knowledge_base(id) ON DELETE CASCADE,
    link_type VARCHAR(20) NOT NULL DEFAULT 'auto',
    confidence DECIMAL(3,2),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE(project_id, knowledge_id)
);

CREATE INDEX IF NOT EXISTS idx_pkl_project ON project_knowledge_links(project_id);
CREATE INDEX IF NOT EXISTS idx_pkl_knowledge ON project_knowledge_links(knowledge_id);
CREATE INDEX IF NOT EXISTS idx_pkl_link_type ON project_knowledge_links(link_type);

-- Project embeddings (768-dim, same as knowledge_base)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'unified_projects' AND column_name = 'embedding'
    ) THEN
        ALTER TABLE unified_projects ADD COLUMN embedding vector(768);
    END IF;
END $$;

-- Bridge jobs -> project tracking
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'bridge_jobs' AND column_name = 'project_id'
    ) THEN
        ALTER TABLE bridge_jobs ADD COLUMN project_id INT REFERENCES unified_projects(id);
        CREATE INDEX idx_bridge_jobs_project ON bridge_jobs(project_id);
    END IF;
END $$;

-- Task -> agent assignment
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'unified_tasks' AND column_name = 'assigned_agent'
    ) THEN
        ALTER TABLE unified_tasks ADD COLUMN assigned_agent INT REFERENCES agents(id);
        CREATE INDEX idx_unified_tasks_agent ON unified_tasks(assigned_agent);
    END IF;
END $$;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < /mnt/archie_brain/database/migrations/154_project_knowledge_links.sql
```

Expected: No errors. Tables and columns created.

- [ ] **Step 3: Verify migration**

```bash
docker exec archie_database psql -U archie -d archie -c "\d project_knowledge_links"
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'unified_projects' AND column_name = 'embedding'"
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'bridge_jobs' AND column_name = 'project_id'"
docker exec archie_database psql -U archie -d archie -c "SELECT column_name FROM information_schema.columns WHERE table_name = 'unified_tasks' AND column_name = 'assigned_agent'"
```

Expected: All 4 queries return results confirming schema exists.

- [ ] **Step 4: Commit**

```bash
git add database/migrations/154_project_knowledge_links.sql
git commit -m "feat: add project_knowledge_links table and column additions for integration"
```

---

### Task 2: Knowledge Link Service

**Files:**
- Create: `platform_v2/services/knowledge_link_service.py`

- [ ] **Step 1: Create the service file**

```python
"""knowledge_link_service.py -- Project-Knowledge linking, gap analysis, auto-linking.

Provides CRUD for project<->knowledge links, embedding-based auto-linking,
and per-project knowledge gap analysis.
"""

import logging
import numpy as np
from typing import List, Dict, Optional, Tuple
from database import get_db_cursor

logger = logging.getLogger(__name__)

# --- Auto-linking constants ---
SIMILARITY_THRESHOLD = 0.70
BRIDGE_JOB_THRESHOLD = 0.60
CONFIDENCE_BOOST = 0.15
DEFAULT_BATCH_SIZE = 200
BACKFILL_BATCH_SIZE = 500

# --- Gap analysis weights ---
GAP_WEIGHTS = {
    "vault_note": 0.30,
    "mistake_learned": 0.20,
    "code_snippet": 0.15,
    "decisions": 0.20,
    "agent_activity": 0.15,
}


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a = np.array(vec1, dtype=np.float32)
    b = np.array(vec2, dtype=np.float32)
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


# --- CRUD ---


def link_knowledge_to_project(knowledge_id: int, project_id: int, link_type: str = "manual", confidence: float = 1.0) -> bool:
    """Create a manual or auto link between a knowledge entry and a project."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO project_knowledge_links (project_id, knowledge_id, link_type, confidence)
                   VALUES (%s, %s, %s, %s)
                   ON CONFLICT (project_id, knowledge_id) DO UPDATE
                   SET link_type = EXCLUDED.link_type, confidence = EXCLUDED.confidence""",
                (project_id, knowledge_id, link_type, min(confidence, 1.0)),
            )
            return True
    except Exception as e:
        logger.error("[KnowledgeLink] Failed to link knowledge %s to project %s: %s", knowledge_id, project_id, e)
        return False


def unlink_knowledge(knowledge_id: int, project_id: int) -> bool:
    """Remove a link between a knowledge entry and a project."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "DELETE FROM project_knowledge_links WHERE project_id = %s AND knowledge_id = %s",
                (project_id, knowledge_id),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error("[KnowledgeLink] Failed to unlink: %s", e)
        return False


def get_project_knowledge(project_id: int, type_filter: Optional[str] = None) -> List[Dict]:
    """Get all knowledge entries linked to a project."""
    try:
        with get_db_cursor() as (conn, cur):
            sql = """SELECT kb.id, kb.title, kb.knowledge_type, kb.category,
                            kb.importance_score, pkl.link_type, pkl.confidence, pkl.id as link_id
                     FROM project_knowledge_links pkl
                     JOIN knowledge_base kb ON kb.id = pkl.knowledge_id
                     WHERE pkl.project_id = %s"""
            params = [project_id]
            if type_filter:
                sql += " AND kb.knowledge_type = %s"
                params.append(type_filter)
            sql += " ORDER BY pkl.confidence DESC, kb.importance_score DESC"
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.error("[KnowledgeLink] get_project_knowledge failed: %s", e)
        return []


def get_knowledge_projects(knowledge_id: int) -> List[Dict]:
    """Get all projects linked to a knowledge entry."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT p.id, p.name, p.slug, p.status, pkl.link_type, pkl.confidence
                   FROM project_knowledge_links pkl
                   JOIN unified_projects p ON p.id = pkl.project_id
                   WHERE pkl.knowledge_id = %s
                   ORDER BY pkl.confidence DESC""",
                (knowledge_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        logger.error("[KnowledgeLink] get_knowledge_projects failed: %s", e)
        return []


# --- Gap Analysis ---


def get_project_knowledge_gaps(project_id: int) -> Dict:
    """Compute knowledge completeness score and gap details for a project."""
    try:
        with get_db_cursor() as (conn, cur):
            # Count linked knowledge by type
            cur.execute(
                """SELECT kb.knowledge_type, COUNT(*) as cnt
                   FROM project_knowledge_links pkl
                   JOIN knowledge_base kb ON kb.id = pkl.knowledge_id
                   WHERE pkl.project_id = %s
                   GROUP BY kb.knowledge_type""",
                (project_id,),
            )
            type_counts = {row[0]: row[1] for row in cur.fetchall()}

            # Count decisions
            cur.execute(
                "SELECT COUNT(*) FROM project_decisions WHERE project_id = %s",
                (project_id,),
            )
            decision_count = cur.fetchone()[0]

            # Count agent activity (bridge jobs)
            cur.execute(
                "SELECT COUNT(*) FROM bridge_jobs WHERE project_id = %s",
                (project_id,),
            )
            agent_activity_count = cur.fetchone()[0]

            # Compute gaps
            gaps = {}
            score = 0.0

            if type_counts.get("vault_note", 0) > 0:
                score += GAP_WEIGHTS["vault_note"]
            else:
                gaps["vault_note"] = "No documentation linked"

            if type_counts.get("mistake_learned", 0) > 0:
                score += GAP_WEIGHTS["mistake_learned"]
            else:
                gaps["mistake_learned"] = "No mistakes logged"

            if type_counts.get("code_snippet", 0) > 0:
                score += GAP_WEIGHTS["code_snippet"]
            else:
                gaps["code_snippet"] = "No code snippets linked"

            if decision_count > 0:
                score += GAP_WEIGHTS["decisions"]
            else:
                gaps["decisions"] = "No architectural decisions"

            if agent_activity_count > 0:
                score += GAP_WEIGHTS["agent_activity"]
            else:
                gaps["agent_activity"] = "No agent activity recorded"

            return {
                "project_id": project_id,
                "completeness": round(score * 100),
                "gaps": gaps,
                "counts": {
                    "vault_note": type_counts.get("vault_note", 0),
                    "mistake_learned": type_counts.get("mistake_learned", 0),
                    "code_snippet": type_counts.get("code_snippet", 0),
                    "decisions": decision_count,
                    "agent_activity": agent_activity_count,
                },
                "needs_attention": score < 0.50,
            }
    except Exception as e:
        logger.error("[KnowledgeLink] get_project_knowledge_gaps failed: %s", e)
        return {"project_id": project_id, "completeness": 0, "gaps": {}, "counts": {}, "needs_attention": True}


def get_all_gaps(status: str = "active") -> List[Dict]:
    """Get gap analysis for all projects with given status, sorted worst-first."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT id, name, slug FROM unified_projects WHERE status = %s ORDER BY priority DESC",
                (status,),
            )
            projects = cur.fetchall()

        results = []
        for pid, name, slug in projects:
            gap_data = get_project_knowledge_gaps(pid)
            gap_data["name"] = name
            gap_data["slug"] = slug
            results.append(gap_data)

        results.sort(key=lambda x: x["completeness"])
        return results
    except Exception as e:
        logger.error("[KnowledgeLink] get_all_gaps failed: %s", e)
        return []


# --- Auto-Linking ---


def _get_project_embeddings() -> List[Tuple[int, str, List[float], List[str]]]:
    """Fetch all active projects with their embeddings. Returns (id, slug, embedding, tags)."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, slug, embedding, tags
                   FROM unified_projects
                   WHERE status IN ('active', 'planning')
                   AND embedding IS NOT NULL"""
            )
            results = []
            for row in cur.fetchall():
                pid, slug, emb, tags = row
                if emb is not None:
                    emb_list = list(emb) if hasattr(emb, '__iter__') else []
                    tag_list = tags if isinstance(tags, list) else []
                    results.append((pid, slug, emb_list, tag_list))
            return results
    except Exception as e:
        logger.error("[KnowledgeLink] _get_project_embeddings failed: %s", e)
        return []


def _compute_project_embedding(project_id: int) -> bool:
    """Compute and cache embedding for a project from its name + description + tags."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT name, description, tags FROM unified_projects WHERE id = %s",
                (project_id,),
            )
            row = cur.fetchone()
            if not row:
                return False
            name, desc, tags = row

        # Build text to embed
        text_parts = [name or ""]
        if desc:
            text_parts.append(desc[:500])
        if tags and isinstance(tags, list):
            text_parts.append(" ".join(tags))
        text = " ".join(text_parts).strip()
        if not text:
            return False

        # Use the same embedding service as knowledge_base
        from tools.consciousness.services.knowledge_embedding_generator import KnowledgeEmbeddingGenerator

        generator = KnowledgeEmbeddingGenerator()
        embedding = generator.generate_embedding(text)
        if not embedding:
            return False

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "UPDATE unified_projects SET embedding = %s WHERE id = %s",
                (embedding, project_id),
            )
            return True
    except Exception as e:
        logger.error("[KnowledgeLink] _compute_project_embedding failed for %s: %s", project_id, e)
        return False


def auto_link_knowledge(batch_size: int = DEFAULT_BATCH_SIZE) -> Dict:
    """Auto-link unlinked knowledge entries to projects via embedding similarity.

    Called by the Autonomy job every 30 minutes.
    Returns stats dict with counts of linked/skipped/errors.
    """
    stats = {"linked": 0, "skipped": 0, "errors": 0, "projects_embedded": 0}

    try:
        # Step 1: Ensure all active projects have embeddings
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id FROM unified_projects
                   WHERE status IN ('active', 'planning')
                   AND embedding IS NULL"""
            )
            missing = [row[0] for row in cur.fetchall()]

        for pid in missing:
            if _compute_project_embedding(pid):
                stats["projects_embedded"] += 1

        # Step 2: Get project embeddings
        project_embeddings = _get_project_embeddings()
        if not project_embeddings:
            logger.info("[KnowledgeLink] No projects with embeddings, skipping auto-link")
            return stats

        # Step 3: Get unlinked knowledge entries with embeddings
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT kb.id, kb.embedding, kb.category, kb.tags
                   FROM knowledge_base kb
                   WHERE kb.embedding IS NOT NULL
                   AND kb.is_archived = false
                   AND NOT EXISTS (
                       SELECT 1 FROM project_knowledge_links pkl WHERE pkl.knowledge_id = kb.id
                   )
                   LIMIT %s""",
                (batch_size,),
            )
            unlinked = cur.fetchall()

        logger.info("[KnowledgeLink] Processing %d unlinked entries against %d projects", len(unlinked), len(project_embeddings))

        for kb_id, kb_embedding, kb_category, kb_tags in unlinked:
            try:
                if kb_embedding is None:
                    stats["skipped"] += 1
                    continue

                kb_emb_list = list(kb_embedding) if hasattr(kb_embedding, '__iter__') else []
                if not kb_emb_list:
                    stats["skipped"] += 1
                    continue

                kb_tag_list = kb_tags if isinstance(kb_tags, list) else []

                best_sim = 0.0
                best_project_id = None

                for pid, slug, proj_emb, proj_tags in project_embeddings:
                    sim = _cosine_similarity(kb_emb_list, proj_emb)

                    # Boost if category contains project slug or tags overlap
                    if kb_category and slug and slug in (kb_category or "").lower():
                        sim = min(sim + CONFIDENCE_BOOST, 1.0)
                    elif kb_tag_list and proj_tags and set(kb_tag_list) & set(proj_tags):
                        sim = min(sim + CONFIDENCE_BOOST, 1.0)

                    if sim > best_sim:
                        best_sim = sim
                        best_project_id = pid

                if best_sim >= SIMILARITY_THRESHOLD and best_project_id is not None:
                    if link_knowledge_to_project(kb_id, best_project_id, link_type="auto", confidence=best_sim):
                        stats["linked"] += 1
                    else:
                        stats["errors"] += 1
                else:
                    stats["skipped"] += 1

            except Exception as e:
                logger.error("[KnowledgeLink] Error processing kb_id %s: %s", kb_id, e)
                stats["errors"] += 1

        logger.info("[KnowledgeLink] Auto-link complete: %s", stats)
        return stats

    except Exception as e:
        logger.error("[KnowledgeLink] auto_link_knowledge failed: %s", e)
        stats["errors"] += 1
        return stats


def auto_link_bridge_jobs(batch_size: int = DEFAULT_BATCH_SIZE) -> Dict:
    """Auto-link bridge jobs to projects via text matching.

    Runs as part of the same Autonomy job. Matches job descriptions
    against project names/tags with a lower threshold.
    """
    stats = {"linked": 0, "skipped": 0, "errors": 0}

    try:
        project_embeddings = _get_project_embeddings()
        if not project_embeddings:
            return stats

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, capability, prompt
                   FROM bridge_jobs
                   WHERE project_id IS NULL
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (batch_size,),
            )
            unlinked_jobs = cur.fetchall()

        if not unlinked_jobs:
            return stats

        # Generate embeddings for job texts on the fly
        from tools.consciousness.services.knowledge_embedding_generator import KnowledgeEmbeddingGenerator

        generator = KnowledgeEmbeddingGenerator()

        for job_id, capability, prompt in unlinked_jobs:
            try:
                text = "{} {}".format(capability or "", (prompt or "")[:300]).strip()
                if not text:
                    stats["skipped"] += 1
                    continue

                job_emb = generator.generate_embedding(text)
                if not job_emb:
                    stats["skipped"] += 1
                    continue

                best_sim = 0.0
                best_pid = None

                for pid, slug, proj_emb, proj_tags in project_embeddings:
                    sim = _cosine_similarity(job_emb, proj_emb)
                    if sim > best_sim:
                        best_sim = sim
                        best_pid = pid

                if best_sim >= BRIDGE_JOB_THRESHOLD and best_pid is not None:
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            "UPDATE bridge_jobs SET project_id = %s WHERE id = %s",
                            (best_pid, job_id),
                        )
                    stats["linked"] += 1
                else:
                    stats["skipped"] += 1

            except Exception as e:
                logger.error("[KnowledgeLink] Error linking bridge job %s: %s", job_id, e)
                stats["errors"] += 1

        logger.info("[KnowledgeLink] Bridge job auto-link: %s", stats)
        return stats

    except Exception as e:
        logger.error("[KnowledgeLink] auto_link_bridge_jobs failed: %s", e)
        stats["errors"] += 1
        return stats
```

- [ ] **Step 2: Verify file syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/services/knowledge_link_service.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add platform_v2/services/knowledge_link_service.py
git commit -m "feat: add knowledge_link_service with auto-linking, gap analysis, CRUD"
```

---

### Task 3: Job Registration

**Files:**
- Create: `platform_v2/services/knowledge_link_jobs.py`
- Modify: `platform_v2/app.py:3270` (near `register_budget_jobs`)

- [ ] **Step 1: Create the jobs file**

```python
"""knowledge_link_jobs.py -- Auto-link knowledge to projects job registration.

Registers the auto-linking job with job_service. Called at app startup.
Follows the same pattern as budget_jobs.py.
"""

import logging
from services.knowledge_link_service import auto_link_knowledge, auto_link_bridge_jobs

logger = logging.getLogger(__name__)


def _run_auto_link():
    """Run both knowledge and bridge job auto-linking."""
    kb_stats = auto_link_knowledge()
    bj_stats = auto_link_bridge_jobs(batch_size=100)
    return {
        "knowledge": kb_stats,
        "bridge_jobs": bj_stats,
        "total_linked": kb_stats.get("linked", 0) + bj_stats.get("linked", 0),
    }


def register_knowledge_link_jobs(job_service):
    """Register knowledge auto-linking job with the central job service."""
    job_service.register_job(
        name="auto_link_knowledge_to_projects",
        func=_run_auto_link,
        interval_hours=0.5,
        department="Research & Development",
        description="Auto-link knowledge entries and bridge jobs to projects via embedding similarity (every 30 min)",
    )
    logger.info("[KnowledgeLinkJobs] Registered auto_link_knowledge_to_projects job")
```

- [ ] **Step 2: Register in app.py startup**

Find the block near line 3270 in `platform_v2/app.py` where `register_budget_jobs` is called. Add immediately after:

```python
            from services.knowledge_link_jobs import register_knowledge_link_jobs
            register_knowledge_link_jobs(_job_service)
```

- [ ] **Step 3: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/services/knowledge_link_jobs.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/knowledge_link_jobs.py platform_v2/app.py
git commit -m "feat: register auto_link_knowledge_to_projects Autonomy job"
```

---

### Task 4: Project Service — Agent Contributions

**Files:**
- Modify: `platform_v2/services/project_service.py` (append new function)

- [ ] **Step 1: Check existing imports**

Read the top of `platform_v2/services/project_service.py`. Ensure it has `import logging` and `logger = logging.getLogger(__name__)`. If not, add them.

- [ ] **Step 2: Append get_agent_contributions function**

Add at the bottom of the file:

```python
def get_agent_contributions(project_id, days=None):
    """Get agent work stats for a project: dispatch counts and task completions."""
    try:
        with get_db_cursor() as (conn, cur):
            # Bridge dispatch counts per agent
            if days:
                cur.execute(
                    """SELECT bj.agent_name, COUNT(*) as dispatch_count
                        FROM bridge_jobs bj
                        WHERE bj.project_id = %s
                        AND bj.created_at >= NOW() - make_interval(days => %s)
                        AND bj.agent_name IS NOT NULL
                        GROUP BY bj.agent_name
                        ORDER BY dispatch_count DESC""",
                    (project_id, days),
                )
            else:
                cur.execute(
                    """SELECT bj.agent_name, COUNT(*) as dispatch_count
                        FROM bridge_jobs bj
                        WHERE bj.project_id = %s
                        AND bj.agent_name IS NOT NULL
                        GROUP BY bj.agent_name
                        ORDER BY dispatch_count DESC""",
                    (project_id,),
                )
            dispatches = {row[0]: row[1] for row in cur.fetchall()}

            # Task completions per agent
            if days:
                cur.execute(
                    """SELECT a.name, COUNT(*) as task_count
                        FROM unified_tasks t
                        JOIN agents a ON a.id = t.assigned_agent
                        WHERE t.project_id = %s
                        AND t.status = 'completed'
                        AND t.completed_at >= NOW() - make_interval(days => %s)
                        GROUP BY a.name
                        ORDER BY task_count DESC""",
                    (project_id, days),
                )
            else:
                cur.execute(
                    """SELECT a.name, COUNT(*) as task_count
                        FROM unified_tasks t
                        JOIN agents a ON a.id = t.assigned_agent
                        WHERE t.project_id = %s
                        AND t.status = 'completed'
                        GROUP BY a.name
                        ORDER BY task_count DESC""",
                    (project_id,),
                )
            tasks = {row[0]: row[1] for row in cur.fetchall()}

            # Merge into unified agent list
            all_agents = set(list(dispatches.keys()) + list(tasks.keys()))
            contributions = []
            for agent in all_agents:
                contributions.append({
                    "agent_name": agent,
                    "dispatch_count": dispatches.get(agent, 0),
                    "tasks_completed": tasks.get(agent, 0),
                    "total_actions": dispatches.get(agent, 0) + tasks.get(agent, 0),
                })
            contributions.sort(key=lambda x: x["total_actions"], reverse=True)
            return contributions
    except Exception as e:
        logger.error("[ProjectService] get_agent_contributions failed: %s", e)
        return []
```

- [ ] **Step 3: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/services/project_service.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add platform_v2/services/project_service.py
git commit -m "feat: add get_agent_contributions to project_service"
```

---

### Task 5: Bridge Dispatcher — project_id Support

**Files:**
- Modify: `ai_bridge/bridge_dispatcher.py:7305-7380` (dispatch + dispatch_json functions)

- [ ] **Step 1: Read the request_work method**

Search `bridge_dispatcher.py` for the `bridge_jobs` INSERT statement to understand where job rows are created. Find the exact INSERT SQL.

- [ ] **Step 2: Add project_id to bridge_jobs INSERT**

In the method that inserts into `bridge_jobs`, add `project_id` to the column list and values. The `project_id` value comes from kwargs:

At the top of `request_work()` (or wherever the INSERT happens), extract:
```python
project_id = kwargs.pop("project_id", None)
```

Then in the INSERT statement, add `, project_id` to columns and `%s` to values, with `project_id` in the params tuple.

- [ ] **Step 3: Verify syntax**

```bash
python3 -c "import ast; ast.parse(open('/mnt/archie_brain/ai_bridge/bridge_dispatcher.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add ai_bridge/bridge_dispatcher.py
git commit -m "feat: pass project_id through bridge dispatch to bridge_jobs table"
```

---

### Task 6: Dashboard API Endpoints

**Files:**
- Modify: `platform_v2/tools/consciousness/dashboard_routes.py`

- [ ] **Step 1: Read the file to find insertion point**

Read dashboard_routes.py to find the end of `register_dashboard_routes()`. New routes go inside that function, after `api_dashboard_summary`.

- [ ] **Step 2: Add 5 new routes**

Add inside `register_dashboard_routes(bp, admin_required)`, after the existing `api_dashboard_summary` route:

```python
    @bp.route("/api/dashboard/project-knowledge/<int:project_id>")
    @login_required
    @admin_required
    def api_project_knowledge(project_id):
        """Get linked knowledge entries and gap analysis for a project."""
        from services.knowledge_link_service import get_project_knowledge, get_project_knowledge_gaps

        type_filter = request.args.get("type")
        knowledge = get_project_knowledge(project_id, type_filter=type_filter)
        gaps = get_project_knowledge_gaps(project_id)
        return jsonify({"success": True, "knowledge": knowledge, "gaps": gaps})

    @bp.route("/api/dashboard/agent-contributions/<int:project_id>")
    @login_required
    @admin_required
    def api_agent_contributions(project_id):
        """Get agent work stats for a project."""
        from services.project_service import get_agent_contributions

        days = request.args.get("days", type=int)
        contributions = get_agent_contributions(project_id, days=days)
        return jsonify({"success": True, "contributions": contributions})

    @bp.route("/api/dashboard/knowledge-gaps")
    @login_required
    @admin_required
    def api_knowledge_gaps():
        """Get gap analysis for all active projects, sorted worst-first."""
        from services.knowledge_link_service import get_all_gaps

        status = request.args.get("status", "active")
        gaps = get_all_gaps(status=status)
        return jsonify({"success": True, "gaps": gaps})

    @bp.route("/api/dashboard/link-knowledge", methods=["POST"])
    @login_required
    @admin_required
    def api_link_knowledge():
        """Manually link a knowledge entry to a project."""
        from services.knowledge_link_service import link_knowledge_to_project

        data = request.get_json() or {}
        project_id = data.get("project_id")
        knowledge_id = data.get("knowledge_id")
        if not project_id or not knowledge_id:
            return jsonify({"success": False, "error": "project_id and knowledge_id required"}), 400
        ok = link_knowledge_to_project(int(knowledge_id), int(project_id), link_type="manual")
        return jsonify({"success": ok})

    @bp.route("/api/dashboard/unlink-knowledge/<int:link_id>", methods=["DELETE"])
    @login_required
    @admin_required
    def api_unlink_knowledge(link_id):
        """Remove a project-knowledge link."""
        from database import get_db_cursor

        try:
            with get_db_cursor(commit=True) as (conn, cur):
                cur.execute(
                    "DELETE FROM project_knowledge_links WHERE id = %s RETURNING project_id, knowledge_id",
                    (link_id,),
                )
                row = cur.fetchone()
                if row:
                    return jsonify({"success": True, "removed": {"project_id": row[0], "knowledge_id": row[1]}})
                return jsonify({"success": False, "error": "Link not found"}), 404
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 3: Ensure `request` and `jsonify` are imported**

Check that `from flask import request, jsonify` is at the top. It likely already is since `api_dashboard_summary` exists.

- [ ] **Step 4: Verify syntax**

```bash
docker exec archie_platform python3 -c "import ast; ast.parse(open('/app/tools/consciousness/dashboard_routes.py').read()); print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/dashboard_routes.py
git commit -m "feat: add 5 dashboard API endpoints for project-knowledge integration"
```

---

### Task 7: Dashboard CSS

**Files:**
- Create: `platform_v2/static/css/consciousness-dashboard-v2.css`

- [ ] **Step 1: Create the CSS file**

```css
/* consciousness-dashboard-v2.css -- Project-Knowledge Integration Panels
   Prefix: cs- (matches consciousness module)
   Accent: #8b5cf6 (purple)
*/

/* --- Project-Knowledge Map --- */

.cs-project-card {
    background: rgba(139, 92, 246, 0.08);
    border: 1px solid rgba(139, 92, 246, 0.25);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 12px;
    cursor: pointer;
    transition: border-color 0.2s;
}

.cs-project-card:hover {
    border-color: rgba(139, 92, 246, 0.5);
}

.cs-project-card-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
}

.cs-project-card-title {
    font-family: 'Antonio', sans-serif;
    font-size: 1.1rem;
    color: #e2e8f0;
    text-transform: uppercase;
}

.cs-project-card-stats {
    display: flex;
    gap: 12px;
    font-size: 0.85rem;
    color: #94a3b8;
    align-items: center;
}

.cs-project-card-expanded {
    display: none;
    margin-top: 12px;
    padding-top: 12px;
    border-top: 1px solid rgba(139, 92, 246, 0.15);
}

.cs-project-card.expanded .cs-project-card-expanded {
    display: block;
}

.cs-kb-entry {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    font-size: 0.85rem;
    color: #cbd5e1;
}

.cs-link-badge {
    font-size: 0.7rem;
    padding: 2px 6px;
    border-radius: 4px;
    text-transform: uppercase;
    font-weight: 600;
}

.cs-link-badge.auto {
    background: rgba(0, 229, 255, 0.15);
    color: #00e5ff;
}

.cs-link-badge.manual {
    background: rgba(251, 191, 36, 0.15);
    color: #fbbf24;
}

/* --- Completeness Ring --- */

.cs-completeness-ring {
    width: 48px;
    height: 48px;
    position: relative;
    flex-shrink: 0;
}

.cs-completeness-ring svg {
    transform: rotate(-90deg);
    width: 48px;
    height: 48px;
}

.cs-completeness-ring .ring-bg {
    fill: none;
    stroke: rgba(139, 92, 246, 0.15);
    stroke-width: 4;
}

.cs-completeness-ring .ring-fill {
    fill: none;
    stroke: #8b5cf6;
    stroke-width: 4;
    stroke-linecap: round;
    transition: stroke-dashoffset 0.6s ease;
}

.cs-completeness-ring .ring-text {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.7rem;
    font-weight: 700;
    color: #e2e8f0;
}

/* --- Agent Contributions --- */

.cs-contrib-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.85rem;
}

.cs-contrib-table th {
    text-align: left;
    padding: 8px 12px;
    color: #8b5cf6;
    font-family: 'Antonio', sans-serif;
    text-transform: uppercase;
    font-size: 0.8rem;
    border-bottom: 1px solid rgba(139, 92, 246, 0.25);
}

.cs-contrib-table td {
    padding: 8px 12px;
    color: #cbd5e1;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.cs-contrib-filters {
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
}

.cs-contrib-filter-btn {
    padding: 4px 12px;
    border-radius: 4px;
    border: 1px solid rgba(139, 92, 246, 0.3);
    background: transparent;
    color: #94a3b8;
    cursor: pointer;
    font-size: 0.8rem;
    transition: all 0.2s;
}

.cs-contrib-filter-btn.active {
    background: rgba(139, 92, 246, 0.2);
    color: #8b5cf6;
    border-color: #8b5cf6;
}

/* --- Knowledge Gaps --- */

.cs-gap-row {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.cs-gap-name {
    flex: 1;
    font-size: 0.9rem;
    color: #e2e8f0;
}

.cs-gap-chips {
    display: flex;
    gap: 6px;
    flex-wrap: wrap;
}

.cs-gap-chip {
    font-size: 0.7rem;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 600;
}

.cs-gap-chip.docs { background: rgba(139, 92, 246, 0.15); color: #8b5cf6; }
.cs-gap-chip.mistakes { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.cs-gap-chip.snippets { background: rgba(34, 211, 238, 0.15); color: #22d3ee; }
.cs-gap-chip.decisions { background: rgba(251, 191, 36, 0.15); color: #fbbf24; }
.cs-gap-chip.activity { background: rgba(16, 185, 129, 0.15); color: #10b981; }

.cs-gap-actions {
    display: flex;
    gap: 6px;
}

.cs-gap-action-btn {
    padding: 4px 10px;
    border-radius: 4px;
    border: 1px solid rgba(139, 92, 246, 0.3);
    background: transparent;
    color: #94a3b8;
    cursor: pointer;
    font-size: 0.75rem;
    transition: all 0.2s;
}

.cs-gap-action-btn:hover {
    background: rgba(139, 92, 246, 0.15);
    color: #8b5cf6;
}

/* --- Responsive --- */

@media (max-width: 768px) {
    .cs-gap-row {
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
    }
    .cs-project-card-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 8px;
    }
    .cs-contrib-filters {
        flex-wrap: wrap;
    }
}

@media (max-width: 480px) {
    .cs-gap-actions {
        width: 100%;
    }
    .cs-gap-action-btn {
        flex: 1;
        text-align: center;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/css/consciousness-dashboard-v2.css
git commit -m "feat: add CSS for consciousness dashboard integration panels"
```

---

### Task 8: Dashboard JavaScript

**Files:**
- Create: `platform_v2/static/js/consciousness-dashboard-v2.js`

- [ ] **Step 1: Create the JS file**

Note: All user-derived content is passed through `escHtml()` (from consciousness.js) before DOM insertion to prevent XSS.

```javascript
/* consciousness-dashboard-v2.js -- Project-Knowledge Integration Panels
   Depends on: consciousness.js (api() and escHtml() helpers)
   Security: All dynamic content passed through escHtml() before rendering.
*/

(function () {
  "use strict";

  var _contribDays = null;
  var _contribProjectId = null;

  // --- Completeness Ring SVG ---

  function renderCompletenessRing(pct) {
    var r = 20, circ = 2 * Math.PI * r;
    var offset = circ - (pct / 100) * circ;
    var el = document.createElement("div");
    el.className = "cs-completeness-ring";

    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 48 48");

    var bg = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    bg.setAttribute("class", "ring-bg");
    bg.setAttribute("cx", "24");
    bg.setAttribute("cy", "24");
    bg.setAttribute("r", String(r));
    svg.appendChild(bg);

    var fill = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    fill.setAttribute("class", "ring-fill");
    fill.setAttribute("cx", "24");
    fill.setAttribute("cy", "24");
    fill.setAttribute("r", String(r));
    fill.setAttribute("stroke-dasharray", String(circ));
    fill.setAttribute("stroke-dashoffset", String(offset));
    svg.appendChild(fill);

    el.appendChild(svg);

    var txt = document.createElement("div");
    txt.className = "ring-text";
    txt.textContent = pct + "%";
    el.appendChild(txt);

    return el;
  }

  // --- Panel 1: Project-Knowledge Map ---

  function loadProjectKnowledgeMap() {
    api("/api/dashboard/knowledge-gaps").then(function (data) {
      if (!data || !data.success) return;
      var container = document.getElementById("cs-project-knowledge-map");
      if (!container) return;

      container.textContent = "";

      if (!data.gaps || data.gaps.length === 0) {
        var p = document.createElement("p");
        p.style.color = "#94a3b8";
        p.textContent = "No active projects found.";
        container.appendChild(p);
        return;
      }

      data.gaps.forEach(function (proj) {
        var card = document.createElement("div");
        card.className = "cs-project-card";
        card.addEventListener("click", function () {
          toggleProjectCard(card, proj.project_id);
        });

        var header = document.createElement("div");
        header.className = "cs-project-card-header";

        var title = document.createElement("span");
        title.className = "cs-project-card-title";
        title.textContent = proj.name;
        header.appendChild(title);

        var stats = document.createElement("div");
        stats.className = "cs-project-card-stats";
        stats.appendChild(renderCompletenessRing(proj.completeness));

        var labels = [
          (proj.counts.vault_note || 0) + " docs",
          (proj.counts.mistake_learned || 0) + " mistakes",
          (proj.counts.code_snippet || 0) + " snippets"
        ];
        labels.forEach(function (lbl) {
          var sp = document.createElement("span");
          sp.textContent = lbl;
          stats.appendChild(sp);
        });
        header.appendChild(stats);
        card.appendChild(header);

        var expanded = document.createElement("div");
        expanded.className = "cs-project-card-expanded";
        expanded.id = "cs-proj-expand-" + proj.project_id;
        card.appendChild(expanded);

        container.appendChild(card);
      });
    });
  }

  function toggleProjectCard(el, projectId) {
    var isExpanded = el.classList.contains("expanded");
    document.querySelectorAll(".cs-project-card.expanded").forEach(function (c) {
      c.classList.remove("expanded");
    });
    if (isExpanded) return;

    el.classList.add("expanded");
    var expandEl = document.getElementById("cs-proj-expand-" + projectId);
    if (!expandEl) return;

    expandEl.textContent = "";
    var loading = document.createElement("p");
    loading.style.color = "#94a3b8";
    loading.textContent = "Loading...";
    expandEl.appendChild(loading);

    // Also load agent contributions for this project
    loadAgentContributions(projectId, _contribDays);

    api("/api/dashboard/project-knowledge/" + projectId).then(function (data) {
      expandEl.textContent = "";
      if (!data || !data.success) {
        var err = document.createElement("p");
        err.style.color = "#ef4444";
        err.textContent = "Failed to load.";
        expandEl.appendChild(err);
        return;
      }
      var kb = data.knowledge || [];
      if (kb.length === 0) {
        var empty = document.createElement("p");
        empty.style.color = "#94a3b8";
        empty.textContent = "No linked knowledge entries yet.";
        expandEl.appendChild(empty);
        return;
      }
      kb.forEach(function (entry) {
        var row = document.createElement("div");
        row.className = "cs-kb-entry";

        var badge = document.createElement("span");
        badge.className = "cs-link-badge " + entry.link_type;
        badge.textContent = entry.link_type;
        row.appendChild(badge);

        var titleSpan = document.createElement("span");
        titleSpan.textContent = entry.title || "Untitled";
        row.appendChild(titleSpan);

        var typeSpan = document.createElement("span");
        typeSpan.style.color = "#64748b";
        typeSpan.style.marginLeft = "auto";
        typeSpan.textContent = entry.knowledge_type || "";
        row.appendChild(typeSpan);

        expandEl.appendChild(row);
      });
    });
  }

  // --- Panel 2: Agent Contributions ---

  function loadAgentContributions(projectId, days) {
    _contribProjectId = projectId;
    _contribDays = days;

    var url = "/api/dashboard/agent-contributions/" + projectId;
    if (days) url += "?days=" + days;

    api(url).then(function (data) {
      if (!data || !data.success) return;
      var container = document.getElementById("cs-agent-contributions-body");
      if (!container) return;

      container.textContent = "";

      var contribs = data.contributions || [];
      if (contribs.length === 0) {
        var p = document.createElement("p");
        p.style.color = "#94a3b8";
        p.textContent = "No agent contributions recorded for this project.";
        container.appendChild(p);
        return;
      }

      var table = document.createElement("table");
      table.className = "cs-contrib-table";

      var thead = document.createElement("thead");
      var headRow = document.createElement("tr");
      ["Agent", "Dispatches", "Tasks", "Total"].forEach(function (h) {
        var th = document.createElement("th");
        th.textContent = h;
        headRow.appendChild(th);
      });
      thead.appendChild(headRow);
      table.appendChild(thead);

      var tbody = document.createElement("tbody");
      contribs.forEach(function (c) {
        var tr = document.createElement("tr");
        var vals = [c.agent_name, c.dispatch_count, c.tasks_completed, c.total_actions];
        vals.forEach(function (v) {
          var td = document.createElement("td");
          td.textContent = String(v);
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      container.appendChild(table);
    });
  }

  window.setContribFilter = function (days) {
    document.querySelectorAll(".cs-contrib-filter-btn").forEach(function (b) {
      b.classList.toggle("active", parseInt(b.dataset.days || "0") === (days || 0));
    });
    if (_contribProjectId) {
      loadAgentContributions(_contribProjectId, days);
    }
  };

  // --- Panel 3: Knowledge Gaps ---

  function loadKnowledgeGaps() {
    api("/api/dashboard/knowledge-gaps").then(function (data) {
      if (!data || !data.success) return;
      var container = document.getElementById("cs-knowledge-gaps-body");
      if (!container) return;

      container.textContent = "";

      var gaps = data.gaps || [];
      if (gaps.length === 0) {
        var p = document.createElement("p");
        p.style.color = "#94a3b8";
        p.textContent = "No active projects.";
        container.appendChild(p);
        return;
      }

      var gapChipMap = {
        vault_note: { cls: "docs", label: "DOCS" },
        mistake_learned: { cls: "mistakes", label: "MISTAKES" },
        code_snippet: { cls: "snippets", label: "SNIPPETS" },
        decisions: { cls: "decisions", label: "DECISIONS" },
        agent_activity: { cls: "activity", label: "AGENTS" }
      };

      gaps.forEach(function (proj) {
        var row = document.createElement("div");
        row.className = "cs-gap-row";

        row.appendChild(renderCompletenessRing(proj.completeness));

        var nameSpan = document.createElement("span");
        nameSpan.className = "cs-gap-name";
        nameSpan.textContent = proj.name;
        row.appendChild(nameSpan);

        var chips = document.createElement("div");
        chips.className = "cs-gap-chips";
        Object.keys(proj.gaps || {}).forEach(function (key) {
          var info = gapChipMap[key];
          if (info) {
            var chip = document.createElement("span");
            chip.className = "cs-gap-chip " + info.cls;
            chip.textContent = info.label;
            chips.appendChild(chip);
          }
        });
        row.appendChild(chips);

        var actions = document.createElement("div");
        actions.className = "cs-gap-actions";

        var btnDecision = document.createElement("button");
        btnDecision.className = "cs-gap-action-btn";
        btnDecision.textContent = "+ Decision";
        btnDecision.addEventListener("click", function (e) {
          e.stopPropagation();
          window.location.href = "/dev-hq";
        });
        actions.appendChild(btnDecision);

        var btnDocs = document.createElement("button");
        btnDocs.className = "cs-gap-action-btn";
        btnDocs.textContent = "+ Docs";
        btnDocs.addEventListener("click", function (e) {
          e.stopPropagation();
          if (typeof switchConsciousnessTab === "function") {
            switchConsciousnessTab("knowledge");
          }
        });
        actions.appendChild(btnDocs);

        row.appendChild(actions);
        container.appendChild(row);
      });
    });
  }

  // --- Init ---

  window.loadDashboardV2Panels = function () {
    loadProjectKnowledgeMap();
    loadKnowledgeGaps();
  };

  // Hook into existing tab switch
  if (typeof window._dashboardV2Loaded === "undefined") {
    window._dashboardV2Loaded = true;
    var _origSwitch = window.switchConsciousnessTab;
    if (_origSwitch) {
      window.switchConsciousnessTab = function (tab) {
        _origSwitch(tab);
        if (tab === "dashboard") {
          loadDashboardV2Panels();
        }
      };
    }
  }
})();
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/static/js/consciousness-dashboard-v2.js
git commit -m "feat: add JS for consciousness dashboard integration panels (DOM-safe rendering)"
```

---

### Task 9: Dashboard HTML Panels

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

- [ ] **Step 1: Read the dashboard template**

Read `consciousness_dashboard.html` to find:
1. Where CSS links are included (in `<head>` or `{% block extra_head %}`)
2. Where JS scripts are loaded (before `</body>` or `{% block extra_scripts %}`)
3. Where `panel-dashboard` ends (the closing `</div>`)

- [ ] **Step 2: Add CSS link**

In the template's head section (with other CSS links), add:

```html
<link rel="stylesheet" href="/static/css/consciousness-dashboard-v2.css">
```

- [ ] **Step 3: Add JS script**

Before `</body>` or after the existing consciousness.js include, add:

```html
<script src="/static/js/consciousness-dashboard-v2.js"></script>
```

- [ ] **Step 4: Add the 3 LCARS panels inside panel-dashboard**

Insert before the closing `</div>` of `panel-dashboard`:

```html
<!-- Project-Knowledge Map -->
<div style="--frame-color: #8b5cf6; --frame-rgb: 139,92,246; margin-bottom: 20px; margin-top: 20px;">
  <div class="lcars-frame">
    <div class="lcars-sidebar">
      <div style="background:#8b5cf6;flex:2;border-radius:8px 0 0 0"></div>
      <div style="background:#6d28d9;flex:1"></div>
      <div style="background:#8b5cf6;flex:1;border-radius:0 0 0 8px"></div>
    </div>
    <div class="lcars-content">
      <div class="lcars-bar" style="background:#8b5cf6">
        <span class="lcars-bar-text">PROJECT-KNOWLEDGE MAP</span>
      </div>
      <div class="lcars-body" id="cs-project-knowledge-map">
        <p style="color:#94a3b8">Loading project-knowledge map...</p>
      </div>
      <div class="lcars-footer-bar" style="background:#8b5cf6"></div>
    </div>
  </div>
</div>

<!-- Agent Contributions -->
<div style="--frame-color: #8b5cf6; --frame-rgb: 139,92,246; margin-bottom: 20px;">
  <div class="lcars-frame">
    <div class="lcars-sidebar">
      <div style="background:#8b5cf6;flex:2;border-radius:8px 0 0 0"></div>
      <div style="background:#6d28d9;flex:1"></div>
      <div style="background:#8b5cf6;flex:1;border-radius:0 0 0 8px"></div>
    </div>
    <div class="lcars-content">
      <div class="lcars-bar" style="background:#8b5cf6">
        <span class="lcars-bar-text">AGENT CONTRIBUTIONS</span>
      </div>
      <div class="lcars-body">
        <div class="cs-contrib-filters">
          <button class="cs-contrib-filter-btn active" data-days="0" onclick="setContribFilter(null)">All Time</button>
          <button class="cs-contrib-filter-btn" data-days="7" onclick="setContribFilter(7)">7 Days</button>
          <button class="cs-contrib-filter-btn" data-days="30" onclick="setContribFilter(30)">30 Days</button>
        </div>
        <div id="cs-agent-contributions-body">
          <p style="color:#94a3b8">Select a project from the map above to see agent contributions.</p>
        </div>
      </div>
      <div class="lcars-footer-bar" style="background:#8b5cf6"></div>
    </div>
  </div>
</div>

<!-- Knowledge Gaps -->
<div style="--frame-color: #8b5cf6; --frame-rgb: 139,92,246; margin-bottom: 20px;">
  <div class="lcars-frame">
    <div class="lcars-sidebar">
      <div style="background:#8b5cf6;flex:2;border-radius:8px 0 0 0"></div>
      <div style="background:#6d28d9;flex:1"></div>
      <div style="background:#8b5cf6;flex:1;border-radius:0 0 0 8px"></div>
    </div>
    <div class="lcars-content">
      <div class="lcars-bar" style="background:#8b5cf6">
        <span class="lcars-bar-text">KNOWLEDGE GAPS</span>
      </div>
      <div class="lcars-body" id="cs-knowledge-gaps-body">
        <p style="color:#94a3b8">Loading knowledge gaps...</p>
      </div>
      <div class="lcars-footer-bar" style="background:#8b5cf6"></div>
    </div>
  </div>
</div>
```

- [ ] **Step 5: Wire up panel loading**

In `platform_v2/static/js/consciousness.js`, find the `loadTabData` function. In the `"dashboard"` case, add after the existing fetch call:

```javascript
if (typeof loadDashboardV2Panels === "function") { loadDashboardV2Panels(); }
```

- [ ] **Step 6: Deploy and verify**

```bash
docker compose restart archie_platform
```

Navigate to `http://192.168.1.200:3000/tools/consciousness` and check the Dashboard tab. Verify all 3 panels render.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html platform_v2/static/js/consciousness.js
git commit -m "feat: add project-knowledge map, agent contributions, and knowledge gaps panels to dashboard"
```

---

### Task 10: Deploy, Verify, and Complete

**Files:** None (verification only)

- [ ] **Step 1: Full restart**

```bash
docker compose restart archie_platform
```

- [ ] **Step 2: Verify migration**

```bash
docker exec archie_database psql -U archie -d archie -c "SELECT COUNT(*) FROM project_knowledge_links"
```

Expected: `0` (table exists, empty)

- [ ] **Step 3: Verify API endpoints**

```bash
curl -sb -c /tmp/cookies.txt http://192.168.1.200:3000/login -d "username=admin&password=..." && \
curl -sb -b /tmp/cookies.txt http://192.168.1.200:3000/tools/consciousness/api/dashboard/knowledge-gaps | python3 -m json.tool | head -20
```

Expected: JSON with `"success": true` and a `"gaps"` array.

- [ ] **Step 4: Trigger auto-linker manually**

```bash
docker exec archie_platform python3 -c "
from services.knowledge_link_service import auto_link_knowledge
result = auto_link_knowledge(batch_size=50)
print(result)
"
```

Expected: Stats dict showing links created.

- [ ] **Step 5: Verify dashboard in browser**

Open `http://192.168.1.200:3000/tools/consciousness` then Dashboard tab. Take screenshot and verify:
- Project-Knowledge Map panel shows active projects with completeness rings
- Knowledge Gaps panel shows projects ranked by completeness
- Clicking a project card expands to show linked KB entries

- [ ] **Step 6: Complete MCP task**

```
mcp complete_task 1633 "Dev HQ + Consciousness integration: project_knowledge_links table, auto-linker Autonomy job (30min), 5 dashboard API endpoints, 3 LCARS panels (project-knowledge map, agent contributions, knowledge gaps)"
```

- [ ] **Step 7: Log decision**

```
mcp log_decision "Consciousness Dashboard is the unified command center. Knowledge linked to projects via embedding similarity (auto, 0.70 threshold). Junction table for many-to-many. Bridge jobs and tasks get project_id/assigned_agent columns."
```

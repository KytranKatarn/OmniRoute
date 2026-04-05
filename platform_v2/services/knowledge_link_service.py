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
SIMILARITY_THRESHOLD = 0.40
BRIDGE_JOB_THRESHOLD = 0.30
CONFIDENCE_BOOST = 0.15
DEFAULT_BATCH_SIZE = 200
BACKFILL_BATCH_SIZE = 500

# Knowledge types worth auto-linking (skip external github_file noise)
LINKABLE_TYPES = ("vault_note", "mistake_learned", "code_snippet", "conversation_memory", "api_endpoint")

# --- Gap analysis weights ---
GAP_WEIGHTS = {
    "vault_note": 0.30,
    "mistake_learned": 0.20,
    "code_snippet": 0.15,
    "decisions": 0.20,
    "agent_activity": 0.15,
}


def _parse_embedding(emb) -> List[float]:
    """Parse an embedding from DB — may be a string '[0.1, 0.2, ...]' or a list."""
    if isinstance(emb, (list, tuple)):
        return [float(x) for x in emb]
    if isinstance(emb, str):
        emb = emb.strip("[] ")
        if not emb:
            return []
        return [float(x) for x in emb.split(",")]
    if hasattr(emb, "__iter__"):
        return [float(x) for x in emb]
    return []


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


def link_knowledge_to_project(
    knowledge_id: int, project_id: int, link_type: str = "manual", confidence: float = 1.0
) -> bool:
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
            return [dict(row) for row in cur.fetchall()]
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
            return [dict(row) for row in cur.fetchall()]
    except Exception as e:
        logger.error("[KnowledgeLink] get_knowledge_projects failed: %s", e)
        return []


# --- Gap Analysis ---


def get_project_knowledge_gaps(project_id: int) -> Dict:
    """Compute knowledge completeness score and gap details for a project."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT kb.knowledge_type, COUNT(*) as cnt
                   FROM project_knowledge_links pkl
                   JOIN knowledge_base kb ON kb.id = pkl.knowledge_id
                   WHERE pkl.project_id = %s
                   GROUP BY kb.knowledge_type""",
                (project_id,),
            )
            type_counts = {row["knowledge_type"]: row["cnt"] for row in cur.fetchall()}

            cur.execute(
                """SELECT COUNT(*) as cnt
                   FROM project_knowledge_links pkl
                   JOIN knowledge_base kb ON kb.id = pkl.knowledge_id
                   WHERE pkl.project_id = %s
                   AND kb.knowledge_type = 'vault_note'
                   AND kb.source_type = 'auto_documentation'""",
                (project_id,),
            )
            auto_doc_count = cur.fetchone()["cnt"]

            cur.execute(
                "SELECT COUNT(*) FROM project_decisions WHERE project_id = %s",
                (project_id,),
            )
            decision_count = cur.fetchone()["count"]

            cur.execute(
                "SELECT COUNT(*) FROM bridge_jobs WHERE project_id = %s",
                (project_id,),
            )
            agent_activity_count = cur.fetchone()["count"]

            gaps = {}
            score = 0.0

            human_vault_notes = type_counts.get("vault_note", 0) - auto_doc_count
            if human_vault_notes > 0:
                score += GAP_WEIGHTS["vault_note"]
            elif auto_doc_count > 0:
                gaps["vault_note"] = "Drafts only (auto-generated)"
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
                "has_draft_docs": auto_doc_count > 0,
            }
    except Exception as e:
        logger.error("[KnowledgeLink] get_project_knowledge_gaps failed: %s", e)
        return {"project_id": project_id, "completeness": 0, "gaps": {}, "counts": {}, "needs_attention": True}


def get_all_gaps(status: str = "active,planning") -> List[Dict]:
    """Get gap analysis for all projects with given statuses, sorted worst-first.

    status can be a single status or comma-separated list (e.g. 'active,planning').
    """
    try:
        statuses = [s.strip() for s in status.split(",")]
        with get_db_cursor() as (conn, cur):
            placeholders = ",".join(["%s"] * len(statuses))
            cur.execute(
                f"SELECT id, name, slug FROM unified_projects WHERE status IN ({placeholders}) ORDER BY priority DESC",
                statuses,
            )
            projects = cur.fetchall()

        results = []
        for row in projects:
            gap_data = get_project_knowledge_gaps(row["id"])
            gap_data["name"] = row["name"]
            gap_data["slug"] = row["slug"]
            results.append(gap_data)

        results.sort(key=lambda x: x["completeness"])
        return results
    except Exception as e:
        logger.error("[KnowledgeLink] get_all_gaps failed: %s", e)
        return []


# --- Auto-Linking ---


def _get_project_embeddings() -> List[Tuple[int, str, List[float], List[str]]]:
    """Fetch all active projects with their embeddings."""
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
                emb = row["embedding"]
                if emb is not None:
                    emb_list = _parse_embedding(emb)
                    tag_list = row["tags"] if isinstance(row["tags"], list) else []
                    results.append((row["id"], row["slug"], emb_list, tag_list))
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
            name, desc, tags = row["name"], row["description"], row["tags"]

        text_parts = [name or ""]
        if desc:
            text_parts.append(desc[:500])
        if tags and isinstance(tags, list):
            text_parts.append(" ".join(tags))
        text = " ".join(text_parts).strip()
        if not text:
            return False

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
    """Auto-link unlinked knowledge entries to projects via embedding similarity."""
    stats = {"linked": 0, "skipped": 0, "errors": 0, "projects_embedded": 0}

    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id FROM unified_projects
                   WHERE status IN ('active', 'planning')
                   AND embedding IS NULL"""
            )
            missing = [row["id"] for row in cur.fetchall()]

        for pid in missing:
            if _compute_project_embedding(pid):
                stats["projects_embedded"] += 1

        project_embeddings = _get_project_embeddings()
        if not project_embeddings:
            logger.info("[KnowledgeLink] No projects with embeddings, skipping auto-link")
            return stats

        # Backfill detection: use larger batch on first run
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT COUNT(*) as cnt FROM project_knowledge_links")
            if cur.fetchone()["cnt"] == 0:
                batch_size = BACKFILL_BATCH_SIZE
                logger.info("[KnowledgeLink] First run detected, using backfill batch size %d", batch_size)

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT kb.id, kb.embedding, kb.category, kb.tags
                   FROM knowledge_base kb
                   WHERE kb.embedding IS NOT NULL
                   AND kb.knowledge_type IN %s
                   AND NOT EXISTS (
                       SELECT 1 FROM project_knowledge_links pkl WHERE pkl.knowledge_id = kb.id
                   )
                   LIMIT %s""",
                (LINKABLE_TYPES, batch_size),
            )
            unlinked = cur.fetchall()

        logger.info(
            "[KnowledgeLink] Processing %d unlinked entries against %d projects", len(unlinked), len(project_embeddings)
        )

        for row in unlinked:
            kb_id, kb_embedding, kb_category, kb_tags = row["id"], row["embedding"], row["category"], row["tags"]
            try:
                if kb_embedding is None:
                    stats["skipped"] += 1
                    continue

                kb_emb_list = _parse_embedding(kb_embedding)
                if not kb_emb_list:
                    stats["skipped"] += 1
                    continue

                kb_tag_list = kb_tags if isinstance(kb_tags, list) else []

                linked_any = False

                for pid, slug, proj_emb, proj_tags in project_embeddings:
                    sim = _cosine_similarity(kb_emb_list, proj_emb)

                    if kb_category and slug and slug in (kb_category or "").lower():
                        sim = min(sim + CONFIDENCE_BOOST, 1.0)
                    elif kb_tag_list and proj_tags and set(kb_tag_list) & set(proj_tags):
                        sim = min(sim + CONFIDENCE_BOOST, 1.0)

                    if sim >= SIMILARITY_THRESHOLD:
                        if link_knowledge_to_project(kb_id, pid, link_type="auto", confidence=sim):
                            stats["linked"] += 1
                            linked_any = True
                        else:
                            stats["errors"] += 1

                if not linked_any:
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
    """Auto-link bridge jobs to projects via simple text matching.

    Matches project name or slug keywords against job capability/prompt text.
    Fast — no embedding generation needed.
    """
    stats = {"linked": 0, "skipped": 0, "errors": 0}

    try:
        # Get project names and slugs for text matching
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, name, slug, tags
                   FROM unified_projects
                   WHERE status IN ('active', 'planning')"""
            )
            projects = cur.fetchall()

        if not projects:
            return stats

        # Build keyword sets per project from name + slug + tags
        project_keywords = []
        for proj in projects:
            keywords = set()
            # Split slug on hyphens (e.g. "lcars-ui-consolidation" -> ["lcars", "ui", "consolidation"])
            for word in (proj["slug"] or "").split("-"):
                if len(word) >= 4:  # Skip short words like "the", "and", "new"
                    keywords.add(word.lower())
            # Add tags
            if isinstance(proj["tags"], list):
                for tag in proj["tags"]:
                    if len(tag) >= 4:
                        keywords.add(tag.lower())
            if keywords:
                project_keywords.append((proj["id"], proj["name"], keywords))

        if not project_keywords:
            return stats

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, job_type, description
                   FROM bridge_jobs
                   WHERE project_id IS NULL
                   ORDER BY created_at DESC
                   LIMIT %s""",
                (batch_size,),
            )
            unlinked_jobs = cur.fetchall()

        if not unlinked_jobs:
            return stats

        for row in unlinked_jobs:
            try:
                text = "{} {}".format(row["job_type"] or "", (row["description"] or "")[:500]).lower()
                if not text.strip():
                    stats["skipped"] += 1
                    continue

                best_match = 0
                best_pid = None

                for pid, pname, keywords in project_keywords:
                    matches = sum(1 for kw in keywords if kw in text)
                    if matches > best_match:
                        best_match = matches
                        best_pid = pid

                # Require at least 2 keyword matches to link
                if best_match >= 2 and best_pid is not None:
                    with get_db_cursor(commit=True) as (conn, cur):
                        cur.execute(
                            "UPDATE bridge_jobs SET project_id = %s WHERE id = %s",
                            (best_pid, row["id"]),
                        )
                    stats["linked"] += 1
                else:
                    stats["skipped"] += 1

            except Exception as e:
                logger.error("[KnowledgeLink] Error linking bridge job %s: %s", row["id"], e)
                stats["errors"] += 1

        logger.info("[KnowledgeLink] Bridge job auto-link: %s", stats)
        return stats

    except Exception as e:
        logger.error("[KnowledgeLink] auto_link_bridge_jobs failed: %s", e)
        stats["errors"] += 1
        return stats

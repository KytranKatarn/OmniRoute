"""consciousness/jobs.py — Background jobs owned by the Consciousness module.

Extracted from agent_loop.py (Phase 5). Each job is a standalone function.
Registration with APScheduler happens via register_consciousness_jobs().

Jobs extracted:
  - knowledge_deduplication (Job #28)
  - session_indexer (Job #29)
  - agent_consciousness_analysis (Job #49)
  - agent_consciousness_embedding (Job #50)
  - agent_skill_sync (Job #54)
  - agent_github_auto_pull (Job #55)
  - agent_skill_analyzer (Job #56)
  - agent_conversation_consolidation (migrated from consciousness_scheduler)
  - agent_improvement_detection (migrated from consciousness_scheduler)
  - agent_daily_self_reflection (migrated from consciousness_scheduler)
  - agent_weekly_memory_consolidation (migrated from consciousness_scheduler)
  - agent_github_repo_analysis (Job #57) — repo-level relevance analysis
  - agent_skill_adaptation (Job #58) — auto-adapt registered skills for A.R.C.H.I.E.
  - agent_skill_installer (Job #59) — install skills to Claude Code
  - agent_skill_tester (Job #60) — structural validation + dry-run testing
  - agent_skill_fleet_push (Job #61) — push tested skills to fleet nodes
"""

import json
import logging
import os
import time

from services.time_utils import now_local_str

logger = logging.getLogger("agent_loop")

# ---------------------------------------------------------------------------
# Shared helper: _log_cycle  (mirrors AgentLoop._log_cycle)
# ---------------------------------------------------------------------------

# Department mapping for consciousness jobs
_CONSCIOUSNESS_DEPARTMENT = "Documentation & Knowledge"


def _log_cycle(
    job_name: str,
    items_processed: int,
    items_failed: int,
    duration_ms: int,
    details: dict = None,
    error_message: str = None,
    department: str = None,
):
    """Log an agent loop execution cycle to autonomy_loop_log."""
    status = "error" if items_failed > 0 and items_processed == 0 else "partial" if items_failed > 0 else "success"
    # #5339: 107 of 107 failing rows recorded NO reason. Resolve it here rather
    # than at 186 call sites — most are inside an `except`, so the exception is
    # still live in sys.exc_info(). An explicit caller message always wins.
    #
    # GUARDED because this runs on the LOGGING path of every job. Not every caller
    # reaches _log_cycle with platform_v2 on sys.path — fleet_jobs inserts it
    # explicitly before its own service imports — and an ImportError here would
    # turn a LOGGED failure into an UNLOGGED crash, strictly worse than the bug
    # being fixed. F.O.R.G.E. flagged exactly this on PR #2546 and was right.
    try:
        from services.loop_log import explain_failure

        error_message = explain_failure(status, items_failed, error_message, details)
    except Exception:  # noqa: BLE001 — the resolver must never break logging
        pass
    try:
        from db import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO autonomy_loop_log
            (job_name, status, items_processed, items_failed, duration_ms, details, error_message, department)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_name,
                status,
                items_processed,
                items_failed,
                duration_ms,
                json.dumps(details or {}),
                error_message,
                department or _CONSCIOUSNESS_DEPARTMENT,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log agent cycle: {e}")


def _normalize_skill_content(
    skill_name: str,
    repo_name: str,
    skill_id: int,
    raw_content: str,
    quality_score: int,
    capabilities: list,
    departments: list,
    description: str = "",
) -> str:
    """Normalize skill content to standard superset markdown format.

    For already-valid markdown with frontmatter: passthrough with extended fields.
    For other content: wrap in standard format.
    Returns normalized markdown string.
    """
    import re

    import yaml

    # Check if content already has YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw_content, re.DOTALL)

    if fm_match:
        # Has frontmatter — merge our extended fields
        try:
            existing_meta = yaml.safe_load(fm_match.group(1)) or {}
        except yaml.YAMLError:
            existing_meta = {}
        body = fm_match.group(2).strip()

        # Preserve existing name/description if present, add ours if missing
        existing_meta.setdefault("name", skill_name)
        existing_meta.setdefault("description", description or skill_name)
        existing_meta["source_repo"] = repo_name
        existing_meta["quality_score"] = quality_score
        existing_meta["capabilities"] = capabilities or existing_meta.get("capabilities", [])
        existing_meta["departments"] = departments or existing_meta.get("departments", [])
        existing_meta["installed_from"] = skill_id
    else:
        # No frontmatter — build from scratch
        existing_meta = {
            "name": skill_name,
            "description": description or skill_name,
            "source_repo": repo_name,
            "quality_score": quality_score,
            "capabilities": capabilities or [],
            "departments": departments or [],
            "installed_from": skill_id,
        }
        body = raw_content.strip()

    # Build YAML frontmatter
    fm_lines = ["---"]
    fm_lines.append(f"name: {existing_meta['name']}")
    fm_lines.append(f"description: {existing_meta['description']}")
    fm_lines.append(f"source_repo: {existing_meta['source_repo']}")
    fm_lines.append(f"quality_score: {existing_meta['quality_score']}")
    if existing_meta.get("capabilities"):
        caps = ", ".join(str(c) for c in existing_meta["capabilities"])
        fm_lines.append(f"capabilities: [{caps}]")
    if existing_meta.get("departments"):
        depts = ", ".join(str(d) for d in existing_meta["departments"])
        fm_lines.append(f"departments: [{depts}]")
    fm_lines.append(f"installed_from: {existing_meta['installed_from']}")
    fm_lines.append("---")

    # Ensure body has a heading
    if not body.startswith("## ") and not body.startswith("# "):
        body = "## Instructions\n\n" + body

    # Append Archie CLI placeholder if not present
    if "## Archie CLI" not in body:
        body += "\n\n## Archie CLI\n\n(Not yet adapted for A.R.C.H.I.E. platform.)\n"

    # Truncate to 15,000 chars
    result = "\n".join(fm_lines) + "\n\n" + body
    if len(result) > 15000:
        result = result[:14900] + "\n\n<!-- Truncated: original content exceeded 15,000 chars -->\n"

    return result


# ---------------------------------------------------------------------------
# Job implementations (faithful copies from agent_loop.py)
# ---------------------------------------------------------------------------


def deduplicate_knowledge():
    """Job #28: Find and merge duplicate/overlapping knowledge entries."""
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=146,
            department="Documentation & Knowledge",
            session_type="knowledge_deduplication",
            title="Knowledge Deduplication Batch",
            metadata={"interval": "24h"},
        )
    except Exception as _wt_err:
        logger.warning("[C.O.D.E.X.] Work session create failed: %s", _wt_err)

    try:
        from database import get_db_cursor

        with get_db_cursor(commit=True) as (conn, cur):
            # Find entries with very similar titles (potential duplicates)
            cur.execute(
                """
                SELECT a.id as id1, b.id as id2, a.title as title1, b.title as title2
                FROM knowledge_base a
                JOIN knowledge_base b ON a.id < b.id
                WHERE a.is_archived = false AND b.is_archived = false
                AND a.category = b.category
                AND similarity(a.title, b.title) > 0.7
                LIMIT 20
            """
            )
            dupes = cur.fetchall()

            for dupe in dupes:
                # Keep the one with higher importance, archive the other
                cur.execute(
                    """
                    UPDATE knowledge_base SET knowledge_type = 'archie_v1'
                    WHERE id = (
                        SELECT id FROM knowledge_base
                        WHERE id IN (%s, %s)
                        ORDER BY importance_score ASC, created_at ASC
                        LIMIT 1
                    )
                """,
                    (dupe["id1"], dupe["id2"]),
                )

            if dupes:
                logger.info(f"[Knowledge] Archived {len(dupes)} duplicate entries")
        if _session:
            complete_work_session(_session, jobs_completed=1)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — this job performs NO LLM inference (pure DB/git/file work); the row fabricated an agent+model that never ran.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.
    except Exception as e:
        logger.error(f"[Knowledge] Deduplication error: {e}")
        if _session:
            fail_work_session(_session, error_msg=str(e))


def index_claude_sessions():
    """Job #29: Index recent Claude conversation sessions into knowledge_base."""
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=146,
            department="Documentation & Knowledge",
            session_type="session_indexer",
            title="Claude Session Indexer",
            metadata={"interval": "12h"},
        )
    except Exception as _wt_err:
        logger.warning("[C.O.D.E.X.] Work session create failed: %s", _wt_err)

    try:
        from services.session_indexer_service import index_recent_sessions

        count = index_recent_sessions(max_sessions=5)
        if count > 0:
            logger.info(f"[Sessions] Indexed {count} Claude sessions")
        if _session:
            complete_work_session(_session, jobs_completed=1)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — this job performs NO LLM inference (pure DB/git/file work); the row fabricated an agent+model that never ran.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.
    except Exception as e:
        logger.error(f"[Sessions] Indexing error: {e}")
        if _session:
            fail_work_session(_session, error_msg=str(e))


def consciousness_analysis_batch():
    """Job #49: Trigger consciousness analysis batch every 6 hours.

    Only runs if the analysis server loop is enabled in system_config.
    Uses _trigger_loop_op() from processing_routes which handles item
    selection, job creation, and background threading.
    """
    import time as _time

    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=137,
            department="Analytics & Intelligence",
            session_type="analysis_batch",
            title="KB Analysis Batch",
            metadata={"interval": "6h", "model": "mistral:7b"},
        )
    except Exception as _wt_err:
        logger.warning("[S.P.E.C.T.R.A.] Work session create failed: %s", _wt_err)

    start = _time.time()
    try:
        from tools.consciousness.processing_routes import (
            get_server_loops,
            _trigger_loop_op,
        )

        loops = get_server_loops()
        if not loops.get("analysis"):
            logger.debug("[ConsciousnessAnalysis] Analysis loop disabled — skipping")
            if _session:
                complete_work_session(_session, jobs_completed=0)
            return

        logger.info("[ConsciousnessAnalysis] Triggering scheduled analysis batch")
        _trigger_loop_op("analysis")
        _log_cycle(
            "consciousness_analysis",
            1,
            0,
            int((_time.time() - start) * 1000),
            department="Analytics & Intelligence",
        )
        if _session:
            complete_work_session(_session, jobs_completed=1)
        # [#3700] Removed hand-rolled task_execution_log row. _trigger_loop_op("analysis")
        # routes through knowledge_analyzer -> department_dispatcher, which already logs the
        # real per-inference row (actual model, eval_count tokens, real node_used_id). The old
        # hardcoded row (mistral:7b / success=true / node=68 / 0 tokens) was a lossy duplicate.
    except Exception as e:
        logger.warning(f"[ConsciousnessAnalysis] Analysis batch failed: {e}")
        _log_cycle(
            "consciousness_analysis",
            0,
            1,
            int((_time.time() - start) * 1000),
            error_message=str(e),
            department="Analytics & Intelligence",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def consciousness_embedding_batch():
    """Job #50: Trigger consciousness embedding batch every 4 hours.

    Only runs if the embedding server loop is enabled in system_config.
    Uses _trigger_loop_op() from processing_routes which handles
    item selection, job creation, and background threading.
    E.M.B.E.R. (id=126) owns this job — work session surfaces her in DHQ dispatch.
    """
    # E.M.B.E.R. (id=126) work session — surfaces in DHQ Work Tracking + dispatch
    _ember_session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _ember_session = create_work_session(
            agent_id=126,
            department="Documentation & Knowledge",
            session_type="embedding_batch",
            title="KB Embedding Batch — arctic-embed-cpu",
            metadata={"model": "arctic-embed-cpu", "triggered_by": "scheduler"},
        )
    except Exception as _wt_err:
        logger.warning("[E.M.B.E.R.] Work session create failed: %s", _wt_err)

    try:
        from tools.consciousness.processing_routes import (
            get_server_loops,
            _trigger_loop_op,
        )

        loops = get_server_loops()
        if not loops.get("embedding"):
            logger.debug("[Consciousness Batch] Embedding loop disabled — skipping")
            if _ember_session:
                complete_work_session(_ember_session, jobs_completed=0)
            return

        logger.info("[Consciousness Batch] Triggering scheduled embedding batch")
        _start_ts = time.time()
        _trigger_loop_op("embedding")
        _log_cycle("consciousness_embedding", 1, 0, 0, department="Documentation & Knowledge")
        # [#3700 Stage C] Honest embedding telemetry marker so E.M.B.E.R. shows in DHQ Dispatch
        # Traffic. Embeddings are the documented ADR-013 exception (direct Ollama arctic-embed,
        # NOT routed through the dispatcher), so this is an explicit per-cycle batch-trigger
        # marker — not a per-inference row. tokens_used=0 (vector-gen has no chat tokens);
        # node 68 = hub (Archie Starbase) where arctic-embed-cpu runs; request_metadata tags it
        # so the token chart classifies it as LOCAL vector-gen, not fabricated chat inference.
        try:
            from database import get_db_cursor
            from psycopg2.extras import Json

            with get_db_cursor(commit=True) as (_, _cur):
                _cur.execute(
                    """INSERT INTO task_execution_log
                           (agent_id, agent_name, model_used, provider, duration_ms,
                            tokens_used, success, capability, node_used_id, request_metadata)
                       VALUES (126, 'E.M.B.E.R.', 'arctic-embed-cpu', 'ollama', %s,
                               0, true, 'embedding', 68, %s)""",
                    (
                        int((time.time() - _start_ts) * 1000),
                        Json(
                            {
                                "row_kind": "embedding_batch_marker",
                                "token_source": "n/a_embedding",
                                "note": "per-cycle trigger marker; vector-gen (ADR-013 exception)",
                            }
                        ),
                    ),
                )
        except Exception as _tel:
            logger.debug("[E.M.B.E.R.] task_execution_log write failed: %s", _tel)
        if _ember_session:
            complete_work_session(_ember_session, jobs_completed=1)
    except Exception as e:
        _log_cycle(
            "consciousness_embedding",
            0,
            1,
            0,
            error_message=str(e),
            department="Documentation & Knowledge",
        )
        logger.warning(f"[Consciousness Batch] Embedding batch failed: {e}")
        if _ember_session:
            fail_work_session(_ember_session, error_msg=str(e))


def sync_learned_skills():
    """Job #54: Extract skills from ingested GitHub repos and write to Claude rules.

    Scans knowledge_base for github_file entries that contain skill/agent/plugin
    patterns. Builds a summary of learnable skills and writes to
    .claude/rules/learned-skills.md so Claude auto-loads them every session.

    Runs every 6 hours. Only rewrites if new skills are found since last sync.
    """
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=146,
            department="Documentation & Knowledge",
            session_type="skill_sync",
            title="Skill Sync to Claude Rules",
            metadata={"interval": "6h"},
        )
    except Exception as _wt_err:
        logger.warning("[C.O.D.E.X.] Work session create failed: %s", _wt_err)

    start = time.time()
    try:
        from database import get_db_cursor

        # Write to knowledge_base as vault_note — Claude reads via
        # mcp search_knowledge. Also write to host filesystem if accessible.
        rules_path = "/mnt/archie_brain/.claude/rules/learned-skills.md"

        with get_db_cursor() as (conn, cur):
            # Find skill-related files from ingested repos
            cur.execute(
                """
                SELECT DISTINCT
                    SPLIT_PART(title, '/', 1) || '/' || SPLIT_PART(title, '/', 2) as repo,
                    title,
                    LEFT(content, 600) as preview,
                    created_at
                FROM knowledge_base
                WHERE knowledge_type = 'github_file'
                AND content IS NOT NULL AND content != ''
                AND (
                    title ILIKE '%%/skill%%/README%%'
                    OR title ILIKE '%%/agent%%/README%%'
                    OR title ILIKE '%%/plugin%%/README%%'
                    OR title ILIKE '%%skill-creator%%'
                    OR title ILIKE '%%prompt-engineer%%'
                    OR title ILIKE '%%autonomy%%'
                    OR title ILIKE '%%anti-rationalization%%'
                    OR title ILIKE '%%context-engineering%%'
                    OR title ILIKE '%%writing-skills%%'
                )
                ORDER BY created_at DESC
                LIMIT 100
            """
            )
            skill_files = cur.fetchall()

            if not skill_files:
                logger.info("[SkillSync] No skill files found in KB")
                _log_cycle(
                    "skill_sync",
                    1,
                    0,
                    int((time.time() - start) * 1000),
                    department="Engineering & Technology",
                )
                return

            # Group by repo
            repos = {}
            for row in skill_files:
                repo = row["repo"]
                if repo not in repos:
                    repos[repo] = []
                repos[repo].append(
                    {
                        "title": row["title"],
                        "preview": row["preview"],
                    }
                )

            # Also count total github files per repo for context
            cur.execute(
                """
                SELECT
                    SPLIT_PART(title, '/', 1) || '/' || SPLIT_PART(title, '/', 2) as repo,
                    COUNT(*) as total_files
                FROM knowledge_base
                WHERE knowledge_type = 'github_file'
                GROUP BY repo
                ORDER BY total_files DESC
            """
            )
            repo_counts = {r["repo"]: r["total_files"] for r in cur.fetchall()}

        # Build the rules file
        lines = [
            "# Learned Skills from GitHub Ingestion",
            "",
            "Auto-generated by Agent Loop Job #54 (every 6 hours).",
            "These skills were extracted from GitHub repos ingested into the knowledge base.",
            f"Last sync: {now_local_str()}",
            "",
            "**To use:** Search `mcp search_knowledge` with the skill name for full content.",
            "",
            "---",
            "",
            "## Ingested Repos",
            "",
            "| Repo | Files | Skill Content |",
            "|------|-------|---------------|",
        ]

        for repo, total in sorted(repo_counts.items(), key=lambda x: x[1], reverse=True):
            skill_count = len(repos.get(repo, []))
            if skill_count > 0:
                lines.append(f"| {repo} | {total} | {skill_count} skill files |")
            elif total >= 50:
                lines.append(f"| {repo} | {total} | general |")

        lines.extend(["", "## Available Skills", ""])

        for repo, skills in sorted(repos.items()):
            lines.append(f"### {repo}")
            lines.append("")
            for skill in skills[:10]:  # Max 10 per repo
                title = skill["title"].split("/", 2)[-1] if "/" in skill["title"] else skill["title"]
                # Extract first meaningful line from preview
                preview_lines = [
                    l.strip()
                    for l in (skill["preview"] or "").split("\n")
                    if l.strip() and not l.strip().startswith("#") and not l.strip().startswith("--")
                ]
                desc = preview_lines[0][:120] if preview_lines else "No description"
                lines.append(f"- **{title}** — {desc}")
            lines.append("")

        # Add installation pipeline stats
        try:
            with get_db_cursor() as (conn_stats, cur_stats):
                cur_stats.execute(
                    """SELECT
                         COUNT(*) as installed,
                         COUNT(*) FILTER (WHERE dry_run_passed = TRUE) as passed,
                         COUNT(*) FILTER (WHERE dry_run_passed = FALSE) as failed,
                         COUNT(*) FILTER (WHERE adapted = TRUE) as adapted
                       FROM skill_installations
                       WHERE target = 'claude_code'"""
                )
                inst_stats = cur_stats.fetchone()
                lines.append("\n## Skill Catalog Pipeline\n")
                lines.append(
                    "> ⚠️ These GitHub-ingested skills are **reference docs**, NOT loadable "
                    "Claude Code skills. Claude Code only loads `.claude/skills/<name>/SKILL.md` "
                    "dirs + `.claude/commands/*.md`; flat files are silently ignored "
                    "(KB #272126). Use them via `mcp search_knowledge` + the index above.\n"
                )
                lines.append("| Metric | Count |")
                lines.append("|--------|-------|")
                lines.append(f"| Cataloged (KB-searchable) | {inst_stats['installed']} |")
                lines.append(f"| Tested (pass) | {inst_stats['passed']} |")
                lines.append(f"| Tested (fail) | {inst_stats['failed']} |")
                lines.append(f"| Adapted for A.R.C.H.I.E. | {inst_stats['adapted']} |")
        except Exception as stats_err:
            logger.warning(f"[SkillSync] Installation stats failed: {stats_err}")

        lines.extend(
            [
                "---",
                "",
                "## How to Learn from These",
                "",
                "1. `mcp search_knowledge` with the skill name for full content",
                "2. Read the patterns and apply to current task",
                "3. Anti-rationalization patterns (importance 0.95) should be checked when",
                "   about to skip verification or claim something works without testing",
                "",
                "## Key Patterns Already Integrated",
                "",
                "- **Anti-Rationalization** — rationalization table in feedback_03-never-guess.md",
                "- **Skill Creation Workflow** — brainstorm → template → validate → install",
                "- **Prompt Engineering Magic Mode** — auto-refine vague prompts silently",
                "- **Autonomous Execution (Loki Mode)** — auto-resume, kanban monitoring",
            ]
        )

        content = "\n".join(lines) + "\n"
        skill_count = sum(len(s) for s in repos.values())

        # Store in knowledge_base as vault_note (always accessible via MCP)
        with get_db_cursor(commit=True) as (conn2, cur2):
            cur2.execute(
                """
                INSERT INTO knowledge_base (
                    knowledge_type, title, content, category,
                    tags, importance_score
                ) VALUES (
                    'vault_note',
                    'Claude Learned Skills Index (Auto-Generated)',
                    %s, 'agent_skills',
                    %s, 0.90
                )
                ON CONFLICT (title) WHERE title IS NOT NULL DO UPDATE SET
                    content = EXCLUDED.content,
                    updated_at = NOW()
            """,
                (content, ["skill-sync", "auto-generated", "claude-rules"]),
            )

        # Register newly discovered skills in github_skills table
        try:
            with get_db_cursor(commit=True) as (conn3, cur3):
                new_registered = 0
                for repo, skills_list in repos.items():
                    for skill_item in skills_list:
                        title = skill_item["title"]
                        # Get KB entry ID for this skill
                        cur3.execute(
                            """SELECT id, file_path FROM knowledge_base
                               WHERE title = %s AND knowledge_type = 'github_file'
                               LIMIT 1""",
                            (title,),
                        )
                        kb_row = cur3.fetchone()
                        if not kb_row:
                            continue
                        # Upsert into github_skills
                        skill_name = title.split(": ", 1)[-1] if ": " in title else title
                        cur3.execute(
                            """INSERT INTO github_skills
                                   (kb_entry_id, repo_name, skill_name,
                                    description, file_path, status)
                               VALUES (%s, %s, %s, %s, %s, 'discovered')
                               ON CONFLICT (repo_name, file_path) DO NOTHING""",
                            (
                                kb_row["id"],
                                repo,
                                skill_name,
                                (skill_item.get("preview") or "")[:300],
                                kb_row["file_path"],
                            ),
                        )
                        if cur3.rowcount > 0:
                            new_registered += 1
                if new_registered > 0:
                    logger.info(f"[SkillSync] Registered {new_registered} new skills " f"in github_skills table")
        except Exception as reg_err:
            logger.warning(f"[SkillSync] Skill registration failed: {reg_err}")

        # Try writing to host filesystem (may fail if .claude not mounted)
        try:
            os.makedirs(os.path.dirname(rules_path), exist_ok=True)
            with open(rules_path, "w") as f:
                f.write(content)
            logger.info(f"[SkillSync] Wrote {len(repos)} repos, " f"{skill_count} skills to {rules_path}")
        except OSError:
            logger.info(
                f"[SkillSync] {rules_path} not writable from container. "
                f"Stored {len(repos)} repos, {skill_count} skills in KB only."
            )

        # Telegram notification if new skills discovered
        try:
            prev_count = getattr(sync_learned_skills, "_last_skill_count", 0)
            new_skills = skill_count - prev_count if prev_count > 0 else 0
            sync_learned_skills._last_skill_count = skill_count

            if new_skills > 0:
                try:
                    from services.telegram_service import send_sync

                    # Build notification
                    tg_lines = [f"{new_skills} new skill files found across {len(repos)} repos\n"]
                    tg_lines.append(f"Total skills indexed: {skill_count}\n")
                    # Show repos with most skills
                    top_repos = sorted(repos.items(), key=lambda x: len(x[1]), reverse=True)[:5]
                    for rname, rskills in top_repos:
                        tg_lines.append(f"\u2022 {rname} \u2014 {len(rskills)} skills")
                    tg_lines.append("\nView in Consciousness: http://192.168.1.200:3000/tools/consciousness?tab=github")
                    text = "\n".join(tg_lines)
                    send_sync(
                        "Skill Pipeline: New Skills",
                        text,
                        source_module="consciousness.jobs",
                    )
                    logger.info(f"[SkillSync] Telegram sent: {new_skills} new skills")
                except Exception as tg_inner_err:
                    logger.warning(f"[SkillSync] Telegram send failed: {tg_inner_err}")
            elif prev_count == 0:
                # First run — just store baseline, don't notify
                sync_learned_skills._last_skill_count = skill_count
                logger.info(f"[SkillSync] Baseline set: {skill_count} skills")
        except Exception as tg_err:
            logger.warning(f"[SkillSync] Telegram notification failed: {tg_err}")

        _log_cycle(
            "skill_sync",
            1,
            0,
            int((time.time() - start) * 1000),
            department="Engineering & Technology",
        )
        if _session:
            complete_work_session(_session, jobs_completed=1)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — this job performs NO LLM inference (pure DB/git/file work); the row fabricated an agent+model that never ran.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.

    except Exception as e:
        logger.warning(f"[SkillSync] Skill sync failed: {e}")
        _log_cycle(
            "skill_sync",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
            department="Engineering & Technology",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def github_auto_pull():
    """Job #55: Auto-pull tracked GitHub repos and re-index changed files.

    Every 12 hours:
    1. Iterate all repos in github_repositories with a local_path
    2. Git pull each one, detect new commits via rev comparison
    3. For repos with changes, trigger re-index of changed files only
    4. Send Telegram notification summarizing what was refreshed
    """
    import subprocess

    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=136,
            department="Engineering & Technology",
            session_type="github_auto_pull",
            title="GitHub Auto-Pull & Re-Index",
            metadata={"interval": "12h"},
        )
    except Exception as _wt_err:
        logger.warning("[F.O.R.G.E.] Work session create failed: %s", _wt_err)

    start = time.time()
    pulled = 0
    changed_repos = []
    errors = []

    try:
        from database import get_db_cursor

        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, repo_name, repo_type, local_path, status
                   FROM github_repositories
                   WHERE status IN ('cloned', 'indexed')
                   ORDER BY repo_name"""
            )
            repos = cur.fetchall()

        if not repos:
            logger.info("[GitPull] No tracked repos to pull")
            _log_cycle(
                "github_auto_pull",
                1,
                0,
                int((time.time() - start) * 1000),
                department="Engineering & Technology",
            )
            return

        for repo_row in repos:
            repo_name = repo_row["repo_name"]
            local_path = repo_row["local_path"]
            repo_type = repo_row["repo_type"]

            # Skip if not actually cloned on disk
            git_dir = os.path.join(local_path, ".git")
            if not os.path.isdir(git_dir):
                continue

            try:
                # Get current rev before pull
                rev_before = subprocess.run(
                    ["git", "-C", local_path, "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                old_rev = rev_before.stdout.strip() if rev_before.returncode == 0 else None

                # Pull
                result = subprocess.run(
                    ["git", "-C", local_path, "pull", "--ff-only"],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    # Try fetch + reset if ff-only fails
                    subprocess.run(
                        ["git", "-C", local_path, "fetch", "origin"],
                        capture_output=True,
                        text=True,
                        timeout=120,
                    )
                    subprocess.run(
                        ["git", "-C", local_path, "reset", "--hard", "origin/HEAD"],
                        capture_output=True,
                        text=True,
                        timeout=60,
                    )

                pulled += 1

                # Get new rev after pull
                rev_after = subprocess.run(
                    ["git", "-C", local_path, "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                new_rev = rev_after.stdout.strip() if rev_after.returncode == 0 else None

                # Update last_pull timestamp
                with get_db_cursor(commit=True) as (conn2, cur2):
                    cur2.execute(
                        "UPDATE github_repositories SET last_pull = NOW(), updated_at = NOW() WHERE id = %s",
                        (repo_row["id"],),
                    )

                # Check if anything changed
                if old_rev and new_rev and old_rev != new_rev:
                    # Count changed files
                    diff_result = subprocess.run(
                        [
                            "git",
                            "-C",
                            local_path,
                            "diff",
                            "--name-only",
                            old_rev,
                            new_rev,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    changed_files = [f for f in diff_result.stdout.strip().split("\n") if f.strip()]
                    # Incremental re-index: only changed files, from disk
                    try:
                        from tools.consciousness.github_routes import (
                            _incremental_reindex_from_disk,
                        )

                        owner_part, repo_part = repo_name.split("/", 1)
                        idx_count, del_count, skip_count, idx_errors = _incremental_reindex_from_disk(
                            owner_part,
                            repo_part,
                            repo_type,
                            local_path,
                            changed_files,
                            importance=0.85,
                        )
                        logger.info(
                            f"[GitPull] Incremental re-index for {repo_name}: "
                            f"{idx_count} indexed, {del_count} deleted, "
                            f"{skip_count} skipped"
                        )
                    except Exception as idx_err:
                        logger.warning(f"[GitPull] Incremental re-index failed for " f"{repo_name}: {idx_err}")
                        idx_count = 0

                    changed_repos.append(
                        {
                            "name": repo_name,
                            "type": repo_type,
                            "changed_files": len(changed_files),
                            "indexed": idx_count,
                        }
                    )

            except subprocess.TimeoutExpired:
                errors.append(f"{repo_name}: timeout")
            except Exception as pull_err:
                errors.append(f"{repo_name}: {str(pull_err)[:80]}")

        # Send Telegram notification if repos changed
        if changed_repos:
            try:
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                if bot_token:
                    lines = ["\U0001f504 *GitHub Auto-Pull Complete*\n"]
                    total_changed = sum(r["changed_files"] for r in changed_repos)
                    lines.append(f"*{len(changed_repos)}* repos updated, " f"*{total_changed}* files changed\n")
                    total_indexed = sum(r.get("indexed", 0) for r in changed_repos)
                    for r in changed_repos[:10]:
                        idx = r.get("indexed", 0)
                        lines.append(f"\u2022 `{r['name']}` \u2014 {r['changed_files']} changed, {idx} re-indexed")
                    if len(changed_repos) > 10:
                        lines.append(f"\u2022 ...and {len(changed_repos) - 10} more")
                    lines.append(f"\n*{total_indexed}* files re-indexed from disk. " f"Skill sync will run next cycle.")
                    text = "\n".join(lines)

                    from services.telegram_service import send_sync

                    send_sync(
                        "GitHub Auto-Pull Complete",
                        text,
                        source_module="consciousness.jobs",
                    )
            except Exception as tg_err:
                logger.warning(f"[GitPull] Telegram notification failed: {tg_err}")

        logger.info(f"[GitPull] Pulled {pulled} repos, " f"{len(changed_repos)} had changes, {len(errors)} errors")
        _log_cycle(
            "github_auto_pull",
            1,
            0,
            int((time.time() - start) * 1000),
            department="Engineering & Technology",
        )
        if _session:
            complete_work_session(_session, jobs_completed=pulled)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — this job performs NO LLM inference (pure DB/git/file work); the row fabricated an agent+model that never ran.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.

    except Exception as e:
        logger.warning(f"[GitPull] Auto-pull failed: {e}")
        _log_cycle(
            "github_auto_pull",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
            department="Engineering & Technology",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def analyze_discovered_skills():
    """Job #56: AI-analyze discovered skills from GitHub repos.

    Picks up skills with status='discovered' from github_skills table,
    sends each to Bridge for analysis (quality, capabilities, use cases),
    updates the skill record with results.

    Processes up to 10 skills per run to avoid overloading the Bridge.
    Runs every 6 hours, offset from skill sync.
    """
    # Recovery: reset skills stuck in 'analyzing' for >1 hour (crash orphans)
    try:
        from db import get_db

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE github_skills SET status = 'discovered', updated_at = NOW()
            WHERE status = 'analyzing' AND updated_at < NOW() - INTERVAL '1 hour'
        """
        )
        recovered = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        if recovered:
            logger.info("[SkillAnalyzer] Recovered %d stuck 'analyzing' skills", recovered)
    except Exception as e:
        logger.warning("[SkillAnalyzer] Recovery query failed: %s", e)

    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=136,
            department="Engineering & Technology",
            session_type="skill_analysis",
            title="Skill Analyzer (Bridge AI)",
            metadata={"interval": "6h"},
        )
    except Exception as _wt_err:
        logger.warning("[F.O.R.G.E.] Work session create failed: %s", _wt_err)

    start = time.time()
    analyzed = 0
    errors_count = 0

    try:
        from database import get_db_cursor
        from tools.department_hq.services.department_dispatcher import dispatch_json
        from services.agent_service import add_skill
        from services.fleet_dispatch_profile import NEWS_DEPARTMENT

        # Fetch up to 25 unanalyzed skills (increased from 10 to clear backlog faster)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT gs.id, gs.repo_name, gs.skill_name, gs.file_path,
                          gs.description, kb.content
                   FROM github_skills gs
                   LEFT JOIN knowledge_base kb ON kb.id = gs.kb_entry_id
                   WHERE gs.status = 'discovered'
                   ORDER BY gs.created_at ASC
                   LIMIT 25"""
            )
            skills = cur.fetchall()

        if not skills:
            logger.info("[SkillAnalyzer] No discovered skills to analyze")
            _log_cycle(
                "skill_analyzer",
                1,
                0,
                int((time.time() - start) * 1000),
                department="Engineering & Technology",
            )
            return

        logger.info(f"[SkillAnalyzer] Analyzing {len(skills)} skills")

        for skill in skills:
            skill_id = skill["id"]
            content = skill.get("content") or skill.get("description") or ""
            if not content or len(content.strip()) < 50:
                # Too little content to analyze — mark as analyzed with low score
                with get_db_cursor(commit=True) as (conn2, cur2):
                    cur2.execute(
                        """UPDATE github_skills
                           SET status = 'analyzed', quality_score = 1,
                               analysis = %s, updated_at = NOW()
                           WHERE id = %s""",
                        (
                            json.dumps({"note": "Insufficient content for analysis"}),
                            skill_id,
                        ),
                    )
                analyzed += 1
                continue

            # Mark as analyzing
            with get_db_cursor(commit=True) as (conn2, cur2):
                cur2.execute(
                    "UPDATE github_skills SET status = 'analyzing', updated_at = NOW() WHERE id = %s",
                    (skill_id,),
                )

            # Build analysis prompt
            truncated = content[:3000]
            prompt = f"""Analyze this skill/tool from the GitHub repository "{skill['repo_name']}".
File: {skill['skill_name']}

Content:
---
{truncated}
---

Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "quality_score": <1-5 integer, 5=production-ready, 4=good, 3=decent, 2=basic, 1=stub>,
  "summary": "<1-2 sentence description of what this skill does>",
  "capabilities": [<list of capability tags like "code-review", "testing", "debugging", "deployment", "documentation", "refactoring", "security", "monitoring", "data-processing", "ai-prompting", "automation">],
  "target_departments": [<which A.R.C.H.I.E. departments could use this: "Engineering & Technology", "Research & Development", "Analytics & Intelligence", "Creative & Design", "Security & Compliance", "Operations & Infrastructure", "Marketing & Communications", "Logistics & Supply Chain", "Executive Office", "Diplomatic & External Relations", "Finance & Accounting", "Customer Success & Support", "Human Resources & Culture", "Medical & Wellness", "Legal & Regulatory", "Documentation & Knowledge">],
  "adaptation_value": "<high/medium/low - how valuable would it be to adapt this for A.R.C.H.I.E.>",
  "adaptation_notes": "<what would need to change to make it A.R.C.H.I.E.-native>"
}}"""

            system_prompt = (
                "You are a skill analyst for the A.R.C.H.I.E. platform. "
                "Evaluate external skills for quality, capabilities, and "
                "potential adaptation into A.R.C.H.I.E.'s agent workforce. "
                "Respond with valid JSON only."
            )

            try:
                result = dispatch_json(
                    capability="code_analysis",
                    prompt=prompt,
                    module_id="skill_analyzer",
                    system_prompt=system_prompt,
                    # #4343 P1b: GitHub skill/code analysis is batched background work — low
                    # priority so it yields the interactive reserved fleet stream.
                    priority="low",
                )

                if result and isinstance(result, dict):
                    quality = min(5, max(1, int(result.get("quality_score", 2))))
                    capabilities = result.get("capabilities", [])
                    summary = result.get("summary", "")
                    target_departments = result.get("target_departments", result.get("target_stations", []))

                    # Determine final status based on quality
                    new_status = "registered" if quality >= 3 else "analyzed"

                    with get_db_cursor(commit=True) as (conn2, cur2):
                        cur2.execute(
                            """UPDATE github_skills
                               SET status = %s,
                                   quality_score = %s,
                                   description = %s,
                                   capabilities = %s,
                                   analysis = %s,
                                   updated_at = NOW()
                               WHERE id = %s""",
                            (
                                new_status,
                                quality,
                                summary[:500] if summary else skill.get("description"),
                                json.dumps(capabilities),
                                json.dumps(result),
                                skill_id,
                            ),
                        )

                        # Create Repair Bay proposal for low-quality skills
                        if quality < 3:
                            try:
                                adaptation_notes = result.get("adaptation_notes", "")
                                skill_title = (
                                    f"Low-quality external skill: "
                                    f"{skill.get('skill_name', 'unknown')} "
                                    f"from {skill.get('repo_name', 'unknown repo')}"
                                )
                                skill_description = (
                                    f"GitHub skill analysis found quality_score={quality}/5 "
                                    f"(below threshold of 3). "
                                    f"Adaptation notes: {adaptation_notes or 'None provided.'}\n\n"
                                    f"Summary: {summary[:300] if summary else 'N/A'}"
                                )
                                cur2.execute(
                                    """
                                    INSERT INTO improvement_proposals
                                    (title, category, description, code_changes,
                                     rationale, priority, risk_level, status,
                                     metadata, collaboration_enabled)
                                    VALUES (%s, %s, %s, %s, %s, %s, %s,
                                            'proposed', %s::jsonb, false)
                                    """,
                                    (
                                        skill_title,
                                        "low_quality_skill",
                                        skill_description,
                                        "",
                                        (
                                            f"Auto-detected by GitHub skill analyzer: "
                                            f"quality={quality}/5 for skill #{skill_id}"
                                        ),
                                        "low",
                                        "low",
                                        json.dumps(
                                            {
                                                "skill_id": skill_id,
                                                "skill_name": skill.get("skill_name"),
                                                "repo_name": skill.get("repo_name"),
                                                "quality_score": quality,
                                                "capabilities": capabilities,
                                                "adaptation_notes": adaptation_notes,
                                                "source": "github_skill_analyzer",
                                            }
                                        ),
                                    ),
                                )
                                logger.info(
                                    f"[SkillAnalyzer] Created Repair Bay proposal "
                                    f"for low-quality skill #{skill_id} "
                                    f"(quality={quality})"
                                )
                            except Exception as proposal_err:
                                logger.warning(
                                    f"[SkillAnalyzer] Failed to create proposal "
                                    f"for skill #{skill_id}: "
                                    f"{str(proposal_err)[:120]}"
                                )

                        # Auto-assign to agents if quality >= 3
                        if quality >= 3 and target_departments:
                            # Map department names to skill_category values
                            department_to_category = {
                                "Engineering & Technology": "engineering",
                                "Research & Development": "research",
                                "Analytics & Intelligence": "analytics",
                                "Creative & Design": "creative",
                                "Security & Compliance": "security",
                                "Operations & Infrastructure": "operations",
                                "Marketing & Communications": "communications",
                                "Logistics & Supply Chain": "logistics",
                                "Executive Office": "operations",
                                "Diplomatic & External Relations": "diplomacy",
                                "Finance & Accounting": "finance",
                                "Customer Success & Support": "support",
                                "Human Resources & Culture": "hr",
                                "Medical & Wellness": "medical",
                                "Legal & Regulatory": "legal",
                                "Documentation & Knowledge": "documentation",
                                # Legacy station names (backward compat)
                                "ENGINEERING": "engineering",
                                "RESEARCH": "research",
                                "ANALYTICS": "analytics",
                                "CREATIVE": "creative",
                                "SECURITY": "security",
                                "OPERATIONS": "operations",
                                "COMMUNICATIONS": "communications",
                                "LOGISTICS": "logistics",
                                "COMMAND": "operations",
                                "DIPLOMATIC": "diplomacy",
                            }
                            categories = [department_to_category.get(s, s.lower()) for s in target_departments]

                            # Find agents in target departments
                            cur2.execute(
                                """SELECT DISTINCT a.id, a.name
                                   FROM agents a
                                   WHERE a.department IS NOT NULL
                                     -- ADR-010 #741: News & Media (WTF) is the only
                                     -- dedicated team — never auto-assign gh:* skills
                                     -- to it (was the recurring re-add of the cont-4 purge).
                                     AND a.department <> %s
                                     AND a.shift_state IN ('active', 'deployed')
                                     AND EXISTS (
                                         SELECT 1 FROM agent_skills ask
                                         WHERE ask.agent_id = a.id
                                           AND ask.skill_category = ANY(%s)
                                     )""",
                                (NEWS_DEPARTMENT, categories),
                            )
                            target_agents = cur2.fetchall()

                            assigned_ids = []
                            for agent_row in target_agents:
                                # Use first capability as skill name
                                gh_skill_name = (
                                    f"gh:{capabilities[0]}" if capabilities else f"gh:{skill['skill_name'][:50]}"
                                )
                                add_skill(
                                    agent_row["id"],
                                    gh_skill_name,
                                    level=min(quality, 3),
                                    category=categories[0] if categories else "general",
                                )
                                assigned_ids.append(agent_row["id"])

                            # Update github_skills with assigned agent IDs
                            if assigned_ids:
                                cur2.execute(
                                    """UPDATE github_skills
                                       SET agent_ids = %s
                                       WHERE id = %s""",
                                    (json.dumps(assigned_ids), skill_id),
                                )
                                logger.info(
                                    f"[SkillAnalyzer] Assigned skill to "
                                    f"{len(assigned_ids)} agents: "
                                    f"{[a['name'] for a in target_agents[:3]]}"
                                )

                    analyzed += 1
                    logger.info(
                        f"[SkillAnalyzer] Analyzed {skill['skill_name']} "
                        f"from {skill['repo_name']}: quality={quality}, "
                        f"caps={capabilities[:3]}"
                    )
                else:
                    # Bridge returned nothing — reset to discovered for retry
                    with get_db_cursor(commit=True) as (conn2, cur2):
                        cur2.execute(
                            """UPDATE github_skills
                               SET status = 'discovered', updated_at = NOW()
                               WHERE id = %s""",
                            (skill_id,),
                        )
                    errors_count += 1

            except Exception as dispatch_err:
                logger.warning(f"[SkillAnalyzer] Dispatch failed for skill #{skill_id}: " f"{str(dispatch_err)[:80]}")
                # Reset to discovered for retry
                with get_db_cursor(commit=True) as (conn2, cur2):
                    cur2.execute(
                        """UPDATE github_skills
                           SET status = 'discovered', updated_at = NOW()
                           WHERE id = %s""",
                        (skill_id,),
                    )
                errors_count += 1

        # Send Telegram summary if skills were analyzed
        if analyzed > 0:
            try:
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                if bot_token:

                    text = (
                        f"\U0001f52c *Skill Analysis Complete*\n\n"
                        f"*{analyzed}* skills analyzed, *{errors_count}* errors\n"
                        f"_{len(skills)} skills processed this cycle_\n\n"
                        f"[View Skills](http://192.168.1.200:3000/tools/consciousness?tab=github)"
                    )

                    from services.telegram_service import send_sync

                    send_sync(
                        "Skill Analysis Complete",
                        text,
                        source_module="consciousness.jobs",
                    )
            except Exception as tg_err:
                logger.warning(f"[SkillAnalyzer] Telegram notification failed: {tg_err}")

        logger.info(f"[SkillAnalyzer] Done: {analyzed} analyzed, {errors_count} errors")
        _log_cycle(
            "skill_analyzer",
            1,
            0,
            int((time.time() - start) * 1000),
            department="Engineering & Technology",
        )
        if _session:
            complete_work_session(_session, jobs_completed=analyzed)
        # [#3700] Removed hand-rolled task_execution_log row — this job dispatches its real
        # LLM work through department_dispatcher (see dispatch() above), which logs the real
        # per-inference row. The old hardcoded row (F.O.R.G.E./mistral:7b/node=68/0 tokens) was
        # a lossy duplicate.

    except Exception as e:
        logger.warning(f"[SkillAnalyzer] Job failed: {e}")
        _log_cycle(
            "skill_analyzer",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
            department="Engineering & Technology",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def conversation_consolidation():
    """Hourly conversation consolidation — migrated from consciousness_scheduler."""
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=146,
            department="Documentation & Knowledge",
            session_type="conversation_consolidation",
            title="Conversation Consolidation",
            metadata={"interval": "1h"},
        )
    except Exception as _wt_err:
        logger.warning("[C.O.D.E.X.] Work session create failed: %s", _wt_err)

    start = time.time()
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import hourly_conversation_consolidation

        result = hourly_conversation_consolidation()
        duration_ms = int((time.time() - start) * 1000)
        processed = result.get("messages_processed", 0) if isinstance(result, dict) else 0
        _log_cycle(
            "conversation_consolidation",
            processed,
            0,
            duration_ms,
            department="Documentation & Knowledge",
        )
        if _session:
            complete_work_session(_session, jobs_completed=1)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — real LLM work routes through department_dispatcher (via the helper / improvement_chat / auto_tagger), which logs the real per-inference row.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "conversation_consolidation",
            0,
            1,
            duration_ms,
            error_message=str(e),
            department="Documentation & Knowledge",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def improvement_detection():
    """Improvement detection every 6h — migrated from consciousness_scheduler."""
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=140,
            department="Research & Development",
            session_type="improvement_detection",
            title="Improvement Detection",
            metadata={"interval": "6h"},
        )
    except Exception as _wt_err:
        logger.warning("[D.A.R.W.I.N.] Work session create failed: %s", _wt_err)

    start = time.time()
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import (
            improvement_detection as _improvement_detection,
        )

        result = _improvement_detection()
        duration_ms = int((time.time() - start) * 1000)
        found = result.get("improvements_found", 0) if isinstance(result, dict) else 0
        _log_cycle(
            "improvement_detection",
            found,
            0,
            duration_ms,
            department="Engineering & Technology",
        )
        if _session:
            complete_work_session(_session, jobs_completed=1)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — real LLM work routes through department_dispatcher (via the helper / improvement_chat / auto_tagger), which logs the real per-inference row.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "improvement_detection",
            0,
            1,
            duration_ms,
            error_message=str(e),
            department="Engineering & Technology",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def daily_self_reflection():
    """Daily self-reflection at midnight — migrated from consciousness_scheduler."""
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=2,
            department="Executive Office",
            session_type="daily_reflection",
            title="Daily Self-Reflection",
            metadata={"interval": "24h"},
        )
    except Exception as _wt_err:
        logger.warning("[A.R.C.H.I.E.] Work session create failed: %s", _wt_err)

    start = time.time()
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import (
            daily_self_reflection as _daily_self_reflection,
        )

        _daily_self_reflection()
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("daily_self_reflection", 1, 0, duration_ms, department="Executive Office")
        if _session:
            complete_work_session(_session, jobs_completed=1)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — real LLM work routes through department_dispatcher (via the helper / improvement_chat / auto_tagger), which logs the real per-inference row.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "daily_self_reflection",
            0,
            1,
            duration_ms,
            error_message=str(e),
            department="Executive Office",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def weekly_memory_consolidation():
    """Weekly memory consolidation (Sun 3AM) — migrated from consciousness_scheduler."""
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=2,
            department="Executive Office",
            session_type="memory_consolidation",
            title="Weekly Memory Consolidation",
            metadata={"interval": "weekly"},
        )
    except Exception as _wt_err:
        logger.warning("[A.R.C.H.I.E.] Work session create failed: %s", _wt_err)

    start = time.time()
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import (
            weekly_memory_consolidation as _weekly_memory_consolidation,
        )

        result = _weekly_memory_consolidation()
        duration_ms = int((time.time() - start) * 1000)
        decayed = result.get("memories_decayed", 0) if isinstance(result, dict) else 0
        _log_cycle(
            "weekly_memory_consolidation",
            decayed,
            0,
            duration_ms,
            department="Executive Office",
        )
        if _session:
            complete_work_session(_session, jobs_completed=1)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — real LLM work routes through department_dispatcher (via the helper / improvement_chat / auto_tagger), which logs the real per-inference row.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle(
            "weekly_memory_consolidation",
            0,
            1,
            duration_ms,
            error_message=str(e),
            department="Executive Office",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def analyze_repo_relevance():
    """Job #57: AI-analyze GitHub repos for platform relevance.

    Picks repos with review_status='pending' or 'under_review',
    reads README + description, sends to Bridge for relevance analysis.
    Auto-approves high-relevance repos, escalates uncertain ones to Telegram.
    Processes up to 5 repos per run (every 6 hours).
    """
    start = time.time()
    analyzed = 0
    errors_count = 0

    try:
        from database import get_db_cursor
        from tools.department_hq.services.department_dispatcher import dispatch_json

        # Fetch repos needing review (skip recently reviewed)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, repo_name, repo_type, description, indexed_files
                   FROM github_repositories
                   WHERE review_status IN ('pending', 'under_review')
                     AND (reviewed_at IS NULL OR reviewed_at < NOW() - INTERVAL '7 days')
                   ORDER BY indexed_files DESC
                   LIMIT 5"""
            )
            repos = cur.fetchall()

        if not repos:
            logger.info("[RepoRelevance] No repos pending review")
            _log_cycle(
                "github_repo_analysis",
                0,
                0,
                int((time.time() - start) * 1000),
                department="Engineering & Technology",
            )
            return

        logger.info(f"[RepoRelevance] Analyzing {len(repos)} repos for relevance")

        for repo in repos:
            repo_id = repo["id"]
            repo_name = repo["repo_name"]

            # Fetch README from knowledge_base
            readme_content = ""
            try:
                with get_db_cursor() as (conn2, cur2):
                    cur2.execute(
                        """SELECT content FROM knowledge_base
                           WHERE knowledge_type = 'github_file'
                             AND title ILIKE %s
                             AND memory_metadata->>'repo' = %s
                           LIMIT 1""",
                        (f"%{repo_name}%README%", repo_name),
                    )
                    row = cur2.fetchone()
                    if row:
                        readme_content = row["content"][:2000]
            except Exception as readme_err:
                logger.debug(f"[RepoRelevance] No README for {repo_name}: {readme_err}")

            description = repo.get("description") or ""
            if not readme_content and not description:
                # No content to analyze — skip for now
                logger.debug(f"[RepoRelevance] No README or description for {repo_name}, skipping")
                continue

            # Build analysis prompt
            prompt = f"""You are a technology analyst for A.R.C.H.I.E., an AI platform running these services:
- AI agents (122 across 16 departments), Bridge dispatch, Ollama LLM inference
- Media generation (ComfyUI), Plex/Jellyfin media stack
- Security scanning (Nmap, Nuclei, ZAP, Nikto)
- Business Suite (CRM, invoicing, automation planned)
- Watch products (Civic, Legal, Market, Gov news aggregators)
- Website Designer, Store Builder, Content Studio
- Fleet node management (Starbase/Starship)
- Monitoring (Nagios, cAdvisor, ntopng, AdGuard)
- Agent Academy (training, benchmarks, skill development)
- Automation resale roadmap (n8n-style workflows + AI agents)

Analyze this GitHub repository and determine its relevance to our platform:
Repo: {repo_name}
Type: {repo.get("repo_type", "unknown")}
Description: {description[:500]}
README (first 2000 chars): {readme_content}
Files indexed: {repo.get("indexed_files", 0)}

Respond with ONLY valid JSON:
{{
  "relevance": "high" | "medium" | "low" | "none",
  "confidence": 0.0-1.0,
  "summary": "1-2 sentence description of what this repo does",
  "platform_connections": ["list of specific platform features this could enhance"],
  "relevance_tags": ["automation", "media-gen", "agent-framework", "security", "monitoring", "ui-patterns", "orchestration", "skills", "product-template", "embeddings", "benchmarking"],
  "recommendation": "approve" | "review" | "reject",
  "reasoning": "why this recommendation"
}}"""

            system_prompt = (
                "You are a technology analyst for the A.R.C.H.I.E. platform. "
                "Evaluate GitHub repositories for relevance to our AI platform, "
                "business suite, and automation roadmap. "
                "Be generous — consider indirect value like patterns, templates, "
                "and learning opportunities. Respond with valid JSON only."
            )

            try:
                # W.A.T.C.H. wins via skill match (code_analysis Lv4 added 2026-04-27)
                result = dispatch_json(
                    capability="code_analysis",
                    prompt=prompt,
                    module_id="repo_relevance_analyzer",
                    system_prompt=system_prompt,
                )

                if not result:
                    logger.warning(
                        f"[RepoRelevance] dispatch_json returned None for {repo_name} — LLM may have returned non-JSON"
                    )
                elif not isinstance(result, dict):
                    logger.warning(
                        f"[RepoRelevance] dispatch_json returned {type(result).__name__} for {repo_name}: {str(result)[:200]}"
                    )

                if result and isinstance(result, dict):
                    relevance = result.get("relevance", "low")
                    confidence = min(1.0, max(0.0, float(result.get("confidence", 0.5))))
                    summary = result.get("summary", "")
                    tags = result.get("relevance_tags", [])
                    connections = result.get("platform_connections", [])
                    reasoning = result.get("reasoning", "")
                    result.get("recommendation", "review")

                    # Decision logic: auto-approve high relevance, escalate rest
                    if relevance == "high" and confidence >= 0.7:
                        new_status = "approved"
                        notes = f"AI auto-approved: {summary}\nConnections: {', '.join(connections[:5])}\nReasoning: {reasoning}"
                    else:
                        new_status = "under_review"
                        notes = f"AI analysis ({relevance}, {confidence:.0%} confident): {summary}\nConnections: {', '.join(connections[:5])}\nReasoning: {reasoning}"

                    # Update repo
                    with get_db_cursor(commit=True) as (conn3, cur3):
                        cur3.execute(
                            """UPDATE github_repositories
                               SET review_status = %s,
                                   review_notes = %s,
                                   relevance_tags = %s,
                                   reviewed_at = NOW()
                               WHERE id = %s""",
                            (
                                new_status,
                                notes[:2000],
                                tags if tags else None,
                                repo_id,
                            ),
                        )

                    analyzed += 1
                    logger.info(
                        f"[RepoRelevance] {repo_name}: {relevance} relevance " f"({confidence:.0%}) → {new_status}"
                    )

                    # Telegram escalation for non-auto-approved repos
                    if new_status == "under_review":
                        try:
                            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                            if bot_token:

                                text = (
                                    f"\U0001f50d *Repo Review Needed*\n\n"
                                    f"*{repo_name}* ({repo.get('indexed_files', 0)} files)\n"
                                    f"{summary}\n\n"
                                    f"AI says: *{relevance}* relevance ({confidence:.0%} confident)\n"
                                    f"Connections: {', '.join(connections[:3]) or 'none identified'}\n"
                                    f"Reasoning: {reasoning[:200]}\n\n"
                                    f"[Review in Consciousness](http://192.168.1.200:3000/tools/consciousness?tab=github)"
                                )

                                from services.telegram_service import send_sync

                                send_sync(
                                    "Repo Relevance Analysis",
                                    text,
                                    source_module="consciousness.jobs",
                                )
                        except Exception as tg_err:
                            logger.warning(f"[RepoRelevance] Telegram failed: {tg_err}")

                else:
                    errors_count += 1
                    logger.warning(f"[RepoRelevance] Bridge returned nothing for {repo_name}")

            except Exception as dispatch_err:
                errors_count += 1
                logger.warning(f"[RepoRelevance] Dispatch failed for {repo_name}: " f"{str(dispatch_err)[:80]}")

        logger.info(f"[RepoRelevance] Done: {analyzed} analyzed, {errors_count} errors")
        _log_cycle(
            "github_repo_analysis",
            analyzed,
            errors_count,
            int((time.time() - start) * 1000),
            details={
                "repos_checked": len(repos),
                "analyzed": analyzed,
                "errors": errors_count,
            },
            department="Engineering & Technology",
        )
        # [#3700] Removed hand-rolled task_execution_log row — this job dispatches its real
        # per-repo LLM work through department_dispatcher (see dispatch above), which logs the
        # real per-inference rows. The old hardcoded row (D.A.R.W.I.N./'internal'/node=68/
        # 0 tokens) was a lossy duplicate.

    except Exception as e:
        logger.warning(f"[RepoRelevance] Job failed: {e}")
        _log_cycle(
            "github_repo_analysis",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
            department="Engineering & Technology",
        )


def auto_adapt_skills():
    """Job #58: Auto-adapt tested skills for A.R.C.H.I.E. platform.

    Takes quality 5 skills that passed dry-run testing, generates
    ## Archie CLI section with A.R.C.H.I.E.-native directives.
    Reads from skill_installations, not github_skills directly.
    Processes up to 10 per run (every 12 hours).
    """
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=136,
            department="Engineering & Technology",
            session_type="skill_adaptation",
            title="Skill Adaptation for A.R.C.H.I.E.",
            metadata={"interval": "12h"},
        )
    except Exception as _wt_err:
        logger.warning("[F.O.R.G.E.] Work session create failed: %s", _wt_err)

    start = time.time()
    adapted = 0
    errors_count = 0

    try:
        from database import get_db_cursor

        # Fetch registered skills not yet adapted
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT si.id AS installation_id, si.skill_id, si.install_path,
                          si.normalized_content,
                          gs.repo_name, gs.skill_name, gs.description,
                          gs.capabilities, gs.quality_score
                   FROM skill_installations si
                   JOIN github_skills gs ON gs.id = si.skill_id
                   WHERE si.target = 'claude_code'
                     AND si.dry_run_passed = TRUE
                     AND si.adapted = FALSE
                     AND gs.quality_score >= 5
                   ORDER BY gs.quality_score DESC, si.installed_at ASC
                   LIMIT 10"""
            )
            skills = cur.fetchall()

        if not skills:
            logger.info("[SkillAdapt] No registered skills ready for adaptation")
            _log_cycle(
                "skill_adaptation",
                0,
                0,
                int((time.time() - start) * 1000),
                department="Engineering & Technology",
            )
            return

        logger.info(f"[SkillAdapt] Adapting {len(skills)} skills for A.R.C.H.I.E.")

        for skill in skills:
            skill["skill_id"]
            content = skill.get("normalized_content") or skill.get("description") or ""
            if not content or len(content.strip()) < 50:
                continue

            truncated = content[:4000]
            analysis = skill.get("analysis") or {}
            if isinstance(analysis, str):
                try:
                    analysis = json.loads(analysis)
                except Exception:
                    analysis = {}

            prompt = f"""Adapt this external skill for the A.R.C.H.I.E. platform.

Original skill from "{skill['repo_name']}":
Name: {skill['skill_name']}
Capabilities: {skill.get('capabilities', '[]')}

Content:
---
{truncated}
---

A.R.C.H.I.E. context:
- 16 departments (Engineering, Security, Research, Creative, etc.)
- 122 AI agents with skills, departments, shift states
- Bridge dispatcher for all LLM inference (dispatch_json / dispatch)
- LCARS sci-fi UI with station terminals
- Knowledge base with 24,000+ entries and embeddings
- Agent Academy for training and benchmarks
- Autonomy module with scheduled agent loop jobs

Rewrite this skill to be A.R.C.H.I.E.-native:
1. Replace external references with A.R.C.H.I.E. equivalents
2. Map to relevant departments and agents
3. Use Bridge dispatcher patterns instead of direct LLM calls
4. Reference LCARS UI components where applicable
5. Keep the core technique/pattern intact

Respond with the adapted skill content as markdown. Start with a YAML frontmatter block:
---
name: <skill name>
description: <one line>
department: <target department>
capabilities: [<list>]
---
<adapted skill content>"""

            system_prompt = (
                "You are a skill adaptation engine for A.R.C.H.I.E. "
                "Rewrite external skills to use A.R.C.H.I.E.'s architecture. "
                "Preserve the core technique but map all references to the platform."
            )

            try:
                from tools.department_hq.services.department_dispatcher import dispatch

                # prefer_model typo — same rationale as the earlier call
                # site in this file. Route to W.A.T.C.H. which owns the
                # qwen2.5-coder:7b model today. See task #2129.
                dispatch_result = dispatch(
                    capability="code_analysis",
                    prompt=prompt,
                    module_id="skill_adapter",
                    system_prompt=system_prompt,
                    prefer_agent="W.A.T.C.H.",
                )
                if dispatch_result and dispatch_result.queued:
                    logger.info(
                        "[SkillAdapt] Deferred to queue for %s — model cold, will retry automatically",
                        skill["skill_name"],
                    )
                    result = None
                else:
                    result = dispatch_result.response if dispatch_result and dispatch_result.success else None

                if not result and not (dispatch_result and dispatch_result.queued):
                    logger.warning(
                        f"[SkillAdapt] Dispatch returned no result for {skill['skill_name']} — "
                        f"success={getattr(dispatch_result, 'success', '?')}, "
                        f"agent={getattr(dispatch_result, 'agent_name', '?')}, "
                        f"error={getattr(dispatch_result, 'error', '?')}"
                    )
                elif len(result) <= 100:
                    logger.warning(
                        f"[SkillAdapt] Response too short ({len(result)} chars) for {skill['skill_name']}: {result[:100]}"
                    )

                if result and isinstance(result, str) and len(result) > 100:
                    # Read current content and inject ## Archie CLI section
                    current = skill.get("normalized_content") or ""
                    if "## Archie CLI" in current:
                        # Replace existing Archie CLI section
                        import re

                        adapted_full = re.sub(
                            r"## Archie CLI\n.*$",
                            f"## Archie CLI\n\n{result}",
                            current,
                            flags=re.DOTALL,
                        )
                    else:
                        adapted_full = current + f"\n\n## Archie CLI\n\n{result}"

                    # Update skill_installations
                    with get_db_cursor(commit=True) as (conn2, cur2):
                        cur2.execute(
                            """UPDATE skill_installations
                               SET adapted = TRUE,
                                   adapted_content = %s,
                                   adapted_at = NOW()
                               WHERE id = %s""",
                            (adapted_full[:15000], skill["installation_id"]),
                        )

                    # Overwrite installed file with adapted version
                    full_path = os.path.join("/mnt/archie_brain", skill["install_path"])
                    if os.path.exists(os.path.dirname(full_path)):
                        with open(full_path, "w") as f:
                            f.write(adapted_full[:15000])

                    adapted += 1
                    logger.info(
                        f"[SkillAdapt] Adapted {skill['skill_name']} "
                        f"from {skill['repo_name']} → installation #{skill['installation_id']}"
                    )
                else:
                    errors_count += 1
                    logger.warning(f"[SkillAdapt] Bridge returned insufficient content for {skill['skill_name']}")

            except Exception as dispatch_err:
                errors_count += 1
                logger.warning(f"[SkillAdapt] Dispatch failed: {str(dispatch_err)[:80]}")

        # Telegram notification
        if adapted > 0:
            try:
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                if bot_token:

                    text = (
                        f"\U0001f9ec *Skill Adaptation Complete*\n\n"
                        f"*{adapted}* skills adapted for A.R.C.H.I.E.\n"
                        f"_{len(skills)} skills processed this cycle_\n\n"
                        f"[View in Consciousness](http://192.168.1.200:3000/tools/consciousness?tab=github)"
                    )

                    from services.telegram_service import send_sync

                    send_sync(
                        "Skills Adapted for A.R.C.H.I.E.",
                        text,
                        source_module="consciousness.jobs",
                    )
            except Exception as tg_err:
                logger.warning(f"[SkillAdapt] Telegram failed: {tg_err}")

        logger.info(f"[SkillAdapt] Done: {adapted} adapted, {errors_count} errors")
        _log_cycle(
            "skill_adaptation",
            adapted,
            errors_count,
            int((time.time() - start) * 1000),
            details={
                "skills_checked": len(skills),
                "adapted": adapted,
                "errors": errors_count,
            },
            department="Engineering & Technology",
        )
        if _session:
            complete_work_session(_session, jobs_completed=adapted)
        # [#3700] Removed hand-rolled task_execution_log row — this job dispatches its real
        # LLM work through department_dispatcher (see dispatch above), which logs the real
        # per-inference row. The old hardcoded row (F.O.R.G.E./mistral:7b/node=68/0 tokens)
        # was a lossy duplicate.

    except Exception as e:
        logger.warning(f"[SkillAdapt] Job failed: {e}")
        _log_cycle(
            "skill_adaptation",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
            department="Engineering & Technology",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def install_skills_to_claude():
    """Job #59: Catalog registered GitHub skills to the local skills LIBRARY.

    Takes quality 3+ registered skills not yet cataloged, normalizes content to a
    standard superset format, and writes them to .claude/skills-library/github/
    — a browsable reference corpus, NOT .claude/skills/ (which Claude Code scans).

    IMPORTANT: these are reference docs, NOT loadable Claude Code skills. Claude
    Code only loads .claude/skills/<name>/SKILL.md dirs + .claude/commands/*.md;
    flat .md files are silently ignored (KB #272126). The real access path is
    `mcp search_knowledge` + the auto-generated learned-skills.md index. Processes
    up to 5 per run (every 2 hours). No LLM dispatch — file writes only.
    """
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=136,
            department="Engineering & Technology",
            session_type="skill_install",
            title="GitHub Skill Library Cataloger",
            metadata={"interval": "2h"},
        )
    except Exception as _wt_err:
        logger.warning("[F.O.R.G.E.] Work session create failed: %s", _wt_err)

    start = time.time()
    installed = 0
    errors_count = 0
    skipped = 0

    try:
        from database import get_db_cursor

        # Fetch registered skills not yet installed to claude_code
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT gs.id, gs.repo_name, gs.skill_name, gs.file_path,
                          gs.description, gs.quality_score, gs.capabilities,
                          gs.analysis, kb.content
                   FROM github_skills gs
                   LEFT JOIN knowledge_base kb ON kb.id = gs.kb_entry_id
                   WHERE gs.status = 'registered'
                     AND gs.quality_score >= 3
                     AND gs.id NOT IN (
                         SELECT skill_id FROM skill_installations
                         WHERE target = 'claude_code'
                     )
                   ORDER BY gs.quality_score DESC, gs.created_at ASC
                   LIMIT 5"""
            )
            skills = cur.fetchall()

        if not skills:
            logger.info("[SkillInstaller] No registered skills to install")
            _log_cycle(
                "skill_installer",
                0,
                0,
                int((time.time() - start) * 1000),
                department="Engineering & Technology",
            )
            return

        logger.info(f"[SkillCatalog] Cataloging {len(skills)} GitHub skills to the skills library (KB-searchable)")

        # Skills LIBRARY (browsable reference corpus) — deliberately NOT under
        # .claude/skills/, which Claude Code scans for loadable <name>/SKILL.md
        # dirs. Flat files there are silently ignored (KB #272126 / #3962).
        base_dir = "/mnt/archie_brain/.claude/skills-library/github"
        os.makedirs(base_dir, exist_ok=True)

        for skill in skills:
            skill_id = skill["id"]
            content = skill.get("content") or skill.get("description") or ""

            if not content or len(content.strip()) < 50:
                skipped += 1
                continue

            # Extract departments from analysis JSON
            analysis = skill.get("analysis") or {}
            if isinstance(analysis, str):
                try:
                    analysis = json.loads(analysis)
                except Exception:
                    analysis = {}
            departments = analysis.get("target_departments", [])

            # Extract capabilities
            capabilities = skill.get("capabilities") or []
            if isinstance(capabilities, str):
                try:
                    capabilities = json.loads(capabilities)
                except Exception:
                    capabilities = []

            try:
                # Normalize content
                normalized = _normalize_skill_content(
                    skill_name=skill["skill_name"],
                    repo_name=skill["repo_name"],
                    skill_id=skill_id,
                    raw_content=content,
                    quality_score=skill.get("quality_score", 3),
                    capabilities=capabilities,
                    departments=departments,
                    description=skill.get("description", ""),
                )

                # Build catalog path: .claude/skills-library/github/<owner-repo>/<skill-slug>.md
                repo_slug = skill["repo_name"].replace("/", "-").lower()
                skill_slug = skill["skill_name"].replace("/", "-").replace(" ", "-").lower()
                if skill_slug.endswith(".md"):
                    skill_slug = skill_slug[:-3]
                skill_slug += ".md"

                repo_dir = os.path.join(base_dir, repo_slug)
                os.makedirs(repo_dir, exist_ok=True)
                install_path = os.path.join(repo_dir, skill_slug)

                # Write skill file
                with open(install_path, "w") as f:
                    f.write(normalized)

                # Record installation in DB
                rel_path = install_path.replace("/mnt/archie_brain/", "")
                with get_db_cursor(commit=True) as (conn2, cur2):
                    cur2.execute(
                        """INSERT INTO skill_installations
                           (skill_id, target, install_path, normalized_content, installed_at)
                           VALUES (%s, 'claude_code', %s, %s, NOW())
                           ON CONFLICT (skill_id, target) DO UPDATE
                           SET install_path = EXCLUDED.install_path,
                               normalized_content = EXCLUDED.normalized_content,
                               installed_at = NOW()""",
                        (skill_id, rel_path, normalized),
                    )

                installed += 1
                logger.info(
                    f"[SkillCatalog] Cataloged {skill['skill_name']} " f"from {skill['repo_name']} → {rel_path}"
                )

            except Exception as inst_err:
                errors_count += 1
                logger.warning(f"[SkillInstaller] Failed to install {skill['skill_name']}: " f"{str(inst_err)[:80]}")

        logger.info(f"[SkillCatalog] Done: {installed} cataloged, " f"{skipped} skipped, {errors_count} errors")
        _log_cycle(
            "skill_installer",
            installed,
            errors_count,
            int((time.time() - start) * 1000),
            details={
                "installed": installed,
                "skipped": skipped,
                "errors": errors_count,
            },
            department="Engineering & Technology",
        )
        if _session:
            complete_work_session(_session, jobs_completed=installed)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — this job performs NO LLM inference (pure DB/git/file work); the row fabricated an agent+model that never ran.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.

    except Exception as e:
        logger.warning(f"[SkillInstaller] Job failed: {e}")
        _log_cycle(
            "skill_installer",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
            department="Engineering & Technology",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


# Capability → test prompt mapping for dry-run testing
_SKILL_TEST_PROMPTS = {
    "code-review": "Review this Python function for quality issues:\n\ndef calculate_total(items):\n    total = 0\n    for i in items:\n        total = total + i['price'] * i['qty']\n    return total",
    "testing": "Write a unit test for a function `validate_email(email: str) -> bool` that checks if an email address is valid.",
    "debugging": "Debug this error: TypeError: cannot unpack non-iterable NoneType object. The function returns None when the input list is empty.",
    "documentation": "Document this API endpoint: POST /api/users — accepts JSON body with name, email, role fields. Returns 201 with user object or 400 with validation errors.",
    "refactoring": "Refactor this code to be more readable:\n\ndef f(x):\n    return [i for i in x if i > 0 and i % 2 == 0 and i < 100]",
    "security": 'Review this code for security vulnerabilities:\n\nquery = f"SELECT * FROM users WHERE id = {user_id}"',
    "deployment": "Write a Dockerfile for a Python 3.11 Flask application that needs PostgreSQL and Redis connections.",
    "ai-prompting": "Write a system prompt for an AI assistant that helps users debug Python code. The assistant should ask clarifying questions before suggesting fixes.",
    "automation": "Write a bash script that backs up a PostgreSQL database, compresses it, and removes backups older than 7 days.",
    "data-processing": "Write a Python function that reads a CSV file, filters rows where the 'status' column is 'active', and returns the count.",
    "monitoring": "Set up a health check endpoint for a Flask application that verifies database connectivity and returns JSON status.",
}

_DEFAULT_TEST_PROMPT = (
    "Using the skill described above, demonstrate your capability with a concrete example. Show your work step by step."
)


def _generate_test_prompt(capabilities: list) -> str:
    """Generate a test prompt based on skill capabilities."""
    for cap in capabilities:
        cap_lower = cap.lower().strip()
        if cap_lower in _SKILL_TEST_PROMPTS:
            return _SKILL_TEST_PROMPTS[cap_lower]
    return _DEFAULT_TEST_PROMPT


def _validate_skill_structure(content: str) -> tuple:
    """Validate skill markdown structure.

    Returns (is_valid: bool, errors: list[str]).
    """
    import re

    import yaml

    errors = []

    # Check YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not fm_match:
        errors.append("Missing YAML frontmatter (---)")
        return (False, errors)

    try:
        meta = yaml.safe_load(fm_match.group(1)) or {}
    except Exception as e:
        errors.append(f"Invalid YAML frontmatter: {str(e)[:80]}")
        return (False, errors)

    if not meta.get("name"):
        errors.append("Missing 'name' in frontmatter")
    if not meta.get("description"):
        errors.append("Missing 'description' in frontmatter")

    body = fm_match.group(2).strip()
    if len(body) < 100:
        errors.append(f"Body too short ({len(body)} chars, minimum 100)")

    # Check for unclosed code blocks
    fence_count = body.count("```")
    if fence_count % 2 != 0:
        errors.append(f"Unclosed code block ({fence_count} ``` markers)")

    is_valid = len(errors) == 0
    return (is_valid, errors)


def _evaluate_dry_run(response: str, capabilities: list, skill_content: str) -> dict:
    """Evaluate dry-run response against assertions.

    Returns dict of assertion results:
    {"length_ok": bool, "format_ok": bool, "relevant": bool, "no_hallucination": bool}
    """
    assertions = {}

    # Required: length check
    assertions["length_ok"] = len(response.strip()) > 200

    # Required: format check — no errors or refusals
    # Refusal patterns — only match clear refusals, not discussion of errors
    refusal_phrases = [
        "i don't understand",
        "i cannot",
        "i'm not able",
        "i can't help",
        "as an ai",
    ]
    # Error patterns — only match when at start of line (actual stack traces)
    error_line_patterns = [
        "\ntraceback (most recent",
        "\nsyntaxerror:",
        "\nnameerror:",
        "\ntypeerror:",
    ]
    response_lower = response.lower()
    has_refusal = any(p in response_lower for p in refusal_phrases)
    has_error = any(p in "\n" + response_lower for p in error_line_patterns)
    assertions["format_ok"] = not has_refusal and not has_error

    # Advisory: relevance — keyword overlap
    cap_keywords = set()
    for cap in capabilities:
        cap_keywords.update(cap.lower().replace("-", " ").split())
    # Also extract keywords from skill content (first 500 chars)
    content_words = set(skill_content[:500].lower().split())
    check_words = cap_keywords | (
        content_words & {"code", "test", "review", "api", "deploy", "security", "data", "build"}
    )

    if check_words:
        response_words = set(response_lower.split())
        overlap = check_words & response_words
        assertions["relevant"] = len(overlap) / max(len(check_words), 1) >= 0.3
    else:
        assertions["relevant"] = True  # No keywords to check against

    # Advisory: hallucination check (basic — flag obvious fabrications)
    hallucination_markers = ["api key:", "password:", "secret:", "token:"]
    assertions["no_hallucination"] = not any(m in response_lower for m in hallucination_markers)

    return assertions


def test_installed_skills():
    """Job #60: Structural validation + dry-run testing of installed skills.

    Picks up skill_installations rows where struct_valid IS NULL (untested),
    runs structural checks, then dry-runs passing skills through Bridge.
    Processes 1 per run (every 4 hours) — single dispatch to avoid model contention.
    """
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=136,
            department="Engineering & Technology",
            session_type="skill_test",
            title="Skill Tester (Structural + Dry-Run)",
            metadata={"interval": "4h"},
        )
    except Exception as _wt_err:
        logger.warning("[F.O.R.G.E.] Work session create failed: %s", _wt_err)

    start = time.time()
    tested = 0
    errors_count = 0

    try:
        from database import get_db_cursor

        from tools.department_hq.services.department_dispatcher import dispatch

        # Fetch ONE untested installation — single dispatch per cycle
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT si.id, si.skill_id, si.install_path, si.normalized_content,
                          gs.skill_name, gs.capabilities, gs.description
                   FROM skill_installations si
                   JOIN github_skills gs ON gs.id = si.skill_id
                   WHERE si.target = 'claude_code'
                     AND (si.struct_valid IS NULL
                          OR (si.struct_valid = TRUE AND si.dry_run_passed IS NULL))
                   ORDER BY si.installed_at ASC
                   LIMIT 1"""
            )
            installations = cur.fetchall()

        if not installations:
            logger.info("[SkillTester] No untested installations")
            _log_cycle(
                "skill_tester",
                0,
                0,
                int((time.time() - start) * 1000),
                department="Engineering & Technology",
            )
            return

        logger.info(f"[SkillTester] Testing {len(installations)} installed skills")

        for inst in installations:
            inst_id = inst["id"]
            content = inst.get("normalized_content") or ""
            capabilities = inst.get("capabilities") or []
            if isinstance(capabilities, str):
                try:
                    capabilities = json.loads(capabilities)
                except Exception:
                    capabilities = []

            try:
                # Phase 1: Structural validation
                struct_valid, struct_errors = _validate_skill_structure(content)

                if not struct_valid:
                    # Record structural failure
                    with get_db_cursor(commit=True) as (conn2, cur2):
                        cur2.execute(
                            """UPDATE skill_installations
                               SET struct_valid = FALSE,
                                   struct_errors = %s,
                                   tested_at = NOW()
                               WHERE id = %s""",
                            (json.dumps(struct_errors), inst_id),
                        )
                    tested += 1
                    logger.info(
                        f"[SkillTester] {inst['skill_name']} — structural FAIL: "
                        f"{struct_errors[0] if struct_errors else 'unknown'}"
                    )
                    continue

                # Phase 2: Dry-run via Bridge
                test_prompt = _generate_test_prompt(capabilities)

                system_prompt = (
                    f"You are using the following skill:\n\n"
                    f"{content[:3000]}\n\n"
                    f"Apply this skill to the task below. "
                    f"Respond with a concrete, useful result."
                )

                dispatch_result = dispatch(
                    capability="code_analysis",
                    prompt=test_prompt,
                    module_id="skill_tester",
                    system_prompt=system_prompt,
                )

                if dispatch_result and dispatch_result.queued:
                    logger.info("[SkillTester] Deferred to queue — model cold, skipping dry-run for this cycle")
                    continue
                response = ""
                if dispatch_result and dispatch_result.success:
                    response = dispatch_result.response or ""

                # Phase 3: Evaluate assertions
                assertions = _evaluate_dry_run(response, capabilities, content)

                # Required assertions determine pass/fail
                dry_run_passed = assertions.get("length_ok", False) and assertions.get("format_ok", False)

                # Record results
                with get_db_cursor(commit=True) as (conn2, cur2):
                    cur2.execute(
                        """UPDATE skill_installations
                           SET struct_valid = TRUE,
                               struct_errors = '[]'::jsonb,
                               dry_run_passed = %s,
                               dry_run_prompt = %s,
                               dry_run_output = %s,
                               dry_run_assertions = %s,
                               tested_at = NOW()
                           WHERE id = %s""",
                        (
                            dry_run_passed,
                            test_prompt[:1000],
                            response[:5000],
                            json.dumps(assertions),
                            inst_id,
                        ),
                    )

                tested += 1
                status = "PASS" if dry_run_passed else "FAIL"
                logger.info(f"[SkillTester] {inst['skill_name']} — dry-run {status} " f"(assertions: {assertions})")

            except Exception as test_err:
                errors_count += 1
                logger.warning(f"[SkillTester] Failed to test {inst['skill_name']}: " f"{str(test_err)[:80]}")

        logger.info(f"[SkillTester] Done: {tested} tested, {errors_count} errors")
        _log_cycle(
            "skill_tester",
            tested,
            errors_count,
            int((time.time() - start) * 1000),
            details={"tested": tested, "errors": errors_count},
            department="Engineering & Technology",
        )
        if _session:
            complete_work_session(_session, jobs_completed=tested)
        # [#3700] Removed hand-rolled task_execution_log row — this job dispatches its real
        # LLM work through department_dispatcher (see dispatch above), which logs the real
        # per-inference row. The old hardcoded row (F.O.R.G.E./mistral:7b/node=68/0 tokens)
        # was a lossy duplicate.

    except Exception as e:
        logger.warning(f"[SkillTester] Job failed: {e}")
        _log_cycle(
            "skill_tester",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
            department="Engineering & Technology",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


def push_skills_to_fleet():
    """Job #61: Push tested skills to online starship fleet nodes.

    Finds skills not yet pushed to each online starship node,
    POSTs to the node's inbound API. Tracks state in node_skill_pushes.
    Processes up to 5 skills per node per cycle (every 6 hours).
    """
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=139,
            department="Operations & Infrastructure",
            session_type="skill_fleet_push",
            title="Skill Fleet Push (Cluster Distribution)",
            metadata={"interval": "6h"},
        )
    except Exception as _wt_err:
        logger.warning("[B.A.S.E.] Work session create failed: %s", _wt_err)

    start = time.time()
    pushed_total = 0
    errors_total = 0

    try:
        from database import get_db_cursor
        import requests as _req

        # Find online starship nodes (heartbeat within 10 minutes)
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, hostname, mesh_ip, vpn_ip, port, node_name, node_id, node_api_port
                   FROM remote_nodes
                   WHERE deployment_mode = 'starship'
                     AND last_heartbeat > NOW() - INTERVAL '10 minutes'"""
            )
            nodes = cur.fetchall()

        if not nodes:
            logger.debug("[SkillPush] No online starship nodes")
            _log_cycle(
                "skill_fleet_push",
                0,
                0,
                int((time.time() - start) * 1000),
                department="Engineering & Technology",
            )
            return

        # Get tested+passing skills
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
                "skill_fleet_push",
                0,
                0,
                int((time.time() - start) * 1000),
                department="Engineering & Technology",
            )
            return

        all_skill_ids = {s["skill_id"] for s in all_skills}
        skill_map = {s["skill_id"]: s for s in all_skills}

        from tools.department_hq.fleet_helpers import node_inter_cluster_host

        for node in nodes:
            node_db_id = node["id"]
            hostname = node_inter_cluster_host(node)
            inbound_port = node.get("node_api_port") or 3001
            node_name = node["node_name"]

            # Find skills already pushed to this node
            with get_db_cursor() as (conn, cur):
                cur.execute(
                    """SELECT skill_id FROM node_skill_pushes
                       WHERE node_id = %s""",
                    (node_db_id,),
                )
                already_pushed = {r["skill_id"] for r in cur.fetchall()}

            to_push = list(all_skill_ids - already_pushed)[:5]
            if not to_push:
                continue

            logger.info(
                "[SkillPush] Pushing %d skills to %s (%s)",
                len(to_push),
                node_name,
                hostname,
            )

            pushed_this_node = 0
            errors_this_node = 0

            for skill_id in to_push:
                skill = skill_map[skill_id]
                repo_slug = skill["repo_name"].replace("/", "-").lower()
                skill_slug = skill["skill_name"].replace("/", "-").replace(" ", "-").lower()
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
                        _record_push_failure(node_db_id, skill_id, error_msg)
                        errors_this_node += 1

                except Exception as push_err:
                    _record_push_failure(node_db_id, skill_id, str(push_err)[:200])
                    errors_this_node += 1

            pushed_total += pushed_this_node
            errors_total += errors_this_node
            logger.info(
                "[SkillPush] %s: %d pushed, %d errors",
                node_name,
                pushed_this_node,
                errors_this_node,
            )

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
            department="Engineering & Technology",
        )
        if _session:
            complete_work_session(_session, jobs_completed=pushed_total)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — this job performs NO LLM inference (pure DB/git/file work); the row fabricated an agent+model that never ran.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.

    except Exception as e:
        logger.warning("[SkillPush] Job failed: %s", e)
        _log_cycle(
            "skill_fleet_push",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
            department="Engineering & Technology",
        )
        if _session:
            fail_work_session(_session, error_msg=str(e))


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

        text = "\u26a0\ufe0f *Skill Push Failures*\n\n" f"*{len(failures)}* skills stuck (3+ failures):\n"
        for f in failures[:5]:
            text += (
                f"- Skill #{f['skill_id']} \u2192 {f['node_name']} "
                f"({f['fail_count']}x): {(f['last_error'] or '')[:60]}\n"
            )

        from services.telegram_service import send_system

        send_system("Skill Push Failures", text, source_module="consciousness.jobs")
    except Exception as e:
        logger.warning("[SkillPush] Telegram alert failed: %s", e)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def auto_generate_project_docs():
    """Job: Auto-generate project intelligence reports via D.A.R.W.I.N.

    Finds projects below 50% completeness with no recent auto-doc (7-day cooldown),
    generates up to 3 reports per run via Bridge dispatch.
    """
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=140,
            department="Research & Development",
            session_type="project_docs_gen",
            title="D.A.R.W.I.N. Auto-Documentation",
            metadata={"interval": "6h"},
        )
    except Exception as _wt_err:
        logger.warning("[D.A.R.W.I.N.] Work session create failed: %s", _wt_err)

    start = time.time()
    try:
        from services.auto_doc_service import get_doc_candidates, generate_project_docs

        candidates = get_doc_candidates()
        if not candidates:
            logger.debug("[AutoDoc Job] No candidates for doc generation")
            _log_cycle(
                "auto_generate_docs",
                0,
                0,
                int((time.time() - start) * 1000),
                department="Documentation & Knowledge",
            )
            if _session:
                complete_work_session(_session, jobs_completed=0)
            return

        logger.info("[AutoDoc Job] Generating docs for %d projects", len(candidates))
        succeeded = 0
        failed = 0

        for gap_data in candidates:
            result = generate_project_docs(gap_data["project_id"], gap_data=gap_data)
            if result["success"]:
                succeeded += 1
            else:
                failed += 1
                logger.warning(
                    "[AutoDoc Job] Failed for '%s': %s",
                    gap_data.get("name", "unknown"),
                    result.get("error", "unknown"),
                )

        duration = int((time.time() - start) * 1000)
        _log_cycle(
            "auto_generate_docs",
            succeeded,
            failed,
            duration,
            details={
                "candidates": len(candidates),
                "succeeded": succeeded,
                "failed": failed,
            },
            department="Documentation & Knowledge",
        )
        if _session:
            complete_work_session(_session, jobs_completed=succeeded)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — real LLM work routes through department_dispatcher (via the helper / improvement_chat / auto_tagger), which logs the real per-inference row.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        _log_cycle(
            "auto_generate_docs",
            0,
            1,
            duration,
            error_message=str(e),
            department="Documentation & Knowledge",
        )
        logger.warning(f"[AutoDoc Job] Batch failed: {e}")
        if _session:
            fail_work_session(_session, error_msg=str(e))


def auto_link_knowledge_batch():
    """Job: Auto-link knowledge entries to projects via embedding similarity.

    Processes one batch per tick (200 KB entries, 100 bridge jobs).
    Logs results via _log_cycle like all other consciousness jobs.
    """
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=146,
            department="Documentation & Knowledge",
            session_type="knowledge_auto_link",
            title="Knowledge Auto-Link to Projects",
            metadata={"interval": "5m"},
        )
    except Exception as _wt_err:
        logger.warning("[C.O.D.E.X.] Work session create failed: %s", _wt_err)

    start = time.time()
    try:
        from services.knowledge_link_service import (
            auto_link_knowledge,
            auto_link_bridge_jobs,
        )

        kb_stats = auto_link_knowledge(batch_size=200)
        bj_stats = auto_link_bridge_jobs(batch_size=100)

        total_linked = kb_stats.get("linked", 0) + bj_stats.get("linked", 0)
        total_errors = kb_stats.get("errors", 0) + bj_stats.get("errors", 0)
        duration = int((time.time() - start) * 1000)

        _log_cycle(
            "knowledge_auto_link",
            total_linked,
            total_errors,
            duration,
            details={
                "kb_linked": kb_stats.get("linked", 0),
                "kb_skipped": kb_stats.get("skipped", 0),
                "bj_linked": bj_stats.get("linked", 0),
                "bj_skipped": bj_stats.get("skipped", 0),
                "projects_embedded": kb_stats.get("projects_embedded", 0),
            },
            department="Documentation & Knowledge",
        )
        if total_linked > 0:
            logger.info(
                f"[Knowledge Auto-Link] Linked {total_linked} items ({kb_stats.get('linked', 0)} KB + {bj_stats.get('linked', 0)} jobs)"
            )
        if _session:
            complete_work_session(_session, jobs_completed=total_linked)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — this job performs NO LLM inference (pure DB/git/file work); the row fabricated an agent+model that never ran.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        _log_cycle(
            "knowledge_auto_link",
            0,
            1,
            duration,
            error_message=str(e),
            department="Documentation & Knowledge",
        )
        logger.warning(f"[Knowledge Auto-Link] Batch failed: {e}")
        if _session:
            fail_work_session(_session, error_msg=str(e))


def generate_weekly_reports():
    """Job: C.O.D.E.X. weekly knowledge reports.

    Generates a weekly digest for each active/planning project
    that doesn't already have a report from the last 6 days.
    """
    _session = None
    try:
        from services.work_tracking_service import (
            create_work_session,
            complete_work_session,
            fail_work_session,
        )

        _session = create_work_session(
            agent_id=146,
            department="Documentation & Knowledge",
            session_type="weekly_knowledge_report",
            title="C.O.D.E.X. Weekly Knowledge Reports",
            metadata={"interval": "weekly"},
        )
    except Exception as _wt_err:
        logger.warning("[C.O.D.E.X.] Work session create failed: %s", _wt_err)

    start = time.time()
    try:
        from services.weekly_report_service import (
            get_report_candidates,
            generate_weekly_report,
        )

        candidates = get_report_candidates()
        if not candidates:
            logger.debug("[WeeklyReport Job] No candidates for weekly reports")
            _log_cycle(
                "weekly_knowledge_report",
                0,
                0,
                int((time.time() - start) * 1000),
                department="Documentation & Knowledge",
            )
            if _session:
                complete_work_session(_session, jobs_completed=0)
            return

        logger.info("[WeeklyReport Job] Generating reports for %d projects", len(candidates))
        succeeded = 0
        failed = 0
        # #5339 follow-up: the per-project reason was computed here and then thrown
        # away — it reached the logs but never `details`, so the anomaly feed showed
        # "2 of 46 failed" with no way to know WHICH two or why without grepping
        # container logs that may already have rotated. Keep it on the row.
        reasons = []

        for proj in candidates:
            result = generate_weekly_report(proj["id"])
            if result["success"]:
                succeeded += 1
            elif result["error"] == "No activity to report":
                pass  # Not a failure, just skip
            else:
                failed += 1
                reason = result.get("error", "unknown")
                reasons.append(f"{proj.get('name', 'unknown')}: {reason}")
                logger.warning(
                    "[WeeklyReport Job] Failed for '%s': %s",
                    proj.get("name", "unknown"),
                    reason,
                )

        duration = int((time.time() - start) * 1000)
        _log_cycle(
            "weekly_knowledge_report",
            succeeded,
            failed,
            duration,
            details={
                "candidates": len(candidates),
                "succeeded": succeeded,
                "failed": failed,
                "reasons": reasons,
            },
            department="Documentation & Knowledge",
        )
        if _session:
            complete_work_session(_session, jobs_completed=succeeded)
        # [#3700 Stage B] Removed hand-rolled task_execution_log row — this job performs NO LLM inference (pure DB/git/file work); the row fabricated an agent+model that never ran.
        # Old row hardcoded model/success=true/node=68/0 tokens. Job accounting kept via _log_cycle.
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        _log_cycle(
            "weekly_knowledge_report",
            0,
            1,
            duration,
            error_message=str(e),
            department="Documentation & Knowledge",
        )
        logger.warning(f"[WeeklyReport Job] Batch failed: {e}")
        if _session:
            fail_work_session(_session, error_msg=str(e))


# How many missing keys one drip cycle claims. 25 keys = 5 batch_translate batches
# (BATCH_SIZE=5). At one cycle / 15 min a ~1,600-key backlog drains in ~16h of wall
# clock without ever presenting the cluster with a burst it has to shed.
_TRANSLATE_DRIP_KEYS_PER_RUN = 25


def translate_backlog_drip():
    """Job: drain the translation backlog a sip at a time (#5626).

    Replaces the old "click Generate and hope" model, where the whole backlog was
    pushed at the dispatcher in one background thread. Two independent reasons that
    could not drain a contended cluster:

    1. `batch_translate` discarded every QUEUED batch (fixed in translation_service —
       queued is acceptance, not failure).
    2. Nothing ever retried. A key missed once stayed missing until a human clicked
       Generate again.

    The producer is stateless BY CONSTRUCTION: the claim query is `NOT EXISTS`, so a
    translated key simply stops being selected. Nothing marks work in-flight, nothing
    can leak a lock, and a crash mid-drain costs at most one cycle — restart and it
    resumes exactly where it left off.

    Gated twice. `work:translate_backlog_drip:enabled` (DEFAULT OFF — merging this
    must not silently start spending GPU) and `in_flight_over_cap('batch_translate')`,
    which backs off whenever the dispatch pipe for this job_type is already saturated
    rather than adding to a queue that is not draining (#4536).
    """
    try:
        from services.work_control_service import is_enabled

        if not is_enabled("translate_backlog_drip", default=False):
            return {"skipped": "disabled"}

        from services.welfare_governance_service import in_flight_over_cap

        if in_flight_over_cap("batch_translate"):
            logger.info("[TranslateDrip] dispatch pipe saturated — backing off this cycle")
            return {"skipped": "in_flight_over_cap"}

        from database import get_db_cursor
        from ai_bridge.translation_service import SUPPORTED_LANGUAGES, batch_translate

        # Targets are the DECLARED set, not "languages already in the table" — a
        # language with zero rows is exactly the one that needs filling. That includes
        # 'ai' ("AI Semantic"): a deliberate machine-readable target so agents can
        # exchange meaning without prose and a scraper gets an AI-efficient form of the
        # site. It is NOT junk, and must not be filtered out.
        targets = [code for code in SUPPORTED_LANGUAGES if code != "en"]
        if not targets:
            return {"skipped": "no_target_languages"}

        # ROTATE, don't rank by size. Picking "furthest behind" sounds fair and is not:
        # 'ai' starts at ~6,900 missing (every English key) versus he 475, so it would
        # win every cycle for ~3 days and no human language would gain a single key
        # until it finished. Measured on the first live cycle, 2026-08-15.
        #
        # Instead serve the language that has WAITED LONGEST (its newest row is oldest;
        # a language with no rows at all sorts first via NULLS FIRST, so a brand-new
        # target gets started rather than deferred forever). Stateless — derived from
        # the table, no cursor to persist. Still ONE language per cycle, which keeps a
        # single model resident instead of thrashing mistral<->gemma every batch.
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT language, missing, last_progress
                  FROM (
                    SELECT t2_lang.language,
                           (SELECT count(*)
                              FROM translations t1
                             WHERE t1.language = 'en'
                               AND NOT EXISTS (
                                       SELECT 1 FROM translations t2
                                        WHERE t2.key = t1.key AND t2.language = t2_lang.language
                                   )) AS missing,
                           (SELECT max(created_at) FROM translations t3
                             WHERE t3.language = t2_lang.language) AS last_progress
                      FROM unnest(%s::text[]) AS t2_lang(language)
                  ) q
                 -- a column ALIAS cannot appear inside an ORDER BY expression in
                 -- Postgres, hence the wrapping subselect.
                 ORDER BY (missing = 0),          -- finished languages last
                          last_progress ASC NULLS FIRST
                 LIMIT 1
                """,
                (targets,),
            )
            row = cur.fetchone()
            if not row:
                logger.info("[TranslateDrip] backlog empty — nothing to translate")
                return {"translated": 0, "remaining": 0, "note": "backlog empty"}

            language = row["language"] if isinstance(row, dict) else row[0]
            remaining = row["missing"] if isinstance(row, dict) else row[1]

            cur.execute(
                """
                SELECT DISTINCT t1.key, t1.text AS english_text, t1.context
                  FROM translations t1
                 WHERE t1.language = 'en'
                   AND NOT EXISTS (
                           SELECT 1 FROM translations t2
                            WHERE t2.key = t1.key AND t2.language = %s
                       )
                 ORDER BY t1.key
                 LIMIT %s
                """,
                (language, _TRANSLATE_DRIP_KEYS_PER_RUN),
            )
            strings = [(r["key"], r["english_text"], r.get("context") or "") for r in cur.fetchall()]

        if not strings:
            return {"translated": 0, "remaining": remaining, "language": language}

        logger.info(
            "[TranslateDrip] %s: claiming %d of %d missing keys",
            language,
            len(strings),
            remaining,
        )
        results = batch_translate(strings, language, source_label="translate_backlog_drip")
        ok = sum(1 for r in results if r.get("success"))

        # VERIFY BY OUTPUT, NOT BY THE TRANSLATOR'S OWN COUNT (ADR #983).
        # `ok` means the model returned parseable text — it says NOTHING about whether
        # the row reached the table. Measured 2026-08-15: store_translations hit
        # "fe_sendauth: no password supplied", batch_translate still logged
        # "5/5 ok (stored)", and this job would have reported translated=25 with ZERO
        # rows persisted — the #5626 drop-on-failure shape moved to the storage
        # boundary. Re-read the claimed keys and count what actually landed.
        claimed_keys = [s[0] for s in strings]
        with get_db_cursor(commit=False) as (_c2, cur2):
            cur2.execute(
                "SELECT count(*) AS n FROM translations WHERE language = %s AND key = ANY(%s)",
                (language, claimed_keys),
            )
            row2 = cur2.fetchone()
            persisted = int((row2["n"] if isinstance(row2, dict) else row2[0]) or 0)

        if ok and not persisted:
            # Loud, because this is indistinguishable from success in the logs above.
            logger.error(
                "[TranslateDrip] %s: model returned %d translations but NONE persisted — "
                "storage is failing (check store_translations DB auth). Reporting 0.",
                language,
                ok,
            )

        logger.info(
            "[TranslateDrip] %s: %d/%d translated, %d persisted, ~%d still missing",
            language,
            ok,
            len(strings),
            persisted,
            max(remaining - persisted, 0),
        )
        return {
            "language": language,
            "claimed": len(strings),
            "translated": ok,
            "persisted": persisted,
            "storage_failed": bool(ok and not persisted),
            "failed": len(strings) - ok,
            "remaining": max(remaining - persisted, 0),
        }
    except Exception as e:
        logger.error("[TranslateDrip] cycle failed: %s", e)
        return {"error": str(e)}


def register_consciousness_jobs(scheduler, flask_app):
    """Register all consciousness background jobs with the scheduler."""
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    from services.job_governance import governed_job

    def with_ctx(fn):
        """Wrap a job so it runs inside the Flask app context AND under DHQ
        governance (project #332, #2742): every run writes a governance_audit_log
        trail (start/complete/fail) and a failure raises a quiet-hours-gated
        A.R.C.H.I.E. alert. Additive + fail-safe — never changes a job's logic
        (embedding stays on its ADR-013 direct path, dispatch-wired jobs keep
        theirs) and never crashes the shared scheduler. Default notify channel is
        send_system (A.R.C.H.I.E. voice — C.O.D.E.X. has no dedicated channel)."""
        return governed_job(
            fn,
            department="Documentation & Knowledge",
            flask_app=flask_app,
        )

    scheduler.add_job(
        with_ctx(deduplicate_knowledge),
        trigger=IntervalTrigger(hours=24),
        id="knowledge_deduplication",
        name="Agent Loop: Knowledge Deduplication",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # #5626 — translation backlog drip. max_instances=1 + coalesce so a slow cycle
    # (a cold gemma3:12b load can take minutes) can never stack a second producer on
    # top of itself; the work-control flag defaults OFF until an operator enables it.
    scheduler.add_job(
        with_ctx(translate_backlog_drip),
        trigger=IntervalTrigger(minutes=15),
        id="translate_backlog_drip",
        name="Agent Loop: Translation Backlog Drip",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(index_claude_sessions),
        trigger=IntervalTrigger(hours=12),
        id="session_indexer",
        name="Agent Loop: Claude Session Indexer",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(consciousness_analysis_batch),
        trigger=IntervalTrigger(hours=6),
        id="agent_consciousness_analysis",
        name="Agent Loop: Consciousness Analysis Batch",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(consciousness_embedding_batch),
        trigger=IntervalTrigger(minutes=30),
        id="agent_consciousness_embedding",
        name="Agent Loop: Consciousness Embedding Batch",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(sync_learned_skills),
        trigger=IntervalTrigger(hours=6),
        id="agent_skill_sync",
        name="Agent Loop: Skill Sync to Claude",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(github_auto_pull),
        trigger=IntervalTrigger(hours=12),
        id="agent_github_auto_pull",
        name="Agent Loop: GitHub Auto-Pull & Re-Index",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(analyze_discovered_skills),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 01:00:00"),
        id="agent_skill_analyzer",
        name="Agent Loop: Skill Analyzer (Bridge AI)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(conversation_consolidation),
        trigger=IntervalTrigger(hours=1),
        id="agent_conversation_consolidation",
        name="Agent Loop: Conversation Consolidation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(improvement_detection),
        trigger=IntervalTrigger(hours=6),
        id="agent_improvement_detection",
        name="Agent Loop: Improvement Detection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(daily_self_reflection),
        trigger=CronTrigger(hour=0, minute=0, timezone="America/Toronto"),
        id="agent_daily_self_reflection",
        name="Agent Loop: Daily Self-Reflection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(weekly_memory_consolidation),
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="America/Toronto"),
        id="agent_weekly_memory_consolidation",
        name="Agent Loop: Weekly Memory Consolidation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(auto_link_knowledge_batch),
        trigger=IntervalTrigger(minutes=5),
        id="agent_knowledge_auto_link",
        name="Agent Loop: Knowledge Auto-Link to Projects",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(auto_generate_project_docs),
        trigger=IntervalTrigger(hours=6),
        id="agent_auto_generate_docs",
        name="Agent Loop: D.A.R.W.I.N. Auto-Documentation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(generate_weekly_reports),
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0, timezone="America/Toronto"),
        id="agent_weekly_knowledge_report",
        name="Agent Loop: C.O.D.E.X. Weekly Knowledge Reports",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(analyze_repo_relevance),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 02:00:00"),
        id="agent_github_repo_analysis",
        name="Agent Loop: GitHub Repo Relevance Analysis",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(install_skills_to_claude),
        trigger=IntervalTrigger(hours=2),
        id="agent_skill_installer",
        name="Agent Loop: Skill Installer (Claude Code)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(test_installed_skills),
        trigger=IntervalTrigger(hours=4, start_date="2026-01-01 02:00:00"),
        id="agent_skill_tester",
        name="Agent Loop: Skill Tester (Structural + Dry-Run)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(push_skills_to_fleet),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 04:00:00"),
        id="agent_skill_fleet_push",
        name="Agent Loop: Skill Fleet Push (Cluster Distribution)",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    scheduler.add_job(
        with_ctx(auto_adapt_skills),
        trigger=IntervalTrigger(hours=12, start_date="2026-01-01 03:00:00"),
        id="agent_skill_adaptation",
        name="Agent Loop: Skill Adaptation for A.R.C.H.I.E.",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    logger.info("[ConsciousnessJobs] Registered 19 consciousness jobs")

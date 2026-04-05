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
"""

import json
import logging
import os
import time

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
):
    """Log an agent loop execution cycle to autonomy_loop_log."""
    status = "error" if items_failed > 0 and items_processed == 0 else "partial" if items_failed > 0 else "success"
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
                _CONSCIOUSNESS_DEPARTMENT,
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log agent cycle: {e}")


# ---------------------------------------------------------------------------
# Job implementations (faithful copies from agent_loop.py)
# ---------------------------------------------------------------------------


def deduplicate_knowledge():
    """Job #28: Find and merge duplicate/overlapping knowledge entries."""
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
                    UPDATE knowledge_base SET is_archived = true
                    WHERE id = (
                        SELECT id FROM knowledge_base
                        WHERE id IN (%s, %s)
                        ORDER BY importance ASC, created_at ASC
                        LIMIT 1
                    )
                """,
                    (dupe["id1"], dupe["id2"]),
                )

            if dupes:
                logger.info(f"[Knowledge] Archived {len(dupes)} duplicate entries")
    except Exception as e:
        logger.error(f"[Knowledge] Deduplication error: {e}")


def index_claude_sessions():
    """Job #29: Index recent Claude conversation sessions into knowledge_base."""
    try:
        from services.session_indexer_service import index_recent_sessions

        count = index_recent_sessions(max_sessions=5)
        if count > 0:
            logger.info(f"[Sessions] Indexed {count} Claude sessions")
    except Exception as e:
        logger.error(f"[Sessions] Indexing error: {e}")


def consciousness_analysis_batch():
    """Job #49: Trigger consciousness analysis batch every 6 hours.

    Only runs if the analysis server loop is enabled in system_config.
    Uses _trigger_loop_op() from processing_routes which handles
    item selection, job creation, and background threading.
    """
    try:
        from tools.consciousness.processing_routes import (
            get_server_loops,
            _trigger_loop_op,
        )

        loops = get_server_loops()
        if not loops.get("analysis"):
            logger.debug("[Consciousness Batch] Analysis loop disabled — skipping")
            return

        logger.info("[Consciousness Batch] Triggering scheduled analysis batch")
        _trigger_loop_op("analysis")
    except Exception as e:
        logger.warning(f"[Consciousness Batch] Analysis batch failed: {e}")


def consciousness_embedding_batch():
    """Job #50: Trigger consciousness embedding batch every 4 hours.

    Only runs if the embedding server loop is enabled in system_config.
    Uses _trigger_loop_op() from processing_routes which handles
    item selection, job creation, and background threading.
    """
    try:
        from tools.consciousness.processing_routes import (
            get_server_loops,
            _trigger_loop_op,
        )

        loops = get_server_loops()
        if not loops.get("embedding"):
            logger.debug("[Consciousness Batch] Embedding loop disabled — skipping")
            return

        logger.info("[Consciousness Batch] Triggering scheduled embedding batch")
        _trigger_loop_op("embedding")
        _log_cycle("consciousness_embedding", 1, 0, 0)
    except Exception as e:
        _log_cycle("consciousness_embedding", 0, 1, 0, error_message=str(e))
        logger.warning(f"[Consciousness Batch] Embedding batch failed: {e}")


def sync_learned_skills():
    """Job #54: Extract skills from ingested GitHub repos and write to Claude rules.

    Scans knowledge_base for github_file entries that contain skill/agent/plugin
    patterns. Builds a summary of learnable skills and writes to
    .claude/rules/learned-skills.md so Claude auto-loads them every session.

    Runs every 6 hours. Only rewrites if new skills are found since last sync.
    """
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
                _log_cycle("skill_sync", 1, 0, int((time.time() - start) * 1000))
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
            f"Last sync: {time.strftime('%Y-%m-%d %H:%M UTC')}",
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
                bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
                if bot_token:
                    import requests as _req

                    # Build notification
                    tg_lines = ["\U0001f9e0 *New Skills Discovered*\n"]
                    tg_lines.append(f"*{new_skills}* new skill files found across " f"*{len(repos)}* repos\n")
                    tg_lines.append(f"Total skills indexed: *{skill_count}*\n")
                    # Show repos with most skills
                    top_repos = sorted(repos.items(), key=lambda x: len(x[1]), reverse=True)[:5]
                    for rname, rskills in top_repos:
                        tg_lines.append(f"\u2022 `{rname}` \u2014 {len(rskills)} skills")
                    tg_lines.append(
                        "\n[View in Consciousness]" "(http://192.168.1.200:3000/tools/consciousness?tab=github)"
                    )
                    text = "\n".join(tg_lines)

                    from db import get_db

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
                    logger.info(f"[SkillSync] Telegram sent: {new_skills} new skills")
            elif prev_count == 0:
                # First run — just store baseline, don't notify
                sync_learned_skills._last_skill_count = skill_count
                logger.info(f"[SkillSync] Baseline set: {skill_count} skills")
        except Exception as tg_err:
            logger.warning(f"[SkillSync] Telegram notification failed: {tg_err}")

        _log_cycle("skill_sync", 1, 0, int((time.time() - start) * 1000))

    except Exception as e:
        logger.warning(f"[SkillSync] Skill sync failed: {e}")
        _log_cycle("skill_sync", 0, 1, int((time.time() - start) * 1000), error_message=str(e))


def github_auto_pull():
    """Job #55: Auto-pull tracked GitHub repos and re-index changed files.

    Every 12 hours:
    1. Iterate all repos in github_repositories with a local_path
    2. Git pull each one, detect new commits via rev comparison
    3. For repos with changes, trigger re-index of changed files only
    4. Send Telegram notification summarizing what was refreshed
    """
    import subprocess

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
            _log_cycle("github_auto_pull", 1, 0, int((time.time() - start) * 1000))
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

                    from db import get_db

                    tg_conn = get_db()
                    tg_cur = tg_conn.cursor()
                    tg_cur.execute(
                        "SELECT telegram_id FROM telegram_users "
                        "WHERE is_authorized = TRUE AND telegram_id IS NOT NULL"
                    )
                    for row in tg_cur.fetchall():
                        import requests as _req

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
            except Exception as tg_err:
                logger.warning(f"[GitPull] Telegram notification failed: {tg_err}")

        logger.info(f"[GitPull] Pulled {pulled} repos, " f"{len(changed_repos)} had changes, {len(errors)} errors")
        _log_cycle(
            "github_auto_pull",
            1,
            0,
            int((time.time() - start) * 1000),
        )

    except Exception as e:
        logger.warning(f"[GitPull] Auto-pull failed: {e}")
        _log_cycle(
            "github_auto_pull",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


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

    start = time.time()
    analyzed = 0
    errors_count = 0

    try:
        from database import get_db_cursor
        from bridge_dispatcher import dispatch_json
        from services.agent_service import add_skill

        # Fetch up to 10 unanalyzed skills
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT gs.id, gs.repo_name, gs.skill_name, gs.file_path,
                          gs.description, kb.content
                   FROM github_skills gs
                   LEFT JOIN knowledge_base kb ON kb.id = gs.kb_entry_id
                   WHERE gs.status = 'discovered'
                   ORDER BY gs.created_at ASC
                   LIMIT 10"""
            )
            skills = cur.fetchall()

        if not skills:
            logger.info("[SkillAnalyzer] No discovered skills to analyze")
            _log_cycle("skill_analyzer", 1, 0, int((time.time() - start) * 1000))
            return

        logger.info(f"[SkillAnalyzer] Analyzing {len(skills)} skills")

        for skill in skills:
            skill_id = skill["id"]
            content = skill.get("content") or skill.get("description") or ""
            if not content or len(content.strip()) < 20:
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
                                     AND a.shift_state IN ('active', 'deployed')
                                     AND EXISTS (
                                         SELECT 1 FROM agent_skills ask
                                         WHERE ask.agent_id = a.id
                                           AND ask.skill_category = ANY(%s)
                                     )""",
                                (categories,),
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
                    import requests as _req

                    text = (
                        f"\U0001f52c *Skill Analysis Complete*\n\n"
                        f"*{analyzed}* skills analyzed, *{errors_count}* errors\n"
                        f"_{len(skills)} skills processed this cycle_\n\n"
                        f"[View Skills](http://192.168.1.200:3000/tools/consciousness?tab=github)"
                    )

                    from db import get_db

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
            except Exception as tg_err:
                logger.warning(f"[SkillAnalyzer] Telegram notification failed: {tg_err}")

        logger.info(f"[SkillAnalyzer] Done: {analyzed} analyzed, {errors_count} errors")
        _log_cycle("skill_analyzer", 1, 0, int((time.time() - start) * 1000))

    except Exception as e:
        logger.warning(f"[SkillAnalyzer] Job failed: {e}")
        _log_cycle(
            "skill_analyzer",
            0,
            1,
            int((time.time() - start) * 1000),
            error_message=str(e),
        )


def conversation_consolidation():
    """Hourly conversation consolidation — migrated from consciousness_scheduler."""
    start = time.time()
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import hourly_conversation_consolidation

        result = hourly_conversation_consolidation()
        duration_ms = int((time.time() - start) * 1000)
        processed = result.get("messages_processed", 0) if isinstance(result, dict) else 0
        _log_cycle("conversation_consolidation", processed, 0, duration_ms)
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("conversation_consolidation", 0, 1, duration_ms, error_message=str(e))


def improvement_detection():
    """Improvement detection every 6h — migrated from consciousness_scheduler."""
    start = time.time()
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import improvement_detection as _improvement_detection

        result = _improvement_detection()
        duration_ms = int((time.time() - start) * 1000)
        found = result.get("improvements_found", 0) if isinstance(result, dict) else 0
        _log_cycle("improvement_detection", found, 0, duration_ms)
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("improvement_detection", 0, 1, duration_ms, error_message=str(e))


def daily_self_reflection():
    """Daily self-reflection at midnight — migrated from consciousness_scheduler."""
    start = time.time()
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import daily_self_reflection as _daily_self_reflection

        result = _daily_self_reflection()
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("daily_self_reflection", 1, 0, duration_ms)
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("daily_self_reflection", 0, 1, duration_ms, error_message=str(e))


def weekly_memory_consolidation():
    """Weekly memory consolidation (Sun 3AM) — migrated from consciousness_scheduler."""
    start = time.time()
    try:
        import sys

        sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
        from consciousness_scheduler import weekly_memory_consolidation as _weekly_memory_consolidation

        result = _weekly_memory_consolidation()
        duration_ms = int((time.time() - start) * 1000)
        decayed = result.get("memories_decayed", 0) if isinstance(result, dict) else 0
        _log_cycle("weekly_memory_consolidation", decayed, 0, duration_ms)
    except Exception as e:
        duration_ms = int((time.time() - start) * 1000)
        _log_cycle("weekly_memory_consolidation", 0, 1, duration_ms, error_message=str(e))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def auto_link_knowledge_batch():
    """Job: Auto-link knowledge entries to projects via embedding similarity.

    Processes one batch per tick (200 KB entries, 100 bridge jobs).
    Logs results via _log_cycle like all other consciousness jobs.
    """
    start = time.time()
    try:
        from services.knowledge_link_service import auto_link_knowledge, auto_link_bridge_jobs

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
        )
        if total_linked > 0:
            logger.info(
                f"[Knowledge Auto-Link] Linked {total_linked} items ({kb_stats.get('linked', 0)} KB + {bj_stats.get('linked', 0)} jobs)"
            )
    except Exception as e:
        duration = int((time.time() - start) * 1000)
        _log_cycle("knowledge_auto_link", 0, 1, duration, error_message=str(e))
        logger.warning(f"[Knowledge Auto-Link] Batch failed: {e}")


def register_consciousness_jobs(scheduler, flask_app):
    """Register all consciousness background jobs with the scheduler."""
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger

    def with_ctx(fn):
        """Wrap function to run inside Flask app context."""

        def wrapper():
            with flask_app.app_context():
                fn()

        wrapper.__name__ = fn.__name__
        return wrapper

    scheduler.add_job(
        with_ctx(deduplicate_knowledge),
        trigger=IntervalTrigger(hours=24),
        id="knowledge_deduplication",
        name="Agent Loop: Knowledge Deduplication",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(index_claude_sessions),
        trigger=IntervalTrigger(hours=12),
        id="session_indexer",
        name="Agent Loop: Claude Session Indexer",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(consciousness_analysis_batch),
        trigger=IntervalTrigger(hours=6),
        id="agent_consciousness_analysis",
        name="Agent Loop: Consciousness Analysis Batch",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(consciousness_embedding_batch),
        trigger=IntervalTrigger(minutes=30),
        id="agent_consciousness_embedding",
        name="Agent Loop: Consciousness Embedding Batch",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(sync_learned_skills),
        trigger=IntervalTrigger(hours=6),
        id="agent_skill_sync",
        name="Agent Loop: Skill Sync to Claude",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(github_auto_pull),
        trigger=IntervalTrigger(hours=12),
        id="agent_github_auto_pull",
        name="Agent Loop: GitHub Auto-Pull & Re-Index",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(analyze_discovered_skills),
        trigger=IntervalTrigger(hours=6, start_date="2026-01-01 01:00:00"),
        id="agent_skill_analyzer",
        name="Agent Loop: Skill Analyzer (Bridge AI)",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(conversation_consolidation),
        trigger=IntervalTrigger(hours=1),
        id="agent_conversation_consolidation",
        name="Agent Loop: Conversation Consolidation",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(improvement_detection),
        trigger=IntervalTrigger(hours=6),
        id="agent_improvement_detection",
        name="Agent Loop: Improvement Detection",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(daily_self_reflection),
        trigger=CronTrigger(hour=0, minute=0),
        id="agent_daily_self_reflection",
        name="Agent Loop: Daily Self-Reflection",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(weekly_memory_consolidation),
        trigger=CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="agent_weekly_memory_consolidation",
        name="Agent Loop: Weekly Memory Consolidation",
        replace_existing=True,
    )

    scheduler.add_job(
        with_ctx(auto_link_knowledge_batch),
        trigger=IntervalTrigger(minutes=30),
        id="agent_knowledge_auto_link",
        name="Agent Loop: Knowledge Auto-Link to Projects",
        replace_existing=True,
    )

    logger.info("[ConsciousnessJobs] Registered 12 consciousness jobs")

# Skill Import & Testing Pipeline v2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install quality 3+ GitHub skills as usable Claude Code skills, validate them with structural + dry-run testing, and auto-adapt quality 5 skills for A.R.C.H.I.E./Archie CLI.

**Architecture:** New `skill_installations` table tracks per-target install/test/adapt state. Two new jobs (Installer #59, Tester #60) extend the existing consciousness jobs pipeline. Modified Job #58 reads from `skill_installations` instead of `github_skills`. Skills are normalized to a superset markdown format with YAML frontmatter compatible with both Claude Code and Archie CLI.

**Tech Stack:** PostgreSQL, Python/Flask, Bridge dispatcher (`from bridge_dispatcher import dispatch`), APScheduler, YAML frontmatter parsing, filesystem writes to `.claude/skills/github/`.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `database/migrations/skill_installations.sql` | Create `skill_installations` table |
| `platform_v2/tools/consciousness/jobs.py` | Add `install_skills_to_claude()` (Job #59), `test_installed_skills()` (Job #60), modify `auto_adapt_skills()` (Job #58), modify `sync_skills_to_claude()` |
| `platform_v2/tools/consciousness/github_repo_routes.py` | Add `/api/github/skills/pipeline-stats` endpoint |
| `platform_v2/static/js/consciousness.js` | Add pipeline stats display in GitHub tab |

---

### Task 1: Create `skill_installations` Migration

**Files:**
- Create: `database/migrations/skill_installations.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Skill installations tracking — one row per skill per target
-- Tracks install, test, and adaptation state independently per target
CREATE TABLE IF NOT EXISTS skill_installations (
    id SERIAL PRIMARY KEY,
    skill_id INTEGER NOT NULL REFERENCES github_skills(id) ON DELETE CASCADE,
    target VARCHAR(30) NOT NULL,
    install_path TEXT NOT NULL,
    normalized_content TEXT,

    -- Structural validation
    struct_valid BOOLEAN,
    struct_errors JSONB DEFAULT '[]'::jsonb,

    -- Dry-run testing
    dry_run_passed BOOLEAN,
    dry_run_prompt TEXT,
    dry_run_output TEXT,
    dry_run_assertions JSONB DEFAULT '{}'::jsonb,

    -- Adaptation
    adapted BOOLEAN DEFAULT FALSE,
    adapted_content TEXT,
    adapted_at TIMESTAMP,

    -- Timestamps
    installed_at TIMESTAMP DEFAULT NOW(),
    tested_at TIMESTAMP,

    CONSTRAINT uq_skill_target UNIQUE(skill_id, target)
);

CREATE INDEX IF NOT EXISTS idx_skill_installations_target ON skill_installations(target);
CREATE INDEX IF NOT EXISTS idx_skill_installations_tested ON skill_installations(dry_run_passed) WHERE dry_run_passed IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_skill_installations_untested ON skill_installations(id) WHERE struct_valid IS NULL;
```

- [ ] **Step 2: Run the migration**

```bash
docker exec archie_database psql -U archie -d archie -f /mnt/archie_brain/database/migrations/skill_installations.sql
```

Expected: `CREATE TABLE`, `CREATE INDEX` x3 — no errors.

- [ ] **Step 3: Verify table exists**

```bash
docker exec archie_database psql -U archie -d archie -c "\d skill_installations"
```

Expected: Table with all columns, indexes, and constraints shown.

- [ ] **Step 4: Migrate existing adapted skills**

The 4 existing adapted skills in `github_skills` need rows in `skill_installations`:

```sql
INSERT INTO skill_installations (skill_id, target, install_path, adapted, adapted_at, installed_at)
SELECT gs.adapted_from_id, 'claude_code',
       '.claude/skills/github/' || REPLACE(gs.repo_name, '/', '-') || '/' || REPLACE(gs.skill_name, 'adapted/', '') || '.md',
       TRUE, gs.created_at, gs.created_at
FROM github_skills gs
WHERE gs.status = 'adapted' AND gs.adapted_from_id IS NOT NULL
ON CONFLICT (skill_id, target) DO NOTHING;
```

- [ ] **Step 5: Commit**

```bash
git add database/migrations/skill_installations.sql
git commit -m "feat: add skill_installations table for install/test/adapt tracking"
```

---

### Task 2: Skill Normalizer Utility

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py` (add `_normalize_skill_content()` helper)

- [ ] **Step 1: Write the normalizer function**

Add after the existing `_log_cycle()` helper (around line 50), before the job definitions:

```python
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

    # Ensure body has ## Instructions header
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
```

- [ ] **Step 2: Verify the function handles edge cases**

Test mentally: empty content → gets "## Instructions" header. Content with frontmatter → merges fields. Content > 15k → truncated. All paths produce valid YAML + markdown.

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py
git commit -m "feat: add _normalize_skill_content() helper for standard skill format"
```

---

### Task 3: Job #59 — Skill Installer

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py` (add `install_skills_to_claude()`, register in scheduler)

- [ ] **Step 1: Write the installer job function**

Add after `auto_adapt_skills()` (around line 1465):

```python
def install_skills_to_claude():
    """Job #59: Install registered skills to Claude Code as usable skill files.

    Takes quality 3+ registered skills not yet installed, normalizes content
    to standard superset format, writes to .claude/skills/github/<repo>/.
    Processes up to 20 per run (every 2 hours).
    """
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
                   LIMIT 20"""
            )
            skills = cur.fetchall()

        if not skills:
            logger.info("[SkillInstaller] No registered skills to install")
            _log_cycle("skill_installer", 0, 0, int((time.time() - start) * 1000))
            return

        logger.info(f"[SkillInstaller] Installing {len(skills)} skills to Claude Code")

        base_dir = "/mnt/archie_brain/.claude/skills/github"
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

                # Build install path: .claude/skills/github/<owner-repo>/<skill-slug>.md
                repo_slug = skill["repo_name"].replace("/", "-").lower()
                skill_slug = (
                    skill["skill_name"]
                    .replace("/", "-")
                    .replace(" ", "-")
                    .lower()
                    .rstrip(".md")
                )
                if not skill_slug.endswith(".md"):
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
                    f"[SkillInstaller] Installed {skill['skill_name']} "
                    f"from {skill['repo_name']} → {rel_path}"
                )

            except Exception as inst_err:
                errors_count += 1
                logger.warning(
                    f"[SkillInstaller] Failed to install {skill['skill_name']}: "
                    f"{str(inst_err)[:80]}"
                )

        logger.info(
            f"[SkillInstaller] Done: {installed} installed, "
            f"{skipped} skipped, {errors_count} errors"
        )
        _log_cycle(
            "skill_installer",
            installed,
            errors_count,
            int((time.time() - start) * 1000),
            details={"installed": installed, "skipped": skipped, "errors": errors_count},
        )

    except Exception as e:
        logger.warning(f"[SkillInstaller] Job failed: {e}")
        _log_cycle(
            "skill_installer", 0, 1, int((time.time() - start) * 1000),
            error_message=str(e),
        )
```

- [ ] **Step 2: Register Job #59 in the scheduler**

In `register_consciousness_jobs()` (around line 1755), add after the skill adaptation job:

```python
    scheduler.add_job(
        with_ctx(install_skills_to_claude),
        trigger=IntervalTrigger(hours=2),
        id="agent_skill_installer",
        name="Agent Loop: Skill Installer (Claude Code)",
        replace_existing=True,
    )
```

- [ ] **Step 3: Create the github skills directory**

```bash
mkdir -p /mnt/archie_brain/.claude/skills/github
```

- [ ] **Step 4: Deploy and verify job registers**

```bash
docker compose restart archie_platform
sleep 12
docker logs archie_platform 2>&1 | grep 'Skill Installer'
```

Expected: `Added job "Agent Loop: Skill Installer (Claude Code)"`

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py
git commit -m "feat: add Skill Installer job #59 — installs registered skills to Claude Code"
```

---

### Task 4: Job #60 — Skill Tester

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py` (add `test_installed_skills()`, register in scheduler)

- [ ] **Step 1: Write the test prompt generator helper**

Add near the other helpers (after `_normalize_skill_content()`):

```python
# Capability → test prompt mapping for dry-run testing
_SKILL_TEST_PROMPTS = {
    "code-review": "Review this Python function for quality issues:\n\ndef calculate_total(items):\n    total = 0\n    for i in items:\n        total = total + i['price'] * i['qty']\n    return total",
    "testing": "Write a unit test for a function `validate_email(email: str) -> bool` that checks if an email address is valid.",
    "debugging": "Debug this error: TypeError: cannot unpack non-iterable NoneType object. The function returns None when the input list is empty.",
    "documentation": "Document this API endpoint: POST /api/users — accepts JSON body with name, email, role fields. Returns 201 with user object or 400 with validation errors.",
    "refactoring": "Refactor this code to be more readable:\n\ndef f(x):\n    return [i for i in x if i > 0 and i % 2 == 0 and i < 100]",
    "security": "Review this code for security vulnerabilities:\n\nquery = f\"SELECT * FROM users WHERE id = {user_id}\"",
    "deployment": "Write a Dockerfile for a Python 3.11 Flask application that needs PostgreSQL and Redis connections.",
    "ai-prompting": "Write a system prompt for an AI assistant that helps users debug Python code. The assistant should ask clarifying questions before suggesting fixes.",
    "automation": "Write a bash script that backs up a PostgreSQL database, compresses it, and removes backups older than 7 days.",
    "data-processing": "Write a Python function that reads a CSV file, filters rows where the 'status' column is 'active', and returns the count.",
    "monitoring": "Set up a health check endpoint for a Flask application that verifies database connectivity and returns JSON status.",
}

_DEFAULT_TEST_PROMPT = "Using the skill described above, demonstrate your capability with a concrete example. Show your work step by step."


def _generate_test_prompt(capabilities: list) -> str:
    """Generate a test prompt based on skill capabilities."""
    for cap in capabilities:
        cap_lower = cap.lower().strip()
        if cap_lower in _SKILL_TEST_PROMPTS:
            return _SKILL_TEST_PROMPTS[cap_lower]
    return _DEFAULT_TEST_PROMPT
```

- [ ] **Step 2: Write the structural validator helper**

```python
def _validate_skill_structure(content: str) -> tuple:
    """Validate skill markdown structure.

    Returns (is_valid: bool, errors: list[str]).
    """
    import re

    errors = []

    # Check YAML frontmatter
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
    if not fm_match:
        errors.append("Missing YAML frontmatter (---)")
        return (False, errors)

    try:
        import yaml
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

    # Check for binary content
    try:
        body.encode("utf-8")
    except UnicodeEncodeError:
        errors.append("Body contains non-UTF-8 binary content")

    # Check for unclosed code blocks
    fence_count = body.count("```")
    if fence_count % 2 != 0:
        errors.append(f"Unclosed code block ({fence_count} ``` markers)")

    is_valid = len(errors) == 0
    return (is_valid, errors)
```

- [ ] **Step 3: Write the dry-run assertion evaluator**

```python
def _evaluate_dry_run(response: str, capabilities: list, skill_content: str) -> dict:
    """Evaluate dry-run response against assertions.

    Returns dict of assertion results:
    {"length_ok": bool, "format_ok": bool, "relevant": bool, "no_hallucination": bool}
    """
    assertions = {}

    # Required: length check
    assertions["length_ok"] = len(response.strip()) > 200

    # Required: format check — no errors or refusals
    refusal_patterns = [
        "i don't understand",
        "i cannot",
        "i'm not able",
        "error:",
        "traceback (most recent",
        "syntaxerror",
        "nameerror",
        "typeerror",
    ]
    response_lower = response.lower()
    assertions["format_ok"] = not any(p in response_lower for p in refusal_patterns)

    # Advisory: relevance — keyword overlap
    cap_keywords = set()
    for cap in capabilities:
        cap_keywords.update(cap.lower().replace("-", " ").split())
    # Also extract keywords from skill content (first 500 chars)
    content_words = set(skill_content[:500].lower().split())
    check_words = cap_keywords | (content_words & {"code", "test", "review", "api", "deploy", "security", "data", "build"})

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
```

- [ ] **Step 4: Write the tester job function**

Add after `install_skills_to_claude()`:

```python
def test_installed_skills():
    """Job #60: Structural validation + dry-run testing of installed skills.

    Picks up skill_installations rows where struct_valid IS NULL (untested),
    runs structural checks, then dry-runs passing skills through Bridge.
    Processes up to 10 per run (every 4 hours).
    """
    start = time.time()
    tested = 0
    errors_count = 0

    try:
        from database import get_db_cursor
        from bridge_dispatcher import dispatch

        # Fetch untested installations
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT si.id, si.skill_id, si.install_path, si.normalized_content,
                          gs.skill_name, gs.capabilities, gs.description
                   FROM skill_installations si
                   JOIN github_skills gs ON gs.id = si.skill_id
                   WHERE si.target = 'claude_code'
                     AND si.struct_valid IS NULL
                   ORDER BY si.installed_at ASC
                   LIMIT 10"""
            )
            installations = cur.fetchall()

        if not installations:
            logger.info("[SkillTester] No untested installations")
            _log_cycle("skill_tester", 0, 0, int((time.time() - start) * 1000))
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
                logger.info(
                    f"[SkillTester] {inst['skill_name']} — dry-run {status} "
                    f"(assertions: {assertions})"
                )

            except Exception as test_err:
                errors_count += 1
                logger.warning(
                    f"[SkillTester] Failed to test {inst['skill_name']}: "
                    f"{str(test_err)[:80]}"
                )

        logger.info(
            f"[SkillTester] Done: {tested} tested, {errors_count} errors"
        )
        _log_cycle(
            "skill_tester",
            tested,
            errors_count,
            int((time.time() - start) * 1000),
            details={"tested": tested, "errors": errors_count},
        )

    except Exception as e:
        logger.warning(f"[SkillTester] Job failed: {e}")
        _log_cycle(
            "skill_tester", 0, 1, int((time.time() - start) * 1000),
            error_message=str(e),
        )
```

- [ ] **Step 5: Register Job #60 in the scheduler**

In `register_consciousness_jobs()`, add after the Skill Installer registration:

```python
    scheduler.add_job(
        with_ctx(test_installed_skills),
        trigger=IntervalTrigger(hours=4, start_date="2026-01-01 02:00:00"),
        id="agent_skill_tester",
        name="Agent Loop: Skill Tester (Structural + Dry-Run)",
        replace_existing=True,
    )
```

- [ ] **Step 6: Deploy and verify both new jobs register**

```bash
docker compose restart archie_platform
sleep 12
docker logs archie_platform 2>&1 | grep 'Skill Installer\|Skill Tester'
```

Expected: Both jobs show `Added job` messages.

- [ ] **Step 7: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py
git commit -m "feat: add Skill Tester job #60 — structural validation + dry-run assertions"
```

---

### Task 5: Modify Job #58 — Skill Adapter

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py` (rewrite `auto_adapt_skills()` to read from `skill_installations`)

- [ ] **Step 1: Rewrite auto_adapt_skills() to use skill_installations**

Replace the query in `auto_adapt_skills()` that reads from `github_skills` directly. The new version reads from `skill_installations` where `dry_run_passed = TRUE AND adapted = FALSE`:

Change the SQL query (around line 1283) from:

```python
            cur.execute(
                """SELECT gs.id, gs.repo_name, gs.skill_name, gs.description,
                          gs.capabilities, gs.analysis, kb.content
                   FROM github_skills gs
                   LEFT JOIN knowledge_base kb ON kb.id = gs.kb_entry_id
                   WHERE gs.status = 'registered'
                     AND gs.quality_score >= 4
                     AND gs.id NOT IN (SELECT adapted_from_id FROM github_skills WHERE adapted_from_id IS NOT NULL)
                   ORDER BY gs.quality_score DESC, gs.created_at ASC
                   LIMIT 10"""
            )
```

To:

```python
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
```

- [ ] **Step 2: Update the adaptation result storage**

Replace the section that creates a new `github_skills` row (around lines 1372-1410) with updating `skill_installations` instead:

```python
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
```

- [ ] **Step 3: Update the docstring**

Change the docstring to reflect the new flow:

```python
    """Job #58: Auto-adapt tested skills for A.R.C.H.I.E. platform.

    Takes quality 5 skills that passed dry-run testing, generates
    ## Archie CLI section with A.R.C.H.I.E.-native directives.
    Reads from skill_installations, not github_skills directly.
    Processes up to 10 per run (every 12 hours).
    """
```

- [ ] **Step 4: Deploy and verify**

```bash
docker compose restart archie_platform
sleep 12
docker logs archie_platform 2>&1 | grep 'Skill Adaptation'
```

Expected: Job registers without errors.

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py
git commit -m "refactor: Job #58 reads from skill_installations — adapt only tested quality 5 skills"
```

---

### Task 6: Pipeline Stats API Endpoint

**Files:**
- Modify: `platform_v2/tools/consciousness/github_repo_routes.py` (add `/api/github/skills/pipeline-stats`)

- [ ] **Step 1: Add the pipeline stats endpoint**

Add at the end of `register_github_repo_routes()`, before the function's final line:

```python
    @bp.route("/api/github/skills/pipeline-stats")
    @login_or_api_key
    def api_github_skills_pipeline_stats():
        """Return skill pipeline funnel stats for the GitHub tab."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (conn, cur):
                # Skill status counts
                cur.execute(
                    """SELECT status, COUNT(*) as count
                       FROM github_skills
                       GROUP BY status
                       ORDER BY count DESC"""
                )
                status_counts = {r["status"]: r["count"] for r in cur.fetchall()}

                # Installation counts
                cur.execute(
                    """SELECT
                         COUNT(*) as installed,
                         COUNT(*) FILTER (WHERE struct_valid IS NOT NULL) as tested,
                         COUNT(*) FILTER (WHERE dry_run_passed = TRUE) as passed,
                         COUNT(*) FILTER (WHERE dry_run_passed = FALSE) as failed,
                         COUNT(*) FILTER (WHERE adapted = TRUE) as adapted
                       FROM skill_installations
                       WHERE target = 'claude_code'"""
                )
                inst = cur.fetchone()

            return jsonify({
                "success": True,
                "pipeline": {
                    "discovered": status_counts.get("discovered", 0),
                    "analyzing": status_counts.get("analyzing", 0),
                    "analyzed": status_counts.get("analyzed", 0),
                    "registered": status_counts.get("registered", 0),
                    "installed": inst["installed"],
                    "tested": inst["tested"],
                    "passed": inst["passed"],
                    "failed": inst["failed"],
                    "adapted": inst["adapted"],
                },
            })
        except Exception as e:
            logger.error(f"[GitHub] Pipeline stats error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 2: Verify the import for jsonify exists**

Check top of `github_repo_routes.py` — `jsonify` should already be imported from Flask. If not, add it.

- [ ] **Step 3: Deploy and test the endpoint**

```bash
docker compose restart archie_platform
sleep 12
```

Test via browser or curl: `http://192.168.1.200:3000/tools/consciousness/api/github/skills/pipeline-stats`

Expected: JSON with pipeline counts.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/tools/consciousness/github_repo_routes.py
git commit -m "feat: add /api/github/skills/pipeline-stats endpoint for funnel display"
```

---

### Task 7: GitHub Tab Pipeline Stats UI

**Files:**
- Modify: `platform_v2/static/js/consciousness.js` (add pipeline stats display)

- [ ] **Step 1: Add pipeline stats fetcher to the GitHub tab**

Find the GitHub tab initialization in `consciousness.js` and add a stats loader. Add this function:

```javascript
async function loadSkillPipelineStats() {
    try {
        const data = await api('/api/github/skills/pipeline-stats');
        if (!data || !data.success) return;

        const p = data.pipeline;
        const statsHtml = `
            <div class="cs-pipeline-stats" style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px;padding:12px;background:rgba(139,92,246,0.08);border:1px solid rgba(139,92,246,0.2);border-radius:8px;">
                <span style="color:#a78bfa">Discovered: <b>${p.discovered}</b></span>
                <span style="color:#8b5cf6">Registered: <b>${p.registered}</b></span>
                <span style="color:#22d3ee">Installed: <b>${p.installed}</b></span>
                <span style="color:${p.passed > 0 ? '#10b981' : '#6b7280'}">Tested: <b>${p.passed}</b> pass</span>
                ${p.failed > 0 ? `<span style="color:#ef4444">Failed: <b>${p.failed}</b></span>` : ''}
                <span style="color:#fbbf24">Adapted: <b>${p.adapted}</b></span>
            </div>
        `;

        // Insert before the repo list
        const repoList = document.querySelector('.cs-github-repo-list, .cs-github-repos, [data-github-repos]');
        if (repoList) {
            const existing = document.querySelector('.cs-pipeline-stats');
            if (existing) existing.remove();
            repoList.insertAdjacentHTML('beforebegin', statsHtml);
        }
    } catch (e) {
        console.warn('[PipelineStats] Failed to load:', e);
    }
}
```

- [ ] **Step 2: Call the stats loader when GitHub tab opens**

Find the `switchConsciousnessTab` function or GitHub tab activation handler, and add a call:

```javascript
// Inside the github tab activation branch
loadSkillPipelineStats();
```

- [ ] **Step 3: Deploy and verify visually**

```bash
docker compose restart archie_platform
```

Navigate to `http://192.168.1.200:3000/tools/consciousness?tab=github` — verify stats bar appears above repo list.

- [ ] **Step 4: Commit**

```bash
git add platform_v2/static/js/consciousness.js
git commit -m "feat: add pipeline stats bar to Consciousness GitHub tab"
```

---

### Task 8: Modify Skill Sync Job

**Files:**
- Modify: `platform_v2/tools/consciousness/jobs.py` (extend `sync_skills_to_claude()` with installation stats)

- [ ] **Step 1: Find and extend sync_skills_to_claude**

Locate the existing function (search for `sync_skills_to_claude` or the Skill Sync job). Add installation stats to the `learned-skills.md` output.

Add this block after the existing skill table output in the sync function:

```python
        # Add installation pipeline stats
        try:
            cur.execute(
                """SELECT
                     COUNT(*) as installed,
                     COUNT(*) FILTER (WHERE dry_run_passed = TRUE) as passed,
                     COUNT(*) FILTER (WHERE dry_run_passed = FALSE) as failed,
                     COUNT(*) FILTER (WHERE adapted = TRUE) as adapted
                   FROM skill_installations
                   WHERE target = 'claude_code'"""
            )
            inst_stats = cur.fetchone()
            lines.append(f"\n## Installation Pipeline\n")
            lines.append(f"| Metric | Count |")
            lines.append(f"|--------|-------|")
            lines.append(f"| Installed to Claude Code | {inst_stats['installed']} |")
            lines.append(f"| Tested (pass) | {inst_stats['passed']} |")
            lines.append(f"| Tested (fail) | {inst_stats['failed']} |")
            lines.append(f"| Adapted for A.R.C.H.I.E. | {inst_stats['adapted']} |")
        except Exception as stats_err:
            logger.warning(f"[SkillSync] Installation stats failed: {stats_err}")
```

- [ ] **Step 2: Deploy and verify**

```bash
docker compose restart archie_platform
```

Wait for next Skill Sync run (or check `learned-skills.md` after manual trigger).

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/consciousness/jobs.py
git commit -m "feat: extend Skill Sync to report installation pipeline stats"
```

---

### Task 9: End-to-End Verification

**Files:** None — testing only.

- [ ] **Step 1: Check the full pipeline state**

```bash
docker exec archie_database psql -U archie -d archie -c "
SELECT status, COUNT(*) FROM github_skills GROUP BY status ORDER BY count DESC;
"

docker exec archie_database psql -U archie -d archie -c "
SELECT COUNT(*) as installed,
       COUNT(*) FILTER (WHERE struct_valid IS NOT NULL) as tested,
       COUNT(*) FILTER (WHERE dry_run_passed = TRUE) as passed,
       COUNT(*) FILTER (WHERE adapted = TRUE) as adapted
FROM skill_installations WHERE target = 'claude_code';
"
```

- [ ] **Step 2: Verify installed skill files exist**

```bash
ls -la /mnt/archie_brain/.claude/skills/github/ | head -20
find /mnt/archie_brain/.claude/skills/github/ -name '*.md' | head -10
```

Expected: Subdirectories per repo with `.md` skill files.

- [ ] **Step 3: Read a sample installed skill**

```bash
head -30 /mnt/archie_brain/.claude/skills/github/$(ls /mnt/archie_brain/.claude/skills/github/ | head -1)/$(ls /mnt/archie_brain/.claude/skills/github/$(ls /mnt/archie_brain/.claude/skills/github/ | head -1) | head -1)
```

Expected: Standard superset format with YAML frontmatter (name, description, source_repo, quality_score, capabilities, departments, installed_from), body content, and `## Archie CLI` placeholder.

- [ ] **Step 4: Check pipeline stats endpoint**

Navigate to `http://192.168.1.200:3000/tools/consciousness?tab=github`

Expected: Pipeline stats bar showing discovered → registered → installed → tested → adapted counts.

- [ ] **Step 5: Verify no regressions**

```bash
docker logs archie_platform --since 5m 2>&1 | grep -i 'error\|fail' | grep -v 'apscheduler\|huggingface\|Kokoro\|fail2ban' | head -10
```

Expected: No new errors from the skill pipeline jobs.

- [ ] **Step 6: Final commit with all verified**

```bash
git add -A
git status
# Only commit if there are unstaged changes from verification
git commit -m "test: end-to-end verification of skill import pipeline v2"
```

---

## Self-Review Checklist

- **Spec coverage:** All Phase 1 items covered — `skill_installations` table (Task 1), Job #59 Installer (Task 3), Job #60 Tester (Task 4), modified Job #58 Adapter (Task 5), pipeline stats API (Task 6), UI stats (Task 7), Skill Sync update (Task 8), verification (Task 9).
- **Placeholder scan:** No TBDs, TODOs, or "fill in later". All code is complete.
- **Type consistency:** `skill_id`, `installation_id`, `inst_id` used consistently. `dispatch()` returns `DispatchResult` — handled correctly per the bugfix rules. `get_db_cursor(commit=True)` pattern used throughout.
- **Missing from spec:** Phase 2 (Archie CLI) and Phase 3 (Cluster) are explicitly out of scope for this plan — spec says "when ready."
- **Job count:** After implementation: 18 consciousness jobs (was 16) + the 2 new ones.

# Skill Import & Testing Pipeline v2

**Date:** 2026-04-06
**Status:** Approved
**Author:** Claude + Kytran
**Project:** GitHub Skills Pipeline Enhancement

---

## Problem Statement

The current GitHub skill pipeline discovers and analyzes skills but never installs or tests them. 402 skills sit in the database as text — scored and categorized but never used. Many are production-ready Claude Code skills that could work immediately if installed.

Additionally, Archie CLI (`archie-code/`) has its own skill system (`skills/loader.py`, `skills/executor.py`, `skills/community/`) that needs to be fed from the same pipeline. Cluster nodes will eventually sync skills from the hub.

## Design Decisions (from brainstorm)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Install before adapt? | Yes — install as-is, test, then adapt | Get immediate value; don't gate usage on AI rewriting |
| Format normalization | Convert all to standard markdown at install time | Consistency across Claude Code, Archie CLI, cluster |
| Adaptation trigger | Auto for quality 5, on-demand for 3-4 | Best skills get A.R.C.H.I.E.-native versions automatically |
| Testing approach | Structural validation (fast gate) + dry-run with assertions | Both automated; Archie CLI runs dry-run, results logged |
| Install targets | Staged: Claude Code first → Archie CLI → Cluster | Each target activates when ready |
| Tracking | Separate `skill_installations` table | One row per skill per target; independent lifecycle |
| UI ownership | Consciousness = pipeline state; Archie CLI = skill management | Separation of concerns |
| Dry-run observability | All results logged with assertions to `skill_installations` | No ghost code — every test has observable, queryable results |

## Pipeline Flow

```
GitHub Repos → Ingest → Knowledge Base
                              ↓
                 Discover skill files (existing Job #55)
                              ↓
                 Analyze quality 1-5 (existing Job #56, via F.O.R.G.E.)
                              ↓
                 Quality 3+ → status = "registered" (existing)
                              ↓
          ┌── Normalize to standard format ──┐  (NEW - Job #59)
          ↓
    Install to Claude Code
    (.claude/skills/github/<repo>/<skill>.md)
          ↓
    Structural validation (NEW - Job #60)
    - Valid YAML frontmatter?
    - Has name + description?
    - Body > 100 chars?
          ↓
    Dry-run via Archie CLI (NEW - Job #60)
    - Execute skill with test prompt
    - Assert: length, format, relevance, no hallucination
    - Log all results to skill_installations
          ↓
    USABLE — available in Claude Code sessions
          ↓ (Phase 2 — when Archie CLI matures)
    Install to Archie CLI skills/community/
          ↓ (Phase 3 — when cluster exists)
    Sync to cluster nodes via OTA
          ↓ (auto for quality 5, on-demand for 3-4)
    Adapt for A.R.C.H.I.E. (existing Job #58, modified)
    - Generate ## Archie CLI section
    - Rewrite with Bridge/dept/LCARS references
```

## Standard Skill Format (Superset)

One file format readable by both Claude Code and Archie CLI:

```markdown
---
name: skill-name
description: One-line trigger description
source_repo: owner/repo
quality_score: 4
capabilities: [code-review, testing]
departments: [Engineering & Technology, Security & Compliance]
installed_from: 1234
---

## Instructions

(Original skill content, normalized to markdown.
 This is what Claude Code and Archie CLI both read.)

## Archie CLI

(A.R.C.H.I.E.-specific directives added during adaptation step.
 Departments to route through, Bridge dispatch patterns,
 LCARS UI references. Empty section until adapted.
 Claude Code sees this as documentation.
 Archie CLI parses it as directives.)
```

- Claude Code reads everything, ignores unknown frontmatter fields
- Archie CLI uses extended frontmatter (`departments`, `capabilities`) for routing
- The `## Archie CLI` section is additive — original skill works without it

## Database Schema

### Existing: `github_skills` (unchanged)

Linear pipeline status tracking stays as-is:
```
discovered → analyzing → analyzed → registered → archived
```

No new columns needed. The `registered` status means "quality-gated, ready for install."

### New: `skill_installations`

```sql
CREATE TABLE skill_installations (
    id SERIAL PRIMARY KEY,
    skill_id INTEGER NOT NULL REFERENCES github_skills(id) ON DELETE CASCADE,
    target VARCHAR(30) NOT NULL,  -- 'claude_code', 'archie_cli', 'cluster'
    install_path TEXT NOT NULL,    -- filesystem path where skill was written
    normalized_content TEXT,       -- the standardized markdown content

    -- Structural validation
    struct_valid BOOLEAN,
    struct_errors JSONB DEFAULT '[]'::jsonb,

    -- Dry-run testing
    dry_run_passed BOOLEAN,
    dry_run_prompt TEXT,           -- test prompt used
    dry_run_output TEXT,           -- response captured
    dry_run_assertions JSONB DEFAULT '{}'::jsonb,
    -- assertions format: {"length_ok": true, "format_ok": true, "relevant": true, "no_hallucination": true}

    -- Adaptation
    adapted BOOLEAN DEFAULT FALSE,
    adapted_content TEXT,          -- A.R.C.H.I.E.-native version with ## Archie CLI section
    adapted_at TIMESTAMP,

    -- Timestamps
    installed_at TIMESTAMP DEFAULT NOW(),
    tested_at TIMESTAMP,

    CONSTRAINT uq_skill_target UNIQUE(skill_id, target)
);

CREATE INDEX idx_skill_installations_target ON skill_installations(target);
CREATE INDEX idx_skill_installations_tested ON skill_installations(dry_run_passed) WHERE dry_run_passed IS NOT NULL;
```

One row per skill per target. Each target has independent:
- Installation status (installed_at)
- Structural validation (struct_valid, struct_errors)
- Dry-run results (dry_run_passed, assertions)
- Adaptation state (adapted, adapted_content, adapted_at)

## Jobs

### Job #59: Skill Installer (NEW)

| Field | Value |
|-------|-------|
| Schedule | Every 2 hours |
| Batch size | 20 skills |
| Input | `github_skills` where status = 'registered' AND quality_score >= 3 AND no `skill_installations` row for target 'claude_code' |
| Process | 1. Read skill content from `knowledge_base` via `kb_entry_id` |
|         | 2. Normalize to standard format (YAML frontmatter + markdown body) |
|         | 3. Write to `.claude/skills/github/<repo-slug>/<skill-name>.md` |
|         | 4. Insert `skill_installations` row with target='claude_code' |
| Output | Skills available in Claude Code sessions |
| Bridge? | Yes — for README/non-standard content extraction. Passthrough (no LLM) for already-valid skill markdown. |

**Normalization rules:**
- **Already-valid skills** (markdown with frontmatter or clear skill structure): passthrough — add/merge extended frontmatter fields, append `## Archie CLI` placeholder. No LLM needed.
- **READMEs / mixed-content files**: Bridge dispatch to F.O.R.G.E. to extract instructional sections and reformat as skill markdown. LLM required.
- **Non-markdown formats**: Bridge dispatch to convert to markdown. LLM required.
- All outputs: add empty `## Archie CLI` section placeholder, truncate to 15,000 chars max (Claude Code skill size limit).

Most quality 4+ skills are already valid markdown — the LLM path is the exception, not the rule.

### Job #60: Skill Tester (NEW)

| Field | Value |
|-------|-------|
| Schedule | Every 4 hours |
| Batch size | 10 skills |
| Input | `skill_installations` where target = 'claude_code' AND struct_valid IS NULL |
| Process | 1. Structural validation (frontmatter, format, length) |
|         | 2. If structural passes → dry-run via Archie CLI executor |
|         | 3. Evaluate response against assertions |
|         | 4. Update `skill_installations` with results |
| Output | Test pass/fail with detailed assertion results |
| Bridge? | Yes — dry-run sends skill + test prompt through Bridge dispatch |

**Structural validation checks:**
- Has valid YAML frontmatter with `name` and `description`
- Body content > 100 characters
- No binary content or encoding errors
- Valid markdown (no unclosed code blocks)

**Dry-run assertions:**

| Assertion | Pass Condition | Weight |
|-----------|---------------|--------|
| `length_ok` | Response > 200 characters | Required |
| `format_ok` | No error tracebacks, no "I don't understand" / refusal patterns | Required |
| `relevant` | Response references >= 30% of skill's capability keywords | Advisory |
| `no_hallucination` | No references to tools/APIs the skill doesn't mention | Advisory |

Required assertions must pass for `dry_run_passed = true`. Advisory assertions are logged but don't block.

**Test prompt generation:**
The tester generates a contextual test prompt based on the skill's capabilities:
- Code review skill → "Review this Python function: `def add(a, b): return a + b`"
- Testing skill → "Write a test for a user login function"
- Documentation skill → "Document this API endpoint: GET /users"

### Job #58: Skill Adapter (MODIFIED)

| Field | Value |
|-------|-------|
| Schedule | Every 12 hours |
| Batch size | 10 skills |
| Input | `skill_installations` where target = 'claude_code' AND dry_run_passed = TRUE AND adapted = FALSE AND quality_score >= 5 (join to github_skills) |
| Process | 1. Read installed skill content |
|         | 2. Send to Bridge for A.R.C.H.I.E. adaptation |
|         | 3. Generate `## Archie CLI` section with dept/Bridge/LCARS references |
|         | 4. Update `skill_installations.adapted_content` and `adapted = TRUE` |
|         | 5. Overwrite installed file with adapted version |
| Output | A.R.C.H.I.E.-native skill with `## Archie CLI` section |
| Bridge? | Yes — F.O.R.G.E. via code_analysis capability |

Quality 3-4 skills: adapt on-demand only (via Consciousness dashboard button or Archie CLI command).

### Job #55: Skill Sync (MODIFIED)

Extend existing sync to include installation stats in `learned-skills.md`:
- Total installed / tested / adapted counts
- List of newly installed skills since last sync

## Install Paths

| Target | Base Path | Example |
|--------|-----------|---------|
| Claude Code | `.claude/skills/github/` | `.claude/skills/github/obra-superpowers/writing-skills.md` |
| Archie CLI | `archie-code/archie_engine/skills/community/github/` | `archie-code/archie_engine/skills/community/github/obra-superpowers/writing-skills.md` |
| Cluster | Synced from hub via OTA | Same structure as Archie CLI |

Subdirectories per repo prevent name collisions. Slug format: `owner-repo`.

## UI Changes

### Consciousness GitHub Tab (pipeline state only)

Add summary stats row above the repo list:
```
Skills: 402 discovered | 106 registered | 42 installed | 38 tested (35 pass) | 8 adapted
```

No new action buttons — Consciousness shows the funnel, not the controls.

### Archie CLI Skills Dashboard (Phase 2)

Full skill library management:
- Browse installed skills with filter/search
- View test results and assertion details
- Install/uninstall individual skills
- Trigger adaptation for specific skills
- Skill editor for manual adaptation
- Sync status for cluster nodes

## Phased Rollout

### Phase 1: Claude Code Install + Test (This Implementation)
- New `skill_installations` table
- Job #59: Skill Installer (writes to `.claude/skills/github/`)
- Job #60: Skill Tester (structural + dry-run)
- Modified Job #58: Reads from `skill_installations` instead of `github_skills`
- Consciousness tab stats update

### Phase 2: Archie CLI Integration (When Archie CLI matures)
- Job #59 extended: also installs to `archie-code/skills/community/github/`
- Archie CLI skill loader reads from community/github/ directory
- Archie CLI Skills Dashboard UI
- Dry-run testing uses Archie CLI executor directly

### Phase 3: Cluster Distribution (When fleet nodes exist)
- OTA sync of tested skills to cluster nodes
- Node-specific skill filtering (by capabilities/departments)
- Cluster health reporting of skill availability

## Migration

Existing pipeline data preserved:
- 106 registered skills → eligible for Job #59 install on first run
- 4 adapted skills → migrate to `skill_installations` with `adapted = TRUE`
- No data loss — new table is additive

## Out of Scope

- Skill marketplace / sharing between A.R.C.H.I.E. instances
- Skill versioning (track updates to source repos)
- Skill dependency resolution (skill A requires skill B)
- Revenue/licensing tracking for resold skills

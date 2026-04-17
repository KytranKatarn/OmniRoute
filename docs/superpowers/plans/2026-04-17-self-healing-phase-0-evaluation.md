# Self-Healing Loop — Phase 0 Implementation Plan (Evaluation Sprint)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a citation-backed trace of the current self-healing pipeline state so Phases 1-4 plan against real code, not audit inference.

**Architecture:** Investigation sprint. No production code changes. Deliverable is a review document at `docs/superpowers/reviews/<date>-self-healing-pipeline-trace.md` with file:line citations for every pipeline stage and a gap list for Phases 1-4.

**Tech Stack:** Grep, Read, focused DB queries via `docker exec archie_database psql`, python `ast.parse` for syntax checks. No tests to write — output is documentation.

**Parent spec:** `docs/superpowers/specs/2026-04-17-self-healing-loop-design.md` (updated after Task 2 findings — see spec §2a).

**Post-Task 2 correction:** The spec originally referenced `code_health_audits` as the Code Health output table. Phase 0 Task 2 revealed the real table is `code_audit_log`, severity is reconstructed from `notes` (no severity column), and two handlers disagree on the taxonomy. Tasks 3-9 below use the corrected names. Spec §2a documents the full list of deviations.

**Rhythm adaptation:** This is research, not implementation. TDD doesn't apply. Each task's pattern is: state the question, run the exact commands, write the findings section, commit. No placeholders — every task produces concrete file:line citations or a "confirmed absent" backed by explicit search.

**Safety rails:**
- No code changes to any `platform_v2/` or `ai_bridge/` file.
- No DB writes. Read-only queries only.
- Planting a test lint violation (Task 3) uses a file in `sandbox/` or equivalent — never in live module code.
- Document-only commits throughout. Push freeze active until 2026-05-01; all commits local.

---

## File Structure

Only one file is created; no existing files modified.

- **Create:** `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md` (date set at start of Task 1)
- **Nothing else.** This plan does not touch production code.

---

## Task 1: Create review doc skeleton

**Files:**
- Create: `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md`

- [ ] **Step 1.1: Set the date**

Run: `date +%Y-%m-%d`
Capture output (e.g., `2026-04-18`). Use this as `<today>` everywhere in the plan.

- [ ] **Step 1.2: Create the skeleton**

Create `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md` with:

```markdown
# Self-Healing Pipeline Trace — <today>

**Spec:** `docs/superpowers/specs/2026-04-17-self-healing-loop-design.md`
**Method:** Static trace (grep/read) + plant-and-follow. Read-only; no code or DB mutations.

---

## 1. Code Health scanner
_(populated by Task 2)_

## 2. Code Health → Repair Bay bridge
_(populated by Task 4)_

## 3. Repair Bay proposal pipeline
_(populated by Task 5)_

## 4. Repair Bay → DHQ dispatch
_(populated by Task 6)_

## 5. Telegram unification status
_(populated by Task 7)_

## 6. ARCHIE decision infrastructure
_(populated by Task 8)_

## 7. Plant-and-follow results
_(populated by Task 3 outcome reviewed at Task 9)_

## 8. Gap list for Phases 1-4
_(populated by Task 9)_
```

- [ ] **Step 1.3: Commit the skeleton**

```bash
git checkout docs/self-healing-loop-spec  # or create a new branch for the trace work
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git commit -m "docs(trace): skeleton for self-healing pipeline trace"
```

---

## Task 2: Trace the Code Health scanner

**Files:**
- Modify: `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md` — section 1

**Questions to answer:**
- Where is `code_audit_log` written to?
- What triggers a scan (schedule, hook, on-demand)?
- What severity levels exist, and how are they assigned?

- [ ] **Step 2.1: Find writers to `code_audit_log`**

Run:
```bash
grep -rnE "INSERT INTO code_audit_log|UPDATE code_audit_log|code_audit_log" \
  /mnt/archie_brain/platform_v2 /mnt/archie_brain/ai_bridge
```

Expected: hits in `tools/consciousness/code_health_routes.py` + any supporting service. Note the file:line of each write.

- [ ] **Step 2.2: Find scan triggers**

Run:
```bash
grep -rnE "code_health|CodeHealth|run_.*audit|module_audit" \
  /mnt/archie_brain/ai_bridge/agent_loop.py \
  /mnt/archie_brain/platform_v2/tools/consciousness/
```

Expected: agent_loop job references + any scheduled/hook-driven invocations. Note the cron/interval pattern if present.

- [ ] **Step 2.3: Confirm severity schema**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c "\d code_audit_log"
```

Expected: column listing. Note `severity` column type + CHECK constraint if any.

- [ ] **Step 2.4: Write Section 1 of the review doc**

Fill in section 1 with:
- Writer function name + file:line
- Trigger(s) (scheduled job? on-demand API? both?)
- Severity values and how they're assigned (code pointer)
- If anything is stubbed, say so with "confirmed by grep on <date>".

- [ ] **Step 2.5: Commit**

```bash
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git commit -m "docs(trace): section 1 — Code Health scanner"
```

---

## Task 3: Plant a traceable finding

**Files:**
- Create (ephemeral, will be cleaned up in Step 3.5): `sandbox/ch_trace_seed.py` — a trivial file with a known lint violation we can follow

**Purpose:** put a unique marker into the pipeline so we can see where it surfaces.

- [ ] **Step 3.1: Confirm a safe sandbox directory exists**

Run:
```bash
ls /mnt/archie_brain/sandbox/ 2>/dev/null || mkdir -p /mnt/archie_brain/sandbox
```

If no sandbox dir: create one with an intentional `.gitignore` so seed files never commit.

- [ ] **Step 3.2: Write the seed file**

Create `/mnt/archie_brain/sandbox/ch_trace_seed.py`:

```python
# CH_TRACE_MARKER_20260418  — planted for Phase 0 trace
import os
def noop():
    x = 1  # unused var — triggers F841
    try:
        pass
    except:  # bare except — triggers E722
        pass
    return undefined_name  # F821 undefined — deterministic marker
```

- [ ] **Step 3.3: Run flake8 to confirm the seed triggers findings**

Run:
```bash
flake8 --select=F821,F841,E722 /mnt/archie_brain/sandbox/ch_trace_seed.py
```

Expected: 3 lines of output citing the 3 violations. Copy into a scratch note.

- [ ] **Step 3.4: Trigger Code Health scan (method determined in Task 2)**

Using the invocation pattern discovered in Task 2 (on-demand API endpoint or manual job run), scan the file. Capture the response/log.

- [ ] **Step 3.5: Verify findings reach the DB**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT id, file_path, notes, created_at FROM code_audit_log WHERE file_path LIKE '%ch_trace_seed%' ORDER BY created_at DESC LIMIT 5;"
```

Expected: 0-3 rows. Record how many. Note any findings appear in `code_issues` too if Task 2 showed both tables.

- [ ] **Step 3.6: Leave the seed in place**

We'll remove it in Task 9 cleanup. Keep `ch_trace_seed.py` for now — subsequent tasks follow its findings through the pipeline.

- [ ] **Step 3.7: Commit the seed note to the review doc (not the seed file)**

Add a `### 7.1 Planted finding` subsection to section 7 with:
- Marker string: `CH_TRACE_MARKER_20260418`
- Seed file path + SHA256
- Scan trigger used
- Number of rows that reached `code_audit_log` (0 to 3)

```bash
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git commit -m "docs(trace): planted finding recorded in section 7"
```

---

## Task 4: Trace Code Health → Repair Bay bridge

**Files:**
- Modify: `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md` — section 2

**Questions:**
- Does any code read `code_audit_log` and create `improvement_proposals`?
- If a bridge exists, what's its schedule? What severity threshold does it use?
- Does `_has_open_proposal()` exist? Where?

- [ ] **Step 4.1: Search for bridge readers**

Run:
```bash
grep -rnE "code_audit_log|code_issues" \
  /mnt/archie_brain/platform_v2/tools/repair_bay/ \
  /mnt/archie_brain/ai_bridge/agent_loop.py
```

Expected: find any services reading from Code Health tables. Note file:line of each.

- [ ] **Step 4.2: Search for `_has_open_proposal` + variants**

Run:
```bash
grep -rnE "_has_open_proposal|open_proposal|dedup|duplicate.*proposal" \
  /mnt/archie_brain/platform_v2/tools/repair_bay/
```

Expected: locate implementation or confirm absence. If present, note behavior. If absent, log as confirmed missing.

- [ ] **Step 4.3: Search for 6h proactive scan wiring**

Run:
```bash
grep -rnE "proactive|6[h_]|21600|proactive_scan|run_proactive" \
  /mnt/archie_brain/ai_bridge/agent_loop.py \
  /mnt/archie_brain/platform_v2/tools/repair_bay/
```

Expected: locate the scheduler hook if it exists.

- [ ] **Step 4.4: Check if seed file (Task 3) has any Repair Bay proposal after Task 3**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT id, title, file_path, status, created_at FROM improvement_proposals WHERE file_path LIKE '%ch_trace_seed%' ORDER BY created_at DESC LIMIT 5;"
```

Expected: 0 rows (if bridge is missing) or 1+ rows (if bridge is wired). This answers the single biggest open question.

- [ ] **Step 4.5: Write Section 2 of the review doc**

Fill in section 2 with:
- Bridge status: Missing / Partial / Working — backed by the empirical row count
- `_has_open_proposal()` status: Implemented / Stubbed / Missing (with file:line)
- 6h proactive scan: Wired / Unwired (with file:line if wired)
- If bridge exists: severity threshold + schedule

- [ ] **Step 4.6: Commit**

```bash
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git commit -m "docs(trace): section 2 — Code Health → Repair Bay bridge"
```

---

## Task 5: Trace Repair Bay proposal pipeline

**Files:**
- Modify: `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md` — section 3

**Questions:**
- What are the actual status transitions for `improvement_proposals`?
- How does SandboxManager work today? Docker vs schema-separation?
- Is the pre-deploy health gate enforced? Where?

- [ ] **Step 5.1: Enumerate proposal statuses in use**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT status, COUNT(*) FROM improvement_proposals GROUP BY status ORDER BY COUNT(*) DESC;"
```

Expected: distribution of statuses in production DB. Note unusual statuses not documented in the rules file.

- [ ] **Step 5.2: Map status transitions in code**

Run:
```bash
grep -rnE "status\s*=\s*['\"](proposed|approved|code_generating|testing|tested|deployed|fix_requested)" \
  /mnt/archie_brain/platform_v2/tools/repair_bay/
```

Expected: ~dozens of hits across proposal/sandbox/deploy services. Build a rough transition graph from the hits.

- [ ] **Step 5.3: Locate SandboxManager**

Run:
```bash
grep -rnE "class SandboxManager|def create_sandbox|sandbox_type\s*=" \
  /mnt/archie_brain/platform_v2/
```

Expected: main class location + `docker_container` vs `schema_separation` selection logic.

- [ ] **Step 5.4: Locate pre-deploy health gate**

Run:
```bash
grep -rnE "pre.?deploy|health_?gate|ADR-?013|hardcoded.?secret" \
  /mnt/archie_brain/platform_v2/tools/repair_bay/
```

Expected: find the gate enforcement point + what it checks.

- [ ] **Step 5.5: Write Section 3 of the review doc**

Fill in section 3 with:
- Actual status list + count per status
- Transition graph (text-based, e.g., `proposed → approved → code_generating → testing → tested → deployed`)
- SandboxManager file:line + selector logic
- Pre-deploy gate file:line + check list

- [ ] **Step 5.6: Commit**

```bash
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git commit -m "docs(trace): section 3 — Repair Bay pipeline"
```

---

## Task 6: Trace Repair Bay → DHQ dispatch

**Files:**
- Modify: `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md` — section 4

**Questions:**
- Does Repair Bay ever call `dispatcher.dispatch()`?
- Is there an existing category/whitelist concept for "safe" proposals?
- How does a proposal actually get assigned to an agent today?

- [ ] **Step 6.1: Search for dispatcher calls from Repair Bay**

Run:
```bash
grep -rnE "dispatch\(|dispatch_json|get_dispatcher|request_work" \
  /mnt/archie_brain/platform_v2/tools/repair_bay/
```

Expected: may be 0 hits (confirms "manual only"), may be a few (confirms partial wire).

- [ ] **Step 6.2: Search for agent-assignment logic**

Run:
```bash
grep -rnE "assigned_agent_id|agent_id\s*=|assign_to_agent" \
  /mnt/archie_brain/platform_v2/tools/repair_bay/
```

Expected: find where `improvement_proposals.assigned_agent_id` gets set. Note whether it's auto or manual.

- [ ] **Step 6.3: Search for category/whitelist concepts**

Run:
```bash
grep -rnE "category\s*=|whitelist|safe_category|auto_dispatch|auto_approve" \
  /mnt/archie_brain/platform_v2/tools/repair_bay/
```

Expected: find any existing category/whitelist. If absent, confirm as a gap.

- [ ] **Step 6.4: Inspect a recent tested proposal**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT id, title, status, category, assigned_agent_id FROM improvement_proposals WHERE status IN ('tested','deployed') ORDER BY id DESC LIMIT 5;"
```

Expected: real data showing category + agent assignment pattern in production. Note whether `category` column even exists.

- [ ] **Step 6.5: Write Section 4 of the review doc**

Fill in section 4 with:
- Dispatcher calls: found at file:line, OR confirmed absent
- Agent assignment: how + when
- Category/whitelist: status
- Real production data pattern (from Step 6.4)

- [ ] **Step 6.6: Commit**

```bash
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git commit -m "docs(trace): section 4 — Repair Bay → DHQ dispatch"
```

---

## Task 7: Trace Telegram unification

**Files:**
- Modify: `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md` — section 5

**Questions:**
- Is `telegram_service.py` the unified sender, and what does its API look like today?
- Who are the 8 raw-SDK callers specifically?
- Does any caller already support `source_agent` attribution?

- [ ] **Step 7.1: Inspect unified telegram_service**

Run:
```bash
grep -nE "def send|class |source_agent|as_archie" /mnt/archie_brain/platform_v2/services/telegram_service.py
```

Expected: public API surface. Note whether `source_agent` + `as_archie` parameters exist.

- [ ] **Step 7.2: Enumerate raw-SDK callers**

Run:
```bash
grep -rnE "import telegram|from telegram|Bot\(|Updater\(|Application\.builder" \
  /mnt/archie_brain/platform_v2 /mnt/archie_brain/ai_bridge
```

Expected: the 8 (or more/fewer) callers. List each one with file:line + a one-line description of what it sends.

- [ ] **Step 7.3: Count unified vs raw**

Run:
```bash
grep -rnE "from services.telegram_service|from platform_v2.services.telegram_service|telegram_service\." \
  /mnt/archie_brain/platform_v2 /mnt/archie_brain/ai_bridge | wc -l
echo "---"
grep -rnE "import telegram|from telegram" \
  /mnt/archie_brain/platform_v2 /mnt/archie_brain/ai_bridge | wc -l
```

Expected: ratio gives a concrete migration progress number (e.g., "14 unified / 8 raw" → 64% migrated).

- [ ] **Step 7.4: Write Section 5 of the review doc**

Fill in section 5 with:
- telegram_service.py API surface + `source_agent`/`as_archie` status
- Full list of raw-SDK callers (file:line + purpose)
- Migration progress ratio
- Each caller's proposed unification target (inline or deferred)

- [ ] **Step 7.5: Commit**

```bash
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git commit -m "docs(trace): section 5 — Telegram unification status"
```

---

## Task 8: Trace ARCHIE decision infrastructure

**Files:**
- Modify: `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md` — section 6

**Questions:**
- Is there any existing decision queue (archie_decisions table or equivalent)?
- Does `archie_chat` module expose an approval/review surface?
- Does `ai_bridge/agent_loop.py::request_approval()` relate to what we're building?

- [ ] **Step 8.1: Check for decision-queue tables**

Run:
```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND (table_name LIKE '%decision%' OR table_name LIKE '%approval%' OR table_name LIKE '%archie%' OR table_name LIKE '%queue%') ORDER BY table_name;"
```

Expected: list of candidate tables. Note any that look like a decision/approval queue.

- [ ] **Step 8.2: Inspect candidate tables**

For each table from Step 8.1 that looks relevant, run:
```bash
docker exec archie_database psql -U archie -d archie -c "\d <table_name>"
```

Record the schema.

- [ ] **Step 8.3: Search for request_approval logic**

Run:
```bash
grep -nE "def request_approval|def wait_for_approval|def submit_approval" \
  /mnt/archie_brain/ai_bridge/agent_loop.py
```

Expected: existing approval orchestrator functions. These may already be partially what we need.

- [ ] **Step 8.4: Inspect archie_chat for approval surface**

Run:
```bash
grep -rnE "approve|approval|decision|review" /mnt/archie_brain/platform_v2/tools/archie_chat/
```

Expected: whether any UI/API for ARCHIE-side decisions already exists.

- [ ] **Step 8.5: Write Section 6 of the review doc**

Fill in section 6 with:
- Existing tables (schemas) that could serve as `archie_decisions` or must coexist with it
- `request_approval`/`wait_for_approval` current behavior — can we reuse or do we need to replace?
- archie_chat approval surface status
- Concrete recommendation: extend existing vs. greenfield

- [ ] **Step 8.6: Commit**

```bash
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git commit -m "docs(trace): section 6 — ARCHIE decision infrastructure"
```

---

## Task 9: Write the gap list + clean up seed

**Files:**
- Modify: `docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md` — sections 7 + 8
- Remove: `sandbox/ch_trace_seed.py`

**Questions:**
- What does each of Phases 1-4 actually need to build vs. enrich?
- What blocked items came up that should become their own tasks?

- [ ] **Step 9.1: Populate Section 7 (plant-and-follow outcome)**

Using findings from Tasks 3-8, finalize section 7:
- Did the seed finding reach each expected stage?
- At what stage(s) did it drop off or behave unexpectedly?
- What's the end state in the DB right now?

- [ ] **Step 9.2: Write Section 8 (gap list for Phases 1-4)**

For each phase, list the concrete gaps found, using this format:

```markdown
### Phase 1 gaps
- [ ] **Gap 1.1:** <what's missing or stubbed> (evidence: <file:line or DB query result>)
- [ ] **Gap 1.2:** ...

### Phase 2 gaps
...

### Phase 3 gaps
...

### Phase 4 gaps
...
```

Each gap must have evidence from the preceding sections. No gap may be "I suspect" — only "I observed".

- [ ] **Step 9.3: Remove the seed**

Run:
```bash
rm /mnt/archie_brain/sandbox/ch_trace_seed.py
```

Do not delete any rows inserted into `code_audit_log` or `improvement_proposals` — leave them for the Phase 1 plan to handle explicitly (they become part of the real dataset Phase 1's dedup work must handle).

- [ ] **Step 9.4: Commit final trace + cleanup**

```bash
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git rm --ignore-unmatch sandbox/ch_trace_seed.py
git commit -m "docs(trace): final gap list + seed cleanup"
```

---

## Task 10: Log task backlog for the gap list

**Files:**
- No file changes. Creates tasks in `unified_tasks` via MCP.

**Why:** A gap list in a doc is passive. Turning each gap into a tracked task keeps the backlog honest.

- [ ] **Step 10.1: For each gap in Section 8, create a task via MCP**

For every `Gap X.Y` in the review doc, call:

```python
mcp__archie__create_task(
    project_id=152,  # Platform Audit project
    title="Phase <X> — <gap description>",
    description=(
        "From Phase 0 trace: <the gap text>.\n"
        "Evidence: <file:line or DB query>.\n"
        "See <full path to review doc>, section 8, Gap X.Y."
    ),
    priority=9 if phase in (1,2,3) else 8,  # Phase 4 is P8
    task_type="implementation" if "build" else "bugfix",
    estimated_effort="small"|"medium"|"large",
)
```

Capture the returned task_id for each.

- [ ] **Step 10.2: Annotate the review doc with task IDs**

Go back to Section 8 and replace each `Gap X.Y` with `Gap X.Y (#<task_id>)` so the doc is cross-referenced to the backlog.

- [ ] **Step 10.3: Commit the task ID annotations**

```bash
git add docs/superpowers/reviews/<today>-self-healing-pipeline-trace.md
git commit -m "docs(trace): cross-reference gaps to backlog task IDs"
```

---

## Task 11: Hand off to Phase 1 plan writing

**Files:**
- No file changes in this task.

- [ ] **Step 11.1: Verify Phase 0 success criteria**

- [ ] Each pipeline stage (1-7 in spec §3) has a section with file:line evidence.
- [ ] `_has_open_proposal()` status is definitive (present/absent, not "unclear").
- [ ] Dispatcher-call status from Repair Bay is definitive.
- [ ] Raw-SDK Telegram callers are enumerated with exact paths.
- [ ] Existing decision-queue tables are identified or confirmed absent.
- [ ] Gap list has concrete evidence citations for every entry.
- [ ] Backlog tasks exist for every gap.

- [ ] **Step 11.2: Announce readiness for Phase 1 plan**

Report back with:
- Review doc path
- Task IDs created
- Summary count: gaps per phase
- Recommendation: which phase plan to write next (Phase 1 is the default unless Phase 0 uncovered something that changes the ordering).

---

## Notes for the Executor

- **Commit frequently** — end of every task, sometimes end of every step if a step produced meaningful output.
- **If a grep/read step returns zero hits**, that IS the finding. Don't pad results or speculate. Write "Confirmed absent via `<exact command run>`" in the review doc.
- **If a task reveals a gap that changes the plan**, stop and surface it. Don't silently re-scope.
- **Push freeze reminder:** commits stay local until 2026-05-01. Track the branch in Repair Bay's pending-push queue.
- **No database writes.** All psql queries are SELECT/\d. If you find yourself wanting to UPDATE or INSERT, pause — that's Phase 1+ work.
- **Seed file safety:** `sandbox/` should have a `.gitignore` excluding `*` — if it doesn't, add it in Step 3.1 before writing the seed. The seed must never reach git.

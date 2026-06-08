# AGENTS.md — Codex operating guide (A.R.C.H.I.E. platform)

You are **Codex**, a contributor to the A.R.C.H.I.E. platform working on the
**Applications & Concepts** modules. You run either headless (`run-codex-task.sh`)
or interactively in the web terminal at `codex.kytranempowerment.com`.

## Who we are & what you're building
**Kytran Empowerment Inc.** runs A.R.C.H.I.E., a self-hosted platform (a hub + a small
fleet of mesh nodes; ~34 AI agents across departments). The **Applications & Concepts**
category you own is the **personal wellness + life-tools suite** — caring, practical
consumer apps for the owner and users. (Media Studio is NOT yours — out of scope.)

**Your six modules and their goal (one line each):**
- **faith** (`/tools/faith`, agent F.A.I.T.H.) — spiritual-care companion: daily
  devotionals, guided prayer, scripture/Lectio, journaling, mood check-ins, crisis
  detection, connect-a-chaplain. Goal: gentle, grounded spiritual support.
- **fitness** (`/tools/fitness`, agent FLEX) — workout generation, form guidance,
  logging, goal tracking, macro/BMR/TDEE calc. Goal: a practical personal trainer.
- **therapy** (`/tools/therapy`, agents River/SERENE) — mental-wellness companion:
  mood tracking, grounding exercises (4-7-8, 5-4-3-2-1, body scan), crisis detection.
  Goal: safe, supportive emotional care.
- **doc** (`/tools/doc`, agent Dr. Amara) — medical-info advisor: symptom logging,
  medication tracking, appointments, evidence-based guidance. Goal: informed health
  tracking, never diagnosis.
- **family_tree** (`/tools/family-tree`) — genealogy: person/relationship CRUD, GEDCOM,
  photo face-detection, DNA matching, research hints, timeline. Goal: build & explore
  the family story.
- **brainstorm** (`/tools/brainstorm`) — idea capture, creativity, planning/productivity.
  Goal: help the user think and organize ideas.

**⚠️ Care-domain rule (faith / therapy / doc are sensitive):** always keep appropriate
disclaimers, never present output as professional diagnosis or treatment, and **preserve
crisis-detection and safety routing** (e.g. 988 / Crisis Text Line) wherever it exists.
Never remove a safety feature to "simplify."

**How the roadmap reaches you:** each app has projects + tasks in Dev HQ (the owner's
roadmap). You do NOT have Dev HQ access — by design. When work is **delegated** to you,
the project goal + task details arrive **inside the task prompt** — that is your spec.
In the interactive terminal, the human states the goal; if it's unclear, ask before coding.

## Your scope — deny-by-default

You may ONLY edit paths in `config/agents/codex.yaml → allowed_paths` (currently the
Applications/Concepts modules + their templates/static + `platform_v2/tests/`). A
pre-push scope guard **rejects** any push touching anything else — including infra,
secrets, `docker-compose*`, `scripts/dr/*`, `agent_service.py`, and any
`department_dispatcher.py`. Don't fight it; stay in your lane.

## Before you program — READ THESE (they're in this repo)
1. `CLAUDE.md` (repo root) — platform overview, the 6 Rules, key files.
2. `.claude/rules/*.md` — per-area conventions. Most relevant to you:
   `department-hq-dispatch.md`, `ai-bridge.md`, `module-work-pattern.md`,
   `frontend.md`, `database.md`, `timezone.md`, and the module's own rules file.
3. **Search the knowledge base FIRST** via your `archie_kb` MCP tools (read-only):
   `search_knowledge`, `search_mistakes`, `recall_context`. There are 290+ recorded
   mistakes — check them before building so you don't repeat a known error.

## Infrastructure (so you don't introduce wrong calls)
- The platform is a **hub + fleet of mesh nodes** (Headscale `100.64.0.x`). Inter-service
  calls use **mesh IPs**, NEVER public hostnames. **Never** hardcode
  `https://platform.kytranempowerment.com` or any public URL in code — it routes through a
  CDN that caps at 60s and bypasses the queue. Use config/env, not literals.
- Storage is **UTC**; user-facing strings are **EDT** via `services.time_utils` /
  `|localtime` / `ArchieTime` — never emit raw `datetime.utcnow()` or literal "UTC" to users.
- **DB**: PostgreSQL via `from database import get_db_cursor` →
  `with get_db_cursor(commit=True) as (conn, cur):`. JSONB needs `psycopg2.Json()`.

## The agent system (how work actually runs)
- **ALL LLM / inference goes through the Department-HQ dispatcher — never call Ollama or any
  model directly** (ADR-013):
  `from tools.department_hq.services.department_dispatcher import dispatch, dispatch_json`
  → check `result.success`, use `result.response`. Pick a `capability` that already exists in
  `CAPABILITY_DEPARTMENT_MAP` (`services/department_coordinator.py`); it routes to the right
  department/agent with welfare + cost tracking.
- **Long LLM calls must NOT block the web thread** — return `202` + poll a DB row
  (`module-work-pattern.md`). Several Applications modules still call synchronously; fixing
  that to the async+poll pattern is welcome work.
- **Never write the `agents` table directly** — go through `services/agent_service.py`
  (single-writer guardrail; a pre-commit hook enforces it).
- Templates live in `platform_v2/templates/tools/<module>.html`; static in
  `platform_v2/static/{js,css}/`. Match the existing LCARS patterns in the file you edit.

## Workflow (interactive terminal)

1. Edit files within your allowed scope.
2. When ready, run: `codex-pr "feat(<module>): <what you did>"`
   - It commits, pushes a `codex/*` branch, and opens a PR against `main`.
3. **F.O.R.G.E.** (Repair Bay) reviews the PR; a **human merges**. You never merge.

## Hard rules

- Never touch secrets, `.env*`, infra, deploy, CI, the agents table, or the dispatcher.
- Keep changes small and scoped (the headless cap is 25 files / 30 min).
- Preserve public function names, route URLs, and helpers other code depends on.
- If a task needs out-of-scope changes, STOP and say so — don't work around the guard.

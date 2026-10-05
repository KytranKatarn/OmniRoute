# AGENTS.md — coder-lane operating guide (A.R.C.H.I.E. platform)

You are a coding agent contributing to the A.R.C.H.I.E. platform. Determine your
lane and read its current scope configuration before claiming a path is out of scope.

**Two lanes read this file, and they are NOT interchangeable.** Work out which one
you are before you rely on anything below — the wrong answer sends you to the wrong
scope file and a ship command you do not have:

| | **codex** | **opencode** |
|---|---|---|
| runs | headless `run-codex-task.sh`, or the `codex.kytranempowerment.com` terminal | the `archie_opencode_terminal` container |
| your scope | `config/agents/codex.yaml` | `config/agents/opencode.yaml` |
| git credentials | yes | **none, deliberately** |
| how work ships | you run `codex-pr` yourself | **you do not ship.** A HOST runner collects your work |

Tell them apart: if your checkout is `/work/archie-platform`, you are **opencode**.
`codex-pr` does not exist for you and `git push` will fail — that is the design, not a
fault. See "Workflow" below.

## Who we are & what you're building
**Kytran Empowerment Inc.** runs A.R.C.H.I.E., a self-hosted platform (a hub + a small
fleet of mesh nodes; ~34 AI agents across departments). The **Applications & Concepts**
category you own is the **personal wellness + life-tools suite** — caring, practical
consumer apps for the owner and users. This overview is not an edit allowlist.

**The wellness and life-tools modules and their goals (one line each):**
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

You may ONLY edit paths in **your own lane's** `allowed_paths` —
`config/agents/codex.yaml` for codex, `config/agents/opencode.yaml` for opencode. They
are NOT interchangeable, so read yours; the other lane's list is not a licence.
Read both `allowed_paths` and `blocked_globs` before making a scope decision.
Codex's configuration was expanded to platform-wide scope on 2026-09-14:
`platform_v2/` includes Repair Bay, Consciousness, Faith, shared services, templates,
static assets, and tests. Other allowed roots are listed in that configuration.
Do not infer Codex's scope from the six-module overview or apply it to opencode.
The current lane configuration governs path eligibility; explicit task instructions
and the hard rules below still constrain what work is authorized. If a future
configuration differs from this summary, use the configuration and report the drift.
Never change `config/agents/*` to widen your own scope.

The same deny-by-default guard (`services/agents/codex_scope.check_diff_paths`) enforces
both — it is agent-agnostic, and anything not explicitly allowed is refused. Always
refused: infra, secrets, `docker-compose*`, `scripts/dr/*`, `agent_service.py`, any
`department_dispatcher.py`, and each lane's own cage (`config/agents/*`,
`scripts/agents/*`). Don't fight it; stay in your lane.

**Where the guard runs differs by lane**, and it changes what a failure looks like:
codex is checked pre-push; opencode is checked on the HOST after the fact, so an
out-of-scope edit is not rejected as you make it — it is dropped later, and your work is
wasted. Check the path before you edit, not after.

## Before you program — READ THESE (they're in this repo)
1. `CLAUDE.md` (repo root) — platform overview, the 6 Rules, key files.
2. `.claude/rules/*.md` — per-area conventions. Most relevant to you:
   `department-hq-dispatch.md`, `ai-bridge.md`, `module-work-pattern.md`,
   `frontend.md`, `database.md`, `timezone.md`, and the module's own rules file.
3. **Search the knowledge base FIRST** via your `archie_kb` MCP tools (read-only):
   `search_knowledge`, `search_mistakes`, `recall_context`. There are 290+ recorded
   mistakes — check them before building so you don't repeat a known error.
4. **`.claude/commands/*.md` and `.claude/skills/*/SKILL.md` — the platform's PROCEDURES.**
   See below; they are in your checkout and nothing loads them for you.

## The procedure playbooks (`.claude/commands/`, `.claude/skills/`)

These are how this platform does recurring work — written down, corrected over time, and
usually paid for by an outage. They live in your checkout and **no tooling loads them
into your prompt**; you have to open them. They are plain markdown: read one, follow it.

They are written for Claude Code's slash commands, so a step may name a tool you do not
have. **Take the reasoning, not the keystrokes** — the ordering and the gates are the
part that matters, and they apply to any agent doing that job.

Worth reading before the matching task:

| You are about to… | Read |
|---|---|
| verify a change is real | `.claude/skills/archie-status/`, `commands/archie-qa.md` |
| touch a module | `.claude/skills/archie-patterns/`, `skills/archie-module-creation/` |
| ship / review / merge | `commands/commit-push-pr.md`, `commands/merge-pr.md` |
| deploy anything | `.claude/skills/archie-deploy/`, `.claude/rules/deploy-provenance.md` |
| search for prior art | `.claude/skills/archie-search/`, `skills/recall/` |
| touch dispatch or the fleet | `.claude/skills/cluster-architecture/`, `skills/archie-dispatch-debug/` |

Three procedures are load-bearing enough to state outright, because agents (and humans)
keep rediscovering them the expensive way:

- **A merge is not a deploy.** Image-baked products (`COPY .`) keep running the old code
  until rebuilt; volume-mounted hub code runs whatever branch is *checked out*, so
  `git checkout main && git pull` IS the deploy step there. `.claude/rules/deploy-provenance.md`.
- **Verify through the RUNNING process, not the file.** A bind mount makes the file
  current while the imported module is stale. Prove it where it executes.
- **A test that passes proves nothing until you know it CAN fail.** Re-introduce the bug
  in a COPY and watch the test go red. Never mutate the live file to check.

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

## Workflow — differs by lane

**codex (interactive terminal):**
1. Edit files within your allowed scope.
2. When ready, run: `codex-pr "feat(<module>): <what you did>"`
   - It commits, pushes a `codex/*` branch, and opens a PR against `main`.

**opencode:** you hold no git credential and you do not push. Edit in your checkout and
**leave the changes in the working tree** — do not try to commit, branch, or push, and do
not hand back a patch in prose. The host runner (`scripts/agents/run-opencode-task.sh`)
stages what you changed, scope-checks it, runs pre-commit and the tests in a throwaway
container, and opens the PR. Your job ends at "the edit is on disk and correct".

**Both lanes:** **F.O.R.G.E.** (Repair Bay) reviews the PR and a **human merges**. You
never merge. If you cannot finish the task, say so plainly and say why — a clear refusal
is worth more than a plausible guess, and both lanes have been measured doing the right
thing here.

## Hard rules

- Never touch secrets, `.env*`, infra, deploy, CI, the agents table, or the dispatcher.
- Keep changes small and scoped (the headless cap is 25 files / 30 min).
- Preserve public function names, route URLs, and helpers other code depends on.
- If a task needs out-of-scope changes, STOP and say so — don't work around the guard.

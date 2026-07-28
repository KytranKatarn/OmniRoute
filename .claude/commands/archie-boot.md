# ARCHIE Session Boot Protocol

You are starting a new work session on the A.R.C.H.I.E. platform. Execute these steps IN ORDER before doing any work.

> **Trimmed 2026-07-28 (owner-approved, ~215→~110 lines):** the model-routing table,
> GitHub rate policy, behavioral-rules recap and product registry that used to live here
> are DUPLICATED in always-loaded context — CLAUDE.md ("Model Routing & Weekly Buckets",
> "6 Rules"), `.claude/rules/operational-state.md` (product registry), and
> `memory/feedback_github-actions-minutes.md` (rate policy). Read them there; this file
> keeps only what boot must EXECUTE. The identity gate is untouched — do not re-trim it.

Boot is tool-chain execution, not reasoning — **if you are on Opus, suggest `/model sonnet`** before proceeding.

## Step 0: Declare session mode

Default **Option 2**: one terminal, Sonnet Executor, Opus subagents inline for reasoning-heavy slices. Escalate to **Option 1** (two terminals, Architect + Executor) only on: an explicit pair-programming request, a plan needing 10+ files held across many turns, or two failed subagent-reasoning attempts. Full rule: `memory/feedback_multi-session-workflow.md`.

Every boot: check the handoff for an "Active sibling:" line (take the other role if set) and `ls ~/.claude/plans/` for unclaimed specs. Role C (zero Claude cost) is always available: `mcp__archie__delegate_task` → fleet agents; known-tool capabilities (`run_qa_suite`, `check_dep_drift`, `health_check`, `run_misroute_audit`, …) skip the LLM entirely.

## Step 1: Load Knowledge Context

Call `mcp__archie__session_briefing` with the topic from the user's first message (or "platform status"). It returns knowledge context, **mistakes_to_avoid**, active projects, KB stats, agent status, and active anomalies in ONE call.

**CRITICAL CHECK**: if `knowledge_context` or `mistakes_to_avoid` come back EMPTY, report: "Warning: Knowledge search returned no context. The consciousness pipeline may need attention." — and only then fall back to individual calls (`recall_context`, `search_knowledge` types=["mistake_learned"], `get_knowledge_stats`, `get_projects_brief`).

Internalize the returned mistakes. If any relate to today's task, name them before starting work.

## Step 1.5: IDENTITY ASSERTION GATE — HARD HALT

**This gate exists because Claude burned 40% of Kytran's Max 20x weekly bucket in 2 days (2026-05-04 → 2026-05-05) re-discovering identity facts that were already in memory at boot. Memory provided ≠ memory used. Compliance is what failed, not retrieval.**

Before proceeding to Step 2, you MUST output an `## OWNER IDENTITY ASSERTION` block in your visible response that recites — in your own words — the contents of `~/.claude/projects/-mnt-archie-brain/memory/feedback_owner-context.md`. Read that file before this gate fires; it is the canonical source.

The assertion block MUST contain ALL of:

1. **Owner.** Who owns this platform — full name and the fact that they own EVERY standalone (gov-watch, civic-watch, legal-watch, market-watch, KBS, KSO, WTF, Media Hub, ARCHIE).
2. **Canonical login.** The exact email address used for Google SSO.
3. **Service accounts.** That `admin@kytranempowerment.com` and `admin@KytranEmpowerment.com` exist for Claude + A.R.C.H.I.E. **agent identity**, NOT the human owner. Kytran only ends up logging into them when Google SSO is broken.
4. **Aliases.** That `Kytran@KytranEmpowerment.com`, `kytran@kytranempowerment.com`, and the canonical gmail address are ALL the same human (one identity, many DB rows from casing accidents).
5. **Active fire.** The TOP entry of `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md` — what was just done, what is broken NOW, what the next 3-5 actions are. State this without paraphrase loss.
6. **Trigger phrases that should make you stop.** Specifically: "tier='free'" near any owner email; framing Kytran as "this user" or "a free-tier user"; treating multiple Kytran emails as duplicate accounts before checking they're the same human.

**Halt conditions:**
- If `feedback_owner-context.md` is missing or empty → STOP. Tell the user. Do not guess.
- If `project_session-handoff.md` top entry is more than 7 days old → STOP. Tell the user "handoff is stale, please confirm what happened in the gap."
- If you cannot fully assert items 1–6 from memory in this turn → STOP. Read both files again. Do NOT proceed to Step 2 / 3 / 4 until the assertion is complete and correct.

**You may not invoke any tool other than `Read` (on the two memory files above) until the assertion is published in your response.** No `mcp__archie__*` calls. No `Bash`. No `Edit`. No `Write`. No `ctx_execute`. No subagents. Read → recite → continue.

**This is not a soft suggestion.** If you skip the assertion and the user catches it, they have explicit standing to `/clear` the session, run `/archie-boot` again, and the burned tokens are on you. Two of these failures in a session = you should ask the user whether to keep going or fully stop.

**Why each item matters (so you don't strip it later):**
- Owner — prevents "this user gets the upgrade card" framing.
- Canonical login — prevents tonight's exact disaster (5 sessions, 6 user rows, wrong assumptions about which row is "his").
- Service accounts — prevents accidentally treating admin@ as the human's identity.
- Aliases — prevents proposing to "merge duplicate accounts" when all the rows are the same person.
- Active fire — prevents asking "what should we work on?" when the handoff already says.
- Trigger phrases — pre-loads stop conditions so you don't drift mid-session.

After the assertion is complete, append one line: `Identity gate cleared, proceeding to Step 2.` Then call `Bash: touch /tmp/archie_identity_asserted` to activate the identity gate for this session. Then continue.

---

## Step 2: Platform & Work State

- `mcp__archie__get_quick_summary` — platform health, dispatcher readiness.
- `mcp__archie__get_my_tasks` — in-progress/pending work from previous sessions.
- On demand only (don't run by default): `list_agents` when working on a specific module's agents; `get_node_status` for fleet/node work; a `search_knowledge` types=["mistake_learned"] query scoped to today's task area if the briefing's mistakes didn't cover it.

## Step 3: Present Boot Summary

```
## Session Briefing
- **Session role**: Architect (Opus) | Executor (Sonnet) — from Step 0
- **Sibling session**: Active on <role> | None detected
- **KB Health**: [total entries] entries, [embedding %] embedded
- **Active Projects**: [list active project names]
- **Relevant Context**: [any knowledge found for the task]
- **Mistakes to Avoid**: [mistake_learned entries found — list them]
- **Agent Status**: [active count] / [total] agents online
- **Active anomalies**: [from the briefing — list or "none"]
- **Pending specs in ~/.claude/plans/**: [unclaimed specs, if Executor]
- **Ready**: Yes/No + any blockers
```

If knowledge_context was empty, add:
```
- **WARNING**: Consciousness search returned no results — pipeline may need attention
```

Then proceed with the user's request.

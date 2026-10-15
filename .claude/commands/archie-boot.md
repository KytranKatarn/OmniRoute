# ARCHIE Session Boot Protocol

You are starting a new work session on the A.R.C.H.I.E. platform. Execute these steps IN ORDER before doing any work.

> **Trimmed 2026-07-28 (owner-approved, ~215→~110 lines):** the model-routing table,
> GitHub rate policy, behavioral-rules recap and product registry that used to live here
> are DUPLICATED in always-loaded context — CLAUDE.md ("Model Routing & Weekly Buckets",
> "6 Rules"), `.claude/rules/operational-state.md` (product registry), and
> `memory/feedback_github-actions-minutes.md` (rate policy). Read them there; this file
> keeps only what boot must EXECUTE. The identity gate is untouched — do not re-trim it.

> **Reordered 2026-10-15 (task 7258):** the identity gate moved from Step 1.5 to
> Step 1 — ahead of the briefing — because the old order made Step 1's MCP call
> violate the gate's own no-tools rule. Checklist items 2–4 refreshed for post-SSO
> reality (Google SSO was removed 2026-05-06; `feedback_owner-context.md` is the
> living source). Gate substance was NOT trimmed; only its position and stale
> wording changed.

Boot is tool-chain execution, not reasoning — **if you are on Opus, suggest `/model sonnet`** before proceeding. (In lanes where `/model` doesn't exist — the opencode terminal — skip this line silently; see the "Lane tool mapping" block in `AGENTS.md`.)

## Step 0: Declare session mode

Default **Option 2**: one terminal, Sonnet Executor, Opus subagents inline for reasoning-heavy slices. Escalate to **Option 1** (two terminals, Architect + Executor) only on: an explicit pair-programming request, a plan needing 10+ files held across many turns, or two failed subagent-reasoning attempts. Full rule: `memory/feedback_multi-session-workflow.md`.

Decide the mode now — Step 0 is reasoning only, no tool calls. The lookups it implies (the handoff's "Active sibling:" line, `ls ~/.claude/plans/`) happen across the next steps: the handoff is one of the two files the gate makes you Read anyway; the plans listing runs in Step 4, after the gate clears. Role C (zero Claude cost) is always available: `mcp__archie__delegate_task` → fleet agents; known-tool capabilities (`run_qa_suite`, `check_dep_drift`, `health_check`, `run_misroute_audit`, …) skip the LLM entirely.

**Host-instance opencode lanes only** (native binary on the host, checkout `/mnt/archie_brain`): you carry a lane-specific continuity file the shared handoff does not cover — `~/.config/opencode/data/archie-handover.md`. Read it in Step 4's lookups at boot, fold its open items into the Step 5 summary, and **refresh it at session end** with what actually happened. Its authority doc is `scripts/opencode_host_lane_docs/GUARDRAILS.md`, which requires read-at-boot / refresh-at-end; Claude lanes keep the shared handoff, this one is yours alone.

## Step 1: IDENTITY ASSERTION GATE — HARD HALT

**This gate exists because Claude burned 40% of Kytran's Max 20x weekly bucket in 2 days (2026-05-04 → 2026-05-05) re-discovering identity facts that were already in memory at boot. Memory provided ≠ memory used. Compliance is what failed, not retrieval.**

Before proceeding to Step 2, you MUST output an `## OWNER IDENTITY ASSERTION` block in your visible response that recites — in your own words — the contents of `~/.claude/projects/-mnt-archie-brain/memory/feedback_owner-context.md`. Read that file before this gate fires; it is the canonical source. Where that file's older embedded snapshots contradict its top "Identity Truth" section, the top section wins — recite from it.

The assertion block MUST contain ALL of:

1. **Owner.** Who owns this platform — full name and the fact that they own EVERY standalone (gov-watch, civic-watch, legal-watch, market-watch, KBS, KSO, WTF, Media Hub, ARCHIE).
2. **Canonical login.** `kytran@kytranempowerment.com` (email + password; username `kytran`). Google SSO was **removed** (Project Alpha, 2026-05-06) — do not recite an SSO flow. `kytranempowerment@gmail.com` is the backup Google identity for EXTERNAL sites only, never the platform login.
3. **Service accounts.** That `admin@kytranempowerment.com` and `admin@KytranEmpowerment.com` exist for Claude + A.R.C.H.I.E. **agent identity**, NOT the human owner (both deactivated as platform logins 2026-05-06; `claude@` and `archie@` remain the active agent identities). Kytran never logs in as admin@ except as the historical password fallback from when SSO was breaking.
4. **Aliases.** That `Kytran@KytranEmpowerment.com`, `kytran@kytranempowerment.com`, the canonical gmail address, and **Terry** are ALL the same human (one identity, many DB rows from casing accidents; "Kytran and Terry are the same person", owner-stated 2026-06-02).
5. **Active fire.** The TOP entry of `~/.claude/projects/-mnt-archie-brain/memory/project_session-handoff.md` — what was just done, what is broken NOW, what the next 3-5 actions are. State this without paraphrase loss.
6. **Trigger phrases that should make you stop.** Specifically: "tier='free'" near any owner email; framing Kytran as "this user" or "a free-tier user"; treating multiple Kytran emails as duplicate accounts before checking they're the same human.

**Halt conditions:**
- If `feedback_owner-context.md` is missing or empty → STOP. Tell the user. Do not guess.
- If `project_session-handoff.md` top entry is more than 7 days old → STOP. Tell the user "handoff is stale, please confirm what happened in the gap."
- If you cannot fully assert items 1–6 from memory in this turn → STOP. Read both files again. Do NOT proceed to Step 2 / 3 / 4 / 5 until the assertion is complete and correct.

**You may not invoke any tool other than `Read` (on the two memory files above) until the assertion is published in your response.** No `mcp__archie__*` calls. No `Bash`. No `Edit`. No `Write`. No `ctx_execute`. No subagents. Read → recite → continue. (This is why Step 0 does no lookups and why the briefing is Step 2, after the gate.)

**This is not a soft suggestion.** If you skip the assertion and the user catches it, they have explicit standing to `/clear` the session, run `/archie-boot` again, and the burned tokens are on you. Two of these failures in a session = you should ask the user whether to keep going or fully stop.

**Why each item matters (so you don't strip it later):**
- Owner — prevents "this user gets the upgrade card" framing.
- Canonical login — prevents tonight's exact disaster (5 sessions, 6 user rows, wrong assumptions about which row is "his").
- Service accounts — prevents accidentally treating admin@ as the human's identity.
- Aliases — prevents proposing to "merge duplicate accounts" when all the rows are the same person.
- Active fire — prevents asking "what should we work on?" when the handoff already says.
- Trigger phrases — pre-loads stop conditions so you don't drift mid-session.

After the assertion is complete, append one line: `Identity gate cleared, proceeding to Step 2.` Then activate the sentinel for THIS session: `Bash: touch /tmp/archie_identity_asserted_<session-id>` — use your harness's session identifier if it exposes one, otherwise an alias you mint now and cite in your Step 5 summary. The old unsuffixed `/tmp/archie_identity_asserted` is deprecated: it proves *some* session booted, not *this* one. Then continue.

---

## Step 2: Load Knowledge Context

Call `mcp__archie__session_briefing` with the topic = the user's actual work subject. **Never pass the command name** — `/archie-boot` as topic returns unrelated knowledge cards; if the session opens with only a command or no stated task, use the default `"platform status"` and re-run with the real topic once the user states the work. It returns knowledge context, **mistakes_to_avoid**, active projects, KB stats, agent status, and active anomalies in ONE call.

**CRITICAL CHECK**: if `knowledge_context` or `mistakes_to_avoid` come back EMPTY, report: "Warning: Knowledge search returned no context. The consciousness pipeline may need attention." — and only then fall back to individual calls (`recall_context`, `search_knowledge` types=["mistake_learned"], `get_knowledge_stats`, `get_projects_brief`).

Internalize the returned mistakes. If any relate to today's task, name them before starting work. The briefing's default mistake list is generic — the moment the user states real work, also run one task-scoped `search_knowledge` query with types=["mistake_learned"] over that area (Step 3's on-demand line) and name anything relevant.

## Step 3: Platform & Work State

- `mcp__archie__get_quick_summary` — platform health, dispatcher readiness.
- `mcp__archie__get_my_tasks` — in-progress/pending work from previous sessions.
- On demand only (don't run by default): `list_agents` when working on a specific module's agents; `get_node_status` for fleet/node work; the task-scoped `search_knowledge` mistakes query described in Step 2 once today's work is known.

## Step 4: Git, Plans & Ship State

Run after the gate clears (these are the shell lookups Step 0 deferred):

- `git -C <toplevel> rev-parse --show-toplevel` + `git rev-parse --abbrev-ref HEAD` + `git status -sb` — what tree am I in, what branch, who is mid-task. In the shared live tree (`/mnt/archie_brain`) an uncommitted tree means another lane is working: never stage their files, never `git add -A`.
- Determine the **ship route** before writing anything: host opencode instance ships via a **worktree off `origin/main` + real `gh pr create`** (`ship-branch.sh`/`opencode-pr` do NOT exist on the host — see `scripts/opencode_host_lane_docs/GUARDRAILS.md`, which wins for that instance); contained opencode terminal runs `opencode-pr`; headless runs leave changes in the tree for the host runner. Never commit to `main`; never merge your own PR.
- `ls ~/.claude/plans/` — unclaimed specs. **Claim convention:** a spec starts with a `> Claimed: <session>` header the moment a session picks it up; if you take one, prepend it. Specs without the header are fair game.

## Step 5: Present Boot Summary

```
## Session Briefing
- **Session role**: Architect (Opus) | Executor (Sonnet) — from Step 0
- **Sibling session**: Active on <role> | None detected
- **Identity gate**: cleared — sentinel /tmp/archie_identity_asserted_<session-id>
- **Git state**: <toplevel> @ <branch> — clean | dirty (<whose work, if not yours>)
- **Ship route**: host worktree + gh | opencode-pr | leave in tree
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

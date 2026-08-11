# Claude-to-Codex compatibility contract

## Authority

1. Obey current instructions, the nearest AGENTS.md, current code and configuration,
   repository state, and recent Git history before historical Claude text.
2. Read the selected Claude command or skill completely. Cross-check volatile paths, schemas,
   counts, models, task IDs, ports, and service names before relying on them.
3. Preserve .claude files and Claude memory. Never delete, rename, or restructure them.

## Invocation and tools

- Codex skills use $archie-name; /archie-save means the matching $archie-save skill.
- Treat $ARGUMENTS as the user's text following the skill invocation.
- Resolve the repository root with git rev-parse --show-toplevel; do not assume a host path.
- Translate mcp__archie__NAME to the exposed A.R.C.H.I.E. KB/Dev HQ tool with the same
  capability. Discover available tools rather than inventing names.
- The Codex terminal's archie_kb gateway may be read-only. If a required write tool is absent,
  state exactly what was not persisted. Never claim a memory, task, decision, work session,
  or KB note was stored when it was not.
- Prefer A.R.C.H.I.E. MCP resources over direct database reads. Direct SQL is diagnostic-only
  unless the user explicitly authorizes the mutation and active scope permits it.
- Do not call inference providers directly. Platform inference follows ADR-013 through DHQ.

## Memory and session continuity

- Read ~/.claude/projects/-mnt-archie-brain/memory/ as historical knowledge when accessible.
- Store Codex's live handoff at
  ${CODEX_HOME:-$HOME/.codex}/memory/project_session-handoff.md. Create it only from an
  explicitly invoked save/end workflow.
- On boot/resume, read both handoffs when present. Prefer newest evidence, flag conflicts,
  and verify against Git and current code.
- Persist durable knowledge to the platform KB only through an available write-capable tool.
  Do not write the production database as a substitute for a missing MCP tool.
- Never copy secrets, credentials, private identity data, or full sensitive memory into reports.

## Git and Repair Bay

- Inspect git status before writes. Preserve unrelated and pre-existing changes.
- Do not auto-commit unrelated work. Save/end may checkpoint only changes whose ownership and
  scope are clear; otherwise report them and ask.
- In the sandboxed terminal, use codex-pr with a title for authorized Applications/Concepts
  changes. It creates a codex/* branch and PR for F.O.R.G.E. review.
- Never merge a PR from a Codex workflow. A human merges after Repair Bay review.
- Do not translate Claude's automatic merge or human_override behavior into Codex.

## Mutations and production safety

- Read-only inspection is the default for status, probe, handoff, search, and debug workflows.
- Deployments, restarts, migrations, maintenance-window changes, task/agent mutations, account
  changes, and destructive QA actions require explicit user intent and scope permission.
- Never restart production merely to investigate. Never modify Docker/Compose, infrastructure,
  CI, secrets, or production services unless explicitly authorized for that exact change.
- Preserve care-domain disclaimers, crisis detection, and safety routing.
- Never write the agents table directly. Use services.agent_service; hiring/reactivation also
  requires Kytran's explicit approval in the current session.
- Never expose credentials. Do not reuse Claude's login account unless the owner explicitly
  designated it as shared; stop if no Codex account exists.

## Claude-only behavior

- Ignore Claude model-switch, plan-tier, plugin-count, context-window, /compact, and
  Claude-specific subagent instructions. Report Codex state only when actually available.
- Do not spawn subagents unless current runtime instructions and the user explicitly allow it.
- Codex cannot force compaction. Save state and let the host compact automatically.
- Replace Claude session IDs with available Codex identifiers; mark unavailable rather than
  fabricating values.

## Verification

- Lead with observed outcomes and include supporting commands/tests.
- Treat two repeated failures as a stop-and-diagnose point for risky operations.
- Never declare saved, deployed, healthy, synchronized, or fixed without direct evidence.

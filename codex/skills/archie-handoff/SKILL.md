---
name: archie-handoff
description: Display and validate the current Codex and historical Claude A.R.C.H.I.E. handoffs without changing them. Use when the user asks about handoff freshness, continuity, next-session state, or /archie-handoff.
---

# archie-handoff

1. Locate the repository root.
2. Read ../archie-compat/references/compatibility.md completely.
3. Read .claude/commands/archie-handoff.md completely from the repository root.
4. Treat the source as historical workflow knowledge and apply the compatibility contract.
5. Use the user's remaining request as the workflow arguments.

## Codex override

Read-only: never update either handoff. Validate the Codex handoff first and compare the Claude handoff only when accessible.

Preserve the source's reporting intent and domain knowledge after applying these overrides.

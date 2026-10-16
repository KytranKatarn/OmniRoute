---
name: archie-stats
description: Report available Codex session, Git, and work-state metrics without fabricating Claude usage data. Use when asked for session stats, context state, progress metrics, or /archie-stats.
---

# archie-stats

1. Locate the repository root.
2. Read ../archie-compat/references/compatibility.md completely.
3. Read .claude/commands/archie-stats.md completely from the repository root.
4. Treat the source as historical workflow knowledge and apply the compatibility contract.
5. Use the user's remaining request as the workflow arguments.

## Codex override

Do not estimate Claude plan usage, model, plugin count, or context percentage. Report only observable Codex and Git metrics.

Preserve the source's reporting intent and domain knowledge after applying these overrides.

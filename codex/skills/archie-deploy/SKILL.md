---
name: archie-deploy
description: Plan and perform explicitly authorized A.R.C.H.I.E. deployment verification with preflight, health checks, and rollback gates. Use when the user explicitly asks to deploy, restart, or apply platform changes.
---

# archie-deploy

1. Locate the repository root.
2. Read ../archie-compat/references/compatibility.md completely.
3. Read .claude/skills/archie-deploy/SKILL.md completely from the repository root.
4. Treat the source as historical workflow knowledge and apply the compatibility contract.
5. Use the user's remaining request as the workflow arguments.

## Codex override

The skill invocation alone is not permission to deploy unless the user explicitly asked for deployment. Codex's normal PR path is Repair Bay review followed by human merge.

Preserve the source's reporting intent and domain knowledge after applying these overrides.

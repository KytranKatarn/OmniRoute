---
name: archie-bridge-agent
description: Safely interpret the legacy Claude Bridge-agent creation workflow using current DHQ dispatch and agent-service rules. Use when legacy /archie-bridge-agent guidance is requested.
---

# archie-bridge-agent

1. Locate the repository root.
2. Read ../archie-compat/references/compatibility.md completely.
3. Read .claude/skills/archie-bridge-agent/SKILL.md completely from the repository root.
4. Treat the source as historical workflow knowledge and apply the compatibility contract.
5. Use the user's remaining request as the workflow arguments.

## Codex override

This source is superseded and unsafe. Never use its direct agents INSERT, ai_bridge call, or threading pattern; use archie-agent, archie-patterns, agent_service, and DHQ.

Preserve the source's reporting intent and domain knowledge after applying these overrides.

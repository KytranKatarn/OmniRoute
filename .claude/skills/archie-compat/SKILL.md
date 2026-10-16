---
name: archie-compat
description: Shared compatibility rules for translating A.R.C.H.I.E. Claude Code commands and skills into safe Codex workflows. Use whenever a Codex A.R.C.H.I.E. skill reads a source under .claude, or when adapting Claude memory, MCP, Git, deployment, agent, QA, or session behavior for Codex.
---

# A.R.C.H.I.E. Codex compatibility

Read [references/compatibility.md](references/compatibility.md) completely before applying a
Claude-authored command or skill. Treat the referenced .claude file as historical operational
knowledge and this compatibility contract as the execution-layer override.

For a directly invoked A.R.C.H.I.E. wrapper, follow that wrapper first, then its Claude source.
Use the user's remaining prompt as the source command's arguments.

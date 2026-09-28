---
description: List all loaded Archie Skills (project .claude/skills auto-loaded into opencode) plus opencode's own config skills and commands, with a one-line purpose each. Use when the user asks "what skills", "list skills", "archie skills", "do we have a skill for X", or "what commands".
---

List TWO inventories as one compact table/grouped list:

1. **Project skills** (`.claude/skills/`, already in the `skill` tool): platform ops
   (archie-status, archie-deploy, archie-search, archie-patterns, cluster-architecture…),
   modules, procedures (browser-test, webapp-testing…), tools. One line each:
   name — when to use.
2. **opencode's own config** (`/opencode-home/config/opencode/`):
   - skills: `archie-lane-ship` — ship paths A/B, PR hygiene, Repair Bay verdicts,
     owner-authorized merge, Dev HQ/KB coordination matrix, traps.
   - commands: `/archie-boot`, `/archie-end`, `/archie-save`, `/ship`, `/pr`
     (list/fix/reviews/merge), `/status`, `/qa`, `/sync-lane`, `/skills`,
     `grant-devhq-reads.sh` runner note (host script in `_lane_ship/`).
   - always-loaded guardrails: `GUARDRAILS.md` via `opencode.json` instructions.

End with: how to load a skill (`skill` → name), how to run a command (`/<name>`),
and totals per group. If a user asks about a missing capability, name the closest
match or say plainly there is none.

---
description: Load focused context for a specific module or system — lightweight alternative to /archie-boot when you already know what you're working on. Saves ~15k context tokens vs full boot.
---

# /archie-focus

Follow the procedure in `/mnt/archie_brain/.claude/commands/archie-focus.md`.

That file is written for Claude Code. **Take its reasoning, ordering and gates — not
its keystrokes.** `AGENTS.md` says the same thing: the procedures are plain markdown
and a step may name a tool you do not have.

## Tool mapping for this lane

| Written in the source | Use here |
|---|---|
| `mcp__archie__<tool>` | `archie-kb_<tool>` |
| `mcp__archie_kb__<tool>` | `archie-kb_<tool>` |
| `mcp__Claude_Browser__*`, Playwright / chrome-devtools MCP | available **after an opencode restart**; before that, say so |
| `/model`, `/rewind`, `/clear` | not available |

## Standing rules for this lane

- **Never merge or approve your own PR.** F.O.R.G.E. reviews; a human merges.
  `gh` here is the real CLI and `enforce_admins` is `false`, so nothing mechanically
  prevents a merge — restraint is the only control.
- **Never `git add -A` in `/mnt/archie_brain`.** The live tree is shared and serves
  traffic via bind mount. Stage explicit paths.
- **Never print a secret.** Hash it (`sha256sum`, compare prefixes) instead.
- If a step cannot be done here, **report it rather than skipping the gate.**

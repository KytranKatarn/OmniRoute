---
description: Close out a session — commit scoped files in the lane clone, ship with opencode-pr (push + open the PR), complete Dev HQ tasks, refresh the handover, and print a session report. F.O.R.G.E. reviews; a human merges. Use when the user says "end", "done", "close out", "wrap up".
---

Session close-out for the **guard-free** instance
(`archie_opencode_terminal_gf`, port 17687). A port of Claude's `/archie-end`,
rewritten 2026-09-28 (the guarded lane's version committed in the live tree and
handed the branch to `ship-branch.sh`; neither applies here).

**Never merge or approve your own work** — F.O.R.G.E. reviews, a human merges.

## Step 0: Rate check (informational)
`gh` is **unauthenticated in this image** — `gh api` returns "please run gh auth
login", and `gh-read.sh` does not exist here. Read through the platform container,
which holds a working credential that never leaves it:
```bash
docker exec -i archie_platform python3 -   # script on stdin
```
Do NOT attempt `gh pr merge` or approve anything (the guard refuses, and policy
forbids it).

## Step 1: Finalize the working set
- `cd /work/archie-platform` — your work site (full clone, `origin` = GitHub).
- `git status --short`, be on a feature branch (not `main`), then
  `git add <explicit files>` and `git commit -m "<descriptive>"`. Run
  `git diff --cached --check` — there is no pre-commit here.
- `git -C /mnt/archie_brain status --porcelain | head` — read the owner's live tree
  so you can say what is theirs. Do not stage or commit any of it.

## Step 2: Ship
```bash
opencode-pr "fix(<module>): <what and why>"
```
`/ship` has the full detail. Never ship from `/mnt/archie_brain` — refused by
design. Never merge, never self-approve.

## Step 3: Dev HQ tasks
- `add_task_note` for work completed (done / evidence / remaining).
- `set_task_status` to close finished tasks; `create_task` for follow-ups — search
  existing tasks first, duplicates are a known problem on this platform.
- `get_work_history` / `get_activity_feed` if reconstructing the session. If the
  lane MCP identity is denied, say so plainly instead of inventing a result.

## Step 4: Decisions & memories
- Record architectural choices via project tooling; `search_knowledge` before
  writing, to avoid duplicates.
- One file comes in from the host, read-only: `/host-claude-config/settings.json`
  (that is its path IN this container; on the host it is
  `~/.claude/settings.json`). It is not a place to write, and nothing else from
  the host's `~/.claude` is mounted — do not pretend otherwise.

## Step 5: Refresh the handover
Overwrite `/opencode-home/data/archie-handover.md` with this instance's state:
lane identity, the ship path, live-tree vs lane-clone state (yours vs the
owner's), blockers, next actions. That file is the continuity bridge —
`/archie-boot` reads it and cannot replace it.

## Step 6: Session report
```
## Session Complete
**Instance:** opencode guard-free (127.0.0.1:17687)
**Branch:** <b>  **HEAD:** <sha>  **Files changed:** <count> (scoped: yes/no)
**Shipped via:** opencode-pr (lane PAT)
**PR:** <# / url>
### Completed
- <bullets>
### Decisions Logged
- <ids/titles or "none">
### Owner decisions still open
- <e.g. Dev HQ #7026 branch protection / PAT intent; #7027 GUARDRAILS durability>
### For Next Session
1. <priority>
2. <priority>
3. <priority>
```

## Step 7: Final note
End with: "Session saved. Next session: start with `/archie-boot`." Then stop.

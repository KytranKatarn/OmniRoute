---
description: Mid-session checkpoint — commit scoped files in the lane clone, then ship with opencode-pr (push + open the PR). F.O.R.G.E. reviews; a human merges. Use when the user says "save", "checkpoint", "quick save", "push my work".
---

Mid-session checkpoint for the **guard-free** instance
(`archie_opencode_terminal_gf`, port 17687). A port of Claude's `/archie-save`,
rewritten 2026-09-28: the guarded lane's version committed in the live tree and
handed the branch to `ship-branch.sh`, and **neither step exists here**.

**Never merge or approve your own work** — F.O.R.G.E. reviews, a human merges.

## 1. Look before you touch
- `git -C /work/archie-platform status --short` — **this is your work site**: a full
  clone with `origin` = GitHub. Be on a feature branch, not `main`.
- `git -C /mnt/archie_brain status --porcelain | head` — the owner's live tree,
  shared. Look, do not stage. Never `git add -A` / `git add .` there, and never
  ship from there (`opencode-pr` refuses it by design).

## 2. Commit your scoped set in the clone
```bash
cd /work/archie-platform
git switch -c <type>/<short-desc>      # if on main
git add <explicit file list>            # only yours
git diff --cached --check               # whitespace gate by hand (no pre_commit here)
git commit -m "<what and why>"
```
No secrets, no `.env*`, no infra you don't own.

## 3. Ship
```bash
opencode-pr "fix(<module>): <what and why>"
```
`/ship` has the full detail. It commits anything still uncommitted under that
title, pushes `opencode/*`, and opens the PR. **It never merges.** If a PR already
exists for the branch it says so rather than duplicating. Note: the PR body it
writes claims a scope guard this instance does not have — say so when you report.

If `opencode-pr` fails (missing token, or you are in the live tree), report what
stopped you. Do not fall back to `git push` + a hand-rolled PR.

## Checkpoint report
```
## Session Checkpoint
**Instance:** opencode guard-free (127.0.0.1:17687)
**Branch:** <b>  **Commit:** <sha>  **Files:** <scoped list> (scoped: yes/no)
**Shipped via:** opencode-pr (lane PAT)
**PR:** <# / url>
**In progress:** <what's mid-flight>   **Next:** <what next>
```
Then continue working.

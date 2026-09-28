---
description: Ship this guard-free OpenCode terminal's work as a PR — commit in the lane clone, push an opencode/* branch, open a PR against main. F.O.R.G.E. reviews; a human merges. Use when the user says "ship", "make a PR", "push this".
---

**THIS INSTANCE IS THE GUARD-FREE LANE** (`archie_opencode_terminal_gf`, port
17687). It has no scope guard, but the review boundary is unchanged: **F.O.R.G.E.
reviews, a human merges, and the lane never approves or merges its own work.**
Never `gh pr merge`. Never approve your own PR.

This file was rewritten 2026-09-28. The previous version (kept at
`ship.md.guard-bak`) was a verbatim copy of the guarded lane's and sent work
through `/opencode-home/bin/ship-branch.sh` after committing in
`/mnt/archie_brain`. **Neither applies here:** that script does not exist in this
image, and `opencode-pr` — the one that does — *refuses* to run in the live tree.

## The two trees, and which one you ship from

| | `/work/archie-platform` (lane clone) | `/mnt/archie_brain` (owner's live tree) |
|---|---|---|
| what it is | full clone of `KytranKatarn/archie-platform`, `origin` = GitHub, `main` in sync | the served platform checkout, shared with Claude/owner |
| **ship from here** | **YES — the only place** | **NO — refused by `opencode-pr`** |
| edit to serve a change | no; code reaches the platform after merge | yes; a platform edit is served on the next request |
| git identity / hooks | configured; `core.hooksPath=/opt/no-guard` (no scope gate here, by design) | the owner's own hooks — do not touch |

`opencode-pr` refuses the live tree for two measured reasons: it runs
`git add -A` (an untracked `.oc-lane-test/`, a full `platform_v2` copy, was once
swept into a lane commit that way on 2026-09-13), and the live tree's
`core.hooksPath` points at its own `.git/hooks`, not a lane guard. The rule is
structural, not a preference: **work and ship in the clone.**

## Step 1 — commit in the lane clone
```bash
cd /work/archie-platform
git fetch origin && git status --short            # expect clean
git switch -c <type>/<short-desc>                  # never work on main
# ...edit...
git add <explicit files>
git diff --cached --check                          # whitespace gate, run by hand
git commit -m "<what and why>"
```
This lane has no `pre_commit` module, so if a hook misbehaves commit with
`--no-verify` and run the gate yourself. `opencode-pr` will commit anything still
uncommitted for you, so an explicit commit here is what keeps the message honest.

## Step 2 — ship
```bash
opencode-pr "fix(<module>): <what and why>"
```
One argument: the PR title. `opencode-pr` reads the branch you are on, commits
any pending work under that title, pushes `opencode/*`, and opens the PR against
`main` (python `urllib`; this image has no `curl`). It carves an
`opencode/<slug>-<epoch>` branch if you are on `main`, refuses any branch not
starting with `opencode/`, and **never merges**. If a PR already exists for the
branch it reports that instead of duplicating.

**Known wart — do not repeat its claim as fact:** the PR body it writes says
"Scope-guarded to allowed Applications/Concepts paths". **That is false in this
instance** — there is no scope gate here. Say so when you report the PR.

## Step 3 — report
```
## Shipped
**Instance:** opencode guard-free (127.0.0.1:17687)
**Branch:** <b>  **Commit:** <sha>  **Files:** <scoped list>
**PR:** <# / url>
**State it out loud:** the PR body claims a scope guard this instance does not have.
**Next:** F.O.R.G.E. review → human merge (the lane does neither)
```

## If shipping is blocked
`opencode-pr` exits 1 when `/run/secrets/opencode_github_token` is missing, and
refuses when you are in `/mnt/archie_brain`. Neither is a reason to `git push` and
hand-roll a PR: report what stopped you and what the owner must decide. The token
being mounted here is itself **unconfirmed owner intent** (Dev HQ #7026 — branch
protection on `main` is unverifiable from this host, and "PR: write" also permits
merging). Working is not the same as approved.

---
description: Close out a session — commit scoped files to a branch in the live tree, hand the branch to F.O.R.G.E./Repair Bay to push + open the PR, complete Dev HQ tasks, and print a session report. The lane never pushes with its own git and never merges. Use when the user says "end", "done", "close out", "wrap up".
---

opencode is host-direct on `/mnt/archie_brain` and ships **through F.O.R.G.E./Repair Bay** (the host runner holds the GitHub token; a token is ALSO mounted here read-only — which is exactly why you must not push). This is a port of Claude's `/archie-end`.

**Never merge or approve your own work** — F.O.R.G.E. reviews, a human merges.

## Step 0: Rate check (informational)
- `gh api /rate_limit` — read-only, allowed. Do NOT attempt `gh pr merge`/approve (guard refuses; policy forbids).

## Step 1: Finalize the working set
- `git -C /work/archie-platform status --porcelain` — list changes; **stage only this session's files** (never blanket `git add -A`; this clone is shared with every other session on this lane). Anything you did not write this session is not yours to commit.
- Ensure you are on a feature branch, not `main`.
- `git -C /work/archie-platform add <explicit files>` then `git commit -m "<descriptive>"`.
  This is your lane clone. Never stage in `/mnt/archie_brain`.
- **Do NOT `git push`.** A token is mounted at `/run/secrets/opencode_github_token`, so a
  push WOULD succeed — and would bypass the host's scope check. Not pushing is the point.

## Step 2 — Hand the branch to the host runner (this lane does NOT ship)
This lane has no shipping helper: `/opencode-home/bin/` was never copied into this
container, so `ship-branch.sh` and `gh-read.sh` do not exist here, and
`opencode-pr` is not installed either. `gh` is a refusal wrapper, not a client.
**Do not improvise around that** — never `git push`, and never commit in
`/mnt/archie_brain` (that is the OWNER's live tree).

Supported path — the host runner stages your work, scope-checks it, runs the real
tests and opens the PR:

1. Leave the work **committed in the lane clone** `/work/archie-platform`, on a feature branch,
   with an explicit `git add` of only your files. Never `git add -A`.
2. `git -C /work/archie-platform diff --cached --check` (this lane has no pre-commit; run it).
3. Report exactly: `"committed on <branch> in /work/archie-platform — host runner ships (no push from the lane)."`
4. The host runs `scripts/agents/run-opencode-task.sh`. If it rejects the diff,
   the fix returns to you as a task.

**Owner-click fallback:** if the host runner cannot be reached, stop and say
*"committed on `<branch>` — owner: Repair Bay → Pushes → Create PR."* Never
substitute `git push`.

## Step 3: Dev HQ tasks
- `add_task_note` for work completed (done / evidence / remaining).
- `set_task_status` to close finished tasks; `create_task` for follow-ups (search existing tasks first — duplicates are a known problem).
- `get_work_history` / `get_activity_feed` if reconstructing the session.

## Step 4: Decisions & memories
- Record architectural choices via project tooling; `search_knowledge` before writing to avoid duplicates. Host `~/.claude` is not reachable — do not pretend to write it.

## Step 5: Session report
```
## Session Complete
**Lane:** opencode — seeded lane clone at `/work/archie-platform`; the host runner ships
**Branch:** <b>  **HEAD:** <sha>  **Files changed:** <count> (scoped: yes/no)
**Shipped via:** F.O.R.G.E./Repair Bay (platform token)
**PR:** <# / status, or "handed off — owner clicks Create PR">
### Completed
- <bullets>
### Decisions Logged
- <ids/titles or "none">
### For Next Session
1. <priority>
2. <priority>
3. <priority>
```

## Step 6: Final note
End with: "Session saved. Next session: start with `/archie-boot`." Then stop.
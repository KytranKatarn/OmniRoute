---
description: Mid-session checkpoint — commit scoped files to a branch in the live tree, then hand the branch to F.O.R.G.E./Repair Bay to push and open the PR. The lane never pushes with its own git and never merges. Use when the user says "save", "checkpoint", "quick save", "push my work".
---

This opencode lane works in a **seeded clone at `/work/archie-platform`** and ships **through the host
runner**, not by itself. A GitHub token IS mounted here read-only, so the discipline
that matters is: commit locally, never push. This is a port of Claude's `/archie-save`.

**Never merge or approve your own work** — F.O.R.G.E. reviews, a human merges.

## 1. See the tree before touching it
- `git -C /mnt/archie_brain status --porcelain` — the live tree carries the owner's in-progress work. **Stage ONLY this session's files**; never `git add -A` / `git add .` here.
- Be on a feature branch, not `main`. If on `main`, `git switch -c <type>/<short-desc>` first.

## 2. Commit your scoped set
- `git -C /work/archie-platform add <explicit file list>` (only yours), then commit with a
  descriptive message. This is YOUR lane clone — not the owner's live tree at
  `/mnt/archie_brain`. No secrets / `.env*` / infra you don't own.
- **Do NOT `git push`** — a token IS mounted at `/run/secrets/opencode_github_token`,
  so a push would succeed and bypass the host's scope check. Not pushing is the
  point, not a limitation. Commit locally; the host runner ships.

## Step 3 — Hand the branch to the host runner (this lane does NOT ship)
This lane has no shipping helper: `/opencode-home/bin/` was never copied into this
container, so `ship-branch.sh` and `gh-read.sh` do not exist here, and `opencode-pr`
is not installed either. `gh` exists only as a refusal wrapper. **Do not improvise
around that** — in particular, never `git push`, and never commit in
`/mnt/archie_brain` (that is the OWNER's live tree; `opencode-pr` refuses it for
exactly that reason).

The supported path is the host runner, which stages your work, runs the scope
check and the real tests, and opens the PR:

1. Leave your work **committed in the lane clone** `/work/archie-platform`, on a
   feature branch, explicit `git add` of only your files. Never `git add -A`.
2. Run the gates you can run: `git -C /work/archie-platform diff --cached --check`.
3. Report exactly this and stop:
   `"committed on <branch> in /work/archie-platform — host runner ships (no push from the lane)."`
4. The host runs `scripts/agents/run-opencode-task.sh`, which scope-checks, tests
   and opens the PR. If it rejects the diff, the fix comes back to you as a task.

**Owner-click fallback:** if the host runner cannot be reached, stop and say
*"committed on `<branch>` — owner: Repair Bay → Pushes → Create PR."* Never
substitute `git push`.

## 4. Continuity
- `add_task_note` on the in-flight Dev HQ task (done / remaining). Closed tasks need a note.
- Record decisions via archie_kb tools; `search_knowledge` first to avoid duplicates. Host `~/.claude` memory is not reachable — do not claim to write it.

## 5. Report
```
## Session Checkpoint
**Lane:** opencode — host-direct (/mnt/archie_brain)
**Branch:** <b>  **Commit:** <sha>  **Files:** <scoped: yes/no>
**Shipped via:** F.O.R.G.E./Repair Bay (platform token)
**PR:** <# / url, or "handed off — owner clicks Create PR">
**In progress:** <what's mid-flight>   **Next:** <what next>
```
Then continue working.
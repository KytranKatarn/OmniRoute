---
description: Commit this lane's work and hand it to the host runner, which scope-checks, tests and opens the PR.
---

# /ship — hand a branch to the host runner

This lane **does not ship its own work.** It commits, then stops. The host runner
(`scripts/agents/run-opencode-task.sh`) stages what changed, runs the scope check
and the real tests in a throwaway container, and opens the PR. Your job ends at
"the edit is on disk and correct".

**Never `git push`.** A GitHub token *is* mounted at
`/run/secrets/opencode_github_token`, so a push would succeed — and would skip the
scope check entirely. Not pushing is the whole point; it is not a limitation you
are working around.

**Never commit in `/mnt/archie_brain`.** That is the owner's live tree, carrying
their in-progress work. Your work tree is the seeded clone at
`/work/archie-platform`.

## Step 1 — Commit in the lane clone

```bash
git -C /work/archie-platform status --porcelain      # what is mine?
git -C /work/archie-platform rev-parse --abbrev-ref HEAD
git -C /work/archie-platform switch -c <type>/<short-desc>   # if on main
git -C /work/archie-platform add <explicit files>     # NEVER -A or .
git -C /work/archie-platform diff --cached --check    # no pre-commit in this lane
git -C /work/archie-platform commit -m "<descriptive message>"
```

- Stage **only this session's files.** This clone is shared across every session on
  this lane; anything you did not write this session is not yours to commit.
- Never commit to `main`. Branch names are `opencode/*` or `<type>/<short-desc>`.
- The lane's own gate is `git diff --cached --check` (whitespace + conflict
  markers). There is no pre-commit hook here; run it yourself and read the output.
- If the scope guard is armed (`core.hooksPath=/opt/lane-guard`), note that it
  guards *pushes*. You are not pushing, so expect no feedback from it — the host
  runner is what enforces scope.

## Step 2 — Report, and stop

Report exactly this shape and end the turn:

```
committed on <branch> in /work/archie-platform — host runner ships (no push from the lane).
<what changed, and why, in one or two sentences>
<gates you ran and their result>
```

Do not attempt the push yourself, and do not describe the work as shipped until
the host has confirmed a PR number.

## Why there is no `ship-branch.sh` here

`/opencode-home/bin/` **does not exist in a seeded lane** — it is created for the canonical opencode lane only. A seeded
lane has no `ship-branch.sh`, no `opencode-pr`, and a `gh` that exists solely to
refuse merge and auth calls. If a document you are reading tells you to run one of
those, it belongs to a different lane — stop and say so rather than improvising.
`opencode-pr` also refuses `/mnt/archie_brain` by design, and correctly so.

## If the host runner cannot be reached

Stop and tell the owner: *"committed on `<branch>` — owner: Repair Bay → Pushes →
Create PR."* Do not substitute `git push`, and do not try to drive the platform
container's GitHub functions yourself to route around the runner.

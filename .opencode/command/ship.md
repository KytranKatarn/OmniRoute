---
description: Ship work from the opencode host-parallel lane — branch in a worktree, stage explicit paths, survive a reformatting pre-commit hook, open a PR, and register it with Repair Bay. Never merges.
---

# /ship — opencode host-parallel lane

Written from the procedure actually used on 2026-09-30, not adapted from the container
lane. This lane works in `/mnt/archie_brain` directly and **can** push; it has no
`opencode-pr` and no `/work/archie-platform`, and does not need them.

## The two things this lane gets wrong most easily

1. **`git add -A` in the live tree.** `/mnt/archie_brain` is shared with Claude/owner
   *and* bind-mounted into running containers, so a stray `add -A` sweeps someone
   else's in-progress work into your commit — and serves it live. Stage explicit paths.
2. **Building PR branches in the live checkout.** The live tree must stay on `main`,
   because `archie_platform` bind-mounts it. Use a separate worktree.

## Procedure

### 1. Confirm the baseline

```bash
cd /mnt/archie_brain
git fetch -q origin
git status --porcelain          # anything dirty here may not be yours
git rev-parse --abbrev-ref HEAD # should be main
```

If the tree is dirty, **identify which files are yours** before going near `git add`.
Anything you did not write, do not stage.

### 2. Branch in a throwaway worktree

```bash
WT=/home/kytran/.cache/opencode/tmp/opencode/ship-wt
rm -rf "$WT"
git worktree add --detach "$WT" origin/main
cd "$WT" && git checkout -b <type>/<short-slug>
```

### 3. Apply only your change

Prefer `git cherry-pick <sha>` when the work already exists as a commit — it
preserves authorship and message. If a commit bundles unrelated concerns, cherry-pick
it and then `git checkout origin/main -- <the unrelated path>` and
`git commit --amend --no-edit`.

Otherwise `git checkout <branch> -- <explicit paths>`.

### 4. Verify before you commit

```bash
git diff --name-only origin/main...HEAD   # exactly the files you intend
```

For shell: `bash -n` every script. For file modes, compare against the source branch —
`git ls-tree HEAD -- <path>` vs the original. A `chmod +x` that silently did not
record is a recurring failure here; prefer `git update-index --chmod=+x`.

### 5. Commit — and expect the hook to reject the first attempt

`pre-commit` runs the **pinned** `black 24.4.2` with `--line-length=120`. If it
reformats, the commit **fails** — that is normal, not an error to debug. Re-stage the
reformatted file and commit again.

Do **not** pre-format with the host's `black` (currently 26.x); it disagrees with the
pinned version on untouched lines and you will fight it. Let the hook decide.

Never `--amend` a commit the hook rejected — make a new one.

```bash
git add <explicit paths>
git commit -F - <<'EOF'
<why the change, not what the diff says>
EOF
```

A commit message earns its place by recording the **cause**, especially where the
symptom pointed somewhere else than the defect.

### 6. Push and open the PR

```bash
git push -u origin <branch>
gh pr create --base main --head <branch> --title "..." --body "..."
```

The body should carry: what changed, the root cause where it was not obvious, how it
was verified **through the running process**, what is deliberately still unfixed, and
any deploy ordering the reviewer needs.

If the branch bundles genuinely unrelated concerns, **split it** — and pull a
security-boundary change into its own PR with a title that says it needs a decision.

### 7. Register with Repair Bay

So F.O.R.G.E. picks it up for review.

### 8. Stop

**Never merge. Never approve your own PR.** Report the PR URL and hand off.

```bash
gh pr view <n> --json state,mergeStateStatus,reviewDecision
```

## Deploy is a separate step, and it is not a merge

A merge changes nothing running until the image is rebuilt. This repo's containers
`COPY` their code, so:

```bash
docker compose build <service>        # image only — does NOT touch running containers
docker compose up -d --no-deps <svc>  # recreate just this service
```

Two traps that produce false greens:

- A service built `FROM` another service's image inherits that image's code. Rebuilding
  only the leaf rebuilds on the same stale base and **serves old code while looking
  healthy**. Rebuild the base first.
- `docker compose up -d` will not recreate a container whose image ID is unchanged.
  Compare a hash of the file inside the container against the commit before declaring
  a deploy landed.

Verify through the running process, never by reading the file.

## Rollback

Record the outgoing image ID before recreating anything:

```bash
docker inspect -f '{{.Image}}' <container>
```

## Ship when

Nothing is half-done, tests pass, the diff is scoped to intent, and the commit says
why. If a step could not be completed, say which and why — a clear report beats a
plausible guess, and both lanes have been measured getting that wrong.

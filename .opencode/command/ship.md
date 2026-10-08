---
description: Ship work from the opencode host-parallel lane — branch in a worktree, stage explicit paths, survive a reformatting pre-commit hook, open a PR, and register it with Repair Bay. Never merges.
---

# /ship — opencode host-parallel lane

Written from the procedure actually used on 2026-09-30, not adapted from the container
lane. This lane works in `/mnt/archie_brain` directly and **can** push; it has no
`opencode-pr` and no `/work/archie-platform`, and does not need them.

## The three things this lane gets wrong most easily

1. **`git add -A` in the live tree.** `/mnt/archie_brain` is shared with Claude/owner
   *and* bind-mounted into running containers, so a stray `add -A` sweeps someone
   else's in-progress work into your commit — and serves it live. Stage explicit paths.
2. **Building PR branches in the live checkout.** The live tree must stay on `main`,
   because `archie_platform` bind-mounts it. Use a separate worktree.
3. **Assuming the shell remembers where you were.** Tool calls do NOT share cwd —
   a `cd` in one call is gone by the next, back to the default workdir. Every git
   command below must run as a **single self-contained chain starting with its own
   `cd`**; never `cd` in one call and `git` in the next. On 2026-10-08 a bare
   `git add`/`git commit` issued after a `cd` in an *earlier* call landed the commit
   on the live tree's `main` — recovered with `git reset --soft HEAD~1` only after
   verifying the commit held exactly the intended file and its parent was
   `origin/main`. Check that same way if it ever happens: reflog, `git show --stat`,
   parent vs `origin/main`, then soft-reset. Never `--hard` — the tree carries other
   people's uncommitted work.

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
cd /mnt/archie_brain && WT=/home/kytran/.cache/opencode/tmp/opencode/ship-wt \
  && rm -rf "$WT" && git worktree add --detach "$WT" origin/main \
  && cd "$WT" && git checkout -b <type>/<short-slug>
```

If `git worktree add` fails with *missing but already registered*: run
`git -C /mnt/archie_brain worktree prune` and retry — a previous ship's worktree
directory was deleted without deregistering.

### 3. Apply only your change

Prefer `git cherry-pick <sha>` when the work already exists as a commit — it
preserves authorship and message. If a commit bundles unrelated concerns, cherry-pick
it and then `git checkout origin/main -- <the unrelated path>` and
`git commit --amend --no-edit`.

Otherwise `git checkout <branch> -- <explicit paths>`.

### 4. Verify before you commit

```bash
cd "$WT" && git diff --name-only origin/main...HEAD   # exactly the files you intend
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

Gate-check without committing: `pre-commit run --files <your paths>` runs the same
pinned hooks (no stash, no side effects) — that, not host `black`/`flake8`, is the
authoritative pre-commit result.

Never `--amend` a commit the hook rejected — make a new one.

```bash
cd "$WT" && git add <explicit paths> && git commit -F - <<'EOF'
<why the change, not what the diff says>
EOF
```

A commit message earns its place by recording the **cause**, especially where the
symptom pointed somewhere else than the defect.

### 6. Push and open the PR

```bash
cd "$WT" && git push -u origin <branch>
cd "$WT" && gh pr create --base main --head <branch> --title "..." --body "..."
```

The body should carry: what changed, the root cause where it was not obvious, how it
was verified **through the running process**, what is deliberately still unfixed, and
any deploy ordering the reviewer needs.

If the branch bundles genuinely unrelated concerns, **split it** — and pull a
security-boundary change into its own PR with a title that says it needs a decision.

### 7. Register with Repair Bay

So F.O.R.G.E. picks it up for review. There is no helper command — run this
(inside the platform container, where the service and its DB access live):

```bash
docker exec archie_platform python3 -c "
import sys; sys.path.insert(0, '/app')
from tools.repair_bay.services.pr_review_service import poll_open_prs, get_review
p = poll_open_prs()
print('POLL:', {k: p[k] for k in ('tracked','inserted','updated','errors') if k in p})
r = get_review(<PR-NUMBER>) or {}
print('STATUS:', r.get('review_status'))
"
```

`inserted: 1` + `STATUS: pending` = registered; F.O.R.G.E. picks it up on its next
pass. The row moves `pending → in_progress → reviewed` on its own — a row stuck
`in_progress` self-heals through the 20-minute retry/reap cycle, so wait rather
than poking its bookkeeping.

### 8. Stop

**Never merge. Never approve your own PR.** Report the PR URL and hand off.

```bash
gh pr view <n> --json state,mergeStateStatus,reviewDecision
```

Reading the verdict: F.O.R.G.E. writes `ai_summary` (what `merge_state` reads).
A `NEEDS REVIEW` summary that says *"0/1 files read in full"* is the known
fail-closed chunked-review gap (#6822/#6247) — read the summary body for the
actual findings instead of treating it as a clean reject. Also check
`metadata->>'reviewed_head_sha'` matches your PR's head commit; a mismatch means
the verdict predates your last push and is stale.

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

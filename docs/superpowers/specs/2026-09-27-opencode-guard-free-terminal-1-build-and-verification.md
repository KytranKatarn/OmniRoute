# Opencode guard-free terminal — spec, part 1 of 4: Build, verification, and rollback

**Part 1 of 4.** Index, status and Goal: [2026-09-27-opencode-guard-free-terminal](2026-09-27-opencode-guard-free-terminal.md). Next: [part 2](2026-09-27-opencode-guard-free-terminal-2-decisions-and-inspection.md).

---

## Enforcement surfaces, as verified 2026-09-27

There are **four**, not one. Two are the scope guard; two are the shipping workflow.

| # | Surface | What it does | Remove? |
|---|---------|--------------|---------|
| 1 | `/opt/lane-guard/pre-push` (5043 b) | Scope-checks every changed file vs `origin/main`; fails CLOSED | **yes** |
| 2 | `/opt/lane-guard/allowlist.yaml` (3767 b) | The allowlist, read from baked `CODEX_ALLOWLIST_FILE` | **yes** |
| 3 | `/usr/local/bin/opencode-pr` | Commits, pushes `opencode/*`, opens PR. "NEVER merges" | **no** — keep |
| 4 | `/usr/local/bin/gh` | Blocks merge/auth actions from inside the lane | **keep** |

Arming is one place only — `start.sh:89`:

> ⚠️ **The two blocks below are BEFORE and AFTER, not two live states.** The first
> is what the **guarded** image ships; the second is what the **guard-free** image
> ships after the substitution. Read either one alone and you will conclude the
> wrong thing about the other — in particular, the `"scope guard armed"` string in
> the first block is text that is REPLACED, never text the guard-free build runs.
> F.O.R.G.E. raised exactly that false positive on 2026-09-28 (a CRITICAL, "start.sh
> still logs as if scope guard were armed"), from a partial read of this file. It
> is recorded as a dismissed finding with the measurement: in the running
> guard-free container, `/start.sh` line 90 reads
> `"[opencode] scope guard DISABLED (guard-free build)"`. Do not "fix" `start.sh`
> to satisfy that finding — the runtime is already correct.

**BEFORE — the guarded image, unchanged:**

```sh
git -C /work/archie-platform config core.hooksPath /opt/lane-guard 2>/dev/null \
    && echo "[opencode] scope guard armed on the lane clone (opencode/* branches only)" >&2 \
    || echo "[opencode] WARNING: could not arm the scope guard — pushes are unprotected" >&2
```

**AFTER — the guard-free image, what actually runs:**

```sh
git -C /work/archie-platform config core.hooksPath /opt/no-guard 2>/dev/null \
    && echo "[opencode] scope guard DISABLED (guard-free build) (opencode/* branches only)" >&2 \
    || echo "[opencode] INFO: guard-free build, no scope guard — pushes are unprotected" >&2
```

`start.sh` contains **no write-gating of any kind**. The guard is push-time only.
`/mnt/archie_brain` was never armed — it uses the repo's own `.git/hooks/pre-push`,
which is only a warning box for `main`/`develop`.

## Dockerfile

Derived, so `archie_brain-archie_opencode_terminal:latest` is untouched. Additive,
same as the second instance.

```dockerfile
FROM archie_brain-archie_opencode_terminal:latest
USER root
# Repoint the arming at an empty dir instead of removing the block: git runs no hook
# when hooksPath holds no hook file, so this is guard-free without surgery on a
# multi-line shell continuation.
RUN mkdir -p /opt/no-guard \
 && rm -rf /opt/lane-guard \
 && sed -i 's|/opt/lane-guard|/opt/no-guard|g' /start.sh
# The substitution leaves two log lines that now say the opposite of what happened.
# A misleading message in a security control is its own defect — fix the wording.
RUN sed -i 's|scope guard armed on the lane clone|scope guard DISABLED (guard-free build)|' /start.sh \
 && sed -i 's|WARNING: could not arm the scope guard|INFO: guard-free build, no scope guard|' /start.sh
ENV CODEX_ALLOWLIST_FILE=""
```

Validated 2026-09-27 against `archie_brain-archie_opencode_terminal:latest`: the
`/opt/lane-guard` → `/opt/no-guard` substitution removes every reference, deletes the
payload, and leaves `/start.sh` parsing as valid `sh`. The two log-line fixes above
were added *because* that validation showed them still claiming "scope guard armed".

One string substitution, no brace-matching, no dependence on line numbers. The
`ENV` is belt-and-braces: the allowlist file is already gone, so the variable would
point at nothing, but leaving a live-looking var invites confusion.

**What `/opt/no-guard` is FOR, since it looks like dead code and is not:** it is
an empty directory that stands in for the guard as the lane's
`core.hooksPath` target. `/start.sh` is sed-repointed at it so the config value
still resolves to a real directory instead of a dangling path. Three things read
it: `lane_flavor()` returns `guardfree` when `core.hooksPath` is exactly
`/opt/no-guard` (so the two-flavour doc install picks the right set, and an
unknown path installs nothing rather than guessing); `--verify` asserts the
directory exists **and is empty**, so a hook cannot be quietly added to a
lane that has no guard; and nothing ever executes from it. It is a marker plus a
valid hooks path, not a disabled guard.

## Verification

Follows the `grant_opencode_dispatch_scope.py --verify` convention: prove, don't
assume. Every assertion must pass or the image is not used.

```sh
docker run --rm --entrypoint sh <image> -c '
  test ! -e /opt/lane-guard                    || { echo "FAIL: guard payload present"; exit 1; }
  ! grep -q "lane-guard" /start.sh             || { echo "FAIL: start.sh still arms it"; exit 1; }
  echo "PASS: guard absent and unreferenced"
'
```

Then, on a live container:

```sh
git -C /work/archie-platform config --get core.hooksPath   # expect /opt/no-guard
test -f /work/archie-platform/.git/hooks/pre-push           # expect absent
# decisive test: push a change to a normally-blocked path on an opencode/* branch.
# It must succeed. If it does not, the guard is still live somewhere.
```

The last one is the test that counts. The others can all pass while something else
is enforcing.

## What remains after this

- `pre-commit` — runs in the repo, lane-agnostic
- F.O.R.G.E. review — Repair Bay, independent of the lane
- **GitHub branch protection** — the real merge stop. `opencode-pr`'s own header
  notes its PAT carries "Pull requests: write", which is indivisible and therefore
  permits merging. Only `required_approving_review_count` on `main` prevents that.
  Verify it is set; it is the control this spec leans on.

Losing the lane guard means losing *early local feedback* on out-of-scope changes.
It does not mean losing review or merge control.

## Rollback

`docker rm -f` the guard-free instance. The base image and the two running
instances are untouched by construction.

# Opencode guard-free terminal — spec, part 4 of 4: The guarded lane needed the same treatment

**Part 4 of 4.** Index, status and Goal: [2026-09-27-opencode-guard-free-terminal](2026-09-27-opencode-guard-free-terminal.md). This is the last part.

---

## Gap 4 (CLOSED) — the guarded lane needed the same treatment, and it is a different set

Owner decision 2026-09-28: fix `archie_opencode_terminal_host` (17686) the same way.
Its breakage looked identical — 9 referenced paths missing — and was materially
worse underneath. Its documents were not merely pointing at an absent helper:

* they said the work tree is **`/mnt/archie_brain`**, i.e. the OWNER's live tree, and
  told the agent to branch and commit there;
* they said *"the lane has no credential"* — false: the token is mounted, so a
  `git push` would succeed and skip the host's scope check;
* they named `ship-branch.sh`, `opencode-pr`-equivalent helpers and `gh-read.sh`,
  none of which exist in a seeded container, because `/opencode-home/bin/` is only
  ever populated for the canonical lane.

So two sets are now tracked, because the correct answer is genuinely different:

| | guarded (`opencode_guarded_lane_docs/`) | guard-free (`opencode_guardfree_lane_docs/`) |
|---|---|---|
| scope guard | armed; `allowed_paths` is real | none by design |
| commit in | `/work/archie-platform` | `/work/archie-platform` |
| ships by | **the host runner** (`run-opencode-task.sh`) — the lane never pushes | `opencode-pr`, which refuses `/mnt/archie_brain` |
| why | no shipping helper is installed in the container | it must self-ship, and is allowed to |

Blending them would either promise a guard the unrestricted lane does not have, or
send the guarded lane to a helper it cannot reach. `lane_flavor()` reads
`core.hooksPath` to decide (`/opt/lane-guard` vs `/opt/no-guard`) rather than
inferring from a container name, and **installs nothing** when it cannot tell —
guessing here would strip a guarded lane's rules or hand an unrestricted one a
ruleset it must not have.

### The installer could not correct its own past output

Found immediately after shipping the first version. `plan_doc_install` recognised
exactly two overwritable states: "matches the seed" and "matches the tracked copy".
Once it had installed a file, that file matched neither — so on the next run it was
reported as *"edited by a human — left as-is"*, forever. The safety rule was
protecting me from myself.

Fixed with `MANIFEST_DST = /opencode-home/data/.lane_docs_installed.json`: a map of
relpath → sha256 of what this installer last wrote. A file matching its own recorded
hash is *ours*, and safe to upgrade. So the five states are now: absent → create;
matches tracked → already; matches seed → install; **matches our manifest → install
(upgrade)**; anything else → leave alone and say so. The manifest holds hashes
only, never content.

Proven on the live guarded lane, all four: clean install of a seeded file; idempotent
re-run (15 already); upgrade of a file the installer itself wrote after the tracked
copy changed; and a hand-edit still refused with a warning.

### Two of my own checks were wrong before the documents were

Worth recording, because both had already been reported as findings:

* `ship-<name>.sh` was reported as a missing path. The path is a *template*; the
  per-batch script is created on the host. A `<placeholder>` is a shape, not a file,
  and asking "does `/…/ship-` exist?" was my error, reported as a fact. Placeholders
  are now skipped.
* The disclaimer filter matched only `does not exist`, so it flagged my own
  corrected files, which say "do not exist" and "is absent". Widened to the
  phrasings actually used — and **suppression is now printed**, because a check
  whose quiet mode is invisible is a check you cannot audit.

Third instance in this file of the same root cause: something I wrote to detect a
problem was itself generating false ones, and each time the fix was to make it test
reality (existence, hashes, measured state) rather than to guess at intent.

### Gap 5 (CLOSED) — correct, but not repeatable

`install_lane_docs()` was only ever called from `--apply`, and `--apply` refuses
protected lanes. So 17686's corrected instructions were correct **once**, by hand,
and nothing could put them back: wipe that volume and the lane is straight back to
naming `/mnt/archie_brain` and claiming it has no credential. Correct-but-not-
repeatable is the same defect as never-fixed, one step later.

`--repair-docs NAME` closes it, with a deliberately smaller blast radius than
`--apply`, because a protected lane is the owner's:

* creates no container, stops none, replaces none, builds no image, deletes no volume;
* **refused on the source container** — that container's files *are* the baseline
  this installer compares against, so "repairing" it would overwrite the owner's
  own documents with our idea of them. This is the hazard a `start.sh` boot hook
  would have walked straight into, since canonical 17685 is both the source and a
  `guarded`-flavoured lane;
* refused when the container is absent or stopped — it repairs files, it does not
  manage containers;
* refused when `core.hooksPath` cannot be read, rather than guessing a set;
* per-file safety unchanged, so an edited-after-seeding file is still left alone.

All four refusals and both happy paths exercised live. Canonical 17685 afterwards
verified pristine: no manifest, `ship.md` still the original.

**What this does NOT solve, stated plainly:** a fully wiped protected-lane volume.
The docs ride in the lane's clone, so the repeatable path is
`git pull` inside the lane then `--repair-docs`. Re-seeding a protected lane from
nothing involves choosing its image and its guard, which is an owner decision, not
something this script should decide by default.

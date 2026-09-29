# Opencode guard-free terminal — spec, part 3 of 4: Lane instructions: the same defect, second surface

**Part 3 of 4.** Index, status and Goal: [2026-09-27-opencode-guard-free-terminal](2026-09-27-opencode-guard-free-terminal.md). Next: [part 4](2026-09-27-opencode-guard-free-terminal-4-guarded-lane.md).

---

## Lane instructions — the same defect, second surface (2026-09-28)

Gap 2 above was `GUARDRAILS.md`. Fixing it turned up a bigger instance of the same
thing, and the cause is one line of code.

**Root cause:** `seed_config()` tars `config/opencode` out of a source container
and untars it into the target. It never copies `bin/`. So every seeded instance
receives the source lane's *entire* command and skill tree while the helpers those
files invoke are absent. Measured on the live guard-free instance, 5 files plus
`GUARDRAILS.md` told the agent to:

1. commit in `/mnt/archie_brain`, then
2. ship with `bash /opencode-home/bin/ship-branch.sh` — which does not exist.

The second step fails outright. Worse, the two trees are not interchangeable:
`opencode-pr`, the one ship primitive a seeded instance *does* have, **refuses**
`/mnt/archie_brain` by design (`opencode-pr:54`) — it runs `git add -A`, and an
untracked `platform_v2` copy was once swept into a lane commit that way on
2026-09-13. So the seeded instructions walked the agent to the single tree where
shipping is rejected. Verified live: the refusal fires and exits 1, live tree
unchanged.

**Not fixed by copying `bin/`.** `ship-branch.sh` ships the *owner's* live tree,
which is exactly what this lane must never push from. Making it reachable would
turn a missing file into a dangerous one. The command tree has to be rewritten per
instance, so:

- `check_lane_instructions()` now runs after every `--apply` and reports referenced
  paths that do not exist in the container, with `file:line`. It checks
  *existence*, not intent: the first version grepped for the helper's name and
  flagged the corrected files, which mention it only to say it is absent — a check
  that fires on correct work trains you to ignore it. Now: gf → clean, the
  untouched instance → 9 real breakages. Advisory, never fatal; broken docs must
  not block a terminal that otherwise works.
- The guard-free instance's `command/{ship,archie-save,archie-end,archie-boot,
  sync-lane}.md` and both ship/repair skills were rewritten in place (originals at
  `*.guard-bak`) to the one true path: work in `/work/archie-platform`, ship with
  `opencode-pr "<title>"`. Its handover was also missing — `/archie-boot` requires
  `/opencode-home/data/archie-handover.md` and there was no such file, so boot had
  no continuity bridge. Seeded with this instance's own state.

**Found in a second live instance, not fixed there:** `archie_opencode_terminal_host`
(17686, `LANE_NAME=opencode-host`) has the same 9 breakages *and* no handover. Its
`/work` was also empty, so it booted with no repo at all — seeded on 2026-09-28
(via this script's `seed_clone`, so its pre-push guard armed normally on the next
boot: `core.hooksPath=/opt/lane-guard`, `main` @ `e318e3db1` = `origin/main`). Its
documents were left alone: that lane's purpose and owner are not this spec's call,
and its instruction set needs a *guarded*-lane rewrite, not this one's. Listed by
`check_lane_instructions()` for whoever owns it.

**Durability — unchanged from gap 2.** These corrections live in a volume. No
tracked file owns them, so an image rebuild reverts them, and the same root cause
(`seed_config` copying one lane's documents into another) will recur on the next
`--apply`. The fix is a `GUARDRAILS.md` + command tree in the repo, `COPY`ed by the
image the way `opencode-pr.sh` already is — owner-owned, `opencode/` being outside
this lane's `allowed_paths` (Dev HQ #7027).

---

## Gap 3 (CLOSED) — the corrected instruction set is now a tracked artifact

The previous section left durability open: the corrected `GUARDRAILS.md` and
command/skill tree existed only inside gf's home volume, hand-edited. A volume is
not a source of truth. Wipe it (or rebuild the image) and `--apply` would
faithfully re-seed the *guarded* lane's documents again, and the instance would
look perfectly healthy while telling the agent to commit in `/mnt/archie_brain`
and ship with a helper that is not there.

**Now:** `scripts/opencode_guardfree_lane_docs/` holds the corrected set, and
`install_lane_docs()` applies it on every `--apply`, right after `seed_config`:

| file | role |
|---|---|
| `GUARDRAILS.md` | the policy the instance claims to run under |
| `command/{ship,archie-save,archie-end,archie-boot,sync-lane}.md` | what the agent does at each step |
| `skills/archie-lane-ship/SKILL.md`, `skills/archie-repair-bay/SKILL.md` | the two skills that named the missing `gh-read.sh` |
| `handover.md` | seeded to `/opencode-home/data/archie-handover.md` **only if absent** — continuity is a record, not configuration, and is never rewritten |

**The rule that makes it safe to re-run.** Overwrite a file only when it still
byte-matches the source container's copy — proof that nobody has touched it since
seeding. If it matches the tracked copy, leave it. If it matches neither, it was
edited after seeding: **leave it and say so.** The instance is a working terminal
someone may have customised, and an installer that "repairs" files it does not
recognise would silently revert that work on every `--apply`. When the state is
unrecognised, the confused party is the script, not the file. Pre-existing
`*.guard-bak` files are never overwritten either, so the first pristine copy
survives later re-seeds.

Measured on the live instance, all three paths:

* re-run with everything correct → `0 installed, 9 already correct` (idempotent);
* file replaced with the guarded lane's copy (the real post-rebuild state) →
  `installed command/ship.md`, back to the tracked text, existing backup intact;
* file carrying a hand-edit → `WARNING: 1 file(s) differ from BOTH…`, marker
  survived, nothing overwritten.

The image-level half of #7027 is still open and is the OWNER's to close.
`opencode/workspace/GUARDRAILS.md` remains baked into the base image, so
`seed_config` still copies the **guarded** lane's documents into a fresh volume.
Measured again 2026-09-28 after the docs were merged: the source container
(17685) still holds 8 files carrying the wrong ship paths, so a newly created
guard-free volume is wrong **from boot** until it is repaired.

### Provisioning a fresh volume

Moved to [part 5](2026-09-27-opencode-guard-free-terminal-5-provisioning-and-validation.md) — the procedure and the live validation evidence — so this part stays inside the review pass window and the evidence is read in full rather than truncated.

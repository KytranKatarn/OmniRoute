# Opencode guard-free terminal — spec, part 5 of 6: provisioning and validation

**Part 5 of 6.** Index: [2026-09-27-opencode-guard-free-terminal.md](2026-09-27-opencode-guard-free-terminal.md). Narrative: [part 3](2026-09-27-opencode-guard-free-terminal-3-lane-instructions.md).

---

### Provisioning a guard-free volume — REQUIRED step

```bash
python3 scripts/opencode_guardfree_terminal.py --apply      # or, install-only:
python3 scripts/opencode_guardfree_terminal.py --repair-docs archie_opencode_terminal_gf
```

**A fresh guard-free volume is not correct until one of these has run.** Until
then the instance looks healthy while its instructions name `/mnt/archie_brain`
as the work tree and `/opencode-home/bin/ship-branch.sh` as the ship path —
neither of which exists in a seeded lane. `--repair-docs` is the safer of the two:
it installs documents and nothing else, and it refuses the source container.

#### Validated, not asserted

The commands above were exercised against the real instances on 2026-09-28, not
inferred. Observed, verbatim:

- **guard-free `archie_opencode_terminal_gf`** —
  `5 installed/created, 6 already correct` (GUARDRAILS.md and both skills
  upgraded through the installer's own-output path, three new `reference/`
  documents created). Re-running immediately reports
  `0 installed/created, 15 already correct` — **idempotent**.
- **guarded `archie_opencode_terminal_host`** —
  `7 installed/created, 11 already correct`, then idempotent on re-run.
- **source container `archie_opencode_terminal`** — **refused**, by design:
  `ERROR: refusing to install onto 'archie_opencode_terminal': it is the SOURCE
  container. Its files are the baseline this installer compares against, so
  repairing it would overwrite the owner's own documents with our idea of them.`
- **all four refusals** — source container, absent container, unreadable
  `core.hooksPath`, and a container that is not running — each exit non-zero.
- **`check_lane_instructions`** — clean on both lanes, i.e. no instruction file
  still describes the *other* lane.

The idempotence matters as much as the first run: a repair you cannot repeat
safely is a repair you will not run twice.

There is deliberately **no `start.sh` boot hook**, and adding one would be a
regression. Canonical 17685 is both the seed source *and* a guarded-flavour lane,
so a hook that installs by flavour would overwrite the owner's own documents on
every boot. The installer's refusal to touch the source container is the property
that makes the repair safe; a hook cannot have it and stay automatic.

The durable fix is to bake the tracked files into the image, the way
`opencode-pr.sh` is already baked in, so the volume never holds the wrong set.
That is an `opencode/` change and therefore out of this lane's scope. The two
remaining image-level defects — a stale comment in `start.sh` and an
`opencode-pr` header that contradicts the owner's token decision — are checked by
`scripts/opencode_lane_audit.sh` (`--print` shows the patches). Re-run it after
any image rebuild: a rebuild silently restores baked strings, which is how this
whole class of defect started.

## Correction — what is actually known about `main` protection

Moved to [part 6](2026-09-27-opencode-guard-free-terminal-6-main-protection.md) to keep this part inside the review pass window.

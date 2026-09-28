"""A.R.C.H.I.E. opencode lane — support package for the guard-free terminal.

Split out of one 990-line script on 2026-09-28. The reason was reviewability,
not taste: F.O.R.G.E. reviews per FILE with a per-pass cap of 18,768 characters
on the strong model and 9,000 on the weak one, and the single file was 48,503.
A pass truncated it and the review demoted for coverage no matter what. Every
module here is under the 9,000-char cap, so the change is reviewable end to end.

The entry point (scripts/opencode_guardfree_terminal.py) keeps its path and its
CLI exactly as it was, because the tracked lane docs and the handover both tell
people to run it. The design narrative below is the original script's own.

"""
"""Build + run a GUARD-FREE opencode terminal, alongside the existing ones.

Owner request 2026-09-27: "it needs to be running alongside Claude-CLI like
claude... it needs to be able to access and modify everything like claude-cli
does." The scope guard is what stands between the lane and that posture.

    ./scripts/opencode_guardfree_terminal.py              # dry run, prints the plan
    ./scripts/opencode_guardfree_terminal.py --verify     # prove an image is guard-free
    ./scripts/opencode_guardfree_terminal.py --apply      # build the image, run the terminal
    ./scripts/opencode_guardfree_terminal.py --teardown   # remove ONLY the guard-free one

WHY A DERIVED IMAGE
  The scope guard is exactly two files plus one arming line:
    /opt/lane-guard/pre-push        scope-checks every changed file vs origin/main
    /opt/lane-guard/allowlist.yaml  the allowlist (baked CODEX_ALLOWLIST_FILE)
    /start.sh:89                   git -C /work/archie-platform config
                                   core.hooksPath /opt/lane-guard
  Deriving is additive: archie_brain-archie_opencode_terminal:latest is never
  modified, so a bad build cannot break either running terminal.

  The transform repoints the arming at an EMPTY dir rather than deleting the
  block. git runs no hook when hooksPath holds no hook file, so this reaches
  guard-free without surgery on a multi-line shell continuation — which is where
  a hand-written patch would break. Validated 2026-09-27 against the real image:
  every reference removed, payload gone, /start.sh still parses as valid sh.

WHAT IS *NOT* REMOVED — read this before --apply
  Only the two scope-guard files go. These stay, on purpose:
    /usr/local/bin/opencode-pr   commits, pushes opencode/*, opens a PR, NEVER merges
    /usr/local/bin/gh            blocks merge/auth actions from inside the lane
  Removing those would make the lane less capable, not freer. They are the safe
  path to a PR, not a restriction on one.

  The real merge stop is GitHub branch protection, not anything local.
  opencode-pr's own header says its PAT carries "Pull requests: write", which
  GitHub does not let you scope down and therefore permits MERGING. Only
  required_approving_review_count on main prevents that. This script does not
  verify it and cannot; confirm it yourself before relying on this.

WHAT IS LOST
  Early local feedback on out-of-scope changes. Review and merge control are
  untouched: pre-commit, F.O.R.G.E. in Repair Bay, and a human merge all still
  apply. This trades a convenience gate for nothing you actually had.

SAFETY
  * Refuses to run if the target container name already exists unless --replace.
  * --replace stops and removes ONLY --name. It never touches
    archie_opencode_terminal or archie_opencode_terminal_host.
  * The OMNIROUTE key is staged into a 0600 env-file and deleted immediately.
    Its value is never printed, logged, or passed on a command line.
  * Verifies the image is guard-free BEFORE creating a container from it.
  * If the container does not come up healthy, it tears itself down.
  * Seeds /work/archie-platform only into an EMPTY volume, and verifies the clone
    is a real repo afterwards (see seed_clone — without it the lane boots with no
    codebase, no git identity and no credential helper).
  * Host Claude settings are mounted as a SINGLE FILE, read-only, never the
    whole of /home/kytran — that directory holds a plaintext DR replicator
    password, a secrets archive, an Xauthority cookie, and bash history.

KNOWN GAP — the lane's instructions are not in git (two surfaces, one cause)
  1. /opencode-home/config/opencode/GUARDRAILS.md lives only in the container
     volume. The guarded lane's copy describes a scope guard this image does not
     have, so it must be REPLACED for this instance or the lane is told it is
     restricted while it is not. Nothing here or in the Dockerfile writes that
     file. See the spec's "first inspection" section, gap 2.
  2. The whole command/ + skills/ tree, for the same reason and worse in
     practice. seed_config copies it verbatim from a source container, so it
     arrives describing the SOURCE lane: commit in /mnt/archie_brain, ship with
     /opencode-home/bin/ship-branch.sh. Neither works in a seeded instance — see
     check_lane_instructions() for the measurement, which also found the same
     defect in a second live instance (archie_opencode_terminal_host, 17686).
     Corrections are still made by hand in the volume and are lost on rebuild.

  Both die the same way: no tracked file owns them. The fix is a GUARDRAILS.md and
  command/ tree in the repo, COPYed by the image like opencode-pr.sh already is —
  owner-owned, because opencode/ is outside this lane's allowed_paths (#7027).
"""

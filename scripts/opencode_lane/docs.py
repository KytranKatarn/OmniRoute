"""Lane instruction sets, their source of truth, and the check on a container's set.

seed_config copies the SOURCE lane's config/opencode tree verbatim, so a seeded
instance is handed another lane's operating instructions — a volume is not a
source of truth, so the corrected sets live in git and are applied over it. The
flavor is read from core.hooksPath, never the container name.
"""
import os
from pathlib import Path

from .common import run, say


# --------------------------------------------------------------------------
# lane instructions: tracked here, applied into the container
# --------------------------------------------------------------------------
# WHY GIT (measured 2026-09-28): seed_config verbatim-copies the source lane's
# config/opencode tree; hand-fixing the volume works until it is recreated, then
# the breakage returns silently. So the corrected set lives in
# scripts/opencode_{guardfree,guarded}_lane_docs/ and is applied every --apply.
DOCS_DIRS = {
    # A GUARDED lane keeps its rules (deny-by-default allowlist, pre-push guard)
    # and only needs the ship/commit paths corrected: it commits in its own clone
    # and the host runner ships. A GUARD-FREE lane has no scope guard to lean on,
    # so its policy file, commands and skills differ far more, and it ships with
    # opencode-pr. Two sets, not one merged: blending them would either promise a
    # guard the unrestricted lane does not have, or describe a runner it cannot reach.
    "guardfree": Path(__file__).resolve().parent.parent / "opencode_guardfree_lane_docs",
    "guarded": Path(__file__).resolve().parent.parent / "opencode_guarded_lane_docs",
}
HANDOVER_REL = "handover.md"
HANDOVER_DST = "/opencode-home/data/archie-handover.md"

def lane_flavor(name):
    """Which instruction set does this lane need? Read it, do not infer it from the name.

    core.hooksPath is the honest signal: /opt/lane-guard means the lane's scope guard
    is armed, /opt/no-guard means it was deliberately removed. Unknown means unknown —
    return None and install nothing, because guessing here would either strip a
    guarded lane's rules or hand an unrestricted one a ruleset it must not have.
    """
    r = run(["docker", "exec", name, "git", "-C", "/work/archie-platform",
             "config", "--get", "core.hooksPath"], check=False)
    hooks = (r.stdout or "").strip()
    if hooks == "/opt/no-guard":
        return "guardfree"
    if hooks == "/opt/lane-guard":
        return "guarded"
    say("    (core.hooksPath is {!r} — cannot tell which instruction set applies)".format(hooks))
    return None
def doc_files(docs_dir):
    """Every tracked document, discovered rather than hardcoded, so adding a file
    to the directory is enough to have it applied."""
    return sorted(str(p.relative_to(docs_dir)) for p in docs_dir.rglob("*.md")
                  if p.name != HANDOVER_REL and ".guard-bak" not in str(p))
def check_lane_instructions(name, source):
    """Report config files that still describe the SOURCE lane, not this one.

    seed_config copies the whole config/opencode tree from a source container, and
    that tree belongs to the guarded lane. Measured 2026-09-28 on a real seeded
    instance: /ship, /archie-save, /archie-end, /archie-boot and the two
    ship/repair skills told the agent to commit in /mnt/archie_brain and then ship
    with /opencode-home/bin/ship-branch.sh. NEITHER works in a seeded instance:

      * seed_config copies only config/opencode — it never copies bin/, so
        ship-branch.sh does not exist in the target at all;
      * opencode-pr, the one ship primitive that DOES exist, REFUSES
        /mnt/archie_brain by design: it runs `git add -A`, and an untracked
        platform_v2 copy was once swept into a lane commit that way.

    Net effect: the seeded instruction set sends the agent to the single tree
    where shipping is rejected. Copying bin/ in would be the WRONG fix —
    ship-branch.sh ships the owner's live tree, exactly what this lane must never
    push from — so the tree has to be corrected per instance. The least this
    script can do is fail loudly and list what to fix: a silently wrong
    instruction set is worse than a missing one, because the agent trusts it.

    Reports only; never fatal. Broken documentation should not block a terminal
    that otherwise works.

    What it checks, and why not something smarter: a seeded instance's files
    mention paths that may not exist, and MENTIONING a path is not the same as
    instructing its use — my own corrected files name ship-branch.sh precisely to
    say it is absent. So this does not try to read intent (the first version of
    this function did, and flagged the corrected files: a check that fires on
    correct work trains you to ignore it). It does the one thing that is
    mechanical and decisive: extract every absolute path the lane's own
    instructions reference, ask the container whether each one exists, and report
    the missing ones with their file:line. A disclaimer on the same or following
    two lines suppresses the line, so "this does not exist here" is not reported
    as a missing path. Everything else is a pointer for a human to judge, which is
    the right altitude for documentation.
    """
    probe = r'''
cd /opencode-home/config/opencode 2>/dev/null || exit 0
# Only the files that define a SHIP path. The website-publishing skill references
# host paths that legitimately do not exist in any lane; including it turned this
# into noise and taught me to skip the output.
FILES="command/ship.md command/archie-save.md command/archie-end.md command/archie-boot.md skills/archie-lane-ship/SKILL.md skills/archie-repair-bay/SKILL.md"
for f in $FILES; do
  [ -f "$f" ] || continue
  # A file that says its own paths are absent is TALKING ABOUT them, not instructing
  # their use. Report the suppression instead of hiding it: a check whose quiet mode
  # is invisible is a check you cannot audit. (The list has to be as wide as the
  # phrasings I actually write — "does not exist" alone flagged my own corrected
  # files, which say "do not exist" and "is absent", and a check that fires on
  # correct work trains you to ignore it.)
  if tr -d '`' < "$f" | grep -qiE 'do(es)? not exist|not installed|is absent|never copied|not populated|only populated|no such'; then
    echo "DOCUMENTED $f  (names paths it states are absent — not checked)"
    continue
  fi
  grep -n -oE '/(opencode-home|mnt|work|host-claude-config|usr|var)/[A-Za-z0-9_./-]+' "$f" 2>/dev/null \
    | sed 's/[.,;:)]$//' | sort -u -t: -k1,1n \
    | while IFS=: read -r line path; do
        # A <placeholder> means the doc is naming a SHAPE, not a file: ship-<name>.sh
        # is created per batch on the host, so "does /…/ship- exist?" was a
        # question I answered wrongly and reported as a missing path. Check the
        # template, not the truncation.
        case "$path" in *"<"*) continue ;; esac
        [ -e "$path" ] || echo "MISSING $f:$line  $path"
      done
done
'''
    r = run(["docker", "exec", name, "sh", "-c", probe], check=False)
    missing = [l.strip() for l in (r.stdout or "").splitlines() if l.startswith("MISSING")]
    documented = [l.strip() for l in (r.stdout or "").splitlines() if l.startswith("DOCUMENTED")]
    for d in documented:
        say("  {}".format(d.replace("DOCUMENTED ", "suppressed: ").replace(
            "  (names paths it states are absent — not checked)", "")))
    if not missing:
        say("  lane instructions: every ship path they reference exists in this container")
        return True
    say("  WARNING: {} referenced path(s) do not exist here (source lane '{}'):"
        .format(len(missing), source))
    for m in missing:
        say("    {}".format(m.replace("MISSING ", "")))
    if lane_flavor(name) == "guarded":
        say("    For a GUARDED lane the fix is to rewrite the step, not to copy")
        say("    bin/: work in /work/archie-platform, commit, and let the host")
        say("    runner ship it. ship-branch.sh pushes the OWNER's live tree, which")
        say("    this lane must never push from.")
    else:
        say("    A lane told to run these cannot ship. Copy bin/ from the source")
        say("    instance OR rewrite the step: for THIS instance work in")
        say("    /work/archie-platform and ship with  opencode-pr \"<pr title>\"")
        say("    (opencode-pr refuses /mnt/archie_brain by design.)")
    return False

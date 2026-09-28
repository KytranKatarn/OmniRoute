"""The two entry points that a RUNNING lane still needs.

plan() is the dry run: the whole build in words, nothing written. repair_docs()
is --repair-docs — how a lane's corrected instructions are made repeatable when
the lane already exists. Its blast radius is deliberately smaller than --apply's:
it creates nothing, so a container that is absent, or not running, or whose
flavor cannot be read, is refused outright. The worst case is "nothing happened,
and here is why".
"""

from .common import (BASE_IMAGE, GF_IMAGE, HOST_CLAUDE_MOUNT, HOST_CLAUDE_SETTINGS,
                     PROTECTED, die, run, say)
from .docs import DOCS_DIRS, lane_flavor
from .docs_install import install_lane_docs
from .guards import host_file_exists

def plan(name, port, source, replace):
    say("DRY RUN — nothing written. Re-run with --apply.\n")
    say("would:")
    say("  1. build {} FROM {}".format(GF_IMAGE, BASE_IMAGE))
    say("       - repoint /opt/lane-guard -> /opt/no-guard (empty)")
    say("       - delete the guard payload and the allowlist env var")
    say("       - correct two log lines that would then lie")
    say("  2. VERIFY the image is guard-free (6 assertions, fail-closed)")
    say("  3. create volumes {}_work, {}_home".format(name, name))
    say("  4. seed /work/archie-platform from the live tree, origin=GitHub, on main")
    say("       (skipped if the volume already holds a clone — never clobbered)")
    say("  5. run '{}' on 127.0.0.1:{} from that image (LANE_NAME={})".format(
        name, port, "opencode" if name == PROTECTED[0] else "opencode-guardfree"))
    say("       - /mnt/archie_brain rw, docker.sock, github+kb secrets (ro)")
    if host_file_exists(HOST_CLAUDE_SETTINGS):
        say("       - {} -> {} (single file, ro)".format(HOST_CLAUDE_SETTINGS, HOST_CLAUDE_MOUNT))
    say("       - OMNIROUTE_API_KEY via a 0600 env-file, deleted after start")
    say("  6. seed config from '{}' (config tree only)".format(source))
    say("  7. install the TRACKED lane instructions over it")
    say("       (scripts/opencode_guardfree_lane_docs/ — the seeded copy belongs to")
    say("        the source lane and names a ship path that cannot work here)")
    say("       - only over a file that still matches the seed; yours is never touched")
    say("  8. chown volumes 1000:1000 and health-check ttyd")
    say("  9. if unhealthy, tear the container down again")
    say("\nwould NOT touch (protected):")
    for p in PROTECTED:
        say("  - {}".format(p))
    say("\nstill in place after this:")
    say("  - /usr/local/bin/opencode-pr  (ships opencode/*, opens PR, NEVER merges)")
    say("  - /usr/local/bin/gh           (blocks merge/auth from the lane)")
    say("  - pre-commit, F.O.R.G.E. review, human merge")
    say("\nmain is protected, measured 2026-09-28 from host tokens:")
    say("  protected=True, 0 rulesets, required status checks enforcement=off.")
    say("  NOT readable without Administration: read — required_approving_review_count")
    say("  and enforce_admins. The last 10 merges into main all had 0 reviews, so a")
    say("  review-free merge has been possible in practice; whether THIS lane's PAT")
    say("  can still do it is the open question in Dev HQ #7026.")
    return 0
def repair_docs(name, source):
    """Re-apply the tracked instruction set to a lane that already exists.

    Why this exists at all: --apply refuses protected lanes, and --apply is the
    only thing that called install_lane_docs(). So a protected lane's corrected
    instructions were correct once, by hand, and nothing could put them back.
    Wipe that volume and the lane is right back to naming /mnt/archie_brain and
    claiming it has no credential. Correct-but-not-repeatable is the same defect
    as never-fixed, one step later.

    The blast radius is deliberately smaller than --apply's, because a protected
    lane is the owner's:

      * no container is created, stopped, removed or replaced
      * no image is built
      * no volume is deleted
      * it is refused on the SOURCE container — that container's files ARE the
        baseline this installer compares against, so "repairing" it would
        overwrite the owner's own documents with our idea of them
      * it is refused when the lane's flavor cannot be determined, because
        guessing would either strip a guard or hand a free lane a ruleset
      * per-file safety is unchanged: a file that matches neither the seed, the
        tracked copy, nor our own manifest is someone's edit and is left alone

    So the worst case is "nothing happened, and here is why".
    """
    if name == source:
        die("refusing to install onto '{}': it is the SOURCE container. Its files "
            "are the baseline this installer compares against, so repairing it "
            "would overwrite the owner's own documents with our idea of them."
            .format(name))
    r = run(["docker", "inspect", "-f", "{{.State.Running}}", name], check=False)
    if r.returncode != 0:
        die("no container named '{}'. --repair-docs only touches a lane that is "
            "already running; it never creates one. Use --apply for that."
            .format(name))
    if (r.stdout or "").strip() != "true":
        die("'{}' exists but is not running. Start it first — this mode installs "
            "files and does not manage containers.".format(name))
    flavor = lane_flavor(name)
    if flavor is None:
        die("cannot tell whether '{}' is a guarded or guard-free lane (core."
            "hooksPath unreadable). Installing nothing rather than guessing: the "
            "wrong set here would tell a lane it has a guard it lacks, or that it "
            "may push when it must not.".format(name))
    say("repairing lane '{}' (flavor: {}) from {}".format(name, flavor, DOCS_DIRS[flavor]))
    ok = install_lane_docs(name, source)
    return 0 if ok else 1

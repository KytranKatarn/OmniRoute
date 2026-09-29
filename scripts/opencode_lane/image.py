"""Derive and verify the guard-free image.

A derived image, never an edit to the base: archie_brain-archie_opencode_terminal
is shared by the two running terminals, so a bad transform here must not be able
to reach them. verify_image() is fail-closed and runs before any container is
created from the result.
"""

import os
import shutil
import tempfile

from .common import BASE_IMAGE, DOCKERFILE, GF_IMAGE, die, run, say
from .docs import DOCS_DIRS


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------
VERIFY_SNIPPET = r"""
fail=0
test ! -e /opt/lane-guard && echo "PASS guard payload removed" \
  || { echo "FAIL /opt/lane-guard still present"; fail=1; }
grep -q "lane-guard" /start.sh && { echo "FAIL /start.sh still references it"; fail=1; } \
  || echo "PASS no lane-guard reference in /start.sh"
grep -q "scope guard armed" /start.sh && { echo "FAIL stale 'guard armed' log line"; fail=1; } \
  || echo "PASS log lines corrected"
sh -n /start.sh && echo "PASS /start.sh parses as valid sh" \
  || { echo "FAIL /start.sh syntax broken"; fail=1; }
[ -d /opt/no-guard ] && echo "PASS hooksPath target exists and is empty" \
  || { echo "FAIL /opt/no-guard missing"; fail=1; }
ls -A /opt/no-guard 2>/dev/null | grep -q . && { echo "FAIL /opt/no-guard is not empty"; fail=1; }
test -d /opt/lane-docs-guardfree && echo "PASS tracked guardfree docs baked into image" \
  || { echo "FAIL /opt/lane-docs-guardfree missing — fresh volume would be wrong"; fail=1; }
test -x /usr/local/bin/lane-docs-boot && echo "PASS boot wrapper installed" \
  || { echo "FAIL lane-docs-boot missing or not executable"; fail=1; }
sh -n /usr/local/bin/lane-docs-boot && echo "PASS boot wrapper parses as valid sh" \
  || { echo "FAIL boot wrapper syntax broken"; fail=1; }
exit $fail
"""


# A boot-time re-apply of the baked-in instruction set, run as the guard-free
# image's entrypoint PRE-wrapper (then exec the real /start.sh).
#
# WHY THIS EXISTS: the base image bakes NOTHING into /opencode-home (verified
# 2026-09-28: the path does not exist in archie_brain-archie_opencode_terminal),
# and a fresh named volume at /opencode-home is therefore populated from the seed
# the tool writes AFTER the container is already running (seed_config, a docker
# exec). So without this the lane's own operating instructions are wrong from
# boot until a human runs --repair-docs.
#
# WHY -n (NO-CLOBBER) IS LOAD-BEARING, NOT A DETAIL: install_lane_docs() goes to
# real lengths to never overwrite a file a human edited after seeding
# (plan_doc_install: a file matching neither the seed nor our own output is left
# alone and reported). A plain `cp -a` here would quietly undo that on every
# restart — the same "installer repairs what it does not recognise" failure the
# installer was written to avoid, just moved to boot. `cp -an` fills a fresh or
# missing file and leaves every existing file untouched, so a customized
# instruction file survives a restart while a bare volume still comes up correct.
GF_BOOT_WRAPPER = "/usr/local/bin/lane-docs-boot"
GF_BOOT_SNIPPET = r"""#!/bin/sh
# Fill /opencode-home/config/opencode from the instruction set baked into this
# image, WITHOUT overwriting anything already there (see the note baked next to
# this script). Then hand off to the real entrypoint.
set -e
SRC=/opt/lane-docs-guardfree
DST=/opencode-home/config/opencode
if [ -d "$SRC" ]; then
  mkdir -p "$DST"
  # -n: no-clobber. A file a human edited must survive a restart; only fill
  # what is absent so a fresh volume still comes up with the right instructions.
  cp -an "$SRC/." "$DST/" 2>/dev/null || true
  chown -R 1000:1000 /opencode-home 2>/dev/null || true
fi
exec /start.sh "$@"
"""


def _stage_lane_docs(ctx):
    """Copy the tracked guardfree instruction set into the build context."""
    src = DOCS_DIRS["guardfree"]
    if not src.is_dir():
        die("tracked guardfree docs not found at {} — run this from the repo, "
            "not a copy".format(src))
    dst = os.path.join(ctx, "lane-docs")
    shutil.copytree(src, dst)
    return sum(1 for _ in Path(dst).rglob("*.md"))


from pathlib import Path  # noqa: E402  (used only by _stage_lane_docs)


def verify_image(image):
    if run(["docker", "image", "inspect", image], check=False).returncode != 0:
        die("image {} does not exist yet. Build it with --apply first, or pass "
            "--verify after a build.".format(image), code=2)
    say("verifying {} is guard-free...".format(image))
    r = run(["docker", "run", "--rm", "--entrypoint", "sh", image, "-c", VERIFY_SNIPPET],
            check=False)
    for line in (r.stdout or "").strip().splitlines():
        say("  " + line)
    if r.returncode != 0:
        die("image {} is NOT guard-free. Refusing to run a terminal from it."
            .format(image), code=2)
    say("  -> all assertions passed")
    return True


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def build_image():
    if run(["docker", "image", "inspect", GF_IMAGE], check=False).returncode == 0:
        say("image {} already exists; rebuilding.".format(GF_IMAGE))
    ctx = tempfile.mkdtemp(prefix="oc-gf-")
    try:
        n = _stage_lane_docs(ctx)
        say("  staging {} tracked guardfree instruction file(s) into the build".format(n))
        with open(os.path.join(ctx, "Dockerfile"), "w") as fh:
            fh.write(DOCKERFILE)
        with open(os.path.join(ctx, "lane-docs-boot"), "w") as fh:
            fh.write(GF_BOOT_SNIPPET)
        say("building {} ...".format(GF_IMAGE))
        r = run(["docker", "build", "-t", GF_IMAGE, ctx], check=False, capture=True)
        tail = "\n".join((r.stdout or "").strip().splitlines()[-6:])
        for line in tail.splitlines():
            say("  " + line)
        if r.returncode != 0:
            die("build failed:\n" + (r.stderr or tail))
        say("  -> built")
    finally:
        shutil.rmtree(ctx, ignore_errors=True)

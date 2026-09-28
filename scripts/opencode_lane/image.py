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
exit $fail
"""


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
        with open(os.path.join(ctx, "Dockerfile"), "w") as fh:
            fh.write(DOCKERFILE)
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

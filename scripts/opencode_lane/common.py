"""Shared helpers and constants for the opencode lane tooling.

Deliberately the ONLY module every other one imports from, so the rest of the
package can never disagree about what `run` does or which containers are off
limits. `PROTECTED` in particular: it is the list of instances this tooling may
never stop, remove or recreate, and having exactly one copy of it is the point.
"""

import shlex
import subprocess
import sys


BASE_IMAGE = "archie_brain-archie_opencode_terminal:latest"
GF_IMAGE = "archie_opencode_terminal_guardfree:latest"

DEFAULT_NAME = "archie_opencode_terminal_gf"
DEFAULT_PORT = 17687

# Never touched by this script, in any code path.
PROTECTED = ("archie_opencode_terminal", "archie_opencode_terminal_host")

NETWORK = "archie_brain_opencode_terminal_net"
SECRETS = "/mnt/archie_brain/secrets/opencode"
# Single file, ro. See WHAT IS NOT REMOVED / SAFETY in the module docstring.
HOST_CLAUDE_SETTINGS = "/home/kytran/.claude/settings.json"
HOST_CLAUDE_MOUNT = "/host-claude-config/settings.json"

DOCKERFILE = """FROM {base}
USER root
# Point the arming at an empty dir. git runs no hook when hooksPath holds no
# hook file -> guard-free, without editing a multi-line shell continuation.
RUN mkdir -p /opt/no-guard \\
 && rm -rf /opt/lane-guard \\
 && sed -i 's|/opt/lane-guard|/opt/no-guard|g' /start.sh
# The substitution above leaves two log lines claiming the guard is armed. A
# control that reports the opposite of its state is its own defect.
RUN sed -i 's|scope guard armed on the lane clone|scope guard DISABLED (guard-free build)|' /start.sh \\
 && sed -i 's|WARNING: could not arm the scope guard|INFO: guard-free build, no scope guard|' /start.sh
# Same class of defect, in a COMMENT rather than a log line: the git-identity
# comment above names a BAKED scope guard, which is true of the base image and
# false here. The base file is left alone on purpose -- the line is CORRECT in
# the guarded build, so the correction belongs in the derivation, not in a
# hand-edit of a derived image (which a rebuild would silently undo). Measured
# 2026-09-28 on the running guard-free instance, which still showed the stale
# text at /start.sh:78 while line 90 correctly printed DISABLED.
# The pattern is anchored to end-of-line and avoids the apostrophe in "lane's",
# which would otherwise close the shell quoting around the sed.
RUN sed -i 's|^# Git identity + the BAKED scope guard.*$|# Git identity + the lane clone. Guard-free build: no scope guard by design (hooksPath points at an EMPTY /opt/no-guard).|' /start.sh
# Bake the tracked guardfree instruction set in, and fill the lane's config tree
# from it on every boot. The base image bakes nothing into /opencode-home, so a
# fresh volume would otherwise start with the SOURCE lane's documents. Copied
# NO-CLOBBER at boot (see the wrapper) so a file a human edited survives a
# restart. This is the guard-free SET only; the guarded image keeps its own.
COPY lane-docs /opt/lane-docs-guardfree
COPY lane-docs-boot /usr/local/bin/lane-docs-boot
RUN chmod +x /usr/local/bin/lane-docs-boot
# Wrap the base entrypoint: fill the config tree from the baked set (no-clobber),
# then exec the real /start.sh. The base image's ENTRYPOINT is ["/start.sh"].
ENTRYPOINT ["/usr/local/bin/lane-docs-boot"]
ENV CODEX_ALLOWLIST_FILE=""
""".format(base=BASE_IMAGE)


def run(cmd, check=True, capture=True):
    """Run a command. Never echoes secret-bearing arguments."""
    r = subprocess.run(cmd, capture_output=capture, text=True)
    if check and r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        die("command failed: {}\n{}".format(" ".join(shlex.quote(c) for c in cmd[:3]), err))
    return r


def die(msg, code=1):
    sys.stderr.write("ERROR: {}\n".format(msg))
    sys.exit(code)


def say(msg=""):
    print(msg, flush=True)

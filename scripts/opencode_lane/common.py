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

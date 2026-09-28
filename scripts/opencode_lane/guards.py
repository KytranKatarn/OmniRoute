"""Refusals. Every one of these runs BEFORE anything is created or destroyed.

Each guard is a die() rather than a warning because the failure they prevent is
silent: a recreated protected instance, a published port that shadows another
lane's, a bind mount that quietly becomes a directory. In every case the mistake
looks like success afterwards.
"""

import shlex
import sys

from .common import BASE_IMAGE, PROTECTED, die, run, say


# --------------------------------------------------------------------------
# guards
# --------------------------------------------------------------------------
def guard_not_protected(name, override=None):
    """Refuse to touch a protected instance unless the operator names it.

    The override is a value, not a boolean: the caller must repeat the exact
    container name. A bare flag would let a mistyped --name destroy the
    protected instance it was never aimed at.
    """
    if name not in PROTECTED:
        return
    if override != name:
        die("'{}' is a PROTECTED existing instance. This script will not stop, "
            "remove, or recreate it without you naming it explicitly:\n"
            "    --override-protected {}   (repeat the name exactly)".format(name, name))
    say("!! OVERRIDE: '{}' is protected and you just named it explicitly.".format(name))
    say("!! Its volumes are PRESERVED (--replace does not delete volumes), so the")
    say("!! /work clone and lane config survive. Only the container is recreated,")
    say("!! from the guard-free image. Roll back with: {} --replace".format(
        shlex.quote(sys.argv[0])))
    say("")


def guard_override_known(names):
    for n in PROTECTED:
        if n in names:
            say("  NOTE: '{}' is protected; --override-protected names it, so it "
                "will be recreated.".format(n))


def guard_name_free(name, replace):
    exists = run(["docker", "inspect", name], check=False).returncode == 0
    if exists and not replace:
        die("container '{}' already exists. Re-run with --replace to recreate it, "
            "or --teardown to remove it.".format(name))
    return exists


def guard_port_free(port):
    # docker renders a published loopback port as "127.0.0.1:PORT->CONTAINER/tcp".
    # Match the "->" or this check silently never fires.
    out = run(["docker", "ps", "--format", "{{.Ports}}"], check=False).stdout or ""
    if "127.0.0.1:{}->".format(port) in out:
        die("port {} is already published by a running container. Pick another "
            "with --port.".format(port))


def host_file_exists(path):
    """Ask the DOCKER DAEMON whether a bind source is a file.

    A '-v SRC:/dst' source is resolved by the daemon on the host, not by this
    client. If the client runs in a container without the host's /home, a local
    os.path.exists() answers about the WRONG filesystem and silently skips a
    mount that would have worked. Probe through a throwaway container instead.
    """
    r = run(["docker", "run", "--rm", "-v", "{}:/probe:ro".format(path),
             "alpine:3", "test", "-f", "/probe"], check=False)
    return r.returncode == 0


def guard_base_image():
    if run(["docker", "image", "inspect", BASE_IMAGE], check=False).returncode != 0:
        die("base image {} not present locally.".format(BASE_IMAGE))

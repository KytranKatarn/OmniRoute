"""Create the container itself, and take it down again.

run_container() is where a lane actually comes to life, so its guard refusals
matter most: a name or port collision here publishes a SECOND terminal that
shadows a running lane. wait_healthy() probes ttyd INSIDE the container (port
7681; the host port is irrelevant to the probe). teardown() removes a container
AND its volumes, deliberately, so it carries the protected-instance guard too.
"""

import json
import os
import subprocess
import tempfile
import time

from .common import (BASE_IMAGE, GF_IMAGE, HOST_CLAUDE_MOUNT, HOST_CLAUDE_SETTINGS,
                     NETWORK, SECRETS, die, run, say)
from .guards import guard_name_free, guard_not_protected, guard_port_free, host_file_exists


# --------------------------------------------------------------------------
# secrets
# --------------------------------------------------------------------------
def stage_envfile(source_container, lane_name):
    """Write LANE_NAME + OMNIROUTE_API_KEY to a 0600 file. Value never printed."""
    fd, path = tempfile.mkstemp(prefix="oc-gf-env-")
    os.close(fd)
    os.chmod(path, 0o600)
    try:
        with open(path, "w") as fh:
            fh.write("LANE_NAME={}\n".format(lane_name))
            r = run(["docker", "exec", source_container, "cat",
                     "/opencode-home/config/opencode/opencode.json"], check=False)
            if r.returncode != 0 or not r.stdout.strip():
                die("could not read opencode.json from '{}'. Pass --from-instance "
                    "with a container that has one.".format(source_container))
            try:
                cfg = json.loads(r.stdout)
                key = cfg["provider"]["omniroute"]["options"]["apiKey"]
            except (ValueError, KeyError) as e:
                die("could not extract the omniroute key from {}: {}".format(source_container, e))
            fh.write("OMNIROUTE_API_KEY={}\n".format(key))
    except BaseException:
        # BaseException, not Exception: die() raises SystemExit, which would
        # otherwise skip this and leave a 0600 file holding the key on disk.
        if os.path.exists(path):
            os.unlink(path)
        raise
    say("  env-file staged (0600, {} bytes, value not printed)".format(
        os.path.getsize(path)))
    return path
def run_container(name, port, source, replace, lane_name):
    guard_name_free(name, replace)
    if replace:
        remove_container(name)
    guard_port_free(port)

    work_v = "{}_work".format(name)
    home_v = "{}_home".format(name)
    for v in (work_v, home_v):
        run(["docker", "volume", "create", v], check=False)

    # Fresh named volumes are root-owned, and /start.sh crash-loops on that
    # ("cannot create directory '/opencode-home/config'"). Fix the ownership
    # BEFORE the container first starts, so there is no crash loop to recover
    # from. This needs no reference to the target container.
    for v in (work_v, home_v):
        run(["docker", "run", "--rm", "-u", "0", "-v", "{}:/fix".format(v),
             "alpine:3", "chown", "-R", "1000:1000", "/fix"], check=False)
    say("  volumes created and chowned 1000:1000 (pre-start, no crash loop)")

    # Seed only an EMPTY volume. On --replace the existing clone is somebody's
    # work-in-progress, and re-cloning over it would be destructive.
    probe = run(["docker", "run", "--rm", "-u", "1000:1000", "-v", "{}:/probe".format(work_v),
                 "--entrypoint", "sh", BASE_IMAGE, "-c",
                 "test -d /probe/archie-platform/.git && echo HAS_CLONE || echo EMPTY"],
                check=False)
    if "HAS_CLONE" in (probe.stdout or ""):
        say("  {} already holds a clone — leaving it alone".format(work_v))
    else:
        seed_clone(work_v)

    envf = stage_envfile(source, lane_name)
    try:
        cmd = [
            "docker", "run", "-d", "--name", name, "--restart", "unless-stopped",
            "--network", NETWORK, "--user", "1000:1000",
            "--env-file", envf, "-p", "127.0.0.1:{}:7681".format(port),
            "-v", "{}:/work".format(work_v),
            "-v", "{}:/opencode-home".format(home_v),
            "-v", "/mnt/archie_brain:/mnt/archie_brain:rw",
            "-v", "/var/run/docker.sock:/var/run/docker.sock:rw",
            "-v", "{}:{}:ro".format(SECRETS + "/mcp_bearer.txt", "/run/secrets/opencode_kb_bearer"),
            "-v", "{}:{}:ro".format(SECRETS + "/github_token.txt", "/run/secrets/opencode_github_token"),
        ]
        if host_file_exists(HOST_CLAUDE_SETTINGS):
            cmd += ["-v", "{}:{}:ro".format(HOST_CLAUDE_SETTINGS, HOST_CLAUDE_MOUNT)]
            say("  host Claude settings: daemon sees the file -> mounting (single file, ro)")
        else:
            say("  host Claude settings: daemon has no file at {} -> mounting NOTHING"
                .format(HOST_CLAUDE_SETTINGS))
            say("    (NOT an empty -v: docker would silently create a directory there)")
        cmd.append(GF_IMAGE)
        # -d starts it. No start/restart afterwards: a follow-up `docker start`
        # on a running container just errors.
        run(cmd)
    finally:
        if os.path.exists(envf):
            os.unlink(envf)   # key is now in the container env; drop the file

    say("  started '{}' on 127.0.0.1:{}".format(name, port))
    return name, port
def wait_healthy(name, tries=20):
    # 7681 is the port INSIDE the container (ttyd); the host port differs and is
    # irrelevant to this probe.
    probe = ("require('http').get('http://127.0.0.1:7681/',function(r){"
             "console.log('HTTP '+r.statusCode);process.exit(0)})"
             ".on('error',function(){process.exit(1)})")
    say("  waiting for ttyd on 7681 ...")
    restarts = 0
    for _ in range(tries):
        r = run(["docker", "exec", name, "node", "-e", probe], check=False)
        if "HTTP 200" in (r.stdout or ""):
            say("  -> ttyd healthy (HTTP 200)")
            return True
        # .State.Status is lowercase; a crash loop reads "restarting".
        st = (run(["docker", "inspect", name, "--format", "{{.State.Status}}"],
                  check=False).stdout or "").strip()
        if st == "restarting":
            say("  -> container is restart-looping ({} restarts so far)".format(restarts))
            return False
        time.sleep(2)
    say("  -> ttyd did not report healthy in time (last status: {})".format(st or "?"))
    return False
def teardown(name):
    guard_not_protected(name)
    if run(["docker", "inspect", name], check=False).returncode != 0:
        say("'{}' does not exist. Nothing to do.".format(name))
        return 0
    say("removing '{}' (and its volumes)".format(name))
    run(["docker", "rm", "-f", name], check=False)
    for v in ("{}_work".format(name), "{}_home".format(name)):
        run(["docker", "volume", "rm", "-f", v], check=False)
    say("  -> removed. The other two instances are untouched.")
    return 0

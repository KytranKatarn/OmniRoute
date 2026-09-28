"""Get a new lane to a usable state: the /work clone and the seeded config.

Order matters and is not incidental. /start.sh gates ALL of its git setup behind
`[ -d /work/archie-platform/.git ]`, so seed_clone() must happen before the
container first starts or the lane boots with no repo, no identity and no
credential helper. Volume ownership is fixed pre-start for the same reason: a
root-owned fresh volume makes /start.sh crash-loop, and there is no version of
"fix it after" that does not involve watching it crash.
"""

import subprocess

from .common import BASE_IMAGE, SECRETS, die, run, say
from .guards import host_file_exists


def remove_container(name):
    if run(["docker", "inspect", name], check=False).returncode == 0:
        say("  removing existing '{}'".format(name))
        run(["docker", "rm", "-f", name], check=False)


def seed_clone(work_v):
    """Clone the repo into the /work volume BEFORE the container first starts.

    /start.sh:85 gates ALL of its git setup behind `[ -d /work/archie-platform/.git ]`
    — identity, safe.directory, hooksPath and the credential helper. The base image
    bakes NO /work at all (verified: `ls /work` in the base image -> "No such file or
    directory"), so a FRESH volume leaves the lane with no repo, no git identity and
    no credential helper: opencode opens with nothing in scope and could not push.
    Seeding first makes that gate pass on the very first boot.

    Cloned from the MOUNTED LIVE TREE, not from GitHub: local, so no credential is
    needed to build the clone, and the history is identical to the canonical lane's.
    origin is then repointed at GitHub, because opencode-pr pushes to origin.

    The fetch is best-effort and honest about it — a clone that could not reach
    GitHub is a working lane on a slightly stale main, not a broken one, so this
    warns instead of dying. Everything else here fails closed.
    """
    say("  seeding the repo clone into {} ...".format(work_v))
    seed_sh = r'''
set -e
git clone --quiet /mnt/archie_brain /work/archie-platform
git -C /work/archie-platform remote set-url origin https://github.com/KytranKatarn/archie-platform.git
if [ -s /run/secrets/opencode_github_token ]; then
  T=$(cat /run/secrets/opencode_github_token)
  if git -C /work/archie-platform -c credential.helper="!f() { echo username=x-access-token; echo password=$T; }; f" \
       fetch --quiet origin --prune \
     && git -C /work/archie-platform checkout -q -B main origin/main; then
    echo "SEEDED_FETCHED"
  else
    echo "SEEDED_FETCH_FAILED"
  fi
else
  git -C /work/archie-platform checkout -q -B main 2>/dev/null || true
  echo "SEEDED_NO_TOKEN"
fi
echo "SEEDED_HEAD=$(git -C /work/archie-platform rev-parse --short HEAD 2>/dev/null || echo none)"
'''
    cmd = ["docker", "run", "--rm", "-u", "1000:1000",
           "-v", "{}:/work".format(work_v),
           "-v", "/mnt/archie_brain:/mnt/archie_brain:ro",
           "--entrypoint", "sh",
           BASE_IMAGE, "-c", seed_sh]
    # Only mount the token if the DAEMON sees a file there. A '-v SRC:/dst' whose
    # source is missing silently creates a DIRECTORY — mount nothing rather than
    # something that looks like the secret and is not.
    tok = SECRETS + "/github_token.txt"
    if host_file_exists(tok):
        cmd[2:2] = ["-v", "{}:/run/secrets/opencode_github_token:ro".format(tok)]
    r = run(cmd, check=False)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "SEEDED_" not in out:
        die("could not seed the repo clone into {}:\n{}".format(work_v, out.strip()[-500:]))
    if "SEEDED_FETCHED" in out:
        say("  clone seeded and fast-forwarded to origin/main")
    elif "SEEDED_NO_TOKEN" in out:
        say("  clone seeded from the live tree; no GitHub token, so main is whatever")
        say("  the live tree holds. A working lane, not an up-to-date one.")
    else:
        say("  WARNING: clone seeded but the fetch from GitHub FAILED — main may be stale")
    for line in out.strip().splitlines():
        if line.startswith("SEEDED_HEAD="):
            say("  clone HEAD {}".format(line.split("=", 1)[1]))
    # Prove it. A volume that stayed empty passes the container health check and
    # still opens with no codebase — which is the exact failure this prevents.
    chk = run(["docker", "run", "--rm", "-u", "1000:1000", "-v", "{}:/work".format(work_v),
               "--entrypoint", "git", BASE_IMAGE,
               "-C", "/work/archie-platform", "rev-parse", "--is-inside-work-tree"],
              check=False)
    if (chk.stdout or "").strip() != "true":
        die("seed verification failed: /work/archie-platform is not a git repo.")
    say("  -> clone verified present in the volume")


def seed_config(name, source):
    say("  seeding config from '{}'".format(source))
    r = run(["docker", "exec", "-u", "0", name, "mkdir", "-p",
             "/opencode-home/config/opencode"], check=False)
    if r.returncode != 0:
        return False
    tar = subprocess.run(
        ["docker", "exec", source, "tar", "-c", "-C", "/opencode-home/config/opencode", "."],
        capture_output=True)
    if tar.returncode != 0 or not tar.stdout:
        say("  WARNING: could not read config from source; skipping seed")
        return False
    untar = subprocess.run(
        ["docker", "exec", "-i", "-u", "0", name, "tar", "-x",
         "-C", "/opencode-home/config/opencode"], input=tar.stdout, capture_output=True)
    run(["docker", "exec", "-u", "0", name, "chown", "-R", "1000:1000", "/opencode-home"],
        check=False)
    return untar.returncode == 0

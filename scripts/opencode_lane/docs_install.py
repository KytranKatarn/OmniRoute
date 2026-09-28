"""Apply the tracked instruction set, and decide what it may touch.

The safety rule is the whole design. A file is overwritten ONLY when it still
byte-matches the seed (nobody has edited it) or our own manifest (we wrote it and
are upgrading our own output). Matching neither means a human changed it, and it
is left alone with a warning. An installer that "repairs" files it does not
recognise would silently revert someone's work on every run.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

from .common import die, run, say
from .docs import DOCS_DIRS, HANDOVER_DST, HANDOVER_REL, doc_files, lane_flavor


def plan_doc_install(current, desired, baseline, mine=None):
    """Decide what to do with one instruction file. Pure, so it can be tested.

    current  = bytes in the target container, or None if the file is absent
    desired  = the tracked copy in this repo
    baseline = the source container's copy, i.e. what seed_config just wrote
    mine     = sha256 of what THIS installer last wrote here, or None

    Five cases:

      absent    -> create it. The source lane may simply not have this file.
      == desired-> already correct; leave it alone. This is the common case on
                   a re-run, and it is what makes the whole thing idempotent.
      == baseline-> the freshly seeded, known-wrong copy. The only state we
                   overwrite without further evidence. Matching the source
                   exactly is the proof that nobody has edited it since.
      == mine    -> an older version WE wrote. Safe to upgrade, and without this
                   case the installer could never correct its own past output:
                   once it had installed a file, that file would match neither
                   the seed nor the new tracked copy, and would be reported as
                   "edited by a human" forever. Found the hard way, immediately
                   after shipping, by fixing one sentence in a doc I had written
                   the day before.
      otherwise -> someone changed it after seeding. LEAVE IT and say so.

    That last case is the whole point. The instance is a working terminal that
    a human may well have customised; an installer that "repairs" files it does
    not recognise would silently revert someone's work on every --apply. When
    the state is unrecognised the script is the confused one, not the file, and
    the only safe response is to stop and report.
    """
    if current is None:
        return "create"
    if current == desired:
        return "already"
    if baseline is not None and current == baseline:
        return "install"
    if mine and hashlib.sha256(current).hexdigest() == mine:
        return "install"
    return "custom"


MANIFEST_DST = "/opencode-home/data/.lane_docs_installed.json"
def _read_manifest(name):
    r = subprocess.run(["docker", "exec", name, "cat", MANIFEST_DST], capture_output=True)
    if r.returncode != 0 or not r.stdout.strip():
        return {}
    try:
        d = json.loads(r.stdout.decode("utf-8"))
        return d if isinstance(d, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}
def _write_manifest(name, data):
    _put_in_container(name, MANIFEST_DST,
                      json.dumps(data, indent=1, sort_keys=True).encode() + b"\n")
def _cat_in_container(name, path):
    r = subprocess.run(["docker", "exec", name, "cat", path], capture_output=True)
    return r.stdout if r.returncode == 0 else None
def _put_in_container(name, path, data):
    parent = os.path.dirname(path)
    run(["docker", "exec", "-u", "0", name, "mkdir", "-p", parent], check=False)
    w = subprocess.run(["docker", "exec", "-i", "-u", "0", name, "tee", path],
                       input=data, capture_output=True)
    run(["docker", "exec", "-u", "0", name, "chown", "1000:1000", path], check=False)
    return w.returncode == 0
def install_lane_docs(name, source, flavor=None):
    """Write the tracked instruction set into `name`. Idempotent, never clobbers.

    Returns True if every file ended up correct or was deliberately left alone.
    """
    flavor = flavor or lane_flavor(name)
    if flavor is None:
        say("  SKIPPING lane instructions: cannot tell whether '{}' is guarded or"
            .format(name))
        say("  guard-free, and installing the wrong set is worse than none.")
        return False
    docs_dir = DOCS_DIRS[flavor]
    say("  installing tracked '{}' lane instructions (scripts/{}/)".format(
        flavor, docs_dir.name))
    if not docs_dir.is_dir():
        say("    ERROR: {} not found — run this from the repo, not a copy".format(docs_dir))
        return False
    lane_docs = doc_files(docs_dir)
    baseline_ok = True
    counts = {"install": 0, "create": 0, "already": 0, "custom": 0, "failed": 0}
    custom = []
    manifest = _read_manifest(name)

    for rel in lane_docs:
        tracked = docs_dir / rel
        dst = "/opencode-home/config/opencode/" + rel
        desired = tracked.read_bytes()
        current = _cat_in_container(name, dst)
        baseline = _cat_in_container(source, dst)
        if baseline is None and current != desired:
            baseline_ok = False
        action = plan_doc_install(current, desired, baseline, manifest.get(rel))

        if action in ("create", "install") and current is not None:
            # Keep the pre-existing file, but never clobber an earlier backup.
            if _cat_in_container(name, dst + ".guard-bak") is None:
                _put_in_container(name, dst + ".guard-bak", current)
        if action in ("create", "install"):
            ok = _put_in_container(name, dst, desired)
            counts["install" if action == "install" else "create"] += 1
            if ok:
                manifest[rel] = hashlib.sha256(desired).hexdigest()
            say("    {}  {}".format("installed" if action == "install" else "created ", rel)
                + ("" if ok else "   (WRITE FAILED)"))
            if not ok:
                counts["failed"] += 1
        elif action == "already":
            manifest[rel] = hashlib.sha256(desired).hexdigest()
            counts["already"] += 1
        else:
            counts["custom"] += 1
            custom.append(rel)

    # Continuity: create only. Never overwrite a handover that exists.
    h_tracked = docs_dir / HANDOVER_REL
    if h_tracked.is_file() and _cat_in_container(name, HANDOVER_DST) is None:
        if _put_in_container(name, HANDOVER_DST, h_tracked.read_bytes()):
            say("    created  data/archie-handover.md (absent before — /archie-boot requires it)")
            counts["create"] += 1
        else:
            say("    WARNING: could not create {}".format(HANDOVER_DST))
            counts["failed"] += 1
    elif h_tracked.is_file():
        counts["already"] += 1

    if manifest:
        _write_manifest(name, manifest)
    say("    {} installed/created, {} already correct".format(
        counts["install"] + counts["create"], counts["already"]))
    if not baseline_ok:
        say("    NOTE: could not read the source copy of at least one file; anything")
        say("          already edited here is left untouched by design.")
    if custom:
        say("    WARNING: {} file(s) differ from BOTH the tracked copy and the seed"
            .format(len(custom)))
        for rel in custom:
            say("      {}  (edited after seeding — left as-is, diff it if unexpected)"
                .format(rel))
        say("    These are yours, not a bug in this script. Nothing was overwritten.")
    return counts["failed"] == 0

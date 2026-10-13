"""component_vps_pull.sh dumps Citadel's real databases and pulls them to the hub (task #7183).

The script is run for real in a sandbox. ssh/rsync/docker are exported shell FUNCTIONS (they beat PATH, which lib_common.sh resets) and
DOCKER_HOST is unreachable, so nothing can touch Citadel or the production backup_log. A fake "Citadel" is just a directory.
"""

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "backup" / "component_vps_pull.sh"

# Fake Citadel. FAKE_MISSING lists containers that "do not exist"; FAKE_SHORT lists containers whose pg_restore -l is too short (bad dump).
SHIMS = r"""
export CITADEL="$SANDBOX/citadel"
docker() {
  local a=("$@")
  if [[ "${a[0]}" == "exec" && "${a[1]}" == "-i" && "${a[2]}" == "archie_database" ]]; then cat >/dev/null; echo "$*" >> "$SHIM_LOG"; return 0; fi
  [[ "${a[0]}" == "exec" ]] && { shift; [[ "$1" == "-i" ]] && shift; ctr="$1"; shift; } || { ctr="${a[1]%%:*}"; }
  if [[ " $FAKE_MISSING " == *" ${ctr} "* ]]; then echo "Error: No such container: ${ctr}" >&2; return 1; fi
  case "$1" in
    pg_dump) head -c 4096 /dev/zero | tr '\0' 'x'; return 0 ;;
    pg_restore) cat >/dev/null; if [[ " $FAKE_SHORT " == *" ${ctr} "* ]]; then echo one; else seq 1 40; fi; return 0 ;;
    python3) return 0 ;;
    rm) return 0 ;;
    cat) printf 'SQLITE-SNAPSHOT-%s' "$ctr"; return 0 ;;
    cp) echo "docker cp cannot read a tmpfs /tmp" >&2; return 1 ;;
  esac
  return 0
}
export -f docker
# `ssh [opts] root@host 'remote command'` -> run the remote command locally against the fake Citadel
ssh() { local cmd="${@: -1}"; bash -c "$cmd"; }
export -f ssh
# `rsync -a root@host:/path dest/` -> plain copy
rsync() { local src="${@: -2:1}"; local dst="${@: -1}"; cp "${src#*:}" "$dst"; }
export -f rsync
"""


@pytest.fixture
def sandbox(tmp_path):
    env = {
        "PATH": os.environ["PATH"],
        "DOCKER_HOST": "unix:///nonexistent/docker.sock",
        "HOME": str(tmp_path),
        "SANDBOX": str(tmp_path),
        "SHIM_LOG": str(tmp_path / "shim.log"),
        "BACKUP_ROOT": str(tmp_path / "backups"),
        "BACKUP_LOG_FILE": str(tmp_path / "backup.log"),
        "BACKUP_VPS_REMOTE_DIR": str(tmp_path / "citadel" / "stage"),
        "FAKE_MISSING": "",
        "FAKE_SHORT": "",
    }
    (tmp_path / "backups").mkdir()
    (tmp_path / "citadel" / "stage").mkdir(parents=True)
    return tmp_path, env


def run(sandbox_, **override):
    tmp, env = sandbox_
    env = {**env, **override}
    run_dir = tmp / "run"
    r = subprocess.run(["bash", "-c", SHIMS + f"bash {SCRIPT} {run_dir}"], env={**env}, capture_output=True, text=True)
    return r, run_dir / "vps_pull", tmp / "citadel" / "stage"


def test_every_mapped_database_is_pulled_and_citadel_is_left_clean(sandbox):
    r, out, stage = run(sandbox)
    assert r.returncode == 0, r.stdout + r.stderr
    names = sorted(p.name.rsplit("_", 1)[0] for p in out.iterdir() if p.is_file())
    assert names == ["civic_watch", "gov_watch", "legal_watch", "market_watch", "wtf"], names
    assert (
        list(stage.iterdir()) == []
    ), "Citadel staging must be empty after a verified pull (no 0-byte or partial files left behind)"


def test_the_dead_thenews_entry_is_gone_and_no_old_container_naming_remains():
    code = "\n".join(line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#"))
    assert "thenews" not in code
    assert "${db}_db" not in code and "-U postgres" not in code


def test_a_missing_container_fails_the_run_loudly_but_the_others_are_still_dumped(sandbox):
    r, out, stage = run(sandbox, FAKE_MISSING="gov_watch_db")
    assert r.returncode == 1, "a vanished container must fail the component, not warn quietly"
    got = sorted(p.name.rsplit("_", 1)[0] for p in out.iterdir() if p.is_file())
    assert "gov_watch" not in got and {"wtf", "civic_watch", "legal_watch", "market_watch"} <= set(got)
    assert "VPS dump FAILED for gov_watch" in (sandbox[0] / "backup.log").read_text() + r.stdout + r.stderr


def test_a_dump_that_does_not_validate_is_rejected_and_leaves_no_file_anywhere(sandbox):
    r, out, stage = run(sandbox, FAKE_SHORT="what-the-fact-wtf-postgres-1")
    assert r.returncode == 1
    assert not any(p.name.startswith("wtf_") for p in out.iterdir()), "a bad dump must not reach the hub"
    assert list(stage.iterdir()) == [], "and must not leave a .partial on Citadel"


def test_the_hub_copy_is_checksum_verified_before_citadel_is_cleaned(sandbox):
    src = SCRIPT.read_text()
    assert src.index("sha256sum") < src.index("rm -f '${remote_file}'")


def test_vps_pull_reaches_the_usb_tier_and_retention_keeps_two_weeklies_there():
    """The pulled databases used to exist only on the hub's primary disk (Drive is too small): the USB must carry them too, and the
    retention table must say how many, or the USB tier would fill the disk or prune them away."""
    import importlib.util

    root = SCRIPT.parent
    spec = importlib.util.spec_from_file_location("tier_sync_usb", root / "tier_sync_usb.py")
    usb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(usb)
    assert "vps_pull" in usb.TIER_COMPONENTS
    spec = importlib.util.spec_from_file_location("retention_prune", root / "retention_prune.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    assert rp.RETENTION["vps_pull"]["usb"] == (0, 2, 0)

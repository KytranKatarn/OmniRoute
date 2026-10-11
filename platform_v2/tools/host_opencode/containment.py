"""
Host OpenCode containment helpers — placement evidence plus verification.

Proves, for a given runner PID, that it cannot migrate out of its assigned
cgroup, reach the supervisor control channel, or read issuer secrets. All
filesystem/kernel reads go through injectable callables so fixtures stay
deterministic. Nothing here starts supervision or admits replacements.
"""

import os
from typing import Callable, Dict, List, Optional, Tuple

SUPERVISOR_OWNED_MARKERS = (
    "broker.sock",
    "broker_private.key",
    "broker_journal.db",
)


def place_in_cgroup(pid: int, cgroup_procs: str) -> bool:
    """Best-effort placement of a PID into a cgroup (echo pid > cgroup.procs).

    Returns True only when the write succeeds. Callers must follow with
    verify_confinement — placement alone proves nothing.
    """
    try:
        with open(cgroup_procs, "w") as handle:
            handle.write(str(int(pid)))
        return True
    except (OSError, ValueError, TypeError):
        return False


def read_proc_cgroup(
    pid: int,
    *,
    read_fn: Optional[Callable[[int], Optional[str]]] = None,
) -> Optional[str]:
    """Read a process's cgroup path. Injectable for fixtures."""
    if read_fn is not None:
        try:
            return read_fn(pid)
        except Exception:
            return None
    try:
        with open(f"/proc/{int(pid)}/cgroup", "r") as handle:
            line = handle.read().strip().split("\n")[0]
    except (OSError, IndexError, ValueError):
        return None
    return line.split("name=")[-1] if "name=" in line else line


def verify_confinement(
    pid: int,
    expected_cgroup: str,
    *,
    read_fn: Optional[Callable[[int], Optional[str]]] = None,
    member_pids_fn: Optional[Callable[[str], Optional[List[int]]]] = None,
) -> Tuple[bool, str]:
    """Verify a runner PID is confined to its assigned cgroup.

    Checks the process's own cgroup record AND its membership in the
    cgroup's procs listing. Either check failing means not confined.
    """
    if not expected_cgroup:
        return False, "no expected cgroup"
    actual = read_proc_cgroup(pid, read_fn=read_fn)
    if actual is None:
        return False, "could not read process cgroup"
    want = expected_cgroup.strip().rstrip("/")
    got = actual.strip().rstrip("/")
    if want != got and not got.startswith(want + "/"):
        return False, f"cgroup mismatch: assigned={want}, actual={got}"
    if member_pids_fn is not None:
        try:
            members = member_pids_fn(want)
        except Exception:
            return False, "could not list cgroup members"
        if not isinstance(members, list) or int(pid) not in members:
            return False, "pid absent from cgroup procs"
    return True, "confinement confirmed"


def verify_isolation(
    runner_root: str,
    *,
    exists_fn: Optional[Callable[[str], bool]] = None,
    supervisor_paths: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """Verify supervisor-owned paths are not reachable from the runner root.

    Fails closed when the check itself cannot run. `exists_fn(path)` answers
    whether `path` is visible inside the runner's mount view; any supervisor
    marker (socket, signing key, journal) visible there fails the check.
    """
    markers = list(supervisor_paths) if supervisor_paths else list(SUPERVISOR_OWNED_MARKERS)
    if not runner_root:
        return False, "no runner root"

    def _checker(path: str) -> bool:
        if exists_fn is not None:
            return bool(exists_fn(path))
        try:
            return os.path.exists(os.path.join(runner_root, os.path.basename(path)))
        except Exception:
            return True  # fail closed: check failure counts as visible

    try:
        for marker in markers:
            if _checker(marker):
                return False, f"supervisor path visible to runner: {marker}"
    except Exception:
        return False, "isolation check failed"
    return True, "isolation confirmed"


def process_reaped(
    pid: int,
    *,
    exists_fn: Optional[Callable[[int], bool]] = None,
) -> Optional[bool]:
    """Reaping evidence for a PID: True=reaped, False=still present, None=unknown.

    A zombie still has a /proc entry, so it counts as NOT reaped — the
    supervisor reaper has not accounted for the child exit yet.
    """
    try:
        if exists_fn is not None:
            alive = exists_fn(pid)
        else:
            alive = os.path.exists(f"/proc/{int(pid)}")
    except Exception:
        return None
    if alive is None:
        return None
    return not bool(alive)


def evidence_bundle(
    pid: int,
    expected_cgroup: str,
    runner_root: str,
    *,
    read_fn: Optional[Callable[[int], Optional[str]]] = None,
    member_pids_fn: Optional[Callable[[str], Optional[List[int]]]] = None,
    exists_fn: Optional[Callable[[str], bool]] = None,
    proc_exists_fn: Optional[Callable[[int], bool]] = None,
) -> Dict[str, object]:
    """Collect the full containment evidence bundle for one runner PID."""
    confined, confinement_detail = verify_confinement(
        pid, expected_cgroup, read_fn=read_fn, member_pids_fn=member_pids_fn
    )
    isolated, isolation_detail = verify_isolation(runner_root, exists_fn=exists_fn)
    reaped = process_reaped(pid, exists_fn=proc_exists_fn)
    return {
        "confined": confined,
        "confinement_detail": confinement_detail,
        "isolated": isolated,
        "isolation_detail": isolation_detail,
        "reaped": reaped,
    }

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

# Default isolation surface: the actual absolute supervisor paths. Bare
# basenames alone are unsafe — a private key visible at a nested runner
# path (e.g. <root>/var/lib/.../broker_private.key) would pass a
# basename-only check. Absolute defaults make the nested-mirror check
# meaningful without caller configuration.
DEFAULT_SUPERVISOR_PATHS = (
    "/run/host-opencode-broker/broker.sock",
    "/var/lib/host-opencode/keys/broker_private.key",
    "/var/lib/host-opencode/keys/broker_public.key",
    "/var/lib/host-opencode/broker_journal.db",
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


def _default_realpath(path: str) -> str:
    return os.path.realpath(path)


def verify_isolation(
    runner_root: str,
    *,
    exists_fn: Optional[Callable[[str], bool]] = None,
    realpath_fn: Optional[Callable[[str], str]] = None,
    isdir_fn: Optional[Callable[[str], bool]] = None,
    supervisor_paths: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    """Verify supervisor-owned paths are not reachable from the runner root.

    Per supervisor path (absolute host paths, not bare markers):
    1. the resolved path must not sit inside the resolved runner root
       (catches symlink redirection into the worktree);
    2. neither the basename copy at the root nor the nested mirror of the
       absolute path (e.g. `<root>/var/lib/host-opencode/keys/...`) may
       exist (catches leaked copies at any depth we can name);
    3. any check failure fails closed.
    The runner root itself must exist and be a directory: a missing or
    unreadable root reports confirmed isolation otherwise, which is wrong.
    """
    markers = list(supervisor_paths) if supervisor_paths else list(DEFAULT_SUPERVISOR_PATHS)
    if not runner_root:
        return False, "no runner root"
    resolve = realpath_fn if realpath_fn is not None else _default_realpath
    isdir = isdir_fn if isdir_fn is not None else os.path.isdir

    def _visible(path: str) -> bool:
        if exists_fn is not None:
            return bool(exists_fn(path))
        try:
            return os.path.exists(path)
        except Exception:
            return True  # fail closed: check failure counts as visible

    try:
        try:
            root_is_dir = isdir(runner_root)
        except Exception:
            return False, "cannot stat runner root"
        if root_is_dir is not True:
            return False, "runner root missing or not a directory"
        root_real = resolve(runner_root)
    except Exception:
        return False, "cannot resolve runner root"
    if not isinstance(root_real, str) or not root_real:
        return False, "cannot resolve runner root"
    root_prefix = root_real.rstrip("/") + "/"
    try:
        for marker in markers:
            try:
                target_real = resolve(marker)
            except Exception:
                return False, f"cannot resolve supervisor path: {marker}"
            if not isinstance(target_real, str) or not target_real:
                return False, f"cannot resolve supervisor path: {marker}"
            if target_real == root_real or target_real.startswith(root_prefix):
                return False, f"supervisor path inside runner tree: {marker}"
            candidates = [os.path.join(root_real, os.path.basename(target_real))]
            rel = target_real.lstrip("/")
            if rel:
                candidates.append(os.path.join(root_real, rel))
            for candidate in candidates:
                if _visible(candidate):
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
    realpath_fn: Optional[Callable[[str], str]] = None,
    isdir_fn: Optional[Callable[[str], bool]] = None,
    expected_pids: Optional[List[int]] = None,
    reap_confirmed_fn: Optional[Callable[[int], Optional[bool]]] = None,
) -> Dict[str, object]:
    """Collect the full containment evidence bundle for one runner PID.

    `reaped` is True only when the reaper confirms every expected PID
    accounted for. PID disappearance alone (or a missing inventory) yields
    None (unknown) or False — never a positive reaping claim.
    """
    confined, confinement_detail = verify_confinement(
        pid, expected_cgroup, read_fn=read_fn, member_pids_fn=member_pids_fn
    )
    isolated, isolation_detail = verify_isolation(
        runner_root, exists_fn=exists_fn, realpath_fn=realpath_fn, isdir_fn=isdir_fn
    )
    reaped: Optional[bool] = None
    if isinstance(expected_pids, list) and len(expected_pids) > 0 and reap_confirmed_fn is not None:
        try:
            confirmations = [reap_confirmed_fn(int(p)) for p in expected_pids]
        except Exception:
            confirmations = [None]
        if all(c is True for c in confirmations):
            reaped = True
        else:
            reaped = False
    return {
        "confined": confined,
        "confinement_detail": confinement_detail,
        "isolated": isolated,
        "isolation_detail": isolation_detail,
        "reaped": reaped,
    }

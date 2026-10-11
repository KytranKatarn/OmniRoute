"""
Host OpenCode independent observers — Docker, host/cgroup, publication.

Each observer re-observes kernel/Docker/GitHub state itself; caller-supplied
stop claims are never trusted. All boundaries are injectable so the
deterministic fixture suite can prove every failure mode stays UNKNOWN/False
without Docker, systemd, or network access.

Return contract (matches broker.check_trusted_completion):
- Docker: {"id", "state", "restart_disabled", "labels_match"} or None
- Host: {"cgroup_empty", "service"} or None
- Publication: {"settled"} or None

None means UNKNOWN — the broker treats it as rejection, never as positive
evidence. Supervised execution and replacement admission stay off; these
helpers only observe, they never start/stop anything.
"""

from typing import Any, Callable, Dict, Optional

TERMINAL_DOCKER_STATUSES = frozenset({"stopped", "exited", "dead", "removing"})
RESTART_DISABLED_POLICIES = frozenset({"", "no", "none"})
STOPPED_SERVICES = frozenset({"inactive", "dead"})


def _is_full_id(value: Any) -> bool:
    """A Docker full ID is 64 hex chars. Anything shorter (names, short IDs,
    prefixes) is NOT an identity — it must be resolved first."""
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def resolve_container_id(
    name: str,
    inspect_fn: Callable[[str], Optional[Dict[str, Any]]],
) -> Optional[str]:
    """Resolve a daemon name to its full container ID, or None.

    The resolved ID must itself be a full ID; a daemon answering a name
    query with a non-ID is a mismatch, not an identity.
    """
    try:
        info = inspect_fn(name)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    full_id = info.get("Id")
    if not _is_full_id(full_id):
        return None
    return str(full_id).lower()


def _norm(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text if text else None


def observe_docker(
    container_name: str,
    assignment_id: str,
    *,
    inspect_fn: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None,
    expected_labels: Optional[Dict[str, str]] = None,
    pinned_full_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Independently inspect the exact Docker container.

    Returns evidence only when ALL hold: the daemon resolves the target to a
    single container whose full ID equals the durably pinned ID recorded at
    discovery, the sealed target matches (exact full ID, or name plus
    ownership labels), its state is terminal with all flags explicitly
    present, restart is explicitly disabled, and expected ownership labels
    match. A name-only target with no pinned ID always fails: resolution
    happens at discovery time, and terminal observation requires the pin.
    Anything else returns None.
    """
    if inspect_fn is None:
        return None
    if not container_name or not assignment_id:
        return None
    try:
        info = inspect_fn(container_name)
    except Exception:
        return None
    if not isinstance(info, dict):
        return None

    full_id = info.get("Id")
    if not _is_full_id(full_id):
        return None
    full_id = str(full_id).lower()
    if pinned_full_id is None or not _is_full_id(pinned_full_id):
        # No durably pinned identity for this observation: a name-only
        # target cannot produce positive stop evidence on its own.
        return None
    if full_id != str(pinned_full_id).lower():
        return None
    if _is_full_id(container_name):
        # Sealed target is a full ID: the daemon ID must equal it exactly.
        # Name equality alone is rejected — names are reusable, IDs are not.
        if full_id != str(container_name).lower():
            return None
    else:
        # Sealed target is a broker-assigned name: it must match the
        # daemon-reported name, and ownership labels (checked below) bind
        # this exact container to the assignment.
        import re as _re

        if _re.fullmatch(r"[0-9a-fA-F]+", container_name) and len(container_name) != 64:
            # Hex-like but shorter than a full ID: an ambiguous short-ID /
            # prefix target. It could resolve to several containers across
            # time, so it is never an identity — even with matching labels.
            return None
        daemon_name = info.get("Name", "")
        if not isinstance(daemon_name, str) or daemon_name.lstrip("/") != container_name:
            return None

    state = info.get("State")
    if not isinstance(state, dict):
        return None
    # Every flag must be explicitly present: a missing Status, Running,
    # Restarting, or Paused key is UNKNOWN, never a default-false.
    for flag in ("Status", "Running", "Restarting", "Paused"):
        if flag not in state:
            return None
    status = _norm(state.get("Status"))
    if status not in TERMINAL_DOCKER_STATUSES:
        return None
    if state.get("Running") is not False:
        return None
    if state.get("Restarting") is not False:
        return None
    if state.get("Paused") is not False:
        return None

    try:
        host_config = info.get("HostConfig")
        restart_section = host_config.get("RestartPolicy") if isinstance(host_config, dict) else None
        policy_name = restart_section.get("Name") if isinstance(restart_section, dict) else None
    except (AttributeError, TypeError):
        return None
    if not isinstance(policy_name, str):
        # A missing restart policy proves nothing about restart behavior.
        return None
    if (_norm(policy_name) or "") not in RESTART_DISABLED_POLICIES:
        return None

    labels = info.get("Config", {}).get("Labels") if isinstance(info.get("Config"), dict) else None
    if labels is None:
        labels = info.get("Labels")
    if not isinstance(labels, dict) or not labels:
        # Ownership labels are mandatory on every path — including sealed
        # full-ID targets. An ID with no labels cannot be bound to the
        # assignment that claims it.
        return None
    if not expected_labels:
        return None
    for key, want in expected_labels.items():
        if labels.get(key) != want:
            return None

    return {
        "id": container_name,
        "full_id": full_id,
        "state": status,
        "restart_disabled": True,
        "labels_match": True,
    }


def observe_host(
    cgroup: str,
    assignment_id: str,
    *,
    service_state_fn: Optional[Callable[[str], Optional[str]]] = None,
    cgroup_pids_fn: Optional[Callable[[str], Optional[list]]] = None,
    service_unit: Optional[str] = None,
    expected_pids: Optional[list] = None,
    reap_confirmed_fn: Optional[Callable[[int], Optional[bool]]] = None,
) -> Optional[Dict[str, Any]]:
    """Independently verify host service stop, cgroup quiescence, and reaping.

    Returns evidence only when ALL hold: the owned service reports stopped,
    the cgroup (plus descendants, via the injected listing) is empty on two
    consecutive reads, AND the supervisor reaper confirms every expected
    runner PID accounted for. PID disappearance alone never establishes an
    accounted-for exit — only the reaper's explicit confirmation does — and
    a missing or empty PID inventory stays UNKNOWN.
    """
    if service_state_fn is None or cgroup_pids_fn is None:
        return None
    if not cgroup or not assignment_id:
        return None
    try:
        raw_state = service_state_fn(service_unit or cgroup)
        first = cgroup_pids_fn(cgroup)
    except Exception:
        return None
    if _norm(raw_state) not in STOPPED_SERVICES:
        return None
    if not isinstance(first, list):
        return None
    if len(first) != 0:
        return None
    # Second consecutive read: guards against a snapshot racing a fork.
    try:
        second = cgroup_pids_fn(cgroup)
    except Exception:
        return None
    if not isinstance(second, list) or len(second) != 0:
        return None
    # A missing or empty PID inventory proves nothing: without named PIDs
    # there is no exit the reaper could have accounted for.
    if not isinstance(expected_pids, list) or len(expected_pids) == 0:
        return None
    if reap_confirmed_fn is None:
        return None
    try:
        confirmations = []
        for pid in expected_pids:
            confirmed = reap_confirmed_fn(int(pid))
            if confirmed is not True:
                # False, None, or unreadable: the exit is not accounted for.
                return None
            confirmations.append(True)
        if not confirmations:
            return None
    except Exception:
        return None
    return {"cgroup_empty": True, "service": "stopped", "reaped": True}


def make_publication_observer(
    repo: str,
    branch: str,
    get_push_status: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
    get_pr_status: Optional[Callable[[], Optional[Dict[str, Any]]]] = None,
) -> Callable[[str], Optional[Dict[str, Any]]]:
    """Bind publication reconciliation to an exact repo/branch.

    Returns an observer taking assignment_id. Settled=True only when the
    push is positively confirmed AND the PR state is unambiguous (an open or
    merged PR whose head matches the pushed SHA, or a positively confirmed
    absence — never an elapsed grace period or a single empty lookup). A
    timed-out create that may have succeeded remotely stays UNKNOWN.
    """

    def _observe(assignment_id: str) -> Optional[Dict[str, Any]]:
        if get_push_status is None or get_pr_status is None:
            return None
        if not assignment_id or not repo or not branch:
            return None
        try:
            push = get_push_status()
            pr = get_pr_status()
        except Exception:
            return None
        if not isinstance(push, dict) or not isinstance(pr, dict):
            return None
        if push.get("confirmed") is not True:
            return None
        # Outstanding operations must be explicitly reported as settled:
        # a missing key defaults to UNKNOWN, never to settled.
        pending = push.get("pending_ops", "UNKNOWN")
        if not isinstance(pending, list) or len(pending) != 0:
            return None
        pushed_sha = push.get("sha")
        if not isinstance(pushed_sha, str) or not pushed_sha:
            return None
        # Every settling path is bound to this exact repo/branch — including
        # absence: a proof scoped to another repo or branch proves nothing.
        if pr.get("repo") != repo or pr.get("branch") != branch:
            return None
        # The PR side has its own outstanding-operation surface: a pending
        # create (or any pending PR operation) means the remote state is
        # still in flight, even when the push side looks settled.
        pr_pending = pr.get("pending_ops", "UNKNOWN")
        if not isinstance(pr_pending, list) or len(pr_pending) != 0:
            return None
        if pr.get("pending_create") is True:
            return None
        pr_state = _norm(pr.get("state"))
        if pr_state in ("open", "merged"):
            if pr.get("head_sha") != pushed_sha:
                return None
            return {
                "settled": True,
                "assignment_id": assignment_id,
                "repo": repo,
                "branch": branch,
                "head_sha": pushed_sha,
            }
        if pr_state == "absent":
            # Absence is only proof with a positive confirmation marker —
            # e.g. a listing that covers the repo namespace — never a bare
            # empty lookup.
            if pr.get("absence_proof") is not True:
                return None
            return {
                "settled": True,
                "assignment_id": assignment_id,
                "repo": repo,
                "branch": branch,
                "head_sha": pushed_sha,
            }
        # "unknown", "timeout", "ambiguous", "pending", missing state: UNKNOWN.
        return None

    return _observe

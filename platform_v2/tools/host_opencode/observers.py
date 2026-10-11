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
) -> Optional[Dict[str, Any]]:
    """Independently inspect the exact Docker container.

    Returns evidence only when ALL hold: the daemon resolves the name to a
    single container, its full ID matches the sealed assignment target, its
    state is terminal, restart is disabled, and expected ownership labels
    match. Anything else (live container, pending start, label/ID mismatch,
    daemon error) returns None.
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
    if not isinstance(full_id, str) or not full_id:
        return None
    # The sealed target may be a full ID or a broker-assigned name; the
    # daemon-resolved identity must equal it exactly — never by prefix.
    if full_id != container_name and info.get("Name", "").lstrip("/") != container_name:
        return None

    state = info.get("State")
    if not isinstance(state, dict):
        return None
    status = _norm(state.get("Status"))
    if status not in TERMINAL_DOCKER_STATUSES:
        return None
    if state.get("Running") is True or state.get("Restarting") is True:
        return None
    if state.get("Paused") is True:
        return None

    restart_policy = ""
    try:
        restart_policy = _norm(info.get("HostConfig", {}).get("RestartPolicy", {}).get("Name")) or ""
    except (AttributeError, TypeError):
        return None
    if restart_policy not in RESTART_DISABLED_POLICIES:
        return None

    labels = info.get("Config", {}).get("Labels") or info.get("Labels") or {}
    if not isinstance(labels, dict):
        return None
    if expected_labels:
        for key, want in expected_labels.items():
            if labels.get(key) != want:
                return None

    return {
        "id": container_name,
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
) -> Optional[Dict[str, Any]]:
    """Independently verify host service stop and cgroup quiescence.

    Returns evidence only when the owned service reports stopped AND the
    cgroup (plus descendants, via the injected listing) is empty. An empty
    cgroup.procs snapshot alone is insufficient — the caller must supply a
    listing that covers descendants, and reaping is confirmed by a second
    consecutive empty read.
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
    return {"cgroup_empty": True, "service": "stopped"}


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
        pushed_sha = push.get("sha")
        if not isinstance(pushed_sha, str) or not pushed_sha:
            return None
        pr_state = _norm(pr.get("state"))
        if pr_state in ("open", "merged"):
            if pr.get("head_sha") != pushed_sha:
                return None
            if pr.get("repo") != repo or pr.get("branch") != branch:
                return None
            return {"settled": True}
        if pr_state == "absent":
            # Absence is only proof with a positive confirmation marker —
            # e.g. a listing that covers the repo namespace — never a bare
            # empty lookup.
            if pr.get("absence_proof") is not True:
                return None
            return {"settled": True}
        # "unknown", "timeout", "ambiguous", missing state: UNKNOWN.
        return None

    return _observe

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


# ============================================================================
# Live clients — read-only host boundaries for the activation phase.
# NOT used by broker_main (fail-closed stubs stay until owner authorization).
# Every helper fails closed (None) on any error, timeout, or ambiguity.
# ============================================================================

DOCKER_INSPECT_TIMEOUT = 10
SYSTEMCTL_TIMEOUT = 10
GITHUB_TIMEOUT = 15


def docker_inspect_live(name, *, run_fn=None):
    """Read-only `docker inspect` for one container. Returns the inspect
    dict or None. Never starts, stops, or creates anything."""
    import json as _json
    import subprocess as _sp

    run = run_fn if run_fn is not None else _sp.run
    if not isinstance(name, str) or not name:
        return None
    try:
        proc = run(
            ["docker", "inspect", "--format", "{{json .}}", name],
            capture_output=True,
            text=True,
            timeout=DOCKER_INSPECT_TIMEOUT,
        )
    except Exception:
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    try:
        data = _json.loads((getattr(proc, "stdout", "") or "").strip())
    except Exception:
        return None
    if isinstance(data, list):
        if len(data) != 1:
            return None
        data = data[0]
    return data if isinstance(data, dict) else None


def make_live_docker_observer(expected_labels=None, *, inspect_fn=None):
    """Observer closure using live `docker inspect` (or an injected fake)."""
    live_inspect = inspect_fn if inspect_fn is not None else docker_inspect_live

    def _observe(container_name, assignment_id, pinned_full_id=None):
        return observe_docker(
            container_name,
            assignment_id,
            inspect_fn=live_inspect,
            expected_labels=expected_labels,
            pinned_full_id=pinned_full_id,
        )

    return _observe


def systemd_state_live(unit, *, run_fn=None):
    """Read-only `systemctl is-active` for one unit. Returns the state
    string or None."""
    import subprocess as _sp

    run = run_fn if run_fn is not None else _sp.run
    if not isinstance(unit, str) or not unit:
        return None
    try:
        proc = run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=SYSTEMCTL_TIMEOUT,
        )
    except Exception:
        return None
    out = (getattr(proc, "stdout", "") or "").strip().lower()
    return out if out else None


def cgroup_pids_live(path, *, read_fn=None, walk_fn=None):
    """List all PIDs in a cgroup subtree (cgroup.procs at every level).

    Returns a sorted list of ints, [] when quiescent, or None when any
    level is unreadable. Both the walk and the reads are injectable so
    fixtures never touch the real cgroupfs.
    """
    import os as _os

    if not isinstance(path, str) or not path:
        return None
    try:
        collected = set()
        unreadable = False

        def _onerror(_err):
            nonlocal unreadable
            unreadable = True

        if walk_fn is not None:
            walk_iter = walk_fn(path)
        else:
            walk_iter = _os.walk(path, onerror=_onerror)

        if read_fn is not None:
            read = read_fn
        else:
            def read(p):
                with open(p, "r") as handle:
                    return handle.read()

        for root, _dirs, files in walk_iter:
            if unreadable:
                return None
            if "cgroup.procs" not in files:
                continue
            text = read(_os.path.join(root, "cgroup.procs"))
            for token in str(text).split():
                if token.lstrip("-").isdigit():
                    collected.add(int(token))
        if unreadable:
            return None
    except Exception:
        return None
    return sorted(collected)


def github_api_get_live(url, token, *, get_fn=None):
    """Read-only GitHub REST GET. Returns parsed JSON or None."""
    try:
        import requests as _requests
    except Exception:
        return None
    get = get_fn if get_fn is not None else _requests.get
    if not isinstance(url, str) or not url.startswith("https://api.github.com/"):
        return None
    if not isinstance(token, str) or not token:
        return None
    try:
        resp = get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "ARCHIE-broker-observer",
            },
            timeout=GITHUB_TIMEOUT,
        )
    except Exception:
        return None
    if getattr(resp, "status_code", 0) != 200:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    return data if isinstance(data, (dict, list)) else None


def make_live_host_observer(
    service_unit,
    cgroup_path,
    *,
    expected_pids=None,
    reap_confirmed_fn=None,
    state_fn=None,
    pids_fn=None,
):
    """Observer closure using live systemd/cgroup reads (or injected fakes)."""
    _state = state_fn if state_fn is not None else systemd_state_live
    _pids = pids_fn if pids_fn is not None else cgroup_pids_live

    def _observe(cgroup, assignment_id):
        return observe_host(
            cgroup or cgroup_path,
            assignment_id,
            service_state_fn=lambda u: _state(service_unit or u),
            cgroup_pids_fn=lambda c: _pids(cgroup_path if not c else c),
            service_unit=service_unit,
            expected_pids=expected_pids,
            reap_confirmed_fn=reap_confirmed_fn,
        )

    return _observe


def make_live_publication_observer(repo, branch, sha, token, *, api_get_fn=None):
    """Observer closure reconciling one push + PR state via live GitHub reads.

    Push confirmation comes from the compare endpoint (base...head); PR
    state from a head-filtered pulls listing. Any ambiguity stays UNKNOWN.
    """
    getter = api_get_fn if api_get_fn is not None else github_api_get_live

    def _observe(assignment_id):
        compare = getter(f"https://api.github.com/repos/{repo}/compare/{branch}...{sha}", token)
        if not isinstance(compare, dict):
            return None
        # Confirmation requires the compare to reference our exact head SHA.
        head_commit = compare.get("head_commit") or {}
        commits = compare.get("commits") or []
        shas = {head_commit.get("sha")} | {c.get("sha") for c in commits if isinstance(c, dict)}
        if sha not in shas:
            return None
        pulls = getter(f"https://api.github.com/repos/{repo}/pulls?state=open&head={sha}", token)
        if pulls is None:
            return None
        return make_publication_observer(
            repo,
            branch,
            get_push_status=lambda: {"confirmed": True, "sha": sha},
            get_pr_status=lambda: _pr_view(pulls, repo, branch, sha),
        )(assignment_id)

    return _observe


def _pr_view(pulls, repo, branch, sha):
    """Reduce a pulls listing to the observer's PR view. Open PRs whose
    head matches win; otherwise UNKNOWN (absence needs a namespace-wide
    listing the live path does not claim)."""
    if isinstance(pulls, dict):
        items = pulls.get("items", [])
    elif isinstance(pulls, list):
        items = pulls
    else:
        return {"state": "unknown"}
    if not isinstance(items, list):
        return {"state": "unknown"}
    for item in items:
        if not isinstance(item, dict):
            continue
        head = item.get("head") or {}
        base = item.get("base") or {}
        if (
            isinstance(head, dict)
            and head.get("sha") == sha
            and isinstance(base, dict)
            and base.get("repo", {}).get("full_name") == repo
            and base.get("ref") == branch
        ):
            state = item.get("state", "open")
            return {
                "state": state if state in ("open", "merged") else "unknown",
                "head_sha": sha,
                "repo": repo,
                "branch": branch,
                "pending_ops": [] if state in ("open", "merged") else ["unknown"],
            }
    return {"state": "unknown"}


def json_dumps_safe(value):
    """Best-effort JSON dump for substring checks; never raises."""
    import json as _json

    try:
        return _json.dumps(value, sort_keys=True, default=str)
    except Exception:
        return ""

"""Cockpit -> hub proxy for the Crew and Code Builder panes (#6653 Phase 4).

Same shape as approvals_proxy: PLATFORM_URL + Bearer INTERNAL_API_KEY read at call time,
Docker-internal hostname only. Unlike the approvals proxy this one PASSES THROUGH the
hub's status code and JSON so the UI can show the hub's own error text verbatim — no
fail-soft empties, no optimistic success. Transport/config failures are 503 dicts.
"""

import os

import requests

READ_TIMEOUT = 15
WRITE_TIMEOUT = 30
ACTIONS = ("assign", "shift-state", "skills/add", "skills/remove", "budget")
TASK_ACTIONS = ("status", "priority", "note", "delegate")
_TASK_LIST_KEYS = ("q", "project_id", "status", "min_priority", "limit", "offset")


def _base():
    return os.getenv("PLATFORM_URL", "http://archie_platform:3000").rstrip("/")


def _call(method, path, json=None, params=None):
    key = os.getenv("INTERNAL_API_KEY", "")
    if not key:
        return 503, {"success": False, "error": "comms is not configured to reach the hub (no internal key)"}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    timeout = WRITE_TIMEOUT if method == "POST" else READ_TIMEOUT
    try:
        r = requests.request(method, f"{_base()}{path}", json=json, headers=headers, timeout=timeout, params=params)
    except requests.RequestException as exc:
        return 503, {"success": False, "error": f"hub unreachable: {exc.__class__.__name__}"}
    try:
        data = r.json()
    except ValueError:
        data = {"success": False, "error": f"HTTP {r.status_code}"}
    if not isinstance(data, dict):
        data = {"success": False, "error": "unexpected hub response"}
    return r.status_code, data


def _int(v, name):
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer")


# ---- Crew ----------------------------------------------------------------------------
def list_agents(params):
    allowed = {k: v for k, v in (params or {}).items() if k in ("q", "department", "state", "worker_type", "limit", "offset", "include_decommissioned")}
    return _call("GET", "/api/internal/agents", params=allowed)


def get_agent(agent_id):
    return _call("GET", f"/api/internal/agents/{_int(agent_id, 'agent_id')}")


def create_agent(body):
    return _call("POST", "/api/internal/agents/create", json=body or {})


def agent_action(agent_id, action, body):
    if action not in ACTIONS:
        return 400, {"success": False, "error": f"unknown action {action!r}"}
    return _call("POST", f"/api/internal/agents/{_int(agent_id, 'agent_id')}/{action}", json=body or {})


# ---- Code Builder --------------------------------------------------------------------
def build_providers():
    return _call("GET", "/api/internal/cloud-code/providers")


def build_run(body):
    return _call("POST", "/api/internal/cloud-code/run", json=body or {})


def build_status(job_id):
    return _call("GET", f"/api/internal/cloud-code/run/{_int(job_id, 'job_id')}")


def build_runs(limit=20):
    return _call("GET", "/api/internal/cloud-code/runs", params={"limit": _int(limit, "limit")})


# ---- Work pane: projects + tasks (#6679 Phase 4b) --------------------------------------
def list_projects(params):
    allowed = {k: v for k, v in (params or {}).items() if k in ("status", "limit", "offset")}
    return _call("GET", "/api/internal/projects", params=allowed)


def list_tasks(params):
    allowed = {k: v for k, v in (params or {}).items() if k in _TASK_LIST_KEYS}
    return _call("GET", "/api/internal/tasks", params=allowed)


def get_task(task_id):
    return _call("GET", f"/api/internal/tasks/{_int(task_id, 'task_id')}")


def create_task(body):
    return _call("POST", "/api/internal/tasks", json=body or {})


def task_action(task_id, action, body):
    if action not in TASK_ACTIONS:
        return 400, {"success": False, "error": f"unknown action {action!r}"}
    return _call("POST", f"/api/internal/tasks/{_int(task_id, 'task_id')}/{action}", json=body or {})


# ---- Code Builder: apply (#6680 Phase 4b) ----------------------------------------------
def build_apply(job_id):
    return _call("POST", f"/api/internal/cloud-code/run/{_int(job_id, 'job_id')}/apply", json={})

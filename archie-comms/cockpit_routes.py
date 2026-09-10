"""Cockpit page + /api/cockpit/* routes (#6653 Phase 4). Session-gated like the
approvals routes (session['user_id']); every hub call goes through
services.cockpit_proxy, which passes the hub's status + JSON through verbatim.
A Blueprint so it is testable without importing app_comms."""

from functools import wraps

from flask import Blueprint, jsonify, redirect, render_template, request, session

from services import cockpit_proxy as cp

cockpit_bp = Blueprint("cockpit", __name__)


def _require_session(fn):
    @wraps(fn)
    def _wrapped(*a, **k):
        if not session.get("user_id"):
            return jsonify({"error": "Not authenticated"}), 401
        return fn(*a, **k)

    return _wrapped


def _pass(result):
    status, payload = result
    return jsonify(payload), status


@cockpit_bp.route("/cockpit")
def cockpit_page():
    if not session.get("user_id"):
        return redirect("/login?next=/cockpit")
    return render_template("cockpit.html")


# ---- Crew ----------------------------------------------------------------------------
@cockpit_bp.route("/api/cockpit/agents", methods=["GET"])
@_require_session
def cockpit_agents():
    return _pass(cp.list_agents(request.args.to_dict()))


@cockpit_bp.route("/api/cockpit/agents/<int:agent_id>", methods=["GET"])
@_require_session
def cockpit_agent(agent_id):
    return _pass(cp.get_agent(agent_id))


@cockpit_bp.route("/api/cockpit/agents/create", methods=["POST"])
@_require_session
def cockpit_agent_create():
    return _pass(cp.create_agent(request.get_json(silent=True) or {}))


def _action_route(action):
    def view(agent_id):
        return _pass(cp.agent_action(agent_id, action, request.get_json(silent=True) or {}))

    view.__name__ = "cockpit_agent_" + action.replace("/", "_").replace("-", "_")
    return _require_session(view)


for _action in cp.ACTIONS:
    cockpit_bp.add_url_rule(f"/api/cockpit/agents/<int:agent_id>/{_action}", view_func=_action_route(_action), methods=["POST"])


# ---- Code Builder --------------------------------------------------------------------
@cockpit_bp.route("/api/cockpit/build/providers", methods=["GET"])
@_require_session
def cockpit_build_providers():
    return _pass(cp.build_providers())


@cockpit_bp.route("/api/cockpit/build/run", methods=["POST"])
@_require_session
def cockpit_build_run():
    return _pass(cp.build_run(request.get_json(silent=True) or {}))


@cockpit_bp.route("/api/cockpit/build/runs", methods=["GET"])
@_require_session
def cockpit_build_runs():
    try:
        limit = int(request.args.get("limit") or 20)
    except ValueError:
        return jsonify({"success": False, "error": "limit must be an integer"}), 400
    return _pass(cp.build_runs(limit))


@cockpit_bp.route("/api/cockpit/build/<int:job_id>", methods=["GET"])
@_require_session
def cockpit_build_status(job_id):
    return _pass(cp.build_status(job_id))


# ---- Work pane: projects + tasks (#6679 Phase 4b) --------------------------------------
@cockpit_bp.route("/api/cockpit/projects", methods=["GET"])
@_require_session
def cockpit_projects():
    return _pass(cp.list_projects(request.args.to_dict()))


@cockpit_bp.route("/api/cockpit/tasks", methods=["GET"])
@_require_session
def cockpit_tasks():
    return _pass(cp.list_tasks(request.args.to_dict()))


@cockpit_bp.route("/api/cockpit/tasks/<int:task_id>", methods=["GET"])
@_require_session
def cockpit_task(task_id):
    return _pass(cp.get_task(task_id))


@cockpit_bp.route("/api/cockpit/tasks", methods=["POST"])
@_require_session
def cockpit_task_create():
    return _pass(cp.create_task(request.get_json(silent=True) or {}))


@cockpit_bp.route("/api/cockpit/tasks/<int:task_id>/<action>", methods=["POST"])
@_require_session
def cockpit_task_action(task_id, action):
    return _pass(cp.task_action(task_id, action, request.get_json(silent=True) or {}))


# ---- Code Builder: apply (#6680 Phase 4b) ----------------------------------------------
@cockpit_bp.route("/api/cockpit/build/<int:job_id>/apply", methods=["POST"])
@_require_session
def cockpit_build_apply(job_id):
    return _pass(cp.build_apply(job_id))

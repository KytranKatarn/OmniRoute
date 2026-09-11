"""Cockpit page + /api/cockpit/* routes (#6653 Phase 4). Session-gated like the
approvals routes (session['user_id']); every hub call goes through
services.cockpit_proxy, which passes the hub's status + JSON through verbatim.
A Blueprint so it is testable without importing app_comms."""

from functools import wraps

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session

from services import cockpit_proxy as cp
from services import terminal_lanes as tl


def _lane_shapes():
    """Lane list for the cockpit switcher — same shape the comms landing
    pages use, so the two surfaces can never disagree about which lanes
    exist or which of them are host shells."""
    return [
        {
            "key": k,
            "label": c.get("label", k),
            "sandboxed": bool(c.get("sandboxed")),
        }
        for k, c in tl.LANES.items()
    ]

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
    return render_template("cockpit.html", lanes=_lane_shapes())


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


# ---- Terminal lanes (#6653 Phase 5) ----------------------------------------------------
def _require_admin(fn):
    """Admin, checked HERE rather than inferred from the login path.

    Every comms user is an admin today: app_comms.py rejects any SSO login whose
    role != "admin" and sets session["user_id"] in exactly one place inside that accepted
    path. So this is currently redundant — and it is required anyway.

    The proxy validates a token without knowing who asked for it, so the mint is where the
    requester's authority is established. Without an explicit check here, the terminal's
    protection would rest on a property of the SSO login path rather than on anything the
    terminal code states, and a future change admitting non-admins to comms for some
    unrelated feature would silently start handing out shells.
    """

    @wraps(fn)
    def _wrapped(*a, **k):
        if not session.get("user_id"):
            return jsonify({"error": "Not authenticated"}), 401

        # Per-LANE authority when the route names a lane; admin-only otherwise
        # (e.g. the lane LIST, which enumerates every lane and so needs the
        # broadest right). tl.may_use_lane is THE answer — admins by role,
        # everyone else by an explicit grant — and it fails closed.
        lane = k.get("lane")
        if lane is not None and lane in tl.LANES:
            if not tl.may_use_lane(session["user_id"], session.get("role"), lane):
                return jsonify({"error": "You do not have access to this terminal"}), 403
        elif lane is None and session.get("role") != "admin":
            # No lane in the route (e.g. the lane LIST, which enumerates every lane
            # and so needs the broadest right).
            return jsonify({"error": "A terminal needs an admin account"}), 403
        # ⚠️ An UNKNOWN lane deliberately falls through to the route, which raises
        # UnknownLane -> 404. Answering 403 there would be wrong twice: it claims an
        # authorization failure for something that does not exist, and it makes
        # "no such lane" indistinguishable from "not allowed". Caught by
        # test_an_unknown_lane_is_404_not_500 when this gate first returned 403.
        return fn(*a, **k)

    return _wrapped


@cockpit_bp.route("/api/cockpit/terminal/lanes", methods=["GET"])
@_require_admin
def cockpit_terminal_lanes():
    return jsonify({"lanes": tl.lane_status()}), 200


@cockpit_bp.route("/api/cockpit/terminal/<lane>/token", methods=["POST"])
@_require_admin
def cockpit_terminal_token(lane):
    """Mint a one-time, lane-bound token. Terminal bytes never pass through comms."""
    try:
        payload = tl.mint_token(session["user_id"], lane)
    except tl.UnknownLane:
        return jsonify({"error": f"Unknown lane: {lane}"}), 404
    except Exception:
        current_app.logger.exception("cockpit_terminal_token: mint failed lane=%s", lane)
        return jsonify({"error": "Token generation failed"}), 500

    current_app.logger.info(
        "cockpit terminal token minted user_id=%s lane=%s", session["user_id"], lane
    )
    return jsonify(payload), 200

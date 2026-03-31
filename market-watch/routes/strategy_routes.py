"""Strategy Routes — REST endpoints for named trading strategies."""

from flask import Blueprint, jsonify, request
from auth import tier_required

from services.strategy_service import (
    create_strategy,
    delete_strategy,
    get_strategies,
    get_strategy,
    update_strategy,
)

bp = Blueprint("strategies", __name__)


@bp.route("/api/strategies", methods=["GET"])
@tier_required("viewer")
def list_strategies():
    active_only = request.args.get("active", "").lower() == "true"
    return jsonify(get_strategies(active_only=active_only))


@bp.route("/api/strategies/<int:sid>", methods=["GET"])
@tier_required("viewer")
def get_one_strategy(sid):
    strategy = get_strategy(sid)
    if strategy is None:
        return jsonify({"error": "Strategy not found"}), 404
    return jsonify(strategy)


@bp.route("/api/strategies", methods=["POST"])
@tier_required("ai")
def create_one_strategy():
    data = request.get_json(force=True) or {}
    name = data.get("name")
    rules = data.get("rules")
    if not name or rules is None:
        return jsonify({"error": "name and rules are required"}), 400
    description = data.get("description", "")
    strategy = create_strategy(name=name, rules=rules, description=description)
    return jsonify(strategy), 201


@bp.route("/api/strategies/<int:sid>", methods=["PUT"])
@tier_required("ai")
def update_one_strategy(sid):
    data = request.get_json(force=True) or {}
    strategy = update_strategy(sid, **data)
    if strategy is None:
        return jsonify({"error": "Strategy not found"}), 404
    return jsonify(strategy)


@bp.route("/api/strategies/<int:sid>", methods=["DELETE"])
@tier_required("ai")
def delete_one_strategy(sid):
    delete_strategy(sid)
    return jsonify({"success": True})

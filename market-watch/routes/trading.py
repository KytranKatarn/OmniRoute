"""Trading endpoints — manual and agent orders."""

from flask import Blueprint, jsonify, request
from db import get_db
from services.alpaca_client import place_order, get_orders
from services.market_data import get_quote

trading_bp = Blueprint("trading", __name__)


@trading_bp.route("/api/trading/buy", methods=["POST"])
def buy():
    """Place a buy order."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper()
    qty = data.get("qty", 0)

    if not ticker or not qty:
        return jsonify({"success": False, "error": "ticker and qty required"}), 400

    result = place_order(
        ticker=ticker,
        qty=float(qty),
        side="buy",
        order_type=data.get("order_type", "market"),
        limit_price=data.get("limit_price"),
    )

    if result.get("success"):
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO trade_log (ticker, side, qty, order_type, status, order_id) VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, "buy", qty, data.get("order_type", "market"), "submitted", result.get("order_id")),
            )
            conn.commit()
        finally:
            conn.close()

    return jsonify(result)


@trading_bp.route("/api/trading/sell", methods=["POST"])
def sell():
    """Place a sell order."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper()
    qty = data.get("qty", 0)

    if not ticker or not qty:
        return jsonify({"success": False, "error": "ticker and qty required"}), 400

    result = place_order(
        ticker=ticker,
        qty=float(qty),
        side="sell",
        order_type=data.get("order_type", "market"),
        limit_price=data.get("limit_price"),
    )

    if result.get("success"):
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO trade_log (ticker, side, qty, order_type, status, order_id) VALUES (?, ?, ?, ?, ?, ?)",
                (ticker, "sell", qty, data.get("order_type", "market"), "submitted", result.get("order_id")),
            )
            conn.commit()
        finally:
            conn.close()

    return jsonify(result)


@trading_bp.route("/api/trading/orders")
def order_history():
    """Get order history."""
    status = request.args.get("status", "all")
    orders = get_orders(status)
    return jsonify({"success": True, "orders": orders})

"""Trading endpoints — manual and agent orders."""

import json
import logging
import os
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from auth import admin_required, tier_required
from db import get_db
from services import risk_config as rc
from services.alpaca_client import get_orders, place_order
from services.market_data import get_quote

logger = logging.getLogger(__name__)

trading_bp = Blueprint("trading", __name__)


@trading_bp.route("/api/trading/buy", methods=["POST"])
@tier_required("ai")
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
@tier_required("ai")
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
@tier_required("ai")
def order_history():
    """Get order history."""
    status = request.args.get("status", "all")
    orders = get_orders(status)
    return jsonify({"success": True, "orders": orders})


@trading_bp.route("/api/trading/toggle-live", methods=["POST"])
@tier_required("ai")
@admin_required
def toggle_live_trading():
    """Toggle between paper and live Alpaca trading (admin only)."""
    data = request.get_json() or {}
    enabled = data.get("enabled", False)
    return jsonify({"success": True, "live_trading": enabled, "message": "Not yet implemented — Sub-project 3"})


@trading_bp.route("/api/trading/run-cycle", methods=["POST"])
def run_cycle():
    """Execute autonomous trading cycle — triggered by ARCHIE dispatch.

    Auth: service token (machine-to-machine), not user OAuth.
    """
    # Verify service token
    auth_header = request.headers.get("Authorization", "")
    service_token = os.environ.get("ARCHIE_SERVICE_TOKEN", "")
    if service_token and not auth_header.endswith(service_token):
        return jsonify({"success": False, "error": "Invalid service token"}), 401

    # Kill switch
    if not rc.TRADING_ENABLED:
        return jsonify({"success": False, "error": "Trading is disabled"}), 503

    # Dedup check
    conn = get_db()
    try:
        recent = conn.execute(
            "SELECT id FROM cycle_log WHERE status = 'completed' AND completed_at > ? ORDER BY id DESC LIMIT 1",
            (datetime.utcnow() - timedelta(minutes=rc.CYCLE_DEDUP_MINUTES),),
        ).fetchone()
        if recent and not (request.get_json(silent=True) or {}).get("force"):
            return jsonify({"success": True, "skipped": True, "reason": f"Cycle ran within {rc.CYCLE_DEDUP_MINUTES} min"})
    finally:
        conn.close()

    from services.agent_pipeline import run_full_cycle
    from services.execution_engine import evaluate
    from services.portfolio_service import get_portfolio_state
    from services.position_manager import check_price_exits, check_reeval_exits, open_position

    try:
        # Step 1: Check price-based exits
        price_exits = check_price_exits()
        logger.info("Price exits: %d positions closed", len(price_exits))

        # Step 2: Run full analysis cycle
        cycle_result = run_full_cycle()
        results = cycle_result.get("results", [])

        # Step 3: Check re-evaluation exits
        reeval_exits = check_reeval_exits(results)
        logger.info("Reeval exits: %d positions closed", len(reeval_exits))

        # Step 4: Evaluate new recommendations
        portfolio_state = get_portfolio_state()
        trades_executed = 0
        trades_skipped = 0
        errors = 0

        for result in results:
            if result.get("recommendation") != "buy":
                trades_skipped += 1
                continue

            # Build analysis dict for execution engine
            analysis = {
                "ticker": result.get("ticker"),
                "recommendation": result.get("recommendation"),
                "oracle_confidence": result.get("confidence"),
                "risk_approved": result.get("reports", {}).get("shield", {}).get("risk_approved", False),
                "target_price": result.get("target_price"),
                "stop_loss": result.get("reports", {}).get("shield", {}).get("stop_loss"),
                "suggested_position_size": result.get("reports", {}).get("shield", {}).get("position_size"),
                "sector": result.get("reports", {}).get("value", {}).get("sector", "unknown"),
                "analysis_id": result.get("analysis_id"),
            }

            decision = evaluate(analysis, portfolio_state)

            if decision["approved"]:
                if rc.DRY_RUN:
                    logger.info(
                        "[DRY RUN] Would buy %d %s at %.2f",
                        decision["order"]["quantity"],
                        decision["order"]["ticker"],
                        decision["order"]["price"],
                    )
                    trades_executed += 1
                else:
                    order = decision["order"]
                    alpaca_result = place_order(order["ticker"], order["quantity"], "buy")
                    if alpaca_result.get("success"):
                        order["gates_log"] = decision["gates_log"]
                        open_position(order, alpaca_result.get("order_id"))
                        trades_executed += 1
                        logger.info("Executed buy: %d %s at %.2f", order["quantity"], order["ticker"], order["price"])
                    else:
                        errors += 1
                        logger.error("Alpaca order failed for %s: %s", order["ticker"], alpaca_result.get("error"))

                # Refresh portfolio state for next evaluation
                portfolio_state = get_portfolio_state()
            else:
                trades_skipped += 1
                logger.info("Skipped %s: %s", result.get("ticker"), decision["reason"])

        # Step 5: Return summary
        final_state = get_portfolio_state()
        return jsonify({
            "success": True,
            "cycle_id": cycle_result.get("cycle_id"),
            "tickers_analyzed": cycle_result.get("stocks_analyzed", 0),
            "trades_executed": trades_executed,
            "trades_skipped": trades_skipped,
            "positions_closed": len(price_exits) + len(reeval_exits),
            "errors": errors,
            "dry_run": rc.DRY_RUN,
            "portfolio_value": final_state["portfolio_value"],
            "daily_pnl_pct": final_state["daily_pnl_pct"],
        })

    except Exception as e:
        logger.error("Cycle failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@trading_bp.route("/api/trading/positions")
@tier_required("viewer")
def get_positions():
    """Return current open positions with unrealized P&L."""
    from services.portfolio_service import get_portfolio_state

    state = get_portfolio_state()
    return jsonify({"success": True, "positions": state["open_positions"]})


@trading_bp.route("/api/trading/journal")
@tier_required("viewer")
def get_journal():
    """Return trade history with reasoning chain."""
    conn = get_db()
    try:
        limit = request.args.get("limit", 50, type=int)
        rows = conn.execute(
            """SELECT ticker, action, quantity, price, exit_reason, pnl, pnl_pct,
                      risk_gates_log, created_at
               FROM trade_journal ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        trades = []
        for r in rows:
            trade = {
                "ticker": r["ticker"],
                "action": r["action"],
                "quantity": r["quantity"],
                "price": r["price"],
                "exit_reason": r["exit_reason"],
                "pnl": r["pnl"],
                "pnl_pct": r["pnl_pct"],
                "date": r["created_at"],
            }
            if r["risk_gates_log"]:
                try:
                    trade["gates"] = json.loads(r["risk_gates_log"])
                except (json.JSONDecodeError, TypeError):
                    pass
            trades.append(trade)
        return jsonify({"success": True, "trades": trades})
    finally:
        conn.close()

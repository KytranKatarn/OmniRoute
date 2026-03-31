"""Trading endpoints — manual and agent orders."""

import json
import logging
import os
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from auth import admin_required, tier_required
from db import get_db
from services import risk_config as rc
from services.alpaca_client import get_orders, place_order, place_bracket_order, place_trailing_stop, place_short_order
from services.market_data import get_quote
from services.trading_config_service import (
    get_full_config, update_risk_gates, set_toggle, get_toggle, reset_config,
)

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
    """Toggle between paper and live Alpaca trading.
    Requires both admin role AND MW_LIVE_TRADING=true env var (double-lock).
    """
    import os
    data = request.get_json() or {}
    enabled = data.get("enabled", False)

    env_allows = os.environ.get("MW_LIVE_TRADING", "false").lower() in ("true", "1", "yes")
    if enabled and not env_allows:
        return jsonify({
            "success": False,
            "error": "Live trading blocked — MW_LIVE_TRADING env var is not set to true",
        }), 403

    set_toggle("live_trading", enabled)
    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "live_trading": enabled, "env_allows": env_allows})


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

    # Paused check
    if get_toggle("paused", False):
        return jsonify({"success": True, "skipped": True, "reason": "Trading is paused"})

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
    from services.execution_engine import evaluate, evaluate_short
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

        shorts_enabled = os.environ.get("MW_SHORTS_ENABLED", "false").lower() in ("true", "1", "yes")

        for result in results:
            recommendation = result.get("recommendation")

            if recommendation not in ("buy", "sell"):
                trades_skipped += 1
                continue

            # Build analysis dict for execution engine
            analysis = {
                "ticker": result.get("ticker"),
                "recommendation": recommendation,
                "oracle_confidence": result.get("confidence"),
                "risk_approved": result.get("reports", {}).get("shield", {}).get("risk_approved", False),
                "target_price": result.get("target_price"),
                "stop_loss": result.get("reports", {}).get("shield", {}).get("stop_loss"),
                "suggested_position_size": result.get("reports", {}).get("shield", {}).get("position_size"),
                "sector": result.get("reports", {}).get("value", {}).get("sector", "unknown"),
                "analysis_id": result.get("analysis_id"),
                "order_type": result.get("order_type", "market"),
            }

            # --- BUY path ---
            if recommendation == "buy":
                decision = evaluate(analysis, portfolio_state)

                if decision["approved"]:
                    order = decision["order"]
                    order_type = order.get("order_type", "market")

                    if rc.DRY_RUN:
                        logger.info(
                            "[DRY RUN] Would buy %d %s at %.2f (order_type=%s)",
                            order["quantity"],
                            order["ticker"],
                            order["price"],
                            order_type,
                        )
                        trades_executed += 1
                    else:
                        if order_type == "bracket":
                            alpaca_result = place_bracket_order(
                                order["ticker"],
                                order["quantity"],
                                side="buy",
                                take_profit=order.get("target_price"),
                                stop_loss=order.get("stop_loss"),
                            )
                        elif order_type == "trailing_stop":
                            alpaca_result = place_trailing_stop(
                                order["ticker"],
                                order["quantity"],
                                side="buy",
                                trail_percent=order.get("trail_percent"),
                            )
                        else:
                            alpaca_result = place_order(order["ticker"], order["quantity"], "buy")

                        if alpaca_result.get("success"):
                            order["gates_log"] = decision["gates_log"]
                            open_position(order, alpaca_result.get("order_id"))
                            trades_executed += 1
                            logger.info(
                                "Executed buy: %d %s at %.2f (order_type=%s)",
                                order["quantity"], order["ticker"], order["price"], order_type,
                            )
                        else:
                            errors += 1
                            logger.error("Alpaca buy failed for %s: %s", order["ticker"], alpaca_result.get("error"))

                    # Refresh portfolio state for next evaluation
                    portfolio_state = get_portfolio_state()
                else:
                    trades_skipped += 1
                    logger.info("Skipped buy %s: %s", result.get("ticker"), decision["reason"])

            # --- SHORT (sell) path ---
            elif recommendation == "sell" and shorts_enabled:
                decision = evaluate_short(analysis, portfolio_state)

                if decision["approved"]:
                    order = decision["order"]

                    if rc.DRY_RUN:
                        logger.info(
                            "[DRY RUN] Would short %d %s at %.2f",
                            order["quantity"],
                            order["ticker"],
                            order["price"],
                        )
                        trades_executed += 1
                    else:
                        alpaca_result = place_short_order(
                            order["ticker"],
                            order["quantity"],
                            order_type=order.get("order_type", "market"),
                            take_profit=order.get("target_price"),
                            stop_loss=order.get("stop_loss"),
                            trail_percent=order.get("trail_percent"),
                        )

                        if alpaca_result.get("success"):
                            order["gates_log"] = decision["gates_log"]
                            open_position(order, alpaca_result.get("order_id"))
                            trades_executed += 1
                            logger.info(
                                "Executed short: %d %s at %.2f",
                                order["quantity"], order["ticker"], order["price"],
                            )
                        else:
                            errors += 1
                            logger.error("Alpaca short failed for %s: %s", order["ticker"], alpaca_result.get("error"))

                    # Refresh portfolio state for next evaluation
                    portfolio_state = get_portfolio_state()
                else:
                    trades_skipped += 1
                    logger.info("Skipped short %s: %s", result.get("ticker"), decision["reason"])

            else:
                # sell recommendation but shorts disabled
                trades_skipped += 1
                logger.debug("Skipped sell %s: shorts not enabled", result.get("ticker"))

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


# --- Admin Trading Controls ---


@trading_bp.route("/api/trading/config")
@tier_required("ai")
@admin_required
def get_config():
    """Return current risk config + mode toggles + validation ranges."""
    return jsonify({"success": True, **get_full_config()})


@trading_bp.route("/api/trading/config", methods=["PUT"])
@tier_required("ai")
@admin_required
def update_config():
    """Update risk gate thresholds. Saves to DB, applies immediately."""
    data = request.get_json() or {}
    risk_gates = data.get("risk_gates", {})
    if not risk_gates:
        return jsonify({"success": False, "error": "No risk_gates provided"}), 400

    success, errors = update_risk_gates(risk_gates)
    if not success:
        return jsonify({"success": False, "errors": errors}), 400

    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "message": "Config updated", **get_full_config()})


@trading_bp.route("/api/trading/config/reset", methods=["POST"])
@tier_required("ai")
@admin_required
def reset_config_endpoint():
    """Reset all risk gates to env var defaults."""
    reset_config()
    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "message": "Config reset to defaults", **get_full_config()})


@trading_bp.route("/api/trading/toggle-dry-run", methods=["POST"])
@tier_required("ai")
@admin_required
def toggle_dry_run():
    """Toggle DRY_RUN mode."""
    data = request.get_json() or {}
    enabled = data.get("enabled", True)
    set_toggle("dry_run", enabled)
    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "dry_run": enabled})


@trading_bp.route("/api/trading/toggle-enabled", methods=["POST"])
@tier_required("ai")
@admin_required
def toggle_trading_enabled():
    """Toggle TRADING_ENABLED (kill switch)."""
    data = request.get_json() or {}
    enabled = data.get("enabled", True)
    set_toggle("trading_enabled", enabled)
    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "trading_enabled": enabled})


@trading_bp.route("/api/trading/pause-autonomy", methods=["POST"])
@tier_required("ai")
@admin_required
def pause_autonomy():
    """Pause/resume autonomous trading cycles."""
    data = request.get_json() or {}
    paused = data.get("paused", True)
    set_toggle("paused", paused)
    return jsonify({"success": True, "paused": paused})


@trading_bp.route("/api/trading/close-position/<int:position_id>", methods=["POST"])
@tier_required("ai")
@admin_required
def close_position(position_id):
    """Close a single open position at market price."""
    conn = get_db()
    try:
        pos = conn.execute(
            "SELECT * FROM open_positions WHERE id = ? AND status = 'open'", (position_id,)
        ).fetchone()
        if not pos:
            return jsonify({"success": False, "error": "Position not found or already closed"}), 404

        from services.market_data import get_quote
        from services.position_manager import _close_position

        quote = get_quote(pos["ticker"])
        current_price = quote.get("price", pos["entry_price"])
        result = _close_position(conn, pos, current_price, "closed")
        conn.commit()

        if result:
            return jsonify({"success": True, "closed": result})
        return jsonify({"success": False, "error": "Failed to close position"}), 500
    finally:
        conn.close()


@trading_bp.route("/api/trading/close-all", methods=["POST"])
@tier_required("ai")
@admin_required
def close_all_positions():
    """Emergency close all open positions."""
    conn = get_db()
    closed = []
    errors = []
    try:
        positions = conn.execute(
            "SELECT * FROM open_positions WHERE status = 'open'"
        ).fetchall()

        if not positions:
            return jsonify({"success": True, "message": "No open positions", "closed": []})

        from services.market_data import get_quote
        from services.position_manager import _close_position

        for pos in positions:
            quote = get_quote(pos["ticker"])
            current_price = quote.get("price", pos["entry_price"])
            result = _close_position(conn, pos, current_price, "closed")
            if result:
                closed.append(result)
            else:
                errors.append(pos["ticker"])

        conn.commit()
        return jsonify({
            "success": True,
            "closed": closed,
            "errors": errors,
            "total_closed": len(closed),
        })
    finally:
        conn.close()


@trading_bp.route("/api/trading/cycle-status")
@tier_required("ai")
@admin_required
def cycle_status():
    """Return last cycle results + paused state."""
    conn = get_db()
    try:
        last_cycle = conn.execute(
            "SELECT * FROM cycle_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        paused = get_toggle("paused", False)

        result = {
            "success": True,
            "paused": paused,
            "last_cycle": None,
        }
        if last_cycle:
            result["last_cycle"] = {
                "id": last_cycle["id"],
                "status": last_cycle["status"],
                "stocks_analyzed": last_cycle["stocks_analyzed"],
                "trades_made": last_cycle["trades_made"],
                "trades_skipped": last_cycle["trades_skipped"],
                "errors": last_cycle["errors"],
                "started_at": str(last_cycle["started_at"]) if last_cycle["started_at"] else None,
                "completed_at": str(last_cycle["completed_at"]) if last_cycle["completed_at"] else None,
            }
        return jsonify(result)
    finally:
        conn.close()


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

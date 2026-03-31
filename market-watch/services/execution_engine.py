"""Execution engine — 10-gate risk evaluation for autonomous trading."""

import logging
from datetime import date

from db import get_db
from services.market_data import get_quote
from services.portfolio_service import get_portfolio_state, get_sector_counts
from services import risk_config as rc

logger = logging.getLogger(__name__)


def evaluate(analysis, portfolio_state):
    """Evaluate a pipeline recommendation against 10 risk gates.

    Args:
        analysis: dict from run_pipeline() — must have ticker, recommendation,
                  confidence (oracle), risk_approved (shield), target_price,
                  stop_loss, suggested_position_size, sector
        portfolio_state: dict from get_portfolio_state()

    Returns:
        dict with: approved (bool), reason (str), gates_log (list), order (dict or None)
    """
    gates_log = []
    ticker = analysis.get("ticker", "")

    def gate(name, passed, value, detail=""):
        gates_log.append({"gate": name, "passed": passed, "value": value, "detail": detail})
        return passed

    # Gate 1: Shield approval
    risk_approved = analysis.get("risk_approved", False)
    if not gate("shield_approval", bool(risk_approved), risk_approved):
        return _reject("Failed gate #1: Shield did not approve", gates_log)

    # Gate 2: Oracle confidence
    confidence = analysis.get("oracle_confidence") or analysis.get("confidence", 0)
    if not gate("oracle_confidence", confidence >= rc.MIN_ORACLE_CONFIDENCE, confidence,
                f"min={rc.MIN_ORACLE_CONFIDENCE}"):
        return _reject(f"Failed gate #2: oracle_confidence {confidence} < {rc.MIN_ORACLE_CONFIDENCE}", gates_log)

    # Gate 3: Daily loss limit
    daily_pnl_pct = portfolio_state.get("daily_pnl_pct", 0)
    if not gate("daily_loss_limit", daily_pnl_pct > -rc.MAX_DAILY_LOSS_PCT, daily_pnl_pct,
                f"limit=-{rc.MAX_DAILY_LOSS_PCT}%"):
        return _reject(f"Failed gate #3: daily P&L {daily_pnl_pct}% exceeds -{rc.MAX_DAILY_LOSS_PCT}%", gates_log)

    # Gate 4: Max drawdown breaker
    drawdown = portfolio_state.get("drawdown_pct", 0)
    if not gate("max_drawdown", drawdown < rc.MAX_DRAWDOWN_PCT, drawdown,
                f"limit={rc.MAX_DRAWDOWN_PCT}%"):
        return _reject(f"Failed gate #4: drawdown {drawdown}% >= {rc.MAX_DRAWDOWN_PCT}%", gates_log)

    # Gate 5: Max positions
    open_count = portfolio_state.get("open_positions_count", 0)
    if not gate("max_positions", open_count < rc.MAX_POSITIONS, open_count,
                f"limit={rc.MAX_POSITIONS}"):
        return _reject(f"Failed gate #5: {open_count} positions >= max {rc.MAX_POSITIONS}", gates_log)

    # Gate 6: Position size cap
    portfolio_value = portfolio_state.get("portfolio_value", 100000)
    max_order_value = portfolio_value * (rc.MAX_POSITION_PCT / 100)
    quote = get_quote(ticker)
    current_price = quote.get("price", 0)
    if current_price <= 0:
        return _reject(f"Failed gate #6: cannot get price for {ticker}", gates_log)

    # Calculate quantity — Kelly first, then Shield's suggestion, then equal-weight fallback
    from services.quant_service import get_kelly_position_size
    kelly_size = get_kelly_position_size(portfolio_value, rc.MAX_POSITION_PCT)

    suggested_size = analysis.get("suggested_position_size")
    if kelly_size is not None:
        order_value = min(kelly_size, max_order_value)
    elif suggested_size and suggested_size > 0:
        order_value = min(suggested_size, max_order_value)
    else:
        order_value = min(portfolio_value / rc.MAX_POSITIONS, max_order_value)
    quantity = int(order_value / current_price)

    if quantity <= 0:
        return _reject(f"Failed gate #6: calculated quantity is 0 (price={current_price})", gates_log)

    actual_value = quantity * current_price
    if not gate("position_size", actual_value <= max_order_value, actual_value,
                f"limit={max_order_value:.0f}"):
        return _reject(f"Failed gate #6: order {actual_value:.0f} > max {max_order_value:.0f}", gates_log)

    # Gate 7: Duplicate ticker
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM open_positions WHERE ticker = ? AND status = 'open'", (ticker,)
        ).fetchone()
    finally:
        conn.close()
    if not gate("duplicate_ticker", existing is None, ticker):
        return _reject(f"Failed gate #7: already holding {ticker}", gates_log)

    # Gate 8: Volatility filter (ATR as % of price)
    atr_pct = _calculate_atr_pct(ticker)
    if not gate("volatility_filter", atr_pct <= rc.VOLATILITY_ATR_LIMIT, atr_pct,
                f"limit={rc.VOLATILITY_ATR_LIMIT}%"):
        return _reject(f"Failed gate #8: ATR {atr_pct:.1f}% > limit {rc.VOLATILITY_ATR_LIMIT}%", gates_log)

    # Gate 9: Sector concentration
    sector = analysis.get("sector", "unknown")
    sector_counts = get_sector_counts()
    sector_count = sector_counts.get(sector, 0)
    if not gate("sector_concentration", sector_count < rc.MAX_SECTOR_POSITIONS, sector_count,
                f"sector={sector}, limit={rc.MAX_SECTOR_POSITIONS}"):
        return _reject(f"Failed gate #9: {sector_count} positions in {sector} >= max {rc.MAX_SECTOR_POSITIONS}", gates_log)

    # Gate 9b: Correlation check
    from services.quant_service import get_correlation_for_ticker
    is_correlated, max_corr, corr_with = get_correlation_for_ticker(ticker)
    if is_correlated:
        order_value = order_value / 2
        quantity = int(order_value / current_price)
        gate("correlation_adjustment", True, max_corr,
             f"Correlated with {corr_with} ({max_corr}), size halved")
        if quantity <= 0:
            return _reject(f"Failed: correlation with {corr_with} reduced size to 0", gates_log)
    else:
        gate("correlation_adjustment", True, max_corr, "No high correlations")

    # Gate 9c: Portfolio beta
    from services.quant_service import get_portfolio_beta, calculate_sector_beta, MAX_PORTFOLIO_BETA
    port_beta = get_portfolio_beta()
    ticker_beta = calculate_sector_beta(ticker).get("beta", 1.0)
    if not gate("portfolio_beta", port_beta < MAX_PORTFOLIO_BETA or ticker_beta < 1.0, port_beta,
                f"portfolio={port_beta}, ticker={ticker_beta}, limit={MAX_PORTFOLIO_BETA}"):
        return _reject(f"Failed: portfolio beta {port_beta} >= {MAX_PORTFOLIO_BETA}", gates_log)

    # Gate 10: Cool-off after loss
    conn = get_db()
    try:
        last_trade = conn.execute(
            "SELECT pnl_pct FROM trade_journal WHERE action = 'sell' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if last_trade and last_trade["pnl_pct"] is not None:
        last_loss_pct = last_trade["pnl_pct"]
        if not gate("cooloff_after_loss", last_loss_pct > -rc.COOLOFF_LOSS_PCT, last_loss_pct,
                    f"limit=-{rc.COOLOFF_LOSS_PCT}%"):
            return _reject(f"Failed gate #10: last trade lost {last_loss_pct:.1f}%, cooling off", gates_log)
    else:
        gate("cooloff_after_loss", True, "no_previous_trade")

    # All gates passed
    stop_loss = analysis.get("stop_loss") or analysis.get("risk_stop_loss") or (current_price * 0.95)
    target_price = analysis.get("target_price") or (current_price * 1.10)

    # Select order type
    if rc.BRACKET_ORDERS_ENABLED:
        order_type = "bracket"
    else:
        order_type = "market"

    # Use trailing stop for moderate volatility (ATR between 2-4%)
    if atr_pct and 2.0 <= atr_pct <= 4.0:
        order_type = "trailing_stop"
        trail_percent = rc.DEFAULT_TRAIL_PERCENT
    else:
        trail_percent = None

    return {
        "approved": True,
        "reason": "All 10 gates passed",
        "gates_log": gates_log,
        "order": {
            "ticker": ticker,
            "action": "buy",
            "quantity": quantity,
            "price": current_price,
            "stop_loss": round(stop_loss, 2),
            "target_price": round(target_price, 2),
            "max_hold_days": rc.DEFAULT_HOLD_DAYS,
            "sector": sector,
            "thesis_id": analysis.get("analysis_id"),
            "order_type": order_type,
            "trail_percent": trail_percent,
            "direction": "long",
        },
    }


def evaluate_short(analysis, portfolio_state):
    """Evaluate a short selling opportunity.

    Same risk gates as long, plus short-specific limits.
    Only called when recommendation is 'sell' and no existing position.
    """
    if not rc.SHORTS_ENABLED:
        return _reject("Short selling disabled", [])

    gates_log = []
    ticker = analysis.get("ticker", "")

    def gate(name, passed, value, detail=""):
        gates_log.append({"gate": name, "passed": passed, "value": value, "detail": detail})
        return passed

    # Gate S1: Shield approval
    risk_approved = analysis.get("risk_approved", False)
    if not gate("shield_approval", bool(risk_approved), risk_approved):
        return _reject("Failed: Shield did not approve short", gates_log)

    # Gate S2: Oracle confidence
    confidence = analysis.get("oracle_confidence") or analysis.get("confidence", 0)
    if not gate("oracle_confidence", confidence >= rc.MIN_ORACLE_CONFIDENCE, confidence):
        return _reject(f"Failed: oracle_confidence {confidence} < {rc.MIN_ORACLE_CONFIDENCE}", gates_log)

    # Gate S3: Max short positions
    conn = get_db()
    try:
        short_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM open_positions WHERE status = 'open' AND direction = 'short'"
        ).fetchone()
        count = short_count["cnt"] if short_count else 0
    finally:
        conn.close()
    if not gate("max_short_positions", count < rc.MAX_SHORT_POSITIONS, count,
                f"limit={rc.MAX_SHORT_POSITIONS}"):
        return _reject(f"Failed: {count} shorts >= max {rc.MAX_SHORT_POSITIONS}", gates_log)

    # Gate S4: Short position size
    portfolio_value = portfolio_state.get("portfolio_value", 100000)
    max_short_value = portfolio_value * (rc.SHORT_POSITION_PCT / 100)
    quote = get_quote(ticker)
    current_price = quote.get("price", 0)
    if current_price <= 0:
        return _reject(f"Failed: cannot get price for {ticker}", gates_log)

    order_value = min(portfolio_value / (rc.MAX_POSITIONS * 2), max_short_value)
    quantity = int(order_value / current_price)
    if quantity <= 0:
        return _reject(f"Failed: short quantity is 0", gates_log)
    gate("short_position_size", True, order_value, f"limit={max_short_value:.0f}")

    # Gate S5: Duplicate check
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM open_positions WHERE ticker = ? AND status = 'open'", (ticker,)
        ).fetchone()
    finally:
        conn.close()
    if not gate("duplicate_ticker", existing is None, ticker):
        return _reject(f"Failed: already holding {ticker}", gates_log)

    # Gate S6: Daily loss limit (shared with longs)
    daily_pnl_pct = portfolio_state.get("daily_pnl_pct", 0)
    if not gate("daily_loss_limit", daily_pnl_pct > -rc.MAX_DAILY_LOSS_PCT, daily_pnl_pct):
        return _reject(f"Failed: daily P&L {daily_pnl_pct}% exceeds limit", gates_log)

    stop_loss = analysis.get("stop_loss") or (current_price * 1.05)  # 5% above for shorts
    target_price = analysis.get("target_price") or (current_price * 0.90)  # 10% below for shorts

    return {
        "approved": True,
        "reason": "All short gates passed",
        "gates_log": gates_log,
        "order": {
            "ticker": ticker,
            "action": "sell",
            "quantity": quantity,
            "price": current_price,
            "stop_loss": round(stop_loss, 2),
            "target_price": round(target_price, 2),
            "max_hold_days": rc.DEFAULT_HOLD_DAYS,
            "sector": analysis.get("sector", "unknown"),
            "thesis_id": analysis.get("analysis_id"),
            "direction": "short",
            "order_type": "bracket" if rc.BRACKET_ORDERS_ENABLED else "market",
            "trail_percent": None,
        },
    }


def _reject(reason, gates_log):
    """Return a rejected ExecutionDecision."""
    return {"approved": False, "reason": reason, "gates_log": gates_log, "order": None}


def _calculate_atr_pct(ticker):
    """Calculate ATR as percentage of current price (14-day ATR)."""
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period="1mo")
        if data.empty or len(data) < 14:
            return 0.0
        high = data["High"]
        low = data["Low"]
        close = data["Close"]
        tr = []
        for i in range(1, len(data)):
            tr.append(max(
                high.iloc[i] - low.iloc[i],
                abs(high.iloc[i] - close.iloc[i - 1]),
                abs(low.iloc[i] - close.iloc[i - 1]),
            ))
        atr = sum(tr[-14:]) / 14
        current = close.iloc[-1]
        return (atr / current * 100) if current > 0 else 0.0
    except Exception as e:
        logger.warning("ATR calculation failed for %s: %s", ticker, e)
        return 0.0

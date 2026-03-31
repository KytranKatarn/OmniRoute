"""Alpaca paper trading client."""

import os
import logging

logger = logging.getLogger(__name__)

ALPACA_API_KEY = os.environ.get("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
ALPACA_BASE_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")


def _get_client():
    """Get Alpaca trading client. Returns None if not configured."""
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        return None
    try:
        from alpaca.trading.client import TradingClient
        return TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
    except Exception as e:
        logger.error("Alpaca client init failed: %s", e)
        return None


def get_account():
    """Get paper trading account info."""
    client = _get_client()
    if not client:
        return {"configured": False, "error": "Alpaca API keys not set"}
    try:
        account = client.get_account()
        return {
            "configured": True,
            "cash": float(account.cash),
            "portfolio_value": float(account.portfolio_value),
            "buying_power": float(account.buying_power),
            "equity": float(account.equity),
            "status": account.status,
        }
    except Exception as e:
        return {"configured": True, "error": str(e)}


def place_order(ticker, qty, side, order_type="market", limit_price=None):
    """Place a paper trade order."""
    client = _get_client()
    if not client:
        return {"success": False, "error": "Alpaca not configured"}
    try:
        from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL

        if order_type == "limit" and limit_price:
            req = LimitOrderRequest(
                symbol=ticker, qty=qty, side=order_side,
                time_in_force=TimeInForce.DAY, limit_price=limit_price,
            )
        else:
            req = MarketOrderRequest(
                symbol=ticker, qty=qty, side=order_side,
                time_in_force=TimeInForce.DAY,
            )

        order = client.submit_order(req)
        return {
            "success": True,
            "order_id": str(order.id),
            "status": str(order.status),
            "ticker": ticker,
            "side": side,
            "qty": qty,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def place_bracket_order(ticker, qty, side="buy", take_profit=None, stop_loss=None):
    """Place a bracket order — entry + stop-loss + take-profit managed by Alpaca.

    Args:
        ticker: stock ticker
        qty: number of shares
        side: 'buy' or 'sell' (sell for short entry)
        take_profit: target price for profit leg
        stop_loss: stop price for loss leg

    Returns:
        dict with success, order_id, status, legs
    """
    client = _get_client()
    if not client:
        return {"success": False, "error": "Alpaca not configured"}
    try:
        from alpaca.trading.requests import (
            MarketOrderRequest,
            TakeProfitRequest,
            StopLossRequest,
        )
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        order_data = MarketOrderRequest(
            symbol=ticker.upper(),
            qty=int(qty),
            side=order_side,
            time_in_force=TimeInForce.DAY,
            order_class="bracket",
            take_profit=TakeProfitRequest(limit_price=round(take_profit, 2)) if take_profit else None,
            stop_loss=StopLossRequest(stop_price=round(stop_loss, 2)) if stop_loss else None,
        )
        order = client.submit_order(order_data)
        return {
            "success": True,
            "order_id": str(order.id),
            "status": str(order.status),
            "order_type": "bracket",
            "ticker": ticker,
            "side": side,
            "qty": qty,
        }
    except Exception as e:
        logger.error("Bracket order failed for %s: %s", ticker, e)
        return {"success": False, "error": str(e)}


def place_trailing_stop(ticker, qty, side="buy", trail_percent=None):
    """Place a trailing stop order.

    Args:
        ticker: stock ticker
        qty: number of shares
        side: 'buy' or 'sell'
        trail_percent: trailing percentage (e.g., 3.0 for 3%)

    Returns:
        dict with success, order_id, status
    """
    client = _get_client()
    if not client:
        return {"success": False, "error": "Alpaca not configured"}
    try:
        from alpaca.trading.requests import TrailingStopOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        order_data = TrailingStopOrderRequest(
            symbol=ticker.upper(),
            qty=int(qty),
            side=order_side,
            time_in_force=TimeInForce.GTC,
            trail_percent=str(round(trail_percent, 2)),
        )
        order = client.submit_order(order_data)
        return {
            "success": True,
            "order_id": str(order.id),
            "status": str(order.status),
            "order_type": "trailing_stop",
            "ticker": ticker,
            "side": side,
            "qty": qty,
            "trail_percent": trail_percent,
        }
    except Exception as e:
        logger.error("Trailing stop order failed for %s: %s", ticker, e)
        return {"success": False, "error": str(e)}


def place_short_order(ticker, qty, order_type="market", take_profit=None, stop_loss=None, trail_percent=None):
    """Place a short sell order.

    Args:
        ticker: stock ticker
        qty: number of shares to short
        order_type: 'market', 'bracket', or 'trailing_stop'
        take_profit: target price for profit leg (bracket only)
        stop_loss: stop price for loss leg (bracket only)
        trail_percent: trailing percentage (trailing_stop only)

    Returns:
        dict with success, order_id, status
    """
    if order_type == "bracket" and take_profit and stop_loss:
        return place_bracket_order(ticker, qty, side="sell",
                                   take_profit=take_profit, stop_loss=stop_loss)
    elif order_type == "trailing_stop" and trail_percent:
        return place_trailing_stop(ticker, qty, side="sell", trail_percent=trail_percent)
    else:
        return place_order(ticker, qty, "sell")


def get_positions():
    """Get all open positions."""
    client = _get_client()
    if not client:
        return []
    try:
        positions = client.get_all_positions()
        return [
            {
                "ticker": p.symbol,
                "qty": float(p.qty),
                "avg_cost": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in positions
        ]
    except Exception as e:
        logger.error("Failed to get positions: %s", e)
        return []


def get_orders(status="all"):
    """Get recent orders."""
    client = _get_client()
    if not client:
        return []
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        status_map = {"all": QueryOrderStatus.ALL, "open": QueryOrderStatus.OPEN, "closed": QueryOrderStatus.CLOSED}
        req = GetOrdersRequest(status=status_map.get(status, QueryOrderStatus.ALL), limit=50)
        orders = client.get_orders(req)
        return [
            {
                "order_id": str(o.id),
                "ticker": o.symbol,
                "side": str(o.side),
                "qty": float(o.qty) if o.qty else 0,
                "filled_qty": float(o.filled_qty) if o.filled_qty else 0,
                "type": str(o.type),
                "status": str(o.status),
                "created_at": str(o.created_at),
            }
            for o in orders
        ]
    except Exception as e:
        logger.error("Failed to get orders: %s", e)
        return []

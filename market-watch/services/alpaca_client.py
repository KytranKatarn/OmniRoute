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

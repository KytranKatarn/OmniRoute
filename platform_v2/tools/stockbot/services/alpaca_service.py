"""
Alpaca Service — StockBot Phase 3
Live trading integration via Alpaca API (requires alpaca-trade-api pip package).
Credentials stored in user_integrations table under service='alpaca'.
"""

import logging
import sys

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

from database import get_db_cursor

logger = logging.getLogger(__name__)

try:
    import alpaca_trade_api as tradeapi

    ALPACA_AVAILABLE = True
except ImportError:
    ALPACA_AVAILABLE = False
    logger.info("alpaca-trade-api not installed; Alpaca integration disabled")


def is_configured(user_id: int) -> bool:
    """Return True if user has active Alpaca credentials stored."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id FROM user_integrations WHERE user_id = %s AND service = 'alpaca' AND status = 'active'",
            (user_id,),
        )
        return cur.fetchone() is not None


def get_alpaca_client(user_id: int):
    """Load credentials from user_integrations and return an alpaca REST client, or None."""
    if not ALPACA_AVAILABLE:
        return None

    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT credentials FROM user_integrations WHERE user_id = %s AND service = 'alpaca' AND status = 'active'",
            (user_id,),
        )
        row = cur.fetchone()

    if not row:
        return None

    creds = row[0] or {}
    api_key = creds.get("api_key")
    api_secret = creds.get("api_secret")
    base_url = creds.get("base_url", "https://paper-api.alpaca.markets")

    if not api_key or not api_secret:
        return None

    try:
        return tradeapi.REST(api_key, api_secret, base_url, api_version="v2")
    except Exception as e:
        logger.error(f"get_alpaca_client({user_id}) failed: {e}")
        return None


def get_account(user_id: int) -> dict:
    """Fetch Alpaca account info."""
    if not ALPACA_AVAILABLE:
        return {"error": "alpaca-trade-api not installed"}

    client = get_alpaca_client(user_id)
    if not client:
        return {"error": "Alpaca not configured for this user"}

    try:
        acct = client.get_account()
        return {
            "buying_power": float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
            "cash": float(acct.cash),
            "status": acct.status,
            "currency": acct.currency,
        }
    except Exception as e:
        logger.error(f"get_account({user_id}) error: {e}")
        return {"error": str(e)}


def submit_order(user_id: int, ticker: str, qty: float, side: str, order_type: str = "market") -> dict:
    """Submit a live order via Alpaca."""
    if not ALPACA_AVAILABLE:
        return {"error": "alpaca-trade-api not installed"}

    client = get_alpaca_client(user_id)
    if not client:
        return {"error": "Alpaca not configured for this user"}

    ticker = ticker.upper().strip()
    try:
        order = client.submit_order(
            symbol=ticker,
            qty=qty,
            side=side,
            type=order_type,
            time_in_force="day",
        )
        return {
            "success": True,
            "order_id": order.id,
            "symbol": order.symbol,
            "qty": float(order.qty),
            "side": order.side,
            "type": order.type,
            "status": order.status,
            "submitted_at": str(order.submitted_at),
        }
    except Exception as e:
        logger.error(f"submit_order({user_id}, {ticker}) error: {e}")
        return {"success": False, "error": str(e)}


def get_positions(user_id: int) -> list:
    """List open Alpaca positions."""
    if not ALPACA_AVAILABLE:
        return []

    client = get_alpaca_client(user_id)
    if not client:
        return []

    try:
        positions = client.list_positions()
        return [
            {
                "ticker": p.symbol,
                "qty": float(p.qty),
                "avg_entry_price": float(p.avg_entry_price),
                "current_price": float(p.current_price),
                "market_value": float(p.market_value),
                "unrealized_pl": float(p.unrealized_pl),
                "unrealized_plpc": float(p.unrealized_plpc),
            }
            for p in positions
        ]
    except Exception as e:
        logger.error(f"get_positions({user_id}) error: {e}")
        return []


def sync_portfolio(user_id: int) -> dict:
    """Pull Alpaca positions and sync to stock_portfolio table."""
    if not ALPACA_AVAILABLE:
        return {"error": "alpaca-trade-api not installed"}

    positions = get_positions(user_id)
    if not positions and not is_configured(user_id):
        return {"error": "Alpaca not configured for this user"}

    synced = 0
    with get_db_cursor(commit=True) as (conn, cur):
        # Clear live positions for this user (paper_trade=False rows don't exist in portfolio yet,
        # so we track by removing tickers no longer held)
        alpaca_tickers = {p["ticker"] for p in positions}

        # Remove tickers no longer held
        cur.execute(
            "SELECT ticker FROM stock_portfolio WHERE user_id = %s",
            (user_id,),
        )
        existing = {r[0] for r in cur.fetchall()}
        for stale in existing - alpaca_tickers:
            cur.execute(
                "DELETE FROM stock_portfolio WHERE user_id = %s AND ticker = %s",
                (user_id, stale),
            )

        for pos in positions:
            cur.execute(
                """
                INSERT INTO stock_portfolio (user_id, ticker, shares, avg_cost, current_price, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (user_id, ticker) DO UPDATE SET
                    shares = EXCLUDED.shares,
                    avg_cost = EXCLUDED.avg_cost,
                    current_price = EXCLUDED.current_price,
                    updated_at = NOW()
                """,
                (
                    user_id,
                    pos["ticker"],
                    pos["qty"],
                    pos["avg_entry_price"],
                    pos["current_price"],
                ),
            )
            synced += 1

    return {"success": True, "synced": synced}

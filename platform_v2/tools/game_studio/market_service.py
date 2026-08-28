"""
Game Studio — Market Service (Phase 5)
Dynamic resource pricing driven by supply/demand signals from world events.
"""

import logging


from database import get_db_cursor
from tools.game_studio import world_state_service

logger = logging.getLogger(__name__)

_PRICE_FLOOR_MULTIPLIER = 0.1
_PRICE_CEILING_MULTIPLIER = 10.0


def get_market_prices() -> dict:
    """Return all market prices as {resource_type: {base_price, current_price, supply_1h, demand_1h}}."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute("SELECT resource_type, base_price, current_price, supply_1h, demand_1h FROM game_market_prices")
            rows = cur.fetchall()
            return {
                r["resource_type"]: {
                    "base_price": r["base_price"],
                    "current_price": r["current_price"],
                    "supply_1h": r["supply_1h"],
                    "demand_1h": r["demand_1h"],
                }
                for r in rows
            }
    except Exception as e:
        logger.error(f"[market_service] get_market_prices error: {e}")
        return {}


def update_market_prices() -> dict:
    """
    Recalculate market prices from the last hour of world events.
    Supply = sum of positive resource deltas, Demand = sum of negative deltas (abs).
    New price = base * (demand / max(supply, 1)), clamped to [0.1x, 10x] base.
    Returns {resource_type: new_price}.
    """
    updates = {}
    try:
        prices = get_market_prices()
        if not prices:
            return updates

        # Count supply (+delta) and demand (-delta) signals from the last hour
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT
                    data->>'resource_type' AS resource_type,
                    SUM(CASE WHEN (data->>'delta')::float > 0 THEN (data->>'delta')::float ELSE 0 END)    AS supply,
                    SUM(CASE WHEN (data->>'delta')::float < 0 THEN ABS((data->>'delta')::float) ELSE 0 END) AS demand
                  FROM game_world_events
                 WHERE created_at >= NOW() - INTERVAL '1 hour'
                   AND data ? 'resource_type'
                   AND data ? 'delta'
                 GROUP BY data->>'resource_type'
                """
            )
            rows = cur.fetchall()

        signals = {
            r["resource_type"]: {"supply": float(r["supply"] or 0), "demand": float(r["demand"] or 0)} for r in rows
        }

        with get_db_cursor(commit=True) as (conn, cur):
            for resource_type, info in prices.items():
                sig = signals.get(resource_type, {"supply": 0, "demand": 0})
                supply = sig["supply"]
                demand = sig["demand"]
                base = info["base_price"]

                raw_price = base * (demand / max(supply, 1))
                new_price = max(base * _PRICE_FLOOR_MULTIPLIER, min(raw_price, base * _PRICE_CEILING_MULTIPLIER))
                # If no signals, keep current price unchanged
                if demand == 0 and supply == 0:
                    new_price = info["current_price"]

                cur.execute(
                    """
                    UPDATE game_market_prices
                       SET current_price = %s,
                           supply_1h     = %s,
                           demand_1h     = %s,
                           updated_at    = NOW()
                     WHERE resource_type = %s
                    """,
                    (new_price, supply, demand, resource_type),
                )
                updates[resource_type] = new_price

    except Exception as e:
        logger.error(f"[market_service] update_market_prices error: {e}")

    return updates


def trade(from_resource: str, to_resource: str, amount: float, profile_id=None) -> dict:
    """
    Exchange amount of from_resource for to_resource at current market rates.
    Rate = current_price(from) / current_price(to).
    Deducts from_resource, adds to_resource, fires trade_completed world event.
    Returns {success, exchanged, rate, error}.
    """
    try:
        prices = get_market_prices()
        if from_resource not in prices or to_resource not in prices:
            return {"success": False, "error": "Unknown resource type"}

        from_price = prices[from_resource]["current_price"]
        to_price = prices[to_resource]["current_price"]

        if to_price == 0:
            return {"success": False, "error": "Invalid to_resource price (zero)"}

        rate = from_price / to_price
        exchanged = amount * rate

        # Deduct from_resource
        new_from = world_state_service.update_resource(from_resource, -amount, profile_id)
        if new_from is None:
            return {"success": False, "error": f"Failed to deduct {from_resource}"}

        # Add to_resource
        world_state_service.update_resource(to_resource, exchanged, profile_id)

        # Fire trade_completed world event
        world_state_service.create_world_event(
            event_type="trade_completed",
            source_game_type="market",
            profile_id=profile_id,
            data={
                "from_resource": from_resource,
                "to_resource": to_resource,
                "amount": amount,
                "exchanged": exchanged,
                "rate": rate,
                "resource_type": from_resource,
                "delta": -amount,
            },
        )

        return {"success": True, "exchanged": exchanged, "rate": rate}

    except Exception as e:
        logger.error(f"[market_service] trade error: {e}")
        return {"success": False, "error": str(e)}


def get_trade_history(limit: int = 20) -> list:
    """Return the most recent trade_completed world events."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, profile_id, data, created_at
                  FROM game_world_events
                 WHERE event_type = 'trade_completed'
                 ORDER BY created_at DESC
                 LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
            result = []
            for r in rows:
                result.append(
                    {
                        "id": r["id"],
                        "profile_id": r["profile_id"],
                        "data": r["data"],
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                )
            return result
    except Exception as e:
        logger.error(f"[market_service] get_trade_history error: {e}")
        return []

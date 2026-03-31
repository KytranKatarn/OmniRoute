"""Watchlist CRUD endpoints."""

from flask import Blueprint, jsonify, request
from db import get_db
from services.market_data import get_quote
from auth import tier_required

watchlist_bp = Blueprint("watchlist", __name__)


@watchlist_bp.route("/api/watchlist")
@tier_required("viewer")
def list_watchlist():
    """Get all watchlist items with current prices."""
    conn = get_db()
    items = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
    conn.close()

    result = []
    for item in items:
        quote = get_quote(item["ticker"])
        result.append({
            "id": item["id"],
            "ticker": item["ticker"],
            "notes": item["notes"],
            "added_at": item["added_at"],
            "price": quote.get("price", 0),
            "change_percent": quote.get("change_percent", 0),
            "name": quote.get("name", item["ticker"]),
        })
    return jsonify({"success": True, "items": result, "count": len(result)})


@watchlist_bp.route("/api/watchlist", methods=["POST"])
@tier_required("ai")
def add_to_watchlist():
    """Add a ticker to the watchlist."""
    data = request.get_json() or {}
    ticker = (data.get("ticker") or "").upper().strip()
    notes = data.get("notes", "")

    if not ticker:
        return jsonify({"success": False, "error": "Ticker required"}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO watchlist (ticker, notes) VALUES (?, ?)",
            (ticker, notes),
        )
        conn.commit()
        return jsonify({"success": True, "ticker": ticker})
    except Exception as e:
        if "UNIQUE" in str(e):
            return jsonify({"success": False, "error": f"{ticker} already in watchlist"}), 409
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        conn.close()


@watchlist_bp.route("/api/watchlist/<int:item_id>", methods=["DELETE"])
@tier_required("ai")
def remove_from_watchlist(item_id):
    """Remove a ticker from the watchlist."""
    conn = get_db()
    conn.execute("DELETE FROM watchlist WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@watchlist_bp.route("/api/watchlist/bulk", methods=["POST"])
@tier_required("ai")
def bulk_add():
    """Add multiple tickers at once (comma-separated)."""
    data = request.get_json() or {}
    tickers_str = data.get("tickers", "")
    tickers = [t.strip().upper() for t in tickers_str.split(",") if t.strip()]

    conn = get_db()
    added = []
    skipped = []
    for ticker in tickers:
        try:
            conn.execute("INSERT INTO watchlist (ticker) VALUES (?)", (ticker,))
            added.append(ticker)
        except Exception:
            skipped.append(ticker)
    conn.commit()
    conn.close()
    return jsonify({"success": True, "added": added, "skipped": skipped})

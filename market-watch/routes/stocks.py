"""Stock quote and search endpoints."""

from flask import Blueprint, jsonify, request
from services.market_data import get_quote, get_fundamentals, search_tickers

stocks_bp = Blueprint("stocks", __name__)


@stocks_bp.route("/api/stocks/<ticker>")
def stock_quote(ticker):
    """Get current quote for a ticker."""
    quote = get_quote(ticker.upper())
    return jsonify({"success": True, **quote})


@stocks_bp.route("/api/stocks/<ticker>/fundamentals")
def stock_fundamentals(ticker):
    """Get fundamental data for a ticker."""
    data = get_fundamentals(ticker.upper())
    return jsonify({"success": True, **data})


@stocks_bp.route("/api/stocks/search")
def stock_search():
    """Search for tickers."""
    q = request.args.get("q", "")
    if not q:
        return jsonify({"success": False, "error": "Query required"}), 400
    results = search_tickers(q)
    return jsonify({"success": True, "results": results})

"""OHLCV chart data endpoints."""

from flask import Blueprint, jsonify, request
from services.market_data import get_history, calculate_indicators
from auth import tier_required

charts_bp = Blueprint("charts", __name__)


@charts_bp.route("/api/charts/<ticker>")
@tier_required("viewer")
def chart_data(ticker):
    """Get OHLCV data for charting."""
    period = request.args.get("period", "3mo")
    interval = request.args.get("interval", "1d")
    history = get_history(ticker.upper(), period=period, interval=interval)
    return jsonify({"success": True, **history})


@charts_bp.route("/api/charts/<ticker>/indicators")
@tier_required("viewer")
def chart_indicators(ticker):
    """Get technical indicators."""
    indicators = calculate_indicators(ticker.upper())
    return jsonify({"success": True, **indicators})

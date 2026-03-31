"""Historical strategy backtesting engine."""

import json
import logging
import math
from services.market_data import get_history
from services.strategy_library import STRATEGIES, run_strategy

logger = logging.getLogger(__name__)


def run_backtest(tickers, strategy_id="sma_crossover", strategy=None, start_date=None, end_date=None, initial_capital=100000):
    """Run a backtest simulation using the strategy library.

    Args:
        tickers: List of ticker symbols to backtest.
        strategy_id: Strategy identifier from STRATEGIES library (default: sma_crossover).
        strategy: Deprecated alias for strategy_id (kept for backward compat).
        start_date: Optional start date filter (not yet applied to data fetch).
        end_date: Optional end date filter (not yet applied to data fetch).
        initial_capital: Starting capital in dollars (default: 100000).

    Returns:
        dict with success, strategy_id, and per-ticker results.
    """
    # Backward compat: honour old `strategy` kwarg if strategy_id not overridden
    effective_strategy_id = strategy_id if strategy_id != "sma_crossover" else (strategy or strategy_id)

    if effective_strategy_id not in STRATEGIES:
        return {"success": False, "error": f"Unknown strategy: {effective_strategy_id}"}

    results = []
    per_ticker_capital = initial_capital / len(tickers)

    for ticker in tickers:
        history = get_history(ticker, period="1y")
        data = history.get("data", [])
        if not data:
            results.append({"ticker": ticker, "error": "No data available"})
            continue

        closes = [d["close"] for d in data]
        times = [d["time"] for d in data]

        strategy_result = run_strategy(effective_strategy_id, closes, times, per_ticker_capital)

        if "error" in strategy_result:
            results.append({"ticker": ticker, "error": strategy_result["error"]})
            continue

        equity_curve = strategy_result["equity_curve"]
        trades = strategy_result["trades"]
        final_value = strategy_result["final_value"]
        total_return = (final_value - per_ticker_capital) / per_ticker_capital

        # Sharpe ratio
        returns = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]["value"]
            if prev > 0:
                returns.append((equity_curve[i]["value"] - prev) / prev)
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = math.sqrt(sum((r - avg_return) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 1
        sharpe = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0

        # Max drawdown
        peak = equity_curve[0]["value"] if equity_curve else per_ticker_capital
        max_dd = 0
        for point in equity_curve:
            if point["value"] > peak:
                peak = point["value"]
            if peak > 0:
                dd = (peak - point["value"]) / peak
                if dd > max_dd:
                    max_dd = dd

        wins = sum(1 for i in range(1, len(trades), 2) if i < len(trades) and trades[i]["price"] > trades[i - 1]["price"])
        total_trades = len(trades) // 2

        results.append({
            "ticker": ticker,
            "strategy_id": effective_strategy_id,
            "initial_capital": round(per_ticker_capital, 2),
            "final_value": round(final_value, 2),
            "total_return": round(total_return * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd * 100, 2),
            "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            "trade_count": total_trades,
            "equity_curve": equity_curve,
            "trades": trades,
        })

    return {"success": True, "strategy_id": effective_strategy_id, "strategy": effective_strategy_id, "results": results}

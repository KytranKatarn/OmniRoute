"""Historical strategy backtesting engine."""

import json
import logging
import math
from services.market_data import get_history

logger = logging.getLogger(__name__)


def run_backtest(tickers, strategy="sma_crossover", start_date=None, end_date=None, initial_capital=100000):
    """Run a backtest simulation."""
    if strategy == "sma_crossover":
        return _sma_crossover_backtest(tickers, initial_capital)
    return {"success": False, "error": f"Unknown strategy: {strategy}"}


def _sma_crossover_backtest(tickers, initial_capital):
    """Simple SMA 20/50 crossover strategy backtest."""
    results = []
    for ticker in tickers:
        history = get_history(ticker, period="1y")
        data = history.get("data", [])
        if len(data) < 50:
            results.append({"ticker": ticker, "error": "Insufficient data"})
            continue

        closes = [d["close"] for d in data]
        cash = initial_capital / len(tickers)
        shares = 0
        trades = []
        equity_curve = []

        for i in range(50, len(closes)):
            sma_20 = sum(closes[i - 20:i]) / 20
            sma_50 = sum(closes[i - 50:i]) / 50
            price = closes[i]

            portfolio_value = cash + shares * price
            equity_curve.append({"time": data[i]["time"], "value": round(portfolio_value, 2)})

            # Buy signal: SMA 20 crosses above SMA 50
            if sma_20 > sma_50 and shares == 0:
                shares = int(cash / price)
                if shares > 0:
                    cash -= shares * price
                    trades.append({"action": "buy", "price": price, "shares": shares, "time": data[i]["time"]})

            # Sell signal: SMA 20 crosses below SMA 50
            elif sma_20 < sma_50 and shares > 0:
                cash += shares * price
                trades.append({"action": "sell", "price": price, "shares": shares, "time": data[i]["time"]})
                shares = 0

        final_value = cash + shares * closes[-1]
        total_return = (final_value - initial_capital / len(tickers)) / (initial_capital / len(tickers))

        # Calculate Sharpe ratio
        returns = []
        for i in range(1, len(equity_curve)):
            r = (equity_curve[i]["value"] - equity_curve[i - 1]["value"]) / equity_curve[i - 1]["value"]
            returns.append(r)
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = math.sqrt(sum((r - avg_return) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 1
        sharpe = (avg_return / std_return) * math.sqrt(252) if std_return > 0 else 0

        # Max drawdown
        peak = equity_curve[0]["value"]
        max_dd = 0
        for point in equity_curve:
            if point["value"] > peak:
                peak = point["value"]
            dd = (peak - point["value"]) / peak
            if dd > max_dd:
                max_dd = dd

        wins = sum(1 for i in range(1, len(trades), 2) if i < len(trades) and trades[i]["price"] > trades[i - 1]["price"])
        total_trades = len(trades) // 2

        results.append({
            "ticker": ticker,
            "initial_capital": initial_capital / len(tickers),
            "final_value": round(final_value, 2),
            "total_return": round(total_return * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown": round(max_dd * 100, 2),
            "win_rate": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            "trade_count": total_trades,
            "equity_curve": equity_curve,
            "trades": trades,
        })

    return {"success": True, "strategy": "sma_crossover", "results": results}

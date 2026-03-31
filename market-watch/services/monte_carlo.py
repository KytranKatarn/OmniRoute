"""Monte Carlo simulation for backtesting — 1000+ trade sequence randomizations."""

import json
import logging
import math
import random

logger = logging.getLogger(__name__)


def run_monte_carlo(trades, equity_curve, initial_capital, simulations=1000):
    """
    Randomize trade sequence N times. Returns probability distributions
    of returns, drawdown, Sharpe, and ruin probability.

    trades: list of trade dicts with 'action', 'price', 'shares'
    equity_curve: list of {'time', 'value'} dicts (unused directly, kept for signature compat)
    initial_capital: float
    simulations: int, number of Monte Carlo runs
    """
    if not trades or len(trades) < 2:
        return {
            "success": False,
            "error": "Need at least 2 trades for Monte Carlo simulation",
        }

    # Extract paired trade P&L (buy then sell)
    buy_trades = [t for t in trades if t["action"] == "buy"]
    sell_trades = [t for t in trades if t["action"] == "sell"]
    pairs = list(zip(buy_trades, sell_trades))
    if not pairs:
        return {"success": False, "error": "No complete buy/sell pairs found"}

    pnl_list = []
    for buy, sell in pairs:
        shares = buy.get("shares", 1)
        pnl = (sell["price"] - buy["price"]) * shares
        pnl_list.append(pnl)

    sim_results = []
    ruin_count = 0
    ruin_threshold = initial_capital * 0.5  # 50% loss = ruin

    for _ in range(simulations):
        shuffled = pnl_list[:]
        random.shuffle(shuffled)
        capital = initial_capital
        peak = capital
        sim_equity = [capital]
        max_dd = 0
        returns = []
        for pnl in shuffled:
            prev = capital
            capital += pnl
            if capital <= 0:
                capital = 0
            sim_equity.append(capital)
            if capital > peak:
                peak = capital
            dd = (peak - capital) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
            r = (capital - prev) / prev if prev > 0 else 0
            returns.append(r)
        final_return = (capital - initial_capital) / initial_capital if initial_capital > 0 else 0
        avg_r = sum(returns) / len(returns) if returns else 0
        std_r = math.sqrt(sum((r - avg_r) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 1e-9
        sharpe = (avg_r / std_r) * math.sqrt(252) if std_r > 0 else 0
        if capital < ruin_threshold:
            ruin_count += 1
        sim_results.append({
            "final_return": final_return,
            "max_drawdown": max_dd,
            "sharpe": sharpe,
        })

    final_returns = sorted(r["final_return"] for r in sim_results)
    sharpes = sorted(r["sharpe"] for r in sim_results)
    drawdowns = sorted(r["max_drawdown"] for r in sim_results)
    n = len(sim_results)

    def pct(lst, p):
        idx = int(p / 100 * (n - 1))
        return round(lst[idx], 4)

    mean_return = round(sum(final_returns) / n, 4)
    std_return = round(
        math.sqrt(sum((r - mean_return) ** 2 for r in final_returns) / n), 4
    )
    ruin_prob = round(ruin_count / simulations, 4)

    return {
        "success": True,
        "simulations": simulations,
        "mean_return": mean_return,
        "std_return": std_return,
        "percentile_5": pct(final_returns, 5),
        "percentile_25": pct(final_returns, 25),
        "percentile_50": pct(final_returns, 50),
        "percentile_75": pct(final_returns, 75),
        "percentile_95": pct(final_returns, 95),
        "ruin_probability": ruin_prob,
        "mean_sharpe": round(sum(sharpes) / n, 2),
        "mean_max_drawdown": round(sum(drawdowns) / n * 100, 2),
        "distribution": {
            "returns": {
                "p5": pct(final_returns, 5),
                "p25": pct(final_returns, 25),
                "p50": pct(final_returns, 50),
                "p75": pct(final_returns, 75),
                "p95": pct(final_returns, 95),
            },
            "sharpe": {
                "p5": pct(sharpes, 5),
                "p50": pct(sharpes, 50),
                "p95": pct(sharpes, 95),
            },
            "drawdown": {
                "p5": pct(drawdowns, 5),
                "p50": pct(drawdowns, 50),
                "p95": pct(drawdowns, 95),
            },
        },
    }

"""Backtest endpoints — Phase B6 multi-strategy + Monte Carlo + Walk-Forward + Optimizer."""

import json
import logging
from flask import Blueprint, jsonify, request
from db import get_db
from services.backtest_engine import run_backtest
from services.monte_carlo import run_monte_carlo
from services.walk_forward import run_walk_forward
from services.optimizer import optimize_strategy, grid_search, random_search
from services.strategy_library import STRATEGIES, get_strategy_list, _RUNNERS
from services.market_data import get_history
from auth import tier_required

logger = logging.getLogger(__name__)
backtest_bp = Blueprint("backtest", __name__)


@backtest_bp.route("/api/backtest/run", methods=["POST"])
@tier_required("ai")
def run():
    """Run a backtest with any supported strategy."""
    data = request.get_json() or {}
    tickers = data.get("tickers", [])
    strategy = data.get("strategy", "sma_crossover")
    initial_capital = float(data.get("initial_capital", 100000))
    params = data.get("params")

    if not tickers:
        return jsonify({"success": False, "error": "Tickers required"}), 400

    result = run_backtest(tickers, strategy, initial_capital=initial_capital, params=params)

    if result["success"]:
        conn = get_db()
        for r in result.get("results", []):
            if "error" in r:
                continue
            conn.execute(
                """INSERT INTO backtest_results
                   (strategy, tickers, start_date, end_date, initial_capital,
                    final_value, total_return, sharpe_ratio, max_drawdown,
                    win_rate, trade_count, equity_curve, trade_log)
                   VALUES (?, ?, '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    strategy, r["ticker"], r["initial_capital"], r.get("final_value"),
                    r.get("total_return"), r.get("sharpe_ratio"), r.get("max_drawdown"),
                    r.get("win_rate"), r.get("trade_count"),
                    json.dumps(r.get("equity_curve", [])),
                    json.dumps(r.get("trades", [])),
                ),
            )
        conn.commit()
        conn.close()

    return jsonify(result)


@backtest_bp.route("/api/backtest/results")
@tier_required("ai")
def results():
    """Get past backtest results."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM backtest_results ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    conn.close()
    return jsonify({"success": True, "results": [dict(r) for r in rows]})


@backtest_bp.route("/api/backtest/strategies")
@tier_required("viewer")
def strategies():
    """List available strategies with descriptions."""
    return jsonify({"success": True, "strategies": get_strategy_list()})


@backtest_bp.route("/api/backtest/monte-carlo", methods=["POST"])
@tier_required("ai")
def monte_carlo():
    """Run Monte Carlo simulation on a strategy backtest."""
    data = request.get_json() or {}
    tickers = data.get("tickers", [])
    strategy = data.get("strategy", "sma_crossover")
    initial_capital = float(data.get("initial_capital", 100000))
    simulations = min(int(data.get("simulations", 1000)), 5000)
    params = data.get("params")

    if not tickers:
        return jsonify({"success": False, "error": "Tickers required"}), 400

    bt = run_backtest(tickers[:1], strategy, initial_capital=initial_capital, params=params)
    if not bt["success"] or not bt.get("results"):
        return jsonify({"success": False, "error": "Backtest failed for Monte Carlo"}), 400

    bt_result = bt["results"][0]
    if "error" in bt_result:
        return jsonify({"success": False, "error": bt_result["error"]}), 400

    mc = run_monte_carlo(
        bt_result.get("trades", []),
        bt_result.get("equity_curve", []),
        initial_capital,
        simulations=simulations,
    )

    if mc.get("success"):
        conn = get_db()
        conn.execute(
            """INSERT INTO monte_carlo_results
               (ticker, strategy, simulations, mean_return, std_return,
                percentile_5, percentile_25, percentile_50, percentile_75, percentile_95,
                ruin_probability, mean_sharpe, mean_max_drawdown, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                tickers[0], strategy, simulations,
                mc["mean_return"], mc["std_return"],
                mc["percentile_5"], mc["percentile_25"], mc["percentile_50"],
                mc["percentile_75"], mc["percentile_95"],
                mc["ruin_probability"], mc["mean_sharpe"], mc["mean_max_drawdown"],
                json.dumps(mc.get("distribution", {})),
            ),
        )
        conn.commit()
        conn.close()

    return jsonify({**mc, "ticker": tickers[0], "strategy": strategy})


@backtest_bp.route("/api/backtest/walk-forward", methods=["POST"])
@tier_required("ai")
def walk_forward():
    """Run walk-forward analysis for a strategy on a ticker."""
    data = request.get_json() or {}
    ticker = data.get("ticker", "SPY")
    strategy = data.get("strategy", "sma_crossover")
    initial_capital = float(data.get("initial_capital", 100000))
    window_size = int(data.get("window_size", 252))
    step_size = int(data.get("step_size", 63))
    params = data.get("params")

    runner = _RUNNERS.get(strategy)
    if not runner:
        return jsonify({"success": False, "error": f"Unknown strategy: {strategy}"}), 400

    history = get_history(ticker, period="2y")
    hist_data = history.get("data", [])
    if len(hist_data) < window_size + step_size:
        return jsonify({"success": False, "error": "Insufficient historical data"}), 400

    closes = [d["close"] for d in hist_data]
    timestamps = [d["time"] for d in hist_data]

    wf = run_walk_forward(closes, timestamps, runner, initial_capital, params,
                          window_size=window_size, step_size=step_size)

    if wf.get("success"):
        conn = get_db()
        conn.execute(
            """INSERT INTO walk_forward_results
               (strategy, tickers, window_size, step_size, windows,
                avg_oos_sharpe, consistency_ratio, overfitting_score, params_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                strategy, ticker, window_size, step_size,
                json.dumps(wf.get("windows", [])),
                wf["avg_oos_sharpe"], wf["consistency_ratio"], wf["overfitting_score"],
                json.dumps(params or {}),
            ),
        )
        conn.commit()
        conn.close()

    return jsonify({**wf, "ticker": ticker, "strategy": strategy})


@backtest_bp.route("/api/backtest/optimize", methods=["POST"])
@tier_required("ai")
def optimize():
    """Run parameter optimization with walk-forward validation."""
    data = request.get_json() or {}
    ticker = data.get("ticker", "SPY")
    strategy = data.get("strategy", "sma_crossover")
    initial_capital = float(data.get("initial_capital", 100000))
    search_type = data.get("search_type", "grid")
    max_combinations = int(data.get("max_combinations", 30))
    n_iter = int(data.get("n_iter", 20))
    window_size = int(data.get("window_size", 252))
    step_size = int(data.get("step_size", 63))

    runner = _RUNNERS.get(strategy)
    if not runner:
        return jsonify({"success": False, "error": f"Unknown strategy: {strategy}"}), 400

    history = get_history(ticker, period="2y")
    hist_data = history.get("data", [])
    if not hist_data:
        return jsonify({"success": False, "error": "No historical data"}), 400

    closes = [d["close"] for d in hist_data]
    timestamps = [d["time"] for d in hist_data]

    if search_type == "random":
        result = random_search(closes, timestamps, runner, strategy, initial_capital,
                               n_iter=n_iter, window_size=window_size, step_size=step_size)
    else:
        result = grid_search(closes, timestamps, runner, strategy, initial_capital,
                             window_size=window_size, step_size=step_size,
                             max_combinations=max_combinations)

    return jsonify({**result, "ticker": ticker, "strategy": strategy})


@backtest_bp.route("/api/public/backtest-showcase")
def backtest_showcase():
    """Public endpoint — best strategy performance for landing page."""
    conn = get_db()
    rows = conn.execute(
        """SELECT strategy, tickers, total_return, sharpe_ratio, max_drawdown, win_rate,
                  trade_count, created_at
           FROM backtest_results
           WHERE total_return IS NOT NULL
           ORDER BY sharpe_ratio DESC
           LIMIT 6"""
    ).fetchall()
    conn.close()

    showcase = [
        {
            "strategy": dict(r)["strategy"],
            "ticker": dict(r)["tickers"],
            "total_return": dict(r)["total_return"],
            "sharpe_ratio": dict(r)["sharpe_ratio"],
            "max_drawdown": dict(r)["max_drawdown"],
            "win_rate": dict(r)["win_rate"],
            "trade_count": dict(r)["trade_count"],
            "date": dict(r)["created_at"],
        }
        for r in rows
    ]

    # Seed with demo data if no real results yet
    if not showcase:
        showcase = [
            {"strategy": "sma_crossover", "ticker": "SPY", "total_return": 14.2,
             "sharpe_ratio": 1.12, "max_drawdown": 8.3, "win_rate": 58.0, "trade_count": 12, "date": "demo"},
            {"strategy": "rsi_mean_reversion", "ticker": "AAPL", "total_return": 22.7,
             "sharpe_ratio": 1.45, "max_drawdown": 11.2, "win_rate": 63.0, "trade_count": 18, "date": "demo"},
            {"strategy": "macd_momentum", "ticker": "TSLA", "total_return": 31.4,
             "sharpe_ratio": 0.98, "max_drawdown": 19.5, "win_rate": 51.0, "trade_count": 24, "date": "demo"},
        ]

    return jsonify({"success": True, "showcase": showcase})

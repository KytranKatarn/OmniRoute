"""Parameter optimizer — grid and random search with walk-forward validation."""

import logging
import itertools
import random as rand_module
from services.walk_forward import run_walk_forward

logger = logging.getLogger(__name__)

PARAM_GRIDS = {
    "sma_crossover": {
        "fast": [10, 15, 20, 25, 30],
        "slow": [40, 50, 60, 80, 100],
    },
    "rsi_mean_reversion": {
        "period": [10, 14, 21],
        "oversold": [25, 30, 35],
        "overbought": [65, 70, 75],
    },
    "macd_momentum": {
        "fast": [8, 12, 16],
        "slow": [21, 26, 30],
        "signal": [7, 9, 12],
    },
    "bollinger_bounce": {
        "period": [15, 20, 25],
        "std_dev": [1.5, 2.0, 2.5],
    },
    "watch_replay": {
        "confidence_threshold": [0.5, 0.6, 0.7, 0.8],
    },
}


def grid_search(closes, timestamps, strategy_fn, strategy_id, initial_capital,
                window_size=252, step_size=63, max_combinations=50):
    """
    Grid search over PARAM_GRIDS[strategy_id].
    Returns top 5 param sets by avg OOS Sharpe.
    Caps at max_combinations to avoid excessive runtime.
    """
    grid = PARAM_GRIDS.get(strategy_id, {})
    if not grid:
        return {"success": False, "error": f"No param grid for strategy: {strategy_id}"}

    keys = list(grid.keys())
    values = list(grid.values())
    all_combos = list(itertools.product(*values))

    search_type = "grid"
    if len(all_combos) > max_combinations:
        all_combos = rand_module.sample(all_combos, max_combinations)
        search_type = "random_grid"

    results = []
    for combo in all_combos:
        params = dict(zip(keys, combo))
        # Skip invalid combinations
        if strategy_id == "sma_crossover" and params.get("fast", 0) >= params.get("slow", 999):
            continue
        if strategy_id == "macd_momentum" and params.get("fast", 0) >= params.get("slow", 999):
            continue
        wf = run_walk_forward(
            closes, timestamps, strategy_fn, initial_capital, params,
            window_size=window_size, step_size=step_size,
        )
        if not wf.get("success"):
            continue
        results.append({
            "params": params,
            "avg_oos_sharpe": wf["avg_oos_sharpe"],
            "consistency_ratio": wf["consistency_ratio"],
            "overfitting_score": wf["overfitting_score"],
            "total_windows": wf["total_windows"],
        })

    if not results:
        return {"success": False, "error": "All parameter combinations failed"}

    results.sort(key=lambda x: x["avg_oos_sharpe"], reverse=True)
    top_5 = results[:5]

    return {
        "success": True,
        "search_type": search_type,
        "combinations_tested": len(results),
        "best_params": top_5[0]["params"],
        "best_oos_sharpe": top_5[0]["avg_oos_sharpe"],
        "top_results": top_5,
    }


def random_search(closes, timestamps, strategy_fn, strategy_id, initial_capital,
                  n_iter=30, window_size=252, step_size=63):
    """Random search — sample n_iter random param sets."""
    grid = PARAM_GRIDS.get(strategy_id, {})
    if not grid:
        return {"success": False, "error": f"No param grid for strategy: {strategy_id}"}

    results = []
    for _ in range(n_iter):
        params = {k: rand_module.choice(v) for k, v in grid.items()}
        if strategy_id in ("sma_crossover", "macd_momentum"):
            if params.get("fast", 0) >= params.get("slow", 999):
                continue
        wf = run_walk_forward(
            closes, timestamps, strategy_fn, initial_capital, params,
            window_size=window_size, step_size=step_size,
        )
        if not wf.get("success"):
            continue
        results.append({
            "params": params,
            "avg_oos_sharpe": wf["avg_oos_sharpe"],
            "consistency_ratio": wf["consistency_ratio"],
            "overfitting_score": wf["overfitting_score"],
        })

    if not results:
        return {"success": False, "error": "All random combinations failed"}

    results.sort(key=lambda x: x["avg_oos_sharpe"], reverse=True)
    return {
        "success": True,
        "search_type": "random",
        "combinations_tested": len(results),
        "best_params": results[0]["params"],
        "best_oos_sharpe": results[0]["avg_oos_sharpe"],
        "top_results": results[:5],
    }


def optimize_strategy(strategy_id, tickers, param_grid=None, method="grid",
                      max_combos=50, initial_capital=100000):
    """
    Public entry point: optimize parameters for a given strategy.

    Runs grid or random search across parameter combos (capped at max_combos)
    using walk-forward validation on each combo for overfitting protection.

    Returns:
        dict with best_params, all_results sorted by OOS Sharpe,
        and overfitting_warnings list.
    """
    try:
        from services.strategy_library import STRATEGY_RUNNERS
    except ImportError as e:
        return {"success": False, "error": f"Could not import strategy_library: {e}"}

    strategy_fn = STRATEGY_RUNNERS.get(strategy_id)
    if not strategy_fn:
        return {
            "success": False,
            "error": f"Unknown strategy: {strategy_id}. Available: {list(STRATEGY_RUNNERS.keys())}",
        }

    # Override param grid if caller provided one
    if param_grid:
        PARAM_GRIDS[strategy_id] = param_grid

    # Gather price data for all tickers
    try:
        from services.market_data import get_history
    except ImportError as e:
        return {"success": False, "error": f"Could not import market_data: {e}"}

    all_closes = []
    all_timestamps = []
    for ticker in tickers:
        history = get_history(ticker, period="2y")
        data = history.get("data", [])
        if len(data) < 100:
            logger.warning("Insufficient data for %s (%d points)", ticker, len(data))
            continue
        all_closes.extend([d["close"] for d in data])
        all_timestamps.extend([d.get("date", str(i)) for i, d in enumerate(data)])

    if len(all_closes) < 100:
        return {"success": False, "error": "Insufficient price data across all tickers"}

    # Run search
    if method == "random":
        result = random_search(
            all_closes, all_timestamps, strategy_fn, strategy_id,
            initial_capital, n_iter=max_combos,
        )
    else:
        result = grid_search(
            all_closes, all_timestamps, strategy_fn, strategy_id,
            initial_capital, max_combinations=max_combos,
        )

    if not result.get("success"):
        return result

    # Build overfitting warnings
    overfitting_warnings = []
    for r in result.get("top_results", []):
        score = r.get("overfitting_score", 0)
        if score > 0.5:
            overfitting_warnings.append({
                "params": r["params"],
                "overfitting_score": score,
                "warning": "High overfitting risk — IS/OOS performance gap is large",
            })

    return {
        "success": True,
        "strategy_id": strategy_id,
        "method": result["search_type"],
        "combinations_tested": result["combinations_tested"],
        "best_params": result["best_params"],
        "best_oos_sharpe": result["best_oos_sharpe"],
        "all_results": result["top_results"],
        "overfitting_warnings": overfitting_warnings,
    }

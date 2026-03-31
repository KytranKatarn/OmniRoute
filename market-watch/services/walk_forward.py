"""Walk-forward analysis — sliding train/test windows with OOS Sharpe tracking."""

import logging
import math

logger = logging.getLogger(__name__)


def run_walk_forward(closes, timestamps, strategy_fn, initial_capital, params=None,
                     window_size=252, step_size=63):
    """
    Sliding walk-forward analysis.
    - window_size: trading days in each train window (default 252 = 1 year)
    - step_size: days to advance each iteration (default 63 = 1 quarter)
    - strategy_fn: callable(closes, timestamps, capital, params) -> (trades, equity_curve, final_value)
    Returns windows list, avg_oos_sharpe, consistency_ratio, overfitting_score.
    """
    n = len(closes)
    if n < window_size + step_size:
        return {
            "success": False,
            "error": f"Need at least {window_size + step_size} data points for walk-forward analysis",
        }

    windows = []
    oos_sharpes = []
    is_sharpes = []
    start = 0

    while start + window_size + step_size <= n:
        train_end = start + window_size
        test_end = min(train_end + step_size, n)

        is_closes = closes[start:train_end]
        is_timestamps = timestamps[start:train_end]
        oos_closes = closes[train_end:test_end]
        oos_timestamps = timestamps[train_end:test_end]

        try:
            _, is_equity, is_final = strategy_fn(is_closes, is_timestamps, initial_capital, params)
            _, oos_equity, oos_final = strategy_fn(oos_closes, oos_timestamps, initial_capital, params)
        except Exception as exc:
            logger.warning("Walk-forward window failed: %s", exc)
            start += step_size
            continue

        is_sharpe = _compute_sharpe(is_equity)
        oos_sharpe = _compute_sharpe(oos_equity)
        is_return = (is_final - initial_capital) / initial_capital if initial_capital > 0 else 0
        oos_return = (oos_final - initial_capital) / initial_capital if initial_capital > 0 else 0

        windows.append({
            "train_start": timestamps[start] if timestamps else str(start),
            "train_end": timestamps[train_end - 1] if timestamps else str(train_end),
            "test_start": timestamps[train_end] if timestamps else str(train_end),
            "test_end": timestamps[test_end - 1] if test_end > train_end and timestamps else str(test_end),
            "is_sharpe": round(is_sharpe, 2),
            "oos_sharpe": round(oos_sharpe, 2),
            "is_return": round(is_return * 100, 2),
            "oos_return": round(oos_return * 100, 2),
        })

        is_sharpes.append(is_sharpe)
        oos_sharpes.append(oos_sharpe)
        start += step_size

    if not windows:
        return {"success": False, "error": "No windows completed"}

    avg_oos_sharpe = sum(oos_sharpes) / len(oos_sharpes)
    consistency_ratio = sum(1 for s in oos_sharpes if s > 0) / len(oos_sharpes)
    avg_is = sum(is_sharpes) / len(is_sharpes) if is_sharpes else 1e-9
    overfitting_score = max(0.0, (avg_is - avg_oos_sharpe) / abs(avg_is)) if avg_is != 0 else 0.0

    return {
        "success": True,
        "window_size": window_size,
        "step_size": step_size,
        "total_windows": len(windows),
        "windows": windows,
        "avg_oos_sharpe": round(avg_oos_sharpe, 2),
        "consistency_ratio": round(consistency_ratio, 2),
        "overfitting_score": round(overfitting_score, 2),
        "overfit_warning": overfitting_score > 0.5,
    }


def _compute_sharpe(equity_curve):
    """Compute annualized Sharpe from equity curve list."""
    if len(equity_curve) < 2:
        return 0.0
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["value"]
        curr = equity_curve[i]["value"]
        returns.append((curr - prev) / prev if prev > 0 else 0)
    if not returns:
        return 0.0
    avg_r = sum(returns) / len(returns)
    std_r = math.sqrt(sum((r - avg_r) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 1e-9
    return (avg_r / std_r) * math.sqrt(252) if std_r > 0 else 0.0

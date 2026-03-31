"""Strategy library — 5 backtestable strategies for Market Watch."""

import math
import logging

logger = logging.getLogger(__name__)

STRATEGIES = {
    "sma_crossover": {
        "name": "SMA Crossover",
        "description": "Buy when fast SMA crosses above slow SMA, sell on cross below.",
        "params": {"fast": 20, "slow": 50},
        "category": "trend",
    },
    "rsi_mean_reversion": {
        "name": "RSI Mean Reversion",
        "description": "Buy oversold (RSI < 30), sell overbought (RSI > 70).",
        "params": {"period": 14, "oversold": 30, "overbought": 70},
        "category": "mean_reversion",
    },
    "macd_momentum": {
        "name": "MACD Momentum",
        "description": "Buy on MACD line crossing above signal line, sell on cross below.",
        "params": {"fast": 12, "slow": 26, "signal": 9},
        "category": "momentum",
    },
    "bollinger_bounce": {
        "name": "Bollinger Bounce",
        "description": "Buy at lower band, sell at upper band with middle-band stop.",
        "params": {"period": 20, "std_dev": 2.0},
        "category": "mean_reversion",
    },
    "watch_replay": {
        "name": "W.A.T.C.H. Replay",
        "description": "Replay historical W.A.T.C.H. agent buy/sell signals from analysis records.",
        "params": {"confidence_threshold": 0.6},
        "category": "ai_agent",
    },
}


_RUNNERS = {
    "sma_crossover": lambda closes, times, capital, params=None: run_sma_crossover(closes, times, capital, params),
    "rsi_mean_reversion": lambda closes, times, capital, params=None: run_rsi_mean_reversion(closes, times, capital, params),
    "macd_momentum": lambda closes, times, capital, params=None: run_macd_momentum(closes, times, capital, params),
    "bollinger_bounce": lambda closes, times, capital, params=None: run_bollinger_bounce(closes, times, capital, params),
    "watch_replay": lambda closes, times, capital, params=None: run_watch_replay(closes, times, capital, params),
}


def run_strategy(strategy_id, closes, timestamps, initial_capital, params=None):
    """Dispatch to the correct strategy runner by ID.

    Args:
        strategy_id: key from STRATEGIES dict
        closes: numpy array or list of close prices
        timestamps: list of date strings
        initial_capital: starting capital
        params: optional parameter overrides

    Returns:
        dict with: trades, equity_curve, metrics, strategy_id
    """
    if strategy_id not in _RUNNERS:
        return {"error": f"Unknown strategy: {strategy_id}", "trades": [], "metrics": {}}
    return _RUNNERS[strategy_id](closes, timestamps, initial_capital, params)


def get_strategy_list():
    """Return list of available strategies with metadata."""
    return [{"id": k, **v} for k, v in STRATEGIES.items()]


def compute_sma(prices, period):
    """Compute simple moving average list (None for first period-1 entries)."""
    result = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        result[i] = sum(prices[i - period + 1: i + 1]) / period
    return result


def compute_rsi(prices, period=14):
    """Compute RSI list."""
    result = [None] * len(prices)
    if len(prices) < period + 1:
        return result
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = prices[i] - prices[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period, len(prices)):
        if i > period:
            diff = prices[i] - prices[i - 1]
            avg_gain = (avg_gain * (period - 1) + max(diff, 0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-diff, 0)) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        result[i] = 100 - (100 / (1 + rs))
    return result


def compute_ema(prices, period):
    """Compute exponential moving average list."""
    result = [None] * len(prices)
    k = 2 / (period + 1)
    start = period - 1
    if start >= len(prices):
        return result
    result[start] = sum(prices[:period]) / period
    for i in range(start + 1, len(prices)):
        result[i] = prices[i] * k + result[i - 1] * (1 - k)
    return result


def compute_macd(prices, fast=12, slow=26, signal=9):
    """Return (macd_line, signal_line) lists."""
    ema_fast = compute_ema(prices, fast)
    ema_slow = compute_ema(prices, slow)
    macd_line = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    valid_macd = [(i, v) for i, v in enumerate(macd_line) if v is not None]
    signal_line = [None] * len(prices)
    if len(valid_macd) >= signal:
        values = [v for _, v in valid_macd]
        k = 2 / (signal + 1)
        base_idx = valid_macd[signal - 1][0]
        signal_line[base_idx] = sum(values[:signal]) / signal
        for j in range(signal, len(valid_macd)):
            idx = valid_macd[j][0]
            signal_line[idx] = macd_line[idx] * k + signal_line[valid_macd[j - 1][0]] * (1 - k)
    return macd_line, signal_line


def compute_bollinger(prices, period=20, std_dev=2.0):
    """Return (upper, middle, lower) band lists."""
    middle = compute_sma(prices, period)
    upper = [None] * len(prices)
    lower = [None] * len(prices)
    for i in range(period - 1, len(prices)):
        window = prices[i - period + 1: i + 1]
        avg = middle[i]
        variance = sum((p - avg) ** 2 for p in window) / period
        sigma = math.sqrt(variance)
        upper[i] = avg + std_dev * sigma
        lower[i] = avg - std_dev * sigma
    return upper, middle, lower


def compute_metrics(equity_curve, trades, initial_capital):
    """Compute Sharpe, max drawdown, win rate from equity curve + trades."""
    if len(equity_curve) < 2:
        return {"sharpe_ratio": 0, "max_drawdown": 0, "win_rate": 0, "trade_count": 0}
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["value"]
        curr = equity_curve[i]["value"]
        returns.append((curr - prev) / prev if prev > 0 else 0)
    avg_r = sum(returns) / len(returns)
    std_r = math.sqrt(sum((r - avg_r) ** 2 for r in returns) / len(returns)) if len(returns) > 1 else 1e-9
    sharpe = (avg_r / std_r) * math.sqrt(252) if std_r > 0 else 0

    peak = equity_curve[0]["value"]
    max_dd = 0
    for pt in equity_curve:
        if pt["value"] > peak:
            peak = pt["value"]
        dd = (peak - pt["value"]) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    buy_trades = [t for t in trades if t["action"] == "buy"]
    sell_trades = [t for t in trades if t["action"] == "sell"]
    wins = sum(1 for b, s in zip(buy_trades, sell_trades) if s["price"] > b["price"])
    total_pairs = min(len(buy_trades), len(sell_trades))
    win_rate = (wins / total_pairs * 100) if total_pairs > 0 else 0

    return {
        "sharpe_ratio": round(sharpe, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "win_rate": round(win_rate, 1),
        "trade_count": total_pairs,
    }


def run_sma_crossover(closes, timestamps, initial_capital, params=None):
    """SMA crossover strategy. Returns trades + equity_curve + final_value."""
    p = params or STRATEGIES["sma_crossover"]["params"]
    fast, slow = int(p.get("fast", 20)), int(p.get("slow", 50))
    sma_fast = compute_sma(closes, fast)
    sma_slow = compute_sma(closes, slow)
    cash, shares, trades, equity_curve = initial_capital, 0, [], []
    for i in range(slow, len(closes)):
        if sma_fast[i] is None or sma_slow[i] is None:
            continue
        price = closes[i]
        equity_curve.append({"time": timestamps[i], "value": round(cash + shares * price, 2)})
        if sma_fast[i] > sma_slow[i] and shares == 0:
            shares = int(cash / price)
            if shares > 0:
                cash -= shares * price
                trades.append({"action": "buy", "price": price, "shares": shares, "time": timestamps[i]})
        elif sma_fast[i] < sma_slow[i] and shares > 0:
            cash += shares * price
            trades.append({"action": "sell", "price": price, "shares": shares, "time": timestamps[i]})
            shares = 0
    final_value = cash + shares * closes[-1]
    return trades, equity_curve, final_value


def run_rsi_mean_reversion(closes, timestamps, initial_capital, params=None):
    """RSI mean reversion strategy."""
    p = params or STRATEGIES["rsi_mean_reversion"]["params"]
    period = int(p.get("period", 14))
    oversold = float(p.get("oversold", 30))
    overbought = float(p.get("overbought", 70))
    rsi = compute_rsi(closes, period)
    cash, shares, trades, equity_curve = initial_capital, 0, [], []
    for i in range(period, len(closes)):
        if rsi[i] is None:
            continue
        price = closes[i]
        equity_curve.append({"time": timestamps[i], "value": round(cash + shares * price, 2)})
        if rsi[i] < oversold and shares == 0:
            shares = int(cash / price)
            if shares > 0:
                cash -= shares * price
                trades.append({"action": "buy", "price": price, "shares": shares, "time": timestamps[i]})
        elif rsi[i] > overbought and shares > 0:
            cash += shares * price
            trades.append({"action": "sell", "price": price, "shares": shares, "time": timestamps[i]})
            shares = 0
    final_value = cash + shares * closes[-1]
    return trades, equity_curve, final_value


def run_macd_momentum(closes, timestamps, initial_capital, params=None):
    """MACD momentum strategy."""
    p = params or STRATEGIES["macd_momentum"]["params"]
    fast = int(p.get("fast", 12))
    slow = int(p.get("slow", 26))
    signal = int(p.get("signal", 9))
    macd_line, signal_line = compute_macd(closes, fast, slow, signal)
    cash, shares, trades, equity_curve = initial_capital, 0, [], []
    prev_macd, prev_signal = None, None
    for i in range(len(closes)):
        if macd_line[i] is None or signal_line[i] is None:
            prev_macd, prev_signal = macd_line[i], signal_line[i]
            continue
        price = closes[i]
        equity_curve.append({"time": timestamps[i], "value": round(cash + shares * price, 2)})
        if prev_macd is not None and prev_signal is not None:
            crossed_up = prev_macd <= prev_signal and macd_line[i] > signal_line[i]
            crossed_down = prev_macd >= prev_signal and macd_line[i] < signal_line[i]
            if crossed_up and shares == 0:
                shares = int(cash / price)
                if shares > 0:
                    cash -= shares * price
                    trades.append({"action": "buy", "price": price, "shares": shares, "time": timestamps[i]})
            elif crossed_down and shares > 0:
                cash += shares * price
                trades.append({"action": "sell", "price": price, "shares": shares, "time": timestamps[i]})
                shares = 0
        prev_macd, prev_signal = macd_line[i], signal_line[i]
    final_value = cash + shares * closes[-1]
    return trades, equity_curve, final_value


def run_bollinger_bounce(closes, timestamps, initial_capital, params=None):
    """Bollinger Bands bounce strategy."""
    p = params or STRATEGIES["bollinger_bounce"]["params"]
    period = int(p.get("period", 20))
    std_dev = float(p.get("std_dev", 2.0))
    upper, middle, lower = compute_bollinger(closes, period, std_dev)
    cash, shares, trades, equity_curve = initial_capital, 0, [], []
    for i in range(period, len(closes)):
        if upper[i] is None or lower[i] is None:
            continue
        price = closes[i]
        equity_curve.append({"time": timestamps[i], "value": round(cash + shares * price, 2)})
        if price <= lower[i] and shares == 0:
            shares = int(cash / price)
            if shares > 0:
                cash -= shares * price
                trades.append({"action": "buy", "price": price, "shares": shares, "time": timestamps[i]})
        elif price >= upper[i] and shares > 0:
            cash += shares * price
            trades.append({"action": "sell", "price": price, "shares": shares, "time": timestamps[i]})
            shares = 0
        elif middle[i] is not None and shares > 0 and price < middle[i] * 0.97:
            # Stop loss: price drops 3% below middle band
            cash += shares * price
            trades.append({"action": "sell", "price": price, "shares": shares, "time": timestamps[i]})
            shares = 0
    final_value = cash + shares * closes[-1]
    return trades, equity_curve, final_value


def run_watch_replay(closes, timestamps, initial_capital, params=None, analysis_signals=None):
    """
    W.A.T.C.H. Replay: replays signals from passed analysis_signals list.
    Each signal: {"time": "YYYY-MM-DD", "action": "buy"|"sell", "ticker": "...", "confidence": float}
    Falls back to SMA crossover if no signals provided.
    """
    if not analysis_signals:
        return run_sma_crossover(closes, timestamps, initial_capital, params)
    p = params or STRATEGIES["watch_replay"]["params"]
    threshold = float(p.get("confidence_threshold", 0.6))
    signal_map = {}
    for sig in analysis_signals:
        if sig.get("confidence", 1.0) >= threshold:
            signal_map[sig["time"][:10]] = sig["action"]
    cash, shares, trades, equity_curve = initial_capital, 0, [], []
    for i in range(len(closes)):
        price = closes[i]
        equity_curve.append({"time": timestamps[i], "value": round(cash + shares * price, 2)})
        ts = timestamps[i][:10] if timestamps[i] else ""
        action = signal_map.get(ts)
        if action == "buy" and shares == 0:
            shares = int(cash / price)
            if shares > 0:
                cash -= shares * price
                trades.append({"action": "buy", "price": price, "shares": shares, "time": timestamps[i]})
        elif action == "sell" and shares > 0:
            cash += shares * price
            trades.append({"action": "sell", "price": price, "shares": shares, "time": timestamps[i]})
            shares = 0
    final_value = cash + shares * closes[-1]
    return trades, equity_curve, final_value


STRATEGY_RUNNERS = {
    "sma_crossover": run_sma_crossover,
    "rsi_mean_reversion": run_rsi_mean_reversion,
    "macd_momentum": run_macd_momentum,
    "bollinger_bounce": run_bollinger_bounce,
    "watch_replay": run_watch_replay,
}

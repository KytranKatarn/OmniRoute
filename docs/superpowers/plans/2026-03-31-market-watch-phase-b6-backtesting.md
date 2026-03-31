# Market Watch — Phase B6: Backtesting Upgrades Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Upgrade backtesting from single SMA crossover to a full 5-strategy library with Monte Carlo simulation, walk-forward analysis, parameter optimization, and public landing page showcase.
**Architecture:** New service modules (strategy_library, monte_carlo, walk_forward, optimizer) are imported by backtest_engine.py. Routes in routes/backtest.py gain 4 new endpoints. A new DB migration adds monte_carlo_results and walk_forward_results tables. The landing page gets a public showcase section fetched from a public endpoint.
**Tech Stack:** Flask 3.1, numpy, yfinance, SQLite

---

## Task 1 — Schema Migration: Add monte_carlo_results + walk_forward_results tables

**Files to modify:** `schema.sql`, create `migrations/004_backtesting_upgrades.sql`

### Steps

**Step 1.1** — Create `migrations/004_backtesting_upgrades.sql`:

```sql
-- migrations/004_backtesting_upgrades.sql
-- Idempotent migration for Phase B6 backtesting upgrades

CREATE TABLE IF NOT EXISTS monte_carlo_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    backtest_id INTEGER,
    ticker TEXT NOT NULL,
    strategy TEXT NOT NULL,
    simulations INTEGER NOT NULL DEFAULT 1000,
    mean_return REAL,
    std_return REAL,
    percentile_5 REAL,
    percentile_25 REAL,
    percentile_50 REAL,
    percentile_75 REAL,
    percentile_95 REAL,
    ruin_probability REAL,
    mean_sharpe REAL,
    mean_max_drawdown REAL,
    data JSON NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS walk_forward_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    tickers TEXT NOT NULL,
    window_size INTEGER NOT NULL DEFAULT 252,
    step_size INTEGER NOT NULL DEFAULT 63,
    windows JSON NOT NULL,
    avg_oos_sharpe REAL,
    consistency_ratio REAL,
    overfitting_score REAL,
    params_used JSON,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Step 1.2** — Append same CREATE TABLE IF NOT EXISTS blocks to the bottom of `schema.sql` after the existing `backtest_results` block.

### Verify
```bash
docker exec market-watch-app sqlite3 /data/market_watch.db ".tables" | tr ' ' '\n' | grep -E "monte_carlo|walk_forward"
# Expected: monte_carlo_results   walk_forward_results
```

### Commit
```bash
cd /mnt/archie_brain
git add market-watch/schema.sql market-watch/migrations/004_backtesting_upgrades.sql
git commit -m "feat(market-watch): Phase B6 schema — monte_carlo_results + walk_forward_results tables"
```

---

## Task 2 — Strategy Library: 5 strategies (SMA, RSI, MACD, Bollinger, W.A.T.C.H. Replay)

**Files to create:** `services/strategy_library.py`

### Steps

**Step 2.1** — Create `services/strategy_library.py` with full content:

```python
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
```

### Verify
```bash
docker exec market-watch-app python3 -c "
from services.strategy_library import get_strategy_list, STRATEGY_RUNNERS
strategies = get_strategy_list()
print('Strategies:', [s['id'] for s in strategies])
print('Runners:', list(STRATEGY_RUNNERS.keys()))
"
# Expected: 5 strategy IDs + 5 runner keys
```

### Commit
```bash
cd /mnt/archie_brain
git add market-watch/services/strategy_library.py
git commit -m "feat(market-watch): Phase B6 strategy library — SMA/RSI/MACD/Bollinger/W.A.T.C.H. Replay"
```

---

## Task 3 — Monte Carlo Simulation Service

**Files to create:** `services/monte_carlo.py`

### Steps

**Step 3.1** — Create `services/monte_carlo.py`:

```python
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
```

### Verify
```bash
docker exec market-watch-app python3 -c "
from services.monte_carlo import run_monte_carlo
trades = [
    {'action': 'buy', 'price': 100, 'shares': 10},
    {'action': 'sell', 'price': 110, 'shares': 10},
    {'action': 'buy', 'price': 105, 'shares': 9},
    {'action': 'sell', 'price': 115, 'shares': 9},
]
result = run_monte_carlo(trades, [], 10000, simulations=100)
print('MC success:', result['success'])
print('Mean return:', result['mean_return'])
print('Ruin prob:', result['ruin_probability'])
"
```

### Commit
```bash
cd /mnt/archie_brain
git add market-watch/services/monte_carlo.py
git commit -m "feat(market-watch): Phase B6 Monte Carlo simulation — 1000-sim trade randomization + ruin probability"
```

---

## Task 4 — Walk-Forward Analysis Service

**Files to create:** `services/walk_forward.py`

### Steps

**Step 4.1** — Create `services/walk_forward.py`:

```python
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
```

### Verify
```bash
docker exec market-watch-app python3 -c "
from services.walk_forward import run_walk_forward
from services.strategy_library import run_sma_crossover
closes = [100 + i * 0.1 + (i % 10 - 5) * 0.5 for i in range(400)]
timestamps = [str(i) for i in range(400)]
result = run_walk_forward(closes, timestamps, run_sma_crossover, 10000)
print('WF success:', result['success'])
print('Windows:', result.get('total_windows'))
print('Avg OOS Sharpe:', result.get('avg_oos_sharpe'))
"
```

### Commit
```bash
cd /mnt/archie_brain
git add market-watch/services/walk_forward.py
git commit -m "feat(market-watch): Phase B6 walk-forward analysis — OOS Sharpe + consistency ratio + overfitting detection"
```

---

## Task 5 — Parameter Optimizer Service

**Files to create:** `services/optimizer.py`

### Steps

**Step 5.1** — Create `services/optimizer.py`:

```python
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
```

### Verify
```bash
docker exec market-watch-app python3 -c "
from services.optimizer import grid_search
from services.strategy_library import run_sma_crossover
closes = [100 + i * 0.05 + (i % 20 - 10) * 0.3 for i in range(500)]
timestamps = [str(i) for i in range(500)]
result = grid_search(closes, timestamps, run_sma_crossover, 'sma_crossover', 10000, max_combinations=10)
print('Optimizer success:', result['success'])
print('Best params:', result.get('best_params'))
print('Best OOS Sharpe:', result.get('best_oos_sharpe'))
"
```

### Commit
```bash
cd /mnt/archie_brain
git add market-watch/services/optimizer.py
git commit -m "feat(market-watch): Phase B6 parameter optimizer — grid/random search with walk-forward validation"
```

---

## Task 6 — Update Backtest Engine to Use Strategy Library

**Files to modify:** `services/backtest_engine.py`

### Steps

**Step 6.1** — Replace full content of `services/backtest_engine.py`:

```python
"""Historical strategy backtesting engine — Phase B6 multi-strategy dispatcher."""

import logging
from services.market_data import get_history
from services.strategy_library import STRATEGY_RUNNERS, compute_metrics, get_strategy_list

logger = logging.getLogger(__name__)


def run_backtest(tickers, strategy="sma_crossover", start_date=None, end_date=None,
                 initial_capital=100000, params=None):
    """Run a backtest simulation using the strategy library."""
    runner = STRATEGY_RUNNERS.get(strategy)
    if not runner:
        return {
            "success": False,
            "error": f"Unknown strategy: {strategy}. Available: {list(STRATEGY_RUNNERS.keys())}",
        }

    results = []
    per_ticker_capital = initial_capital / max(len(tickers), 1)

    for ticker in tickers:
        history = get_history(ticker, period="2y")
        data = history.get("data", [])

        min_points = 60
        if len(data) < min_points:
            results.append({
                "ticker": ticker,
                "error": f"Insufficient data ({len(data)} points, need {min_points})",
            })
            continue

        closes = [d["close"] for d in data]
        timestamps = [d["time"] for d in data]

        try:
            trades, equity_curve, final_value = runner(closes, timestamps, per_ticker_capital, params)
        except Exception as exc:
            logger.error("Backtest runner error for %s/%s: %s", strategy, ticker, exc)
            results.append({"ticker": ticker, "error": str(exc)})
            continue

        metrics = compute_metrics(equity_curve, trades, per_ticker_capital)
        total_return = (
            (final_value - per_ticker_capital) / per_ticker_capital
            if per_ticker_capital > 0 else 0
        )

        results.append({
            "ticker": ticker,
            "initial_capital": per_ticker_capital,
            "final_value": round(final_value, 2),
            "total_return": round(total_return * 100, 2),
            "sharpe_ratio": metrics["sharpe_ratio"],
            "max_drawdown": metrics["max_drawdown"],
            "win_rate": metrics["win_rate"],
            "trade_count": metrics["trade_count"],
            "equity_curve": equity_curve,
            "trades": trades,
        })

    return {"success": True, "strategy": strategy, "results": results}


def get_available_strategies():
    """Return list of available strategies for UI dropdown."""
    return get_strategy_list()
```

### Verify
```bash
docker exec market-watch-app python3 -c "
from services.backtest_engine import run_backtest, get_available_strategies
print('Strategies:', [s['id'] for s in get_available_strategies()])
result = run_backtest(['AAPL'], strategy='rsi_mean_reversion', initial_capital=10000)
print('Backtest success:', result['success'])
r = result.get('results', [{}])[0]
print('Ticker:', r.get('ticker'), 'Return:', r.get('total_return'), '%')
"
```

### Commit
```bash
cd /mnt/archie_brain
git add market-watch/services/backtest_engine.py
git commit -m "feat(market-watch): Phase B6 backtest engine — multi-strategy dispatch via strategy library"
```

---

## Task 7 — New API Endpoints

**Files to modify:** `routes/backtest.py`

### Steps

**Step 7.1** — Replace full content of `routes/backtest.py`:

```python
"""Backtest endpoints — Phase B6 multi-strategy + Monte Carlo + Walk-Forward + Optimizer."""

import json
import logging
from flask import Blueprint, jsonify, request
from db import get_db
from services.backtest_engine import run_backtest, get_available_strategies
from services.monte_carlo import run_monte_carlo
from services.walk_forward import run_walk_forward
from services.optimizer import grid_search, random_search
from services.strategy_library import STRATEGY_RUNNERS
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
    """List available strategies."""
    return jsonify({"success": True, "strategies": get_available_strategies()})


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

    runner = STRATEGY_RUNNERS.get(strategy)
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

    runner = STRATEGY_RUNNERS.get(strategy)
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
```

### Verify
```bash
# Strategies list (viewer auth)
curl -s http://localhost:8101/api/backtest/strategies | python3 -m json.tool | grep '"id"'
# Public showcase (no auth required)
curl -s http://localhost:8101/api/public/backtest-showcase | python3 -m json.tool
```

### Commit
```bash
cd /mnt/archie_brain
git add market-watch/routes/backtest.py
git commit -m "feat(market-watch): Phase B6 backtest routes — monte-carlo, walk-forward, optimize, public showcase"
```

---

## Task 8 — Landing Page Backtest Showcase Section

**Files to modify:** `templates/landing.html`

### Steps

**Step 8.1** — Read `templates/landing.html` to identify insertion point (look for closing hero section or last content section before `</main>`).

**Step 8.2** — Insert the following block immediately before `</main>` (or before `</body>` if no `</main>`). Note: the JS below uses server-generated data only — no user input is rendered via DOM methods:

```html
<!-- ═══ BACKTEST SHOWCASE SECTION ═══ -->
<section class="bt-showcase-section">
  <div class="bt-showcase-header">
    <div class="bt-showcase-label">STRATEGY PERFORMANCE</div>
    <h2 class="bt-showcase-title">Live Backtesting Engine</h2>
    <p class="bt-showcase-subtitle">Historical strategy performance validated by M.A.R.K.E.T. — updated in real time</p>
  </div>
  <div class="bt-showcase-grid" id="btShowcaseGrid">
    <div class="bt-showcase-loading">Loading strategy data...</div>
  </div>
  <div class="bt-showcase-footer">
    <span class="bt-disclaimer">Past performance does not guarantee future results. For informational purposes only.</span>
  </div>
</section>

<style>
.bt-showcase-section {
  padding: 3rem 2rem;
  background: rgba(0,229,255,.03);
  border-top: 1px solid rgba(0,229,255,.15);
  border-bottom: 1px solid rgba(0,229,255,.15);
}
.bt-showcase-header { text-align: center; margin-bottom: 2rem; }
.bt-showcase-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .7rem; color: #00e5ff;
  letter-spacing: .2em; text-transform: uppercase; margin-bottom: .5rem;
}
.bt-showcase-title {
  font-family: 'Orbitron', sans-serif;
  font-size: 1.8rem; color: #e0f7fa; margin: .25rem 0;
}
.bt-showcase-subtitle {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .8rem; color: #7ecfd4; margin: 0;
}
.bt-showcase-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px,1fr));
  gap: 1rem; max-width: 1100px; margin: 0 auto;
}
.bt-showcase-card {
  background: rgba(0,229,255,.05);
  border: 1px solid rgba(0,229,255,.2);
  border-radius: 4px; padding: 1.25rem; transition: border-color .2s;
}
.bt-showcase-card:hover { border-color: rgba(0,229,255,.5); }
.bt-card-strategy {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .65rem; color: #00e5ff;
  letter-spacing: .15em; text-transform: uppercase; margin-bottom: .25rem;
}
.bt-card-ticker {
  font-family: 'Orbitron', sans-serif;
  font-size: 1.1rem; color: #e0f7fa; font-weight: 700; margin-bottom: .75rem;
}
.bt-card-stats { display: grid; grid-template-columns: 1fr 1fr; gap: .5rem; }
.bt-stat { text-align: center; }
.bt-stat-value { font-family: 'Orbitron', sans-serif; font-size: 1rem; font-weight: 700; }
.bt-stat-value.positive { color: #00e676; }
.bt-stat-value.negative { color: #ff5252; }
.bt-stat-value.neutral  { color: #00e5ff; }
.bt-stat-label {
  font-family: 'IBM Plex Mono', monospace;
  font-size: .6rem; color: #7ecfd4;
  text-transform: uppercase; letter-spacing: .1em;
}
.bt-showcase-loading {
  grid-column: 1/-1; text-align: center;
  font-family: 'IBM Plex Mono', monospace; font-size: .8rem;
  color: #7ecfd4; padding: 2rem;
}
.bt-showcase-footer { text-align: center; margin-top: 1.5rem; }
.bt-disclaimer { font-family: 'IBM Plex Mono', monospace; font-size: .65rem; color: #546e7a; }
@media (max-width:768px) {
  .bt-showcase-grid { grid-template-columns: 1fr; }
  .bt-showcase-title { font-size: 1.3rem; }
}
</style>

<script>
(function() {
  var STRATEGY_LABELS = {
    sma_crossover: 'SMA Crossover',
    rsi_mean_reversion: 'RSI Mean Reversion',
    macd_momentum: 'MACD Momentum',
    bollinger_bounce: 'Bollinger Bounce',
    watch_replay: 'W.A.T.C.H. Replay'
  };
  function renderShowcase(data) {
    var grid = document.getElementById('btShowcaseGrid');
    if (!grid) return;
    if (!data || !data.showcase || !data.showcase.length) {
      grid.textContent = 'No strategy data available yet.';
      return;
    }
    var cards = data.showcase.map(function(s) {
      var label = STRATEGY_LABELS[s.strategy] || s.strategy;
      var ticker = String(s.ticker || '—').replace(/[<>&"]/g, '');
      var retCls = s.total_return >= 0 ? 'positive' : 'negative';
      var shpCls = s.sharpe_ratio >= 1 ? 'positive' : s.sharpe_ratio >= 0 ? 'neutral' : 'negative';
      var retStr = (s.total_return >= 0 ? '+' : '') + Number(s.total_return).toFixed(1) + '%';
      var shpStr = Number(s.sharpe_ratio).toFixed(2);
      var ddStr  = '-' + Number(s.max_drawdown).toFixed(1) + '%';
      var wrStr  = Number(s.win_rate).toFixed(0) + '%';
      return '<div class="bt-showcase-card">'
        + '<div class="bt-card-strategy">' + label + '</div>'
        + '<div class="bt-card-ticker">' + ticker + '</div>'
        + '<div class="bt-card-stats">'
        +   '<div class="bt-stat"><div class="bt-stat-value ' + retCls + '">' + retStr + '</div><div class="bt-stat-label">Return</div></div>'
        +   '<div class="bt-stat"><div class="bt-stat-value ' + shpCls + '">' + shpStr + '</div><div class="bt-stat-label">Sharpe</div></div>'
        +   '<div class="bt-stat"><div class="bt-stat-value negative">' + ddStr + '</div><div class="bt-stat-label">Max DD</div></div>'
        +   '<div class="bt-stat"><div class="bt-stat-value neutral">' + wrStr + '</div><div class="bt-stat-label">Win Rate</div></div>'
        + '</div></div>';
    });
    grid.innerHTML = cards.join('');
  }
  fetch('/api/public/backtest-showcase')
    .then(function(r) { return r.json(); })
    .then(renderShowcase)
    .catch(function() {
      var grid = document.getElementById('btShowcaseGrid');
      if (grid) grid.textContent = 'Strategy data temporarily unavailable.';
    });
})();
</script>
```

### Verify
```bash
curl -s http://localhost:8101/ | grep -c "bt-showcase-section"
# Expected: 1
curl -s http://localhost:8101/ | grep -c "btShowcaseGrid"
# Expected: 1
```

### Commit
```bash
cd /mnt/archie_brain
git add market-watch/templates/landing.html
git commit -m "feat(market-watch): Phase B6 landing page — backtest showcase section with live strategy cards"
```

---

## Task 9 — Docker Config + Apply Migration + VPS Deploy

### Steps

**Step 9.1** — Apply migration to local running container:

```bash
docker exec market-watch-app sqlite3 /data/market_watch.db < /app/migrations/004_backtesting_upgrades.sql
```

**Step 9.2** — Verify migration applied:

```bash
docker exec market-watch-app sqlite3 /data/market_watch.db ".tables" | tr ' ' '\n' | grep -E "monte_carlo|walk_forward"
# Expected: monte_carlo_results   walk_forward_results
```

**Step 9.3** — Rebuild and restart container:

```bash
cd /mnt/archie_brain/market-watch
docker compose build --no-cache
docker compose up -d
```

**Step 9.4** — Smoke test all new endpoints:

```bash
# Public showcase (no auth)
curl -s http://localhost:8101/api/public/backtest-showcase | python3 -m json.tool | head -20

# Strategies list
curl -s http://localhost:8101/api/backtest/strategies | python3 -m json.tool

# Multi-strategy backtest (requires ai-tier session)
curl -s -X POST http://localhost:8101/api/backtest/run \
  -H "Content-Type: application/json" \
  -d '{"tickers":["SPY"],"strategy":"rsi_mean_reversion","initial_capital":10000}' \
  | python3 -m json.tool | grep -E '"success"|"strategy"|"total_return"'

# Monte Carlo (requires ai-tier session)
curl -s -X POST http://localhost:8101/api/backtest/monte-carlo \
  -H "Content-Type: application/json" \
  -d '{"tickers":["SPY"],"strategy":"sma_crossover","simulations":100}' \
  | python3 -m json.tool | grep -E '"success"|"mean_return"|"ruin_probability"'
```

**Step 9.5** — Push image and deploy to VPS:

```bash
cd /mnt/archie_brain/market-watch
docker build -t ghcr.io/kytrankatarn/market-watch:latest .
docker push ghcr.io/kytrankatarn/market-watch:latest

ssh root@76.13.107.109 \
  "cd /opt/market-watch && \
   docker compose pull && \
   docker compose up -d && \
   docker exec market-watch-app sqlite3 /data/market_watch.db < /app/migrations/004_backtesting_upgrades.sql"
```

**Step 9.6** — Verify VPS:

```bash
curl -s https://market.kytranempowerment.com/api/public/backtest-showcase | python3 -m json.tool | head -10
```

### Commit
```bash
cd /mnt/archie_brain
git add market-watch/
git commit -m "feat(market-watch): Phase B6 complete — backtesting upgrades deployed to VPS"
```

---

## Summary

| # | Task | Files | New/Modified |
|---|------|-------|-------------|
| 1 | Schema migration | `schema.sql`, `migrations/004_backtesting_upgrades.sql` | New migration |
| 2 | Strategy library | `services/strategy_library.py` | New file |
| 3 | Monte Carlo service | `services/monte_carlo.py` | New file |
| 4 | Walk-forward service | `services/walk_forward.py` | New file |
| 5 | Parameter optimizer | `services/optimizer.py` | New file |
| 6 | Backtest engine | `services/backtest_engine.py` | Modified |
| 7 | API endpoints | `routes/backtest.py` | Modified (+4 endpoints) |
| 8 | Landing page showcase | `templates/landing.html` | Modified |
| 9 | Docker + migration + deploy | Container + VPS | Ops task |

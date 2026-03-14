"""
Backtest Service — StockBot Phase 4
Simulate trading strategies against historical OHLCV data.
"""

import logging
import math
import sys
from datetime import datetime, timezone

sys.path.insert(0, "/mnt/archie_brain/platform_v2")

import psycopg2.extras
from database import get_db_cursor
from .market_data_service import get_history
from .strategy_service import CONDITION_TYPES

logger = logging.getLogger(__name__)

WARMUP_BARS = 200  # minimum bars before trading begins


def _now_utc():
    return datetime.now(timezone.utc)


# ── Indicator helpers ──────────────────────────────────────────────────────────


def _sma(closes: list, period: int) -> list:
    out = []
    for i in range(len(closes)):
        if i < period - 1:
            out.append(None)
        else:
            out.append(round(sum(closes[i - period + 1 : i + 1]) / period, 4))
    return out


def _ema(closes: list, period: int) -> list:
    out = [None] * len(closes)
    k = 2.0 / (period + 1)
    for i in range(len(closes)):
        if i < period - 1:
            continue
        if i == period - 1:
            out[i] = sum(closes[:period]) / period
        else:
            out[i] = closes[i] * k + out[i - 1] * (1 - k)
    return out


def _rsi(closes: list, period: int = 14) -> list:
    out = [None] * len(closes)
    if len(closes) < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period, len(closes)):
        if i > period:
            diff = closes[i] - closes[i - 1]
            g, l_ = max(diff, 0), max(-diff, 0)
            avg_gain = (avg_gain * (period - 1) + g) / period
            avg_loss = (avg_loss * (period - 1) + l_) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100
        out[i] = round(100 - 100 / (1 + rs), 2)
    return out


def _build_indicators(ohlcv: list, idx: int) -> dict:
    """Build indicator snapshot for strategy evaluation at bar idx."""
    closes = [r["close"] for r in ohlcv[: idx + 1]]
    price = closes[-1]
    indicators = {"price": price, "change_pct": 0.0}

    if len(closes) >= 2:
        prev = closes[-2]
        indicators["change_pct"] = round((price - prev) / prev * 100, 4) if prev else 0.0

    for period in (20, 50, 200):
        sma_vals = _sma(closes, period)
        indicators[f"sma_{period}"] = sma_vals[-1] or price

    rsi_vals = _rsi(closes, 14)
    indicators["rsi"] = rsi_vals[-1] or 50.0

    # MACD signal
    if len(closes) >= 26:
        ema12 = _ema(closes, 12)
        ema26 = _ema(closes, 26)
        if ema12[-1] and ema26[-1] and ema12[-2] and ema26[-2]:
            hist_now = ema12[-1] - ema26[-1]
            hist_prev = ema12[-2] - ema26[-2]
            if hist_now > 0 and hist_prev <= 0:
                indicators["macd_signal"] = "bullish"
            elif hist_now < 0 and hist_prev >= 0:
                indicators["macd_signal"] = "bearish"
            else:
                indicators["macd_signal"] = "none"
        else:
            indicators["macd_signal"] = "none"
    else:
        indicators["macd_signal"] = "none"

    return indicators


# ── Core simulation ────────────────────────────────────────────────────────────


def run_backtest(
    strategy_rules: dict,
    ticker: str,
    period: str = "1y",
    initial_balance: float = 100000.0,
    commission: float = 0.001,
    slippage: float = 0.001,
    strategy_name: str = "Custom Strategy",
) -> dict:
    """
    Simulate a strategy against historical OHLCV data.
    strategy_rules: {conditions: [{type, threshold}], action: {type, shares}}
    Returns full result dict with metrics, equity_curve, trades.
    """
    ticker = ticker.upper().strip()
    ohlcv = get_history(ticker, period)
    if not ohlcv:
        return {"error": f"No historical data for {ticker}/{period}"}

    if len(ohlcv) < WARMUP_BARS + 5:
        return {"error": f"Insufficient data: need {WARMUP_BARS + 5} bars, got {len(ohlcv)}"}

    # Fetch SPY benchmark
    spy_ohlcv = get_history("SPY", period) or []
    spy_start = spy_ohlcv[0]["close"] if spy_ohlcv else None
    spy_end = spy_ohlcv[-1]["close"] if spy_ohlcv else None
    benchmark_return = round((spy_end - spy_start) / spy_start * 100, 2) if spy_start and spy_end else 0.0

    conditions = strategy_rules.get("conditions", [])
    action_cfg = strategy_rules.get("action", {})
    action_type = action_cfg.get("type", "buy")
    shares_per_trade = int(action_cfg.get("shares", 10))

    balance = float(initial_balance)
    position = 0  # shares held
    equity_curve = []
    trades = []
    total_fees = 0.0

    for i in range(WARMUP_BARS, len(ohlcv)):
        bar = ohlcv[i]
        price = bar["close"]
        date = bar["date"]

        indicators = _build_indicators(ohlcv, i)

        # Evaluate all conditions (AND logic)
        all_met = bool(conditions)
        for cond in conditions:
            ctype = cond.get("type")
            threshold = float(cond.get("threshold", 0))
            evaluator = CONDITION_TYPES.get(ctype)
            if evaluator is None or not evaluator(indicators, threshold):
                all_met = False
                break

        if all_met:
            if action_type == "buy" and balance >= price * shares_per_trade:
                exec_price = price * (1 + slippage)
                cost = exec_price * shares_per_trade
                fee = cost * commission
                if balance >= cost + fee:
                    balance -= cost + fee
                    position += shares_per_trade
                    total_fees += fee
                    trades.append(
                        {
                            "date": date,
                            "action": "buy",
                            "shares": shares_per_trade,
                            "price": round(exec_price, 4),
                            "fee": round(fee, 4),
                            "balance_after": round(balance, 2),
                        }
                    )

            elif action_type in ("sell", "sell_all") and position > 0:
                to_sell = position if action_type == "sell_all" else min(shares_per_trade, position)
                exec_price = price * (1 - slippage)
                proceeds = exec_price * to_sell
                fee = proceeds * commission
                balance += proceeds - fee
                position -= to_sell
                total_fees += fee
                trades.append(
                    {
                        "date": date,
                        "action": "sell",
                        "shares": to_sell,
                        "price": round(exec_price, 4),
                        "fee": round(fee, 4),
                        "balance_after": round(balance, 2),
                    }
                )

        equity = balance + position * price
        equity_curve.append({"date": date, "equity": round(equity, 2)})

    # Liquidate remaining position at last price
    if position > 0 and ohlcv:
        last_price = ohlcv[-1]["close"] * (1 - slippage)
        proceeds = last_price * position
        fee = proceeds * commission
        balance += proceeds - fee
        total_fees += fee

    final_balance = round(balance, 2)
    total_return = round((final_balance - initial_balance) / initial_balance * 100, 2)

    # Annualized return (approximate from period string)
    period_years = {
        "1d": 1 / 252,
        "5d": 5 / 252,
        "1mo": 1 / 12,
        "3mo": 0.25,
        "6mo": 0.5,
        "1y": 1.0,
        "2y": 2.0,
        "5y": 5.0,
        "10y": 10.0,
    }.get(period, 1.0)
    ann_return = round(((1 + total_return / 100) ** (1 / period_years) - 1) * 100, 2)
    alpha = round(ann_return - benchmark_return, 2)

    # Sharpe ratio (daily returns from equity curve)
    daily_returns = []
    for i in range(1, len(equity_curve)):
        prev_eq = equity_curve[i - 1]["equity"]
        curr_eq = equity_curve[i]["equity"]
        if prev_eq > 0:
            daily_returns.append((curr_eq - prev_eq) / prev_eq)

    sharpe = 0.0
    if len(daily_returns) > 1:
        mean_r = sum(daily_returns) / len(daily_returns)
        std_r = math.sqrt(sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns))
        if std_r > 0:
            sharpe = round((mean_r / std_r) * math.sqrt(252), 2)

    # Max drawdown
    max_dd = 0.0
    peak = initial_balance
    for pt in equity_curve:
        eq = pt["equity"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Win rate and profit factor
    buy_trades = [t for t in trades if t["action"] == "buy"]
    sell_trades = [t for t in trades if t["action"] == "sell"]
    wins = sum(
        1
        for s in sell_trades
        if s["price"] > (buy_trades[sell_trades.index(s)]["price"] if sell_trades.index(s) < len(buy_trades) else 0)
    )
    win_rate = round(wins / len(sell_trades) * 100, 1) if sell_trades else 0.0

    gross_profit = sum(max(s["price"] - b["price"], 0) * s["shares"] for s, b in zip(sell_trades, buy_trades))
    gross_loss = sum(max(b["price"] - s["price"], 0) * s["shares"] for s, b in zip(sell_trades, buy_trades))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    metrics = {
        "total_return": total_return,
        "annualized_return": ann_return,
        "benchmark_return": benchmark_return,
        "alpha": alpha,
        "sharpe_ratio": sharpe,
        "max_drawdown": round(max_dd, 2),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_trades": len(trades),
        "total_fees": round(total_fees, 2),
    }

    return {
        "strategy_name": strategy_name,
        "ticker": ticker,
        "period": period,
        "initial_balance": initial_balance,
        "final_balance": final_balance,
        "metrics": metrics,
        "equity_curve": equity_curve,
        "trades": trades,
    }


# ── Persistence ────────────────────────────────────────────────────────────────


def save_backtest(user_id: int, result: dict) -> int:
    """INSERT backtest result, return new id."""
    try:
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """
                INSERT INTO stock_backtest_results
                    (user_id, strategy_name, ticker, period, initial_balance, final_balance,
                     metrics, equity_curve, trades)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    user_id,
                    result.get("strategy_name", "Custom Strategy"),
                    result.get("ticker", ""),
                    result.get("period", "1y"),
                    result.get("initial_balance", 100000),
                    result.get("final_balance"),
                    psycopg2.extras.Json(result.get("metrics", {})),
                    psycopg2.extras.Json(result.get("equity_curve", [])),
                    psycopg2.extras.Json(result.get("trades", [])),
                ),
            )
            row = cur.fetchone()
            return row[0] if row else None
    except Exception as e:
        logger.error(f"save_backtest: {e}")
        return None


def get_backtest_results(user_id: int, limit: int = 10) -> list:
    """Return list of past backtests for user (without equity_curve for brevity)."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, strategy_name, ticker, period, initial_balance, final_balance, metrics, created_at
                FROM stock_backtest_results
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (user_id, limit),
            )
            rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "strategy_name": r[1],
                "ticker": r[2],
                "period": r[3],
                "initial_balance": float(r[4]) if r[4] else None,
                "final_balance": float(r[5]) if r[5] else None,
                "metrics": r[6] or {},
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.error(f"get_backtest_results: {e}")
        return []


def get_backtest(backtest_id: int) -> dict:
    """Return full backtest including equity_curve and trades."""
    try:
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """
                SELECT id, strategy_name, ticker, period, initial_balance, final_balance,
                       metrics, equity_curve, trades, created_at
                FROM stock_backtest_results
                WHERE id = %s
                """,
                (backtest_id,),
            )
            row = cur.fetchone()
        if not row:
            return {}
        return {
            "id": row[0],
            "strategy_name": row[1],
            "ticker": row[2],
            "period": row[3],
            "initial_balance": float(row[4]) if row[4] else None,
            "final_balance": float(row[5]) if row[5] else None,
            "metrics": row[6] or {},
            "equity_curve": row[7] or [],
            "trades": row[8] or [],
            "created_at": row[9].isoformat() if row[9] else None,
        }
    except Exception as e:
        logger.error(f"get_backtest({backtest_id}): {e}")
        return {}

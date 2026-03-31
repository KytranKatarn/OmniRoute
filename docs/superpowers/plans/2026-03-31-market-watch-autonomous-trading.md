# Market Watch — Autonomous Trading Loop (Phase A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the W.A.T.C.H. 6-agent pipeline into an autonomous trading loop with 10-gate risk controls, position management, P&L tracking, and ARCHIE hub dispatch integration.

**Architecture:** Autonomy fires a scheduled job during market hours, Bridge dispatches to M.A.R.K.E.T. agent, which triggers Market Watch's run-cycle endpoint. Market Watch checks position exits, runs analysis, evaluates against risk gates, auto-executes approved paper trades, and returns results to the hub.

**Tech Stack:** Flask 3.1, SQLite, Alpaca paper trading API, yfinance, ARCHIE Bridge dispatch

**Spec:** `docs/superpowers/specs/2026-03-31-market-watch-autonomous-trading-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/risk_config.py` | Load all risk thresholds from env vars with defaults |
| Create | `services/execution_engine.py` | 10-gate risk evaluation → ExecutionDecision |
| Create | `services/position_manager.py` | Open position lifecycle, exit triggers |
| Create | `services/portfolio_service.py` | Portfolio state, P&L, drawdown, metrics |
| Modify | `schema.sql` | Add `open_positions`, `trade_journal`, `portfolio_metrics` tables |
| Modify | `routes/trading.py` | Add `run-cycle`, `positions`, `journal` endpoints |
| Modify | `routes/public.py` | Enrich track-record with journal + metrics |
| Modify | `docker-compose.yml` | Add risk config env vars |
| Modify | `.env.example` | Document new env vars |

---

### Task 1: Schema — Add Trading Tables

**Files:**
- Modify: `schema.sql` (append to end)

- [ ] **Step 1: Add three new tables to schema.sql**

Append to the end of `/mnt/archie_brain/market-watch/schema.sql`:

```sql
-- Open positions tracked by autonomous trading loop
CREATE TABLE IF NOT EXISTS open_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    target_price REAL NOT NULL,
    max_hold_days INTEGER DEFAULT 5,
    sector TEXT,
    thesis_id INTEGER REFERENCES analyses(id),
    alpaca_order_id TEXT,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'closed', 'stopped', 'target_hit', 'expired', 'reeval'))
);

-- Trade journal — every entry/exit with reasoning
CREATE TABLE IF NOT EXISTS trade_journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    position_id INTEGER REFERENCES open_positions(id),
    thesis_id INTEGER REFERENCES analyses(id),
    exit_reason TEXT,
    pnl REAL,
    pnl_pct REAL,
    risk_gates_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Portfolio lifetime metrics (single row)
CREATE TABLE IF NOT EXISTS portfolio_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peak_value REAL NOT NULL DEFAULT 100000.0,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Seed portfolio metrics if empty
INSERT OR IGNORE INTO portfolio_metrics (id, peak_value) VALUES (1, 100000.0);
```

- [ ] **Step 2: Verify schema loads**

```bash
cd /mnt/archie_brain/market-watch
rm -f /tmp/test_schema.db
sqlite3 /tmp/test_schema.db < schema.sql
sqlite3 /tmp/test_schema.db ".tables"
```

Expected: All tables including `open_positions`, `trade_journal`, `portfolio_metrics`.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add schema.sql
git commit -m "feat(trading): add open_positions, trade_journal, portfolio_metrics tables"
```

---

### Task 2: Risk Config — Centralized Env Var Loading

**Files:**
- Create: `services/risk_config.py`

- [ ] **Step 1: Create risk_config.py**

Create `/mnt/archie_brain/market-watch/services/risk_config.py`:

```python
"""Centralized risk configuration — all thresholds loaded from env vars."""

import os


def _float(key, default):
    return float(os.environ.get(key, default))


def _int(key, default):
    return int(os.environ.get(key, default))


def _bool(key, default):
    return os.environ.get(key, str(default)).lower() in ("true", "1", "yes")


# Risk gates
MIN_ORACLE_CONFIDENCE = _float("MW_MIN_ORACLE_CONFIDENCE", 0.65)
MAX_DAILY_LOSS_PCT = _float("MW_MAX_DAILY_LOSS_PCT", 3.0)
MAX_DRAWDOWN_PCT = _float("MW_MAX_DRAWDOWN_PCT", 5.0)
MAX_POSITIONS = _int("MW_MAX_POSITIONS", 5)
MAX_POSITION_PCT = _float("MW_MAX_POSITION_PCT", 10.0)
MAX_SECTOR_POSITIONS = _int("MW_MAX_SECTOR_POSITIONS", 2)
VOLATILITY_ATR_LIMIT = _float("MW_VOLATILITY_ATR_LIMIT", 5.0)
COOLOFF_LOSS_PCT = _float("MW_COOLOFF_LOSS_PCT", 2.0)

# Position management
DEFAULT_HOLD_DAYS = _int("MW_DEFAULT_HOLD_DAYS", 5)

# Cycle control
CYCLE_DEDUP_MINUTES = _int("MW_CYCLE_DEDUP_MINUTES", 15)

# Safety
DRY_RUN = _bool("MW_DRY_RUN", False)
TRADING_ENABLED = _bool("MW_TRADING_ENABLED", True)
LIVE_TRADING = _bool("MW_LIVE_TRADING", False)
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.risk_config import MAX_POSITIONS, DRY_RUN; print(f'MAX_POSITIONS={MAX_POSITIONS}, DRY_RUN={DRY_RUN}')"
```

Expected: `MAX_POSITIONS=5, DRY_RUN=False`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add services/risk_config.py
git commit -m "feat(trading): centralized risk config from env vars"
```

---

### Task 3: Portfolio Service — State & P&L Calculation

**Files:**
- Create: `services/portfolio_service.py`

- [ ] **Step 1: Create portfolio_service.py**

Create `/mnt/archie_brain/market-watch/services/portfolio_service.py`:

```python
"""Portfolio service — computes portfolio state, P&L, drawdown on demand."""

import logging
from datetime import date

from db import get_db
from services.market_data import get_quote

logger = logging.getLogger(__name__)


def get_portfolio_state():
    """Compute current portfolio state including unrealized P&L.

    Returns dict with: cash, portfolio_value, daily_pnl, drawdown_pct,
    open_positions_count, peak_value, total_trades, winning_trades, win_rate, total_pnl.
    """
    conn = get_db()
    try:
        # Cash balance
        account = conn.execute(
            "SELECT cash_balance, initial_balance FROM paper_account WHERE id = 1"
        ).fetchone()
        cash = account["cash_balance"] if account else 100000.0
        initial = account["initial_balance"] if account else 100000.0

        # Open positions with unrealized P&L
        positions = conn.execute(
            "SELECT ticker, quantity, entry_price, sector FROM open_positions WHERE status = 'open'"
        ).fetchall()

        unrealized = 0.0
        position_details = []
        for pos in positions:
            quote = get_quote(pos["ticker"])
            current_price = quote.get("price", pos["entry_price"])
            pos_pnl = (current_price - pos["entry_price"]) * pos["quantity"]
            unrealized += pos_pnl
            position_details.append({
                "ticker": pos["ticker"],
                "quantity": pos["quantity"],
                "entry_price": pos["entry_price"],
                "current_price": current_price,
                "pnl": round(pos_pnl, 2),
                "sector": pos["sector"],
            })

        portfolio_value = cash + sum(
            p["current_price"] * p["quantity"] for p in position_details
        ) if position_details else cash

        # Daily realized P&L
        today = date.today().isoformat()
        daily_row = conn.execute(
            "SELECT COALESCE(SUM(pnl), 0) as daily_pnl FROM trade_journal WHERE date(created_at) = ?",
            (today,),
        ).fetchone()
        daily_realized = daily_row["daily_pnl"] if daily_row else 0.0
        daily_pnl = daily_realized + unrealized

        # Metrics
        metrics = conn.execute(
            "SELECT peak_value, total_trades, winning_trades, total_pnl FROM portfolio_metrics WHERE id = 1"
        ).fetchone()
        peak_value = metrics["peak_value"] if metrics else initial
        total_trades = metrics["total_trades"] if metrics else 0
        winning_trades = metrics["winning_trades"] if metrics else 0
        total_pnl = metrics["total_pnl"] if metrics else 0.0

        # Update peak if new high
        if portfolio_value > peak_value:
            peak_value = portfolio_value
            conn.execute(
                "UPDATE portfolio_metrics SET peak_value = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
                (peak_value,),
            )
            conn.commit()

        drawdown_pct = ((peak_value - portfolio_value) / peak_value * 100) if peak_value > 0 else 0.0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        return {
            "cash": round(cash, 2),
            "initial_balance": round(initial, 2),
            "portfolio_value": round(portfolio_value, 2),
            "unrealized_pnl": round(unrealized, 2),
            "daily_pnl": round(daily_pnl, 2),
            "daily_pnl_pct": round((daily_pnl / portfolio_value * 100) if portfolio_value > 0 else 0.0, 2),
            "drawdown_pct": round(drawdown_pct, 2),
            "peak_value": round(peak_value, 2),
            "total_return_pct": round(((portfolio_value - initial) / initial * 100) if initial > 0 else 0.0, 2),
            "open_positions_count": len(positions),
            "open_positions": position_details,
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 2),
        }
    finally:
        conn.close()


def update_metrics_after_trade(pnl):
    """Update portfolio_metrics after a trade closes."""
    conn = get_db()
    try:
        is_win = 1 if pnl > 0 else 0
        conn.execute(
            """UPDATE portfolio_metrics SET
                total_trades = total_trades + 1,
                winning_trades = winning_trades + ?,
                total_pnl = total_pnl + ?,
                updated_at = CURRENT_TIMESTAMP
               WHERE id = 1""",
            (is_win, pnl),
        )
        conn.commit()
    finally:
        conn.close()


def get_sector_counts():
    """Return dict of sector → open position count."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT sector, COUNT(*) as cnt FROM open_positions WHERE status = 'open' AND sector IS NOT NULL GROUP BY sector"
        ).fetchall()
        return {row["sector"]: row["cnt"] for row in rows}
    finally:
        conn.close()
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.portfolio_service import get_portfolio_state, update_metrics_after_trade, get_sector_counts; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add services/portfolio_service.py
git commit -m "feat(trading): portfolio service — state, P&L, drawdown, metrics"
```

---

### Task 4: Execution Engine — 10-Gate Risk Evaluation

**Files:**
- Create: `services/execution_engine.py`

- [ ] **Step 1: Create execution_engine.py**

Create `/mnt/archie_brain/market-watch/services/execution_engine.py`:

```python
"""Execution engine — 10-gate risk evaluation for autonomous trading."""

import logging
from datetime import date

from db import get_db
from services.market_data import get_quote
from services.portfolio_service import get_portfolio_state, get_sector_counts
from services import risk_config as rc

logger = logging.getLogger(__name__)


def evaluate(analysis, portfolio_state):
    """Evaluate a pipeline recommendation against 10 risk gates.

    Args:
        analysis: dict from run_pipeline() — must have ticker, recommendation,
                  confidence (oracle), risk_approved (shield), target_price,
                  stop_loss, suggested_position_size, sector
        portfolio_state: dict from get_portfolio_state()

    Returns:
        dict with: approved (bool), reason (str), gates_log (list), order (dict or None)
    """
    gates_log = []
    ticker = analysis.get("ticker", "")

    def gate(name, passed, value, detail=""):
        gates_log.append({"gate": name, "passed": passed, "value": value, "detail": detail})
        return passed

    # Gate 1: Shield approval
    risk_approved = analysis.get("risk_approved", False)
    if not gate("shield_approval", bool(risk_approved), risk_approved):
        return _reject("Failed gate #1: Shield did not approve", gates_log)

    # Gate 2: Oracle confidence
    confidence = analysis.get("oracle_confidence") or analysis.get("confidence", 0)
    if not gate("oracle_confidence", confidence >= rc.MIN_ORACLE_CONFIDENCE, confidence,
                f"min={rc.MIN_ORACLE_CONFIDENCE}"):
        return _reject(f"Failed gate #2: oracle_confidence {confidence} < {rc.MIN_ORACLE_CONFIDENCE}", gates_log)

    # Gate 3: Daily loss limit
    daily_pnl_pct = portfolio_state.get("daily_pnl_pct", 0)
    if not gate("daily_loss_limit", daily_pnl_pct > -rc.MAX_DAILY_LOSS_PCT, daily_pnl_pct,
                f"limit=-{rc.MAX_DAILY_LOSS_PCT}%"):
        return _reject(f"Failed gate #3: daily P&L {daily_pnl_pct}% exceeds -{rc.MAX_DAILY_LOSS_PCT}%", gates_log)

    # Gate 4: Max drawdown breaker
    drawdown = portfolio_state.get("drawdown_pct", 0)
    if not gate("max_drawdown", drawdown < rc.MAX_DRAWDOWN_PCT, drawdown,
                f"limit={rc.MAX_DRAWDOWN_PCT}%"):
        return _reject(f"Failed gate #4: drawdown {drawdown}% >= {rc.MAX_DRAWDOWN_PCT}%", gates_log)

    # Gate 5: Max positions
    open_count = portfolio_state.get("open_positions_count", 0)
    if not gate("max_positions", open_count < rc.MAX_POSITIONS, open_count,
                f"limit={rc.MAX_POSITIONS}"):
        return _reject(f"Failed gate #5: {open_count} positions >= max {rc.MAX_POSITIONS}", gates_log)

    # Gate 6: Position size cap
    portfolio_value = portfolio_state.get("portfolio_value", 100000)
    max_order_value = portfolio_value * (rc.MAX_POSITION_PCT / 100)
    quote = get_quote(ticker)
    current_price = quote.get("price", 0)
    if current_price <= 0:
        return _reject(f"Failed gate #6: cannot get price for {ticker}", gates_log)

    # Calculate quantity
    suggested_size = analysis.get("suggested_position_size")
    if suggested_size and suggested_size > 0:
        order_value = min(suggested_size, max_order_value)
    else:
        order_value = min(portfolio_value / rc.MAX_POSITIONS, max_order_value)
    quantity = int(order_value / current_price)

    if quantity <= 0:
        return _reject(f"Failed gate #6: calculated quantity is 0 (price={current_price})", gates_log)

    actual_value = quantity * current_price
    if not gate("position_size", actual_value <= max_order_value, actual_value,
                f"limit={max_order_value:.0f}"):
        return _reject(f"Failed gate #6: order {actual_value:.0f} > max {max_order_value:.0f}", gates_log)

    # Gate 7: Duplicate ticker
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM open_positions WHERE ticker = ? AND status = 'open'", (ticker,)
        ).fetchone()
    finally:
        conn.close()
    if not gate("duplicate_ticker", existing is None, ticker):
        return _reject(f"Failed gate #7: already holding {ticker}", gates_log)

    # Gate 8: Volatility filter (ATR as % of price)
    atr_pct = _calculate_atr_pct(ticker)
    if not gate("volatility_filter", atr_pct <= rc.VOLATILITY_ATR_LIMIT, atr_pct,
                f"limit={rc.VOLATILITY_ATR_LIMIT}%"):
        return _reject(f"Failed gate #8: ATR {atr_pct:.1f}% > limit {rc.VOLATILITY_ATR_LIMIT}%", gates_log)

    # Gate 9: Sector concentration
    sector = analysis.get("sector", "unknown")
    sector_counts = get_sector_counts()
    sector_count = sector_counts.get(sector, 0)
    if not gate("sector_concentration", sector_count < rc.MAX_SECTOR_POSITIONS, sector_count,
                f"sector={sector}, limit={rc.MAX_SECTOR_POSITIONS}"):
        return _reject(f"Failed gate #9: {sector_count} positions in {sector} >= max {rc.MAX_SECTOR_POSITIONS}", gates_log)

    # Gate 10: Cool-off after loss
    conn = get_db()
    try:
        last_trade = conn.execute(
            "SELECT pnl_pct FROM trade_journal WHERE action = 'sell' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if last_trade and last_trade["pnl_pct"] is not None:
        last_loss_pct = last_trade["pnl_pct"]
        if not gate("cooloff_after_loss", last_loss_pct > -rc.COOLOFF_LOSS_PCT, last_loss_pct,
                    f"limit=-{rc.COOLOFF_LOSS_PCT}%"):
            return _reject(f"Failed gate #10: last trade lost {last_loss_pct:.1f}%, cooling off", gates_log)
    else:
        gate("cooloff_after_loss", True, "no_previous_trade")

    # All gates passed
    stop_loss = analysis.get("stop_loss") or analysis.get("risk_stop_loss") or (current_price * 0.95)
    target_price = analysis.get("target_price") or (current_price * 1.10)

    return {
        "approved": True,
        "reason": "All 10 gates passed",
        "gates_log": gates_log,
        "order": {
            "ticker": ticker,
            "action": "buy",
            "quantity": quantity,
            "price": current_price,
            "stop_loss": round(stop_loss, 2),
            "target_price": round(target_price, 2),
            "max_hold_days": rc.DEFAULT_HOLD_DAYS,
            "sector": sector,
            "thesis_id": analysis.get("analysis_id"),
        },
    }


def _reject(reason, gates_log):
    """Return a rejected ExecutionDecision."""
    return {"approved": False, "reason": reason, "gates_log": gates_log, "order": None}


def _calculate_atr_pct(ticker):
    """Calculate ATR as percentage of current price (14-day ATR)."""
    try:
        import yfinance as yf
        data = yf.Ticker(ticker).history(period="1mo")
        if data.empty or len(data) < 14:
            return 0.0
        high = data["High"]
        low = data["Low"]
        close = data["Close"]
        tr = []
        for i in range(1, len(data)):
            tr.append(max(
                high.iloc[i] - low.iloc[i],
                abs(high.iloc[i] - close.iloc[i - 1]),
                abs(low.iloc[i] - close.iloc[i - 1]),
            ))
        atr = sum(tr[-14:]) / 14
        current = close.iloc[-1]
        return (atr / current * 100) if current > 0 else 0.0
    except Exception as e:
        logger.warning("ATR calculation failed for %s: %s", ticker, e)
        return 0.0
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.execution_engine import evaluate; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add services/execution_engine.py
git commit -m "feat(trading): 10-gate execution engine with risk evaluation"
```

---

### Task 5: Position Manager — Exit Triggers

**Files:**
- Create: `services/position_manager.py`

- [ ] **Step 1: Create position_manager.py**

Create `/mnt/archie_brain/market-watch/services/position_manager.py`:

```python
"""Position manager — open position lifecycle with 4 exit triggers."""

import json
import logging
from datetime import datetime, timedelta

from db import get_db
from services.market_data import get_quote
from services.alpaca_client import place_order
from services.portfolio_service import update_metrics_after_trade
from services import risk_config as rc

logger = logging.getLogger(__name__)


def check_price_exits():
    """Check open positions for stop-loss, target, and time expiry exits.

    Returns list of closed position summaries.
    """
    conn = get_db()
    closed = []
    try:
        positions = conn.execute(
            "SELECT * FROM open_positions WHERE status = 'open'"
        ).fetchall()

        for pos in positions:
            quote = get_quote(pos["ticker"])
            current_price = quote.get("price", 0)
            if current_price <= 0:
                logger.warning("Cannot get price for %s, skipping exit check", pos["ticker"])
                continue

            exit_reason = None

            # Trigger 1: Stop-loss
            if current_price <= pos["stop_loss"]:
                exit_reason = "stopped"
            # Trigger 2: Target hit
            elif current_price >= pos["target_price"]:
                exit_reason = "target_hit"
            # Trigger 3: Time expiry
            else:
                opened_at = datetime.fromisoformat(str(pos["opened_at"]))
                hold_days = (datetime.utcnow() - opened_at).days
                if hold_days >= pos["max_hold_days"]:
                    exit_reason = "expired"

            if exit_reason:
                result = _close_position(conn, pos, current_price, exit_reason)
                if result:
                    closed.append(result)

        conn.commit()
    finally:
        conn.close()

    return closed


def check_reeval_exits(cycle_analyses):
    """Check open positions against new analysis results.

    Args:
        cycle_analyses: list of dicts from run_full_cycle() results,
                       each with "ticker" and "recommendation"

    Returns list of closed position summaries.
    """
    analysis_map = {}
    for a in cycle_analyses:
        if a.get("ticker") and a.get("recommendation"):
            analysis_map[a["ticker"]] = a["recommendation"]

    conn = get_db()
    closed = []
    try:
        positions = conn.execute(
            "SELECT * FROM open_positions WHERE status = 'open'"
        ).fetchall()

        for pos in positions:
            rec = analysis_map.get(pos["ticker"])
            if rec in ("sell", "skip"):
                quote = get_quote(pos["ticker"])
                current_price = quote.get("price", pos["entry_price"])
                result = _close_position(conn, pos, current_price, "reeval")
                if result:
                    closed.append(result)

        conn.commit()
    finally:
        conn.close()

    return closed


def open_position(order, alpaca_order_id=None):
    """Record a new open position from an approved execution decision.

    Args:
        order: dict from ExecutionDecision.order
        alpaca_order_id: optional Alpaca order ID

    Returns position ID.
    """
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO open_positions
               (ticker, quantity, entry_price, stop_loss, target_price, max_hold_days, sector, thesis_id, alpaca_order_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order["ticker"],
                order["quantity"],
                order["price"],
                order["stop_loss"],
                order["target_price"],
                order.get("max_hold_days", rc.DEFAULT_HOLD_DAYS),
                order.get("sector"),
                order.get("thesis_id"),
                alpaca_order_id,
            ),
        )
        position_id = cur.lastrowid

        # Log entry in trade journal
        conn.execute(
            """INSERT INTO trade_journal
               (ticker, action, quantity, price, position_id, thesis_id, risk_gates_log)
               VALUES (?, 'buy', ?, ?, ?, ?, ?)""",
            (
                order["ticker"],
                order["quantity"],
                order["price"],
                position_id,
                order.get("thesis_id"),
                json.dumps(order.get("gates_log", [])),
            ),
        )

        # Deduct cash
        total_cost = order["quantity"] * order["price"]
        conn.execute(
            "UPDATE paper_account SET cash_balance = cash_balance - ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (total_cost,),
        )

        conn.commit()
        return position_id
    finally:
        conn.close()


def _close_position(conn, pos, sell_price, exit_reason):
    """Close a position (called within an existing connection/transaction).

    Returns summary dict or None on error.
    """
    ticker = pos["ticker"]
    quantity = pos["quantity"]
    entry_price = pos["entry_price"]

    pnl = (sell_price - entry_price) * quantity
    pnl_pct = ((sell_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0

    # Execute sell (unless dry run)
    if not rc.DRY_RUN:
        result = place_order(ticker, quantity, "sell")
        if not result.get("success"):
            logger.error("Failed to sell %s: %s", ticker, result.get("error"))
            return None
    else:
        logger.info("[DRY RUN] Would sell %d %s at %.2f (reason: %s)", quantity, ticker, sell_price, exit_reason)

    # Update position status
    conn.execute(
        "UPDATE open_positions SET status = ? WHERE id = ?",
        (exit_reason, pos["id"]),
    )

    # Log exit in trade journal
    conn.execute(
        """INSERT INTO trade_journal
           (ticker, action, quantity, price, position_id, thesis_id, exit_reason, pnl, pnl_pct)
           VALUES (?, 'sell', ?, ?, ?, ?, ?, ?, ?)""",
        (ticker, quantity, sell_price, pos["id"], pos["thesis_id"], exit_reason, round(pnl, 2), round(pnl_pct, 2)),
    )

    # Return cash
    conn.execute(
        "UPDATE paper_account SET cash_balance = cash_balance + ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
        (sell_price * quantity,),
    )

    # Update metrics
    update_metrics_after_trade(pnl)

    logger.info("Closed %s: %s %.2f → %.2f, P&L: $%.2f (%.1f%%), reason: %s",
                ticker, exit_reason, entry_price, sell_price, pnl, pnl_pct, exit_reason)

    return {
        "ticker": ticker,
        "exit_reason": exit_reason,
        "entry_price": entry_price,
        "sell_price": sell_price,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
    }
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.position_manager import check_price_exits, check_reeval_exits, open_position; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add services/position_manager.py
git commit -m "feat(trading): position manager — exit triggers, open/close lifecycle"
```

---

### Task 6: Wire Run-Cycle Endpoint + Cycle Orchestration

**Files:**
- Modify: `routes/trading.py`

- [ ] **Step 1: Read current trading.py**

Read `/mnt/archie_brain/market-watch/routes/trading.py` to see existing routes.

- [ ] **Step 2: Add run-cycle, positions, and journal endpoints**

Add these imports at the top of `routes/trading.py`:

```python
import json
import os
import logging
from datetime import datetime, timedelta

from services import risk_config as rc
```

Add these three new routes to the file:

```python
logger = logging.getLogger(__name__)


@trading_bp.route("/api/trading/run-cycle", methods=["POST"])
def run_cycle():
    """Execute autonomous trading cycle — triggered by ARCHIE dispatch.

    Auth: service token (machine-to-machine), not user OAuth.
    """
    # Verify service token
    auth_header = request.headers.get("Authorization", "")
    service_token = os.environ.get("ARCHIE_SERVICE_TOKEN", "")
    if service_token and not auth_header.endswith(service_token):
        return jsonify({"success": False, "error": "Invalid service token"}), 401

    # Kill switch
    if not rc.TRADING_ENABLED:
        return jsonify({"success": False, "error": "Trading is disabled"}), 503

    # Dedup check
    conn = get_db()
    try:
        recent = conn.execute(
            "SELECT id FROM cycle_log WHERE status = 'completed' AND completed_at > ? ORDER BY id DESC LIMIT 1",
            (datetime.utcnow() - timedelta(minutes=rc.CYCLE_DEDUP_MINUTES),),
        ).fetchone()
        if recent and not (request.get_json(silent=True) or {}).get("force"):
            return jsonify({"success": True, "skipped": True, "reason": f"Cycle ran within {rc.CYCLE_DEDUP_MINUTES} min"})
    finally:
        conn.close()

    from services.position_manager import check_price_exits, check_reeval_exits, open_position
    from services.execution_engine import evaluate
    from services.portfolio_service import get_portfolio_state
    from services.agent_pipeline import run_full_cycle

    try:
        # Step 1: Check price-based exits
        price_exits = check_price_exits()
        logger.info("Price exits: %d positions closed", len(price_exits))

        # Step 2: Run full analysis cycle
        cycle_result = run_full_cycle()
        results = cycle_result.get("results", [])

        # Step 3: Check re-evaluation exits
        reeval_exits = check_reeval_exits(results)
        logger.info("Reeval exits: %d positions closed", len(reeval_exits))

        # Step 4: Evaluate new recommendations
        portfolio_state = get_portfolio_state()
        trades_executed = 0
        trades_skipped = 0
        errors = 0

        for result in results:
            if result.get("recommendation") != "buy":
                trades_skipped += 1
                continue

            # Build analysis dict for execution engine
            analysis = {
                "ticker": result.get("ticker"),
                "recommendation": result.get("recommendation"),
                "oracle_confidence": result.get("confidence"),
                "risk_approved": result.get("reports", {}).get("shield", {}).get("risk_approved", False),
                "target_price": result.get("target_price"),
                "stop_loss": result.get("reports", {}).get("shield", {}).get("stop_loss"),
                "suggested_position_size": result.get("reports", {}).get("shield", {}).get("position_size"),
                "sector": result.get("reports", {}).get("value", {}).get("sector", "unknown"),
                "analysis_id": result.get("analysis_id"),
            }

            decision = evaluate(analysis, portfolio_state)

            if decision["approved"]:
                if rc.DRY_RUN:
                    logger.info("[DRY RUN] Would buy %d %s at %.2f",
                                decision["order"]["quantity"], decision["order"]["ticker"], decision["order"]["price"])
                    trades_executed += 1
                else:
                    order = decision["order"]
                    alpaca_result = place_order(order["ticker"], order["quantity"], "buy")
                    if alpaca_result.get("success"):
                        order["gates_log"] = decision["gates_log"]
                        open_position(order, alpaca_result.get("order_id"))
                        trades_executed += 1
                        logger.info("Executed buy: %d %s at %.2f", order["quantity"], order["ticker"], order["price"])
                    else:
                        errors += 1
                        logger.error("Alpaca order failed for %s: %s", order["ticker"], alpaca_result.get("error"))

                # Refresh portfolio state for next evaluation
                portfolio_state = get_portfolio_state()
            else:
                trades_skipped += 1
                logger.info("Skipped %s: %s", result.get("ticker"), decision["reason"])

        # Step 5: Return summary
        final_state = get_portfolio_state()
        return jsonify({
            "success": True,
            "cycle_id": cycle_result.get("cycle_id"),
            "tickers_analyzed": cycle_result.get("stocks_analyzed", 0),
            "trades_executed": trades_executed,
            "trades_skipped": trades_skipped,
            "positions_closed": len(price_exits) + len(reeval_exits),
            "errors": errors,
            "dry_run": rc.DRY_RUN,
            "portfolio_value": final_state["portfolio_value"],
            "daily_pnl_pct": final_state["daily_pnl_pct"],
        })

    except Exception as e:
        logger.error("Cycle failed: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@trading_bp.route("/api/trading/positions")
@tier_required("viewer")
def get_positions():
    """Return current open positions with unrealized P&L."""
    from services.portfolio_service import get_portfolio_state
    state = get_portfolio_state()
    return jsonify({"success": True, "positions": state["open_positions"]})


@trading_bp.route("/api/trading/journal")
@tier_required("viewer")
def get_journal():
    """Return trade history with reasoning chain."""
    conn = get_db()
    try:
        limit = request.args.get("limit", 50, type=int)
        rows = conn.execute(
            """SELECT ticker, action, quantity, price, exit_reason, pnl, pnl_pct,
                      risk_gates_log, created_at
               FROM trade_journal ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        trades = []
        for r in rows:
            trade = {
                "ticker": r["ticker"],
                "action": r["action"],
                "quantity": r["quantity"],
                "price": r["price"],
                "exit_reason": r["exit_reason"],
                "pnl": r["pnl"],
                "pnl_pct": r["pnl_pct"],
                "date": r["created_at"],
            }
            if r["risk_gates_log"]:
                try:
                    trade["gates"] = json.loads(r["risk_gates_log"])
                except (json.JSONDecodeError, TypeError):
                    pass
            trades.append(trade)
        return jsonify({"success": True, "trades": trades})
    finally:
        conn.close()
```

Also add `from db import get_db` and `from services.alpaca_client import place_order` to the imports if not already present.

- [ ] **Step 3: Verify app loads**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from app import create_app; app = create_app(); print(f'{len(list(app.url_map.iter_rules()))} routes OK')"
```

Expected: Route count with `OK`.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add routes/trading.py
git commit -m "feat(trading): run-cycle endpoint, positions, journal routes"
```

---

### Task 7: Enrich Public Track Record

**Files:**
- Modify: `routes/public.py`

- [ ] **Step 1: Read current public.py**

Read `/mnt/archie_brain/market-watch/routes/public.py`.

- [ ] **Step 2: Replace track_record endpoint with enriched version**

Replace the `track_record()` function body with:

```python
@public_bp.route("/api/public/track-record")
def track_record():
    """Return W.A.T.C.H. agent's paper trading performance summary."""
    conn = get_db()
    try:
        # Portfolio metrics
        metrics = conn.execute(
            "SELECT peak_value, total_trades, winning_trades, total_pnl FROM portfolio_metrics WHERE id = 1"
        ).fetchone()

        # Paper account
        account = conn.execute(
            "SELECT cash_balance, initial_balance FROM paper_account WHERE id = 1"
        ).fetchone()

        cash = account["cash_balance"] if account else 100000.0
        initial = account["initial_balance"] if account else 100000.0
        total_trades = metrics["total_trades"] if metrics else 0
        winning_trades = metrics["winning_trades"] if metrics else 0
        total_pnl = metrics["total_pnl"] if metrics else 0.0
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0

        # Open positions value
        positions = conn.execute(
            "SELECT COUNT(*) as cnt FROM open_positions WHERE status = 'open'"
        ).fetchone()
        open_count = positions["cnt"] if positions else 0

        # Cycle stats
        cycles = conn.execute(
            """SELECT COUNT(*) as total_cycles, SUM(stocks_analyzed) as total_analyzed
               FROM cycle_log WHERE status = 'completed'"""
        ).fetchone()

        # Recent trades from journal (last 10)
        recent_trades = conn.execute(
            """SELECT ticker, action, quantity, price, exit_reason, pnl, pnl_pct, created_at
               FROM trade_journal ORDER BY created_at DESC LIMIT 10"""
        ).fetchall()

        # Recent analyses (last 5)
        recent_analyses = conn.execute(
            """SELECT ticker, recommendation, director_sentiment,
                      director_confidence, oracle_confidence, created_at
               FROM analyses ORDER BY created_at DESC LIMIT 5"""
        ).fetchall()

        total_return = ((cash + total_pnl - initial) / initial * 100) if initial > 0 else 0.0

        return jsonify({
            "success": True,
            "track_record": {
                "total_return_pct": round(total_return, 2),
                "cash_balance": round(cash, 2),
                "initial_balance": round(initial, 2),
                "total_pnl": round(total_pnl, 2),
                "total_trades": total_trades,
                "winning_trades": winning_trades,
                "win_rate_pct": round(win_rate, 1),
                "open_positions": open_count,
                "total_cycles": cycles["total_cycles"] or 0,
                "total_analyzed": cycles["total_analyzed"] or 0,
                "recent_trades": [
                    {
                        "ticker": t["ticker"],
                        "action": t["action"],
                        "quantity": t["quantity"],
                        "price": t["price"],
                        "exit_reason": t["exit_reason"],
                        "pnl": t["pnl"],
                        "pnl_pct": t["pnl_pct"],
                        "date": t["created_at"],
                    }
                    for t in recent_trades
                ],
                "recent_calls": [
                    {
                        "ticker": r["ticker"],
                        "recommendation": r["recommendation"],
                        "sentiment": r["director_sentiment"],
                        "confidence": r["director_confidence"],
                        "oracle_confidence": r["oracle_confidence"],
                        "date": r["created_at"],
                    }
                    for r in recent_analyses
                ],
            },
        })
    finally:
        conn.close()
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add routes/public.py
git commit -m "feat(api): enrich track-record with journal, metrics, win rate"
```

---

### Task 8: Update Docker Config + Env Template

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Add risk config env vars to docker-compose.yml**

Add these environment variables to the `environment:` section in `/mnt/archie_brain/market-watch/docker-compose.yml`:

```yaml
      # Risk Gates
      - MW_MIN_ORACLE_CONFIDENCE=${MW_MIN_ORACLE_CONFIDENCE:-0.65}
      - MW_MAX_DAILY_LOSS_PCT=${MW_MAX_DAILY_LOSS_PCT:-3.0}
      - MW_MAX_DRAWDOWN_PCT=${MW_MAX_DRAWDOWN_PCT:-5.0}
      - MW_MAX_POSITIONS=${MW_MAX_POSITIONS:-5}
      - MW_MAX_POSITION_PCT=${MW_MAX_POSITION_PCT:-10.0}
      - MW_MAX_SECTOR_POSITIONS=${MW_MAX_SECTOR_POSITIONS:-2}
      - MW_VOLATILITY_ATR_LIMIT=${MW_VOLATILITY_ATR_LIMIT:-5.0}
      - MW_COOLOFF_LOSS_PCT=${MW_COOLOFF_LOSS_PCT:-2.0}
      # Position Management
      - MW_DEFAULT_HOLD_DAYS=${MW_DEFAULT_HOLD_DAYS:-5}
      # Cycle Control
      - MW_CYCLE_DEDUP_MINUTES=${MW_CYCLE_DEDUP_MINUTES:-15}
      # Safety
      - MW_DRY_RUN=${MW_DRY_RUN:-true}
      - MW_TRADING_ENABLED=${MW_TRADING_ENABLED:-true}
      - MW_LIVE_TRADING=${MW_LIVE_TRADING:-false}
```

**NOTE:** `MW_DRY_RUN` defaults to `true` in Docker — safe by default.

- [ ] **Step 2: Add risk config section to .env.example**

Append to `/mnt/archie_brain/market-watch/.env.example`:

```bash

# Risk Gates
MW_MIN_ORACLE_CONFIDENCE=0.65
MW_MAX_DAILY_LOSS_PCT=3.0
MW_MAX_DRAWDOWN_PCT=5.0
MW_MAX_POSITIONS=5
MW_MAX_POSITION_PCT=10.0
MW_MAX_SECTOR_POSITIONS=2
MW_VOLATILITY_ATR_LIMIT=5.0
MW_COOLOFF_LOSS_PCT=2.0

# Position Management
MW_DEFAULT_HOLD_DAYS=5

# Cycle Control
MW_CYCLE_DEDUP_MINUTES=15

# Safety
MW_DRY_RUN=true
MW_TRADING_ENABLED=true
MW_LIVE_TRADING=false
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add docker-compose.yml .env.example
git commit -m "feat(config): risk gates, position, safety env vars in Docker + .env.example"
```

---

### Task 9: Rebuild and Integration Test

- [ ] **Step 1: Rebuild Docker image**

```bash
cd /mnt/archie_brain/market-watch
docker compose build --no-cache
```

- [ ] **Step 2: Restart container**

```bash
docker compose up -d
```

- [ ] **Step 3: Verify app starts**

```bash
docker logs kytran_market_api 2>&1 | tail -5
```

Expected: Flask server running, no import errors.

- [ ] **Step 4: Test run-cycle endpoint (dry run)**

```bash
docker exec kytran_market_api python3 -c "
from app import create_app
app = create_app()
with app.test_client() as c:
    # Test run-cycle (no service token needed in test client)
    import os
    os.environ['MW_DRY_RUN'] = 'true'
    os.environ['ARCHIE_SERVICE_TOKEN'] = ''
    r = c.post('/api/trading/run-cycle', json={'source': 'test', 'force': True})
    import json
    data = json.loads(r.data)
    print(f'Run cycle: {r.status_code} success={data.get(\"success\")} dry_run={data.get(\"dry_run\")}')
    print(f'Analyzed: {data.get(\"tickers_analyzed\")}, Executed: {data.get(\"trades_executed\")}, Skipped: {data.get(\"trades_skipped\")}')
"
```

Expected: Status 200 with cycle results (likely 0 trades since watchlist may be empty).

- [ ] **Step 5: Test positions endpoint**

```bash
docker exec kytran_market_api python3 -c "
from app import create_app
app = create_app()
with app.test_client() as c:
    r = c.get('/api/trading/positions')
    print(f'Positions (no auth): {r.status_code}')
"
```

Expected: 401 (authentication required).

- [ ] **Step 6: Test journal endpoint**

```bash
docker exec kytran_market_api python3 -c "
from app import create_app
app = create_app()
with app.test_client() as c:
    r = c.get('/api/trading/journal')
    print(f'Journal (no auth): {r.status_code}')
"
```

Expected: 401 (authentication required).

- [ ] **Step 7: Test kill switch**

```bash
docker exec kytran_market_api python3 -c "
import os
os.environ['MW_TRADING_ENABLED'] = 'false'
from services import risk_config
risk_config.TRADING_ENABLED = False
from app import create_app
app = create_app()
with app.test_client() as c:
    r = c.post('/api/trading/run-cycle', json={'source': 'test'})
    print(f'Kill switch: {r.status_code}')
"
```

Expected: 503.

- [ ] **Step 8: Browser test — dashboard positions tab**

Open `http://192.168.1.200:8101/dashboard`, log in, verify:
- No errors on positions/journal endpoints
- Dashboard loads normally with auth

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Trading tables schema | schema.sql | 1 |
| 2 | Risk config from env vars | services/risk_config.py | 1 |
| 3 | Portfolio service | services/portfolio_service.py | 1 |
| 4 | 10-gate execution engine | services/execution_engine.py | 1 |
| 5 | Position manager | services/position_manager.py | 1 |
| 6 | Run-cycle + positions + journal routes | routes/trading.py | 1 |
| 7 | Enriched public track record | routes/public.py | 1 |
| 8 | Docker + env config | docker-compose.yml, .env.example | 1 |
| 9 | Rebuild + integration test | Docker rebuild + tests | 0 |

**Total: 9 tasks, ~8 commits, 4 new files, 5 modified files**

**Note:** ARCHIE hub-side integration (Autonomy job, M.A.R.K.E.T. capability registration, Bridge dispatch routing) is a separate task that should be done after this Market Watch side is deployed and tested. It follows the standard Autonomy job pattern documented in the platform rules.

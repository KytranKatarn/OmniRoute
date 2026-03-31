# Market Watch — Autonomous Trading Loop (Phase A) Design

**Date:** 2026-03-31
**Project:** Market Watch — Full Product (StockBot Migration), Sub-project 3 Phase A
**Status:** Approved
**Approach:** Thin Execution Layer (Approach A), architected for Phase B event-driven upgrade

---

## Overview

Wire the W.A.T.C.H. 6-agent pipeline into an autonomous trading loop. ARCHIE's Autonomy module triggers cycles during market hours via Bridge dispatch to M.A.R.K.E.T. agent. Market Watch receives the trigger, checks open positions for exits, runs analysis, evaluates recommendations against a 10-gate risk stack, and auto-executes approved trades on Alpaca paper. All decisions are logged in a trade journal for the public track record.

## Requirements

- Autonomy job fires during NYSE market hours (9:30am-4pm ET, weekdays)
- Bridge dispatches to M.A.R.K.E.T. agent, which calls Market Watch's run-cycle endpoint
- 10 risk gates must all pass before any trade executes
- Shield agent's `risk_approved` is a hard requirement
- Positions have three exit triggers: stop-loss/target, time expiry, Oracle re-evaluation
- All decisions logged with full reasoning chain
- Dry-run and kill-switch safety modes
- Paper trading only (live requires admin toggle + env var double-lock)

---

## 1. Cycle Execution Flow

```
ARCHIE Hub (Autonomy job fires during market hours)
    → Bridge dispatch capability="market_analysis"
    → M.A.R.K.E.T. agent
    → Calls Market Watch POST /api/trading/run-cycle

Market Watch receives trigger:
    1. position_manager.check_price_exits()  — check stop-loss, target, time expiry
    2. run_full_cycle()                       — analyze each watchlist ticker (incl. those with open positions)
    3. position_manager.check_reeval_exits()  — compare new analyses vs open positions (Oracle flip → sell)
    4. For each NEW recommendation (no open position):
       a. execution_engine.evaluate()         — apply 10 risk gates
       b. If approved → place_order()         — execute via Alpaca (paper)
       c. Log to trade_journal                — record decision + reasoning
    5. Update portfolio_metrics               — peak value, win rate, total P&L
    6. Return cycle summary to hub            — trades made, skipped, errors, P&L snapshot
```

**Key behaviors:**
- Price-based exits checked first (stop/target/expiry free capital before new analysis)
- Re-evaluation exits checked after new analysis (Oracle flip triggers sell)
- New entries only for tickers without open positions
- Idempotent: if cycle ran within `MW_CYCLE_DEDUP_MINUTES`, skip
- No background thread needed (Phase B can add real-time position monitoring)

---

## 2. Risk Controls & Execution Engine

**`execution_engine.py`** — `evaluate(analysis, portfolio_state) → ExecutionDecision`

Risk gates checked in order, first failure stops:

| # | Gate | Rule | Default |
|---|------|------|---------|
| 1 | Shield approval | `analysis.risk_approved == True` | Hard requirement |
| 2 | Oracle confidence | `analysis.oracle_confidence >= MIN_CONFIDENCE` | 0.65 |
| 3 | Daily loss limit | `today_pnl >= -MAX_DAILY_LOSS_PCT` | -3% |
| 4 | Max drawdown breaker | `drawdown_pct < MAX_DRAWDOWN_PCT` | 5% |
| 5 | Max positions | `open_positions < MAX_POSITIONS` | 5 |
| 6 | Position size cap | `order_value <= MAX_POSITION_PCT * portfolio_value` | 10% |
| 7 | Duplicate ticker | No existing open position in same ticker | Hard requirement |
| 8 | Volatility filter | `ticker ATR <= VOLATILITY_ATR_LIMIT% of price` | 5% |
| 9 | Sector concentration | `sector_positions < MAX_SECTOR_POSITIONS` | 2 |
| 10 | Cool-off after loss | Skip if last trade lost > `COOLOFF_LOSS_PCT` | 2% |

**ExecutionDecision result:**

```python
{
    "approved": True/False,
    "reason": "All gates passed" / "Failed gate #3: daily_loss_limit (-3.2%)",
    "gates_log": [
        {"gate": "shield_approval", "passed": True, "value": True},
        {"gate": "oracle_confidence", "passed": True, "value": 0.78},
        ...
    ],
    "order": {  # only if approved
        "ticker": "AAPL",
        "action": "buy",
        "quantity": 12,
        "stop_loss": 178.50,
        "target_price": 195.00,
        "max_hold_days": 5,
        "thesis_id": 42,
    }
}
```

**Position sizing:** Uses Shield's `suggested_position_size` if available, capped by `MAX_POSITION_PCT`. Falls back to equal-weight (`portfolio_value / MAX_POSITIONS`) if Shield doesn't specify.

---

## 3. Position Manager

**`position_manager.py`** — manages open position lifecycle.

### Exit Triggers (checked at start of each cycle)

| # | Trigger | Logic | Action |
|---|---------|-------|--------|
| 1 | Stop-loss hit | Current price <= `stop_loss` | Sell at market |
| 2 | Target hit | Current price >= `target_price` | Sell at market |
| 3 | Time expiry | Position age >= `max_hold_days` trading days | Sell at market |
| 4 | Oracle re-evaluation | New analysis flips to "sell" or "skip" | Sell at market |

### New Table: `open_positions`

```sql
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
```

### New Table: `trade_journal`

```sql
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
```

### Close Flow

1. `check_exits()` iterates all `status='open'` positions
2. Fetch current price from market_data cache
3. Check triggers in priority order (stop → target → expiry → re-eval)
4. If triggered: call `place_order(sell)`, update position status, log to `trade_journal`

---

## 4. ARCHIE Hub Integration

### 4a. Autonomy Job

New agent loop job (Job #59):
- **Name:** `market_analysis_cycle`
- **Schedule:** Every 30 min during NYSE hours (9:30am-4pm ET), weekdays
- **Cron:** `*/30 9-15 * * 1-5` (plus final run at 16:00)
- **Action:** Dispatch `capability="market_analysis"` through Bridge
- **Tier:** Tier 1 (auto-approve)

### 4b. Dispatch Flow

```
Autonomy job fires
    → Bridge dispatch to M.A.R.K.E.T. agent
    → M.A.R.K.E.T. calls Market Watch (http://192.168.1.200:8101/api/trading/run-cycle)
    → Market Watch runs pipeline internally (using hub_client for sub-agents)
    → Returns cycle results to M.A.R.K.E.T.
    → M.A.R.K.E.T. reports back to Bridge
    → agent_service.increment_budget() tracks the work
```

If M.A.R.K.E.T. is in cooldown, Bridge escalates via standard chain (cross-department, fleet, cloud).

### 4c. Run-Cycle Endpoint

`POST /api/trading/run-cycle` — machine-to-machine, service token auth.

Request:
```json
{
    "source": "archie_dispatch",
    "dispatch_id": "abc123",
    "force": false
}
```

Response:
```json
{
    "success": true,
    "cycle_id": 7,
    "tickers_analyzed": 5,
    "trades_executed": 1,
    "trades_skipped": 4,
    "positions_closed": 1,
    "errors": 0,
    "portfolio_value": 100250.00,
    "daily_pnl_pct": 0.25
}
```

---

## 5. P&L Tracking & Portfolio State

### Portfolio Service

`portfolio_service.py` — computes current state on demand:

```
portfolio_value = cash_balance + sum(open_positions.quantity * current_price)
daily_pnl = sum(today's trade_journal.pnl) + unrealized gains
peak_value = max portfolio_value seen (stored in portfolio_metrics)
drawdown_pct = (peak_value - portfolio_value) / peak_value * 100
```

### New Table: `portfolio_metrics`

```sql
CREATE TABLE IF NOT EXISTS portfolio_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    peak_value REAL NOT NULL DEFAULT 100000.0,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

Single row, updated after every cycle.

### Public Track Record Updates

`/api/public/track-record` returns richer data:
- Win rate from portfolio_metrics
- Total P&L and return %
- Current drawdown
- Recent trades from trade_journal with entry/exit and P&L
- Open positions count

### Dashboard Endpoints

- `GET /api/trading/positions` — open positions with unrealized P&L
- `GET /api/trading/journal` — trade history with reasoning chain

---

## 6. Configuration & Safety

### Env Vars (all with safe defaults)

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
MW_DRY_RUN=false
MW_TRADING_ENABLED=true
MW_LIVE_TRADING=false
```

### Safety Features

| Feature | Behavior |
|---------|----------|
| Dedup | Skip if cycle completed within `CYCLE_DEDUP_MINUTES` |
| Circuit breaker | If drawdown >= `MAX_DRAWDOWN_PCT`, halt new trades. Position exits still run. |
| Dry-run | Pipeline + risk gates run, but `place_order()` skipped. Logs what would happen. |
| Kill switch | `MW_TRADING_ENABLED=false` disables run-cycle entirely (returns 503) |
| Audit trail | Every cycle → `cycle_log`, every decision → `trade_journal` with full gate results |
| Live double-lock | Real money requires both admin toggle AND `MW_LIVE_TRADING=true` env var |

---

## Files to Create / Modify

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/execution_engine.py` | 10-gate risk evaluation, ExecutionDecision |
| Create | `services/position_manager.py` | Open position lifecycle, exit triggers |
| Create | `services/portfolio_service.py` | Portfolio state, P&L, drawdown calculation |
| Create | `services/risk_config.py` | Centralized config loading from env vars |
| Modify | `schema.sql` | Add `open_positions`, `trade_journal`, `portfolio_metrics` tables |
| Modify | `routes/trading.py` | Add `run-cycle` endpoint, `positions`, `journal` endpoints |
| Modify | `routes/public.py` | Enrich track-record with journal/metrics data |
| Modify | `services/agent_pipeline.py` | Wire execution engine after Oracle recommendation |
| Modify | `docker-compose.yml` | Add risk config env vars |
| Modify | `.env.example` | Document new env vars |

### ARCHIE Hub Side

| Action | File / Location | Purpose |
|--------|----------------|---------|
| Add | Agent loop job #59 | `market_analysis_cycle` — 30-min market hours schedule |
| Add | M.A.R.K.E.T. agent capability | Register `market_analysis` capability |
| Modify | Bridge dispatch | Route `market_analysis` → M.A.R.K.E.T. → Market Watch endpoint |

## Out of Scope (Phase B)

- Event-driven real-time position monitoring (background thread)
- Dynamic position sizing (Kelly criterion, volatility-adjusted)
- Monte Carlo stress testing / walk-forward validation
- Enhanced data sources (Polygon, NewsAPI, transformer sentiment)
- Advanced order types (bracket, trailing stop, short selling)
- Real-time VaR monitoring

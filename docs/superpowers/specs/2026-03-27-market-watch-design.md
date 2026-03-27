# Kytran Market Watch — Product Design Spec

**Date**: 2026-03-27
**Project**: #198 Kytran Watch Suite
**Status**: Approved
**Agent**: M.A.R.K.E.T. — Market Analysis, Risk Knowledge & Equity Trading

---

## Problem

The A.R.C.H.I.E. platform has a mature StockBot module (21 files, 14 DB tables, 31 routes) locked inside the monolith. The Kytran Watch Suite needs a standalone Market Watch product (like Civic Watch :8099 and Legal Watch :8100) that combines the best StockBot features with an AutoHedge-style autonomous multi-agent trading pipeline running on local LLMs.

## Solution

Build Kytran Market Watch fresh using the Watch product template (Flask/SQLite/LCARS/Docker). Cherry-pick the best StockBot features (watchlists, portfolio, alerts, charts, backtesting), add a 4-agent autonomous trading pipeline dispatched via Bridge to local Ollama models, with Alpaca paper trading for execution and yfinance for market data.

---

## Product Identity

| Item | Value |
|------|-------|
| **Name** | Kytran Market Watch |
| **Agent** | M.A.R.K.E.T. — Market Analysis, Risk Knowledge & Equity Trading |
| **Port** | 8101 (internal 8080) |
| **Container** | `kytran_market_api` |
| **Accent Color** | Green (#10b981) |
| **Database** | SQLite (`market.db`) with WAL mode |
| **Framework** | Flask (Python 3.12-alpine) |
| **Data Sources** | yfinance (market data), Alpaca (paper trading) |
| **LLM** | Local Ollama via Bridge dispatcher (smart router picks model) |

---

## Architecture

### Data Flow

```
yfinance ──► Market Data Ingestion ──► SQLite (market.db)
                                          │
Alpaca ◄── Paper Trading Execution ◄── M.A.R.K.E.T. Agent Pipeline
                                          │
Bridge ──► Local LLM (smart router) ──► Agent Analysis Cycles
                                          │
Autonomy Module ──► Governs all recurring loops
```

### M.A.R.K.E.T. Agent Pipeline (4 Roles)

The autonomous trading pipeline follows the AutoHedge pattern: Thesis → Quant → Risk → Execute/Reject → Monitor → New Cycle. Each role dispatches to a local LLM via Bridge with capability tags — the smart router picks the best available model.

| Role | Capability Tag | Responsibility |
|------|---------------|----------------|
| **Director** | `thesis` | Macro analysis, creates trading thesis for each watchlist stock. Evaluates market conditions, sector trends, company fundamentals. |
| **Quant** | `quant_analysis` | Technical + statistical analysis. Calculates indicators (SMA, RSI, MACD, Bollinger), identifies patterns, scores entry/exit signals. |
| **Risk Manager** | `risk_assessment` | Position sizing, stop-loss placement, portfolio exposure limits. Ensures no single position exceeds risk thresholds. Veto power. |
| **Executor** | `trade_execution` | Converts approved thesis into Alpaca paper orders. Sets order type, quantity, limit prices. Monitors fill status. |

**Pipeline flow:**
1. Director generates thesis for a stock (bullish/bearish/neutral with reasoning)
2. Quant validates thesis with technical data (confirms or contradicts)
3. Risk Manager evaluates exposure (approves with sizing, or rejects with reason)
4. If approved: Executor places paper trade via Alpaca
5. If rejected: Log rejection reason, move to next stock
6. After all stocks: Log cycle results, schedule next cycle

**Bridge dispatch pattern:**
```python
dispatcher = get_dispatcher()
result = dispatcher.dispatch(
    capability="thesis",
    prompt=f"Analyze {ticker}: {market_data_summary}",
    module_id="market_watch",
    system_prompt="You are M.A.R.K.E.T.'s Director Agent..."
)
```

### Agent Registration

Register in A.R.C.H.I.E.'s `agents` table:

| Agent | Role | Department | Type |
|-------|------|------------|------|
| M.A.R.K.E.T. | AI Director | ANALYTICS | director |
| M.A.R.K.E.T. Director | Staff | ANALYTICS | staff |
| M.A.R.K.E.T. Quant | Staff | ANALYTICS | staff |
| M.A.R.K.E.T. Risk | Staff | ANALYTICS | staff |
| M.A.R.K.E.T. Executor | Staff | ANALYTICS | staff |

---

## Autonomous Loop

### Agent Loop Job

- **Job name**: `market_watch_cycle`
- **Schedule**: Every 4 hours during market hours (configurable)
- **Registered in**: `ai_bridge/agent_loop.py`
- **Governed by**: Autonomy module

**Cycle steps:**
1. Pull watchlist from Market Watch API
2. Fetch latest market data via yfinance
3. Run M.A.R.K.E.T. pipeline per stock (Director → Quant → Risk → Executor)
4. Log all actions to `cycle_log` table
5. Log to `governance_audit_log` via `_log_autonomy_action()`

### Circuit Breaker

| Constraint | Limit |
|-----------|-------|
| Max trades per day | 10 |
| Max portfolio exposure | 80% of paper account |
| Max single position | 20% of portfolio |
| Max daily loss | 5% of portfolio value |
| Max consecutive losses | 5 |
| Max cycles per day | 6 |

When triggered: stop all trading, Telegram escalation (Tier 2), log to governance.

### Telegram Integration

- Circuit breaker alerts (immediate)
- Daily P&L summary (end of trading day)
- Large position changes (>10% of portfolio)
- Agent escalation (Risk Manager veto on high-conviction thesis)

---

## Dashboard (8 Tabs)

### Tab 1: Dashboard (Overview)

- Portfolio value card (total value, daily P&L, % change)
- Active positions count with top movers
- Live cycle status (idle / running Director / running Quant / etc.)
- Agent pipeline progress indicator
- Recent alerts feed
- Market status (open/closed/pre-market/after-hours)

### Tab 2: Watchlist

- Add/remove tickers with notes
- Current price, daily change %, volume
- Last analysis date and recommendation (bull/bear/neutral badge)
- Bulk add (comma-separated tickers)
- Sort by: name, change %, last analyzed

### Tab 3: Portfolio

- Paper positions table: ticker, qty, avg cost, current price, P&L ($), P&L (%), opened by (agent/manual)
- Total portfolio value and cash balance
- Unrealized vs realized P&L
- Position close button (manual)

### Tab 4: Alerts

- Price alerts: above/below threshold triggers
- Volume alerts: unusual volume detection
- Agent alerts: thesis changes, risk warnings, circuit breaker
- Alert history with timestamps
- Create/delete alert controls

### Tab 5: Analysis

- Agent reports per stock: Director thesis, Quant analysis, Risk assessment
- Recommendation badge (BUY / SELL / HOLD / SKIP)
- Confidence score from each agent
- Historical analysis log (all past reports per ticker)
- Expandable detail cards

### Tab 6: Trading

- Manual order form: ticker, action (buy/sell), qty, order type (market/limit)
- Agent execution history: which agent, what thesis, order details, fill status
- Open orders list
- Order cancel button
- Paper account balance and buying power

### Tab 7: Charts

- Candlestick chart (daily/weekly/monthly)
- Volume bars
- Indicator overlays: SMA (20/50/200), RSI, MACD, Bollinger Bands
- Ticker selector from watchlist
- Library: lightweight-charts (TradingView open source, ~40KB)

### Tab 8: Backtest

- Strategy selector (agent pipeline vs simple moving average vs custom)
- Date range picker
- Initial capital input
- Results: total return, Sharpe ratio, max drawdown, win rate, trade count
- Equity curve chart
- Trade log table

---

## Database Schema (SQLite)

```sql
-- Watchlist
CREATE TABLE watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL UNIQUE,
    notes TEXT,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Paper portfolio positions
CREATE TABLE portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    quantity REAL NOT NULL,
    avg_cost REAL NOT NULL,
    opened_by TEXT DEFAULT 'manual',
    thesis_id INTEGER,
    opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thesis_id) REFERENCES analyses(id)
);

-- Transaction history
CREATE TABLE transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('buy', 'sell')),
    quantity REAL NOT NULL,
    price REAL NOT NULL,
    order_type TEXT DEFAULT 'market',
    executed_by TEXT DEFAULT 'manual',
    thesis_id INTEGER,
    alpaca_order_id TEXT,
    status TEXT DEFAULT 'filled' CHECK (status IN ('pending', 'filled', 'cancelled', 'rejected')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (thesis_id) REFERENCES analyses(id)
);

-- Price and volume alerts
CREATE TABLE alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    alert_type TEXT NOT NULL CHECK (alert_type IN ('price_above', 'price_below', 'volume', 'agent')),
    threshold REAL,
    message TEXT,
    triggered INTEGER DEFAULT 0,
    triggered_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Agent pipeline analysis results
CREATE TABLE analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    cycle_id INTEGER,
    director_thesis TEXT,
    director_sentiment TEXT CHECK (director_sentiment IN ('bullish', 'bearish', 'neutral')),
    director_confidence REAL,
    quant_report TEXT,
    quant_score REAL,
    quant_indicators TEXT,
    risk_assessment TEXT,
    risk_approved INTEGER DEFAULT 0,
    risk_position_size REAL,
    risk_stop_loss REAL,
    recommendation TEXT CHECK (recommendation IN ('buy', 'sell', 'hold', 'skip')),
    executed INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (cycle_id) REFERENCES cycle_log(id)
);

-- Market data cache (TTL-based)
CREATE TABLE market_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    data_type TEXT NOT NULL CHECK (data_type IN ('quote', 'history', 'fundamentals', 'news')),
    data TEXT NOT NULL,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    UNIQUE(ticker, data_type)
);

-- Backtest results
CREATE TABLE backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy TEXT NOT NULL,
    tickers TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    final_value REAL,
    total_return REAL,
    sharpe_ratio REAL,
    max_drawdown REAL,
    win_rate REAL,
    trade_count INTEGER,
    equity_curve TEXT,
    trade_log TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Autonomous cycle tracking
CREATE TABLE cycle_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    stocks_analyzed INTEGER DEFAULT 0,
    trades_made INTEGER DEFAULT 0,
    trades_skipped INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'breaker_tripped')),
    details TEXT
);

-- Data ingestion log (Watch pattern)
CREATE TABLE ingest_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'failure')),
    records_count INTEGER DEFAULT 0,
    error_message TEXT,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Paper trading account
CREATE TABLE paper_account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cash_balance REAL NOT NULL DEFAULT 100000.0,
    initial_balance REAL NOT NULL DEFAULT 100000.0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## File Structure

```
market-watch/
├── app.py                          # Flask app + background threads
├── db.py                           # SQLite init (WAL + FK)
├── schema.sql                      # All tables above
├── requirements.txt                # flask, yfinance, alpaca-py, requests, lightweight-charts
├── Dockerfile                      # python:3.12-alpine
├── docker-compose.yml              # Port 8101, resource limits, read-only rootfs
├── routes/
│   ├── health.py                   # GET /api/health
│   ├── stocks.py                   # GET /api/stocks, /api/stocks/<ticker>
│   ├── watchlist.py                # CRUD /api/watchlist
│   ├── portfolio.py                # GET /api/portfolio, /api/portfolio/summary
│   ├── alerts.py                   # CRUD /api/alerts
│   ├── analysis.py                 # GET /api/analysis, POST /api/analysis/run
│   ├── trading.py                  # POST /api/trading/buy, /sell, /close
│   ├── backtest.py                 # POST /api/backtest/run, GET /api/backtest/results
│   └── charts.py                   # GET /api/charts/<ticker> (OHLCV data)
├── services/
│   ├── market_data.py              # yfinance wrapper (quotes, history, fundamentals)
│   ├── alpaca_client.py            # Alpaca paper trading (orders, positions, account)
│   ├── agent_pipeline.py           # M.A.R.K.E.T. 4-role orchestration via Bridge
│   ├── backtest_engine.py          # Historical strategy simulation
│   └── alert_engine.py             # Alert evaluation + trigger notifications
├── ingest/
│   ├── price_ingest.py             # Background price/quote refresh (every 5min during market hours)
│   └── news_ingest.py              # Financial news ingestion (optional, GDELT finance)
└── static/
    ├── index.html                  # Single-page LCARS dashboard (8 tabs)
    ├── css/
    │   ├── lcars.css               # LCARS frame (green accent #10b981)
    │   └── dashboard.css           # Layout, tables, cards, charts
    └── js/
        ├── app.js                  # Tab routing, DOM init, market status
        ├── api.js                  # Fetch wrapper with error handling
        ├── dashboard.js            # Overview: portfolio value, cycle status, alerts
        ├── watchlist.js            # Watchlist CRUD + price display
        ├── portfolio.js            # Positions table + P&L
        ├── analysis.js             # Agent reports + recommendation badges
        ├── trading.js              # Order form + execution history
        ├── charts.js               # Candlestick + indicators (lightweight-charts)
        ├── alerts.js               # Alert management
        └── backtest.js             # Strategy simulation UI + equity curve
```

---

## Integration Points

### Bridge Dispatcher (agent_pipeline.py)

```python
from bridge_dispatcher import get_dispatcher

def run_pipeline(ticker: str, market_data: dict) -> dict:
    dispatcher = get_dispatcher()

    # Step 1: Director thesis
    thesis = dispatcher.dispatch(
        capability="thesis",
        prompt=f"Analyze {ticker} for trading opportunity: {market_data}",
        module_id="market_watch",
        system_prompt="You are M.A.R.K.E.T.'s Director Agent. Generate a trading thesis..."
    )

    # Step 2: Quant validation
    quant = dispatcher.dispatch(
        capability="quant_analysis",
        prompt=f"Validate thesis for {ticker}: {thesis.response}. Technical data: {indicators}",
        module_id="market_watch",
        system_prompt="You are M.A.R.K.E.T.'s Quant Agent. Analyze technical indicators..."
    )

    # Step 3: Risk assessment
    risk = dispatcher.dispatch(
        capability="risk_assessment",
        prompt=f"Assess risk for {ticker} trade: {thesis.response}. Portfolio: {positions}",
        module_id="market_watch",
        system_prompt="You are M.A.R.K.E.T.'s Risk Manager. Evaluate position sizing..."
    )

    # Step 4: Execute (if risk approved)
    if risk_approved:
        execution = dispatcher.dispatch(
            capability="trade_execution",
            prompt=f"Execute paper trade for {ticker}: {order_details}",
            module_id="market_watch",
            system_prompt="You are M.A.R.K.E.T.'s Executor. Place the paper order..."
        )
```

### Autonomy Module (agent_loop.py)

New agent loop job:
```python
self.scheduler.add_job(
    with_app_context(self._run_market_watch_cycle),
    trigger=IntervalTrigger(hours=4),
    id="market_watch_cycle",
    name="Agent Loop: M.A.R.K.E.T. Trading Cycle",
    replace_existing=True,
)
```

### Docker Compose Addition

```yaml
kytran_market_api:
  build: ./market-watch
  container_name: kytran_market_api
  ports:
    - "8101:8080"
  volumes:
    - ./market-watch/data:/app/data
  environment:
    - ARCHIE_HUB_URL=http://192.168.1.200:3000
    - ALPACA_API_KEY=${ALPACA_API_KEY}
    - ALPACA_SECRET_KEY=${ALPACA_SECRET_KEY}
    - ALPACA_BASE_URL=https://paper-api.alpaca.markets
  read_only: true
  tmpfs:
    - /tmp
  deploy:
    resources:
      limits:
        cpus: '0.5'
        memory: 128M
  restart: unless-stopped
```

### Code Health Registration

Add to `STANDALONE_PRODUCTS` in `code_metrics_service.py`:
```python
{"name": "Kytran Market Watch", "path": "/mnt/archie_brain/market-watch", "port": 8101}
```

---

## Error Handling

| Scenario | Response |
|----------|----------|
| yfinance rate limited | Back off, use cached data, retry next cycle |
| Alpaca API down | Skip execution step, log thesis/analysis only |
| Bridge dispatch fails | Log error, skip stock, continue cycle |
| Risk Manager rejects | Log rejection with reason, no trade, move to next stock |
| Circuit breaker tripped | Stop all trading, Telegram alert, wait for manual reset |
| Market closed | Skip trading cycle, run analysis-only mode |
| SQLite locked | WAL mode handles concurrent reads; writes retry with backoff |

---

## Success Criteria

1. Standalone Docker container runs on port 8101
2. LCARS green-accent dashboard loads with all 8 tabs functional
3. Watchlist add/remove works, prices update via yfinance
4. M.A.R.K.E.T. agent pipeline runs a full cycle (Director → Quant → Risk → Execute)
5. Paper trades execute via Alpaca API
6. Agent loop job runs autonomously every 4h during market hours
7. Circuit breaker stops trading when limits hit
8. Autonomy module logs all cycle actions
9. Backtest engine runs strategy against historical data
10. Charts render with candlesticks and indicators

## Out of Scope (v1)

- Live trading with real money (paper only)
- Options, crypto, forex (equities only)
- Multi-user portfolios (single admin)
- Mobile app
- Integration with StockBot module (standalone replaces it)
- Webhook-based data feeds
- Social sentiment analysis

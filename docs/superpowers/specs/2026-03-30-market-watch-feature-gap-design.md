# Market Watch Feature Gap Fill + LCARS UI — Design Spec

**Date:** 2026-03-30
**Project:** StockBot → Market Watch Migration (Sub-project 1 of 4)
**Status:** Approved

---

## Purpose

Merge StockBot's missing features into Market Watch standalone (market.kytranempowerment.com, port 8101). Upgrade the 4-role agent pipeline to a 5-agent system orchestrated by W.A.T.C.H., add server-side technical indicators, sentiment analysis, strategy management, and apply full LCARS theme.

## Agent Architecture

W.A.T.C.H. (AI Director, Analytics & Intelligence, agent #152) orchestrates 5 existing agents via Bridge dispatch. Cross-department dispatch — agents stay in their current departments.

| Agent | Person | ID | Department | Role in Analysis |
|-------|--------|-----|-----------|-----------------|
| **Quant** | Raj Mehta | 39 | Finance & Accounting | Technical analysis — RSI, MACD, SMA, Bollinger Bands, volume patterns |
| **Value** | Diego Castillo | 40 | Analytics & Intelligence | Fundamental analysis — P/E, earnings, revenue growth, DCF |
| **Pulse** | Alexei Ivanovich | 30 | Operations & Infrastructure | Market sentiment — news scoring, social buzz, sector momentum |
| **Shield** | Suki Taniguchi | 42 | Finance & Accounting | Risk management — position sizing, stop-loss, portfolio exposure |
| **Oracle** | Olivia Oduya | 43 | Analytics & Intelligence | Final synthesis — combines all 4 reports, issues buy/sell/hold with confidence |

### Analysis Flow

```
Market Watch UI → POST /api/analysis/run {ticker}
  → Market Watch backend calls A.R.C.H.I.E. Hub Bridge
    → W.A.T.C.H. receives request, dispatches sequentially:
      1. Quant analyzes technicals (RSI, MACD, SMA, volume)
      2. Value analyzes fundamentals (P/E, earnings, margins)
      3. Pulse analyzes sentiment (news, social, sector)
      4. Shield assesses risk (position size, stop-loss, exposure)
      5. Oracle synthesizes all 4 reports → final recommendation
    → W.A.T.C.H. returns structured result to Market Watch
  → Market Watch stores in analyses table, displays to user
```

### Bridge Dispatch Contract

Market Watch calls: `POST {ARCHIE_HUB_URL}/api/bridge/dispatch`

Payload:
```json
{
  "agent": "W.A.T.C.H.",
  "task": "full_analysis",
  "ticker": "AAPL",
  "market_data": { ... cached quote/history/technicals ... },
  "news": [ ... recent headlines ... ]
}
```

Response:
```json
{
  "quant_report": "...",
  "quant_score": 7.5,
  "value_report": "...",
  "value_score": 6.2,
  "pulse_report": "...",
  "pulse_score": 8.0,
  "risk_assessment": "...",
  "risk_level": "moderate",
  "oracle_synthesis": "...",
  "recommendation": "buy",
  "confidence": 0.78,
  "suggested_position_size": 0.03,
  "stop_loss": 172.50,
  "target_price": 198.00
}
```

## Features to Add

### 1. 5-Agent Pipeline (replaces 4-role system)

Modify `market-watch/services/agent_pipeline.py`:
- Replace Director/Quant/Risk/Executor with W.A.T.C.H. orchestrated dispatch
- Each agent gets market data + their specialty prompt
- Results stored in expanded `analyses` table
- W.A.T.C.H. handles orchestration logic (which agents to call, in what order)

### 2. Technical Indicators (server-side)

Port from StockBot's `market_data_service.py` into `market-watch/services/market_data.py`:
- RSI (14-period relative strength index)
- MACD (12/26/9 moving average convergence/divergence)
- SMA (20, 50, 200 simple moving averages)
- Bollinger Bands (20-period, 2 std dev)
- Volume analysis (avg volume, volume ratio)
- Computed on cached yfinance history data
- Exposed via `GET /api/stocks/<ticker>/technicals`

### 3. Sentiment Analysis

Create `market-watch/services/sentiment.py`:
- Fetch news via yfinance or free news API
- Score sentiment per headline (-1 to +1)
- Aggregate sentiment per ticker
- Store in `sentiment_scores` table
- Fed into Pulse agent's analysis context
- Exposed via `GET /api/stocks/<ticker>/sentiment`

### 4. Strategy Management

Create `market-watch/services/strategy_service.py` and `market-watch/routes/strategy_routes.py`:
- CRUD for named strategies (name, rules JSON, description)
- Strategy rules: entry conditions, exit conditions, position sizing
- Link strategies to backtests
- Exposed via `GET/POST/PUT/DELETE /api/strategies`

### 5. LCARS Theme Overhaul

Update `market-watch/static/` and templates:
- Orbitron for headings, IBM Plex Mono for data
- Cyan (#00e5ff) primary accent, dark background
- LCARS elbow corners on panels
- Station-colored accents for different sections
- Responsive at 480/768/1024px breakpoints
- Match the A.R.C.H.I.E. dashboard aesthetic

### 6. 8-Tab Layout

| Tab | Content | Status |
|-----|---------|--------|
| Dashboard | Portfolio summary, market overview, recent signals | Enhance existing |
| Watchlist | Ticker list with live quotes, sparklines | Exists, enhance |
| Portfolio | Holdings, P&L, transactions, paper account balance | Exists, enhance |
| Analysis | 5-agent reports, recommendation history, confidence scores | Rebuild with 5-agent |
| Charts | Candlestick charts with technical overlays (RSI, MACD, BB) | Exists, add indicators |
| Alerts | Price/volume/agent alerts, trigger history | Exists, enhance |
| Strategies | Strategy CRUD, backtest linkage, active strategy status | New |
| Settings | Alpaca keys, analysis preferences, notification config | Exists, enhance |

## Database Changes (SQLite)

### New tables:

```sql
CREATE TABLE IF NOT EXISTS strategies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    rules TEXT NOT NULL,  -- JSON: entry_conditions, exit_conditions, position_sizing
    is_active INTEGER DEFAULT 1,
    backtest_count INTEGER DEFAULT 0,
    last_backtest_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sentiment_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    source TEXT NOT NULL,  -- 'news', 'social', 'analyst'
    headline TEXT,
    score REAL NOT NULL,  -- -1.0 to 1.0
    summary TEXT,
    url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sentiment_ticker ON sentiment_scores(ticker, created_at);
```

### Modified tables:

```sql
ALTER TABLE analyses ADD COLUMN value_report TEXT;
ALTER TABLE analyses ADD COLUMN value_score REAL;
ALTER TABLE analyses ADD COLUMN pulse_report TEXT;
ALTER TABLE analyses ADD COLUMN pulse_score REAL;
ALTER TABLE analyses ADD COLUMN oracle_synthesis TEXT;
ALTER TABLE analyses ADD COLUMN confidence REAL;
ALTER TABLE analyses ADD COLUMN suggested_position_size REAL;
ALTER TABLE analyses ADD COLUMN stop_loss REAL;
ALTER TABLE analyses ADD COLUMN target_price REAL;
```

## File Changes Summary

### New files:
| File | Purpose |
|------|---------|
| `market-watch/services/sentiment.py` | News sentiment scoring |
| `market-watch/services/strategy_service.py` | Strategy CRUD |
| `market-watch/routes/strategy_routes.py` | Strategy API routes |
| `market-watch/static/css/lcars.css` | LCARS theme styles |

### Modified files:
| File | Change |
|------|--------|
| `market-watch/services/agent_pipeline.py` | Replace 4-role with W.A.T.C.H. 5-agent dispatch |
| `market-watch/services/market_data.py` | Add RSI, MACD, SMA, Bollinger Bands, volume analysis |
| `market-watch/schema.sql` | Add strategies, sentiment_scores tables + analyses columns |
| `market-watch/db.py` | Run new migrations on startup |
| `market-watch/app.py` | Register strategy routes blueprint |
| `market-watch/routes/analysis_routes.py` | Update for 5-agent response format |
| `market-watch/routes/stock_routes.py` | Add /technicals and /sentiment endpoints |
| `market-watch/templates/index.html` | LCARS theme + 8-tab layout |
| `market-watch/static/css/style.css` | LCARS overhaul |
| `market-watch/static/js/app.js` | 8-tab JS, charts with indicator overlays |

## Out of Scope (later sub-projects)
- Subscription/OAuth gating (Sub-project 2)
- Real-time data feeds replacing yfinance (Sub-project 3)
- Autonomous trading loop (Sub-project 3)
- VPS deployment (Sub-project 4)

## Dependencies
- A.R.C.H.I.E. Bridge dispatch accessible from Market Watch container
- W.A.T.C.H. agent active in agents table (currently active, ID #152)
- 5 specialist agents in agents table (currently barracked — need activation)
- yfinance for market data (existing)
- Alpaca paper trading API keys (existing)

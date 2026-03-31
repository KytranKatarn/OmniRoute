# Market Watch — Phase B4: Advanced Risk/Sizing Design

**Date:** 2026-03-31
**Project:** Market Watch — Full Product, Phase B4
**Status:** Approved

---

## Overview

Add a full quant risk suite: Kelly criterion dynamic position sizing, portfolio Value at Risk (VaR), correlation-adjusted sizing, sector beta weighting, and a risk grading system. Metrics visible to admin (full detail), subscribers (simplified), and public (grade badge).

## Requirements

- Kelly criterion replaces fixed-percentage sizing (half-Kelly, capped by MAX_POSITION_PCT)
- Historical VaR at 95% and 99% confidence
- Correlation matrix for open positions, diversification score 0-100
- Sector beta vs SPY benchmark
- All metrics cached in risk_metrics table with weekly TTL
- Risk grade (A+ through F) based on composite score
- Falls back to fixed sizing if <10 trades in history

---

## 1. Kelly Criterion Position Sizing

Kelly % = W - [(1 - W) / R] where W = win rate, R = avg win / avg loss ratio.

- Half-Kelly by default (industry standard)
- Falls back to fixed percentage if <10 trades
- Capped by existing MAX_POSITION_PCT gate
- Kelly only reduces sizing, never increases beyond cap
- Source data: portfolio_metrics (win rate) + trade_journal (avg win/loss)

## 2. Value at Risk (VaR)

Historical VaR from portfolio daily returns.
- Collect daily returns per position from yfinance 252-day history
- Weight by position size
- VaR(95%) = 5th percentile, VaR(99%) = 1st percentile
- Returns: var_95_pct, var_95_dollar, var_99_pct, var_99_dollar, portfolio_volatility
- Optional risk gate: block trades if var_95_pct > MAX_VAR_PCT (disabled by default)

## 3. Correlation-Adjusted Sizing + Sector Beta

Correlation matrix from 90-day daily returns. Diversification score = (1 - avg_pairwise_correlation) * 100.

Sector beta = cov(ticker, SPY) / var(SPY) from 90-day returns.

Position sizing adjustment: Kelly fraction reduced if new ticker >0.7 correlated with any open position (size halved). Portfolio beta gate: block if > MAX_PORTFOLIO_BETA (default 1.5).

## 4. Dashboard + Public Exposure

Admin: Full detail (Kelly, VaR, correlations, beta, diversification, refresh button).
Viewer: Risk grade, VaR statement, diversification label, portfolio beta.
Public: Risk grade badge on landing page.

Risk grade = weighted composite: VaR within 2% (30%), diversification >60 (25%), beta <1.3 (20%), win rate >50% (15%), drawdown <3% (10%). Grade: A+(95), A(90), B+(85), B(80), C(70), D(60), F(<60).

## 5. Database

```sql
CREATE TABLE IF NOT EXISTS risk_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_type TEXT NOT NULL,
    ticker TEXT,
    data JSON NOT NULL,
    calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,
    UNIQUE(metric_type, ticker)
);
```

## 6. API Endpoints

| Method | Route | Auth | Purpose |
|--------|-------|------|---------|
| GET | `/api/trading/risk-metrics` | admin | Full quant detail |
| POST | `/api/trading/risk-metrics/refresh` | admin | Force recalculate |
| GET | `/api/trading/risk-summary` | viewer | Grade + VaR + diversification |
| GET | `/api/public/risk-grade` | none | Grade letter + label |

## 7. Configuration

```bash
MW_KELLY_ENABLED=true
MW_KELLY_FRACTION=0.5           # Half-Kelly
MW_KELLY_MIN_TRADES=10
MW_VAR_GATE_ENABLED=false
MW_MAX_VAR_PCT=3.0
MW_MAX_PORTFOLIO_BETA=1.5
MW_CORRELATION_THRESHOLD=0.7
MW_RISK_METRICS_TTL_DAYS=7
```

## 8. Files

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/quant_service.py` | Kelly, VaR, correlations, beta, diversification, risk grade |
| Create | `routes/risk.py` | Risk API endpoints |
| Modify | `services/execution_engine.py` | Use Kelly sizing + correlation adjustment + beta gate |
| Modify | `schema.sql` | Add risk_metrics table |
| Modify | `static/index.html` | Admin risk detail + viewer risk summary in dashboard |
| Modify | `templates/landing.html` | Public risk grade badge |
| Modify | `docker-compose.yml` | Quant env vars |
| Modify | `.env.example` | Document quant env vars |

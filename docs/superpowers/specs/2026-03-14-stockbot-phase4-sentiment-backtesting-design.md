# StockBot Phase 4: News Sentiment + Backtesting — Design Spec

## Overview

Add news sentiment analysis from multiple sources (RSS, NewsAPI, Reddit) with AI-powered sentiment scoring via Bridge. Add strategy backtesting engine with realistic simulation (slippage, fees) and full performance metrics (Sharpe, drawdown, win rate, benchmark comparison).

## News Sentiment

### Sources
- Yahoo Finance RSS, Reuters RSS, MarketWatch RSS (free, no key)
- NewsAPI.org (free tier, API key in .env, 100 req/day)
- Reddit (subreddits: wallstreetbets, stocks, investing — via JSON API, no auth needed)

### sentiment_service.py (~150 lines)
- `fetch_news(ticker, sources=['rss','newsapi','reddit'])` — aggregate headlines from all sources
- `analyze_sentiment(ticker)` — fetch news, send headlines to Bridge Sentiment Agent (Priya/pulse), get scored sentiment per headline + overall score
- `get_sentiment_history(ticker)` — past sentiment analyses from DB
- Headlines cached in `stock_news_cache` table (ticker, source, headline, url, sentiment_score, analyzed_at)

### Bridge integration
Send batch of headlines to the existing Sentiment Agent (pulse/Priya Sharma) with enhanced prompt:
"Analyze these headlines for {ticker}. Score each -1.0 to +1.0. Return JSON: {overall_score, headlines: [{text, score, impact}], summary}"

### APScheduler
Add to job #27: after strategy evaluation, run sentiment scan for watchlist tickers (cap 3/cycle).

## Backtesting Engine

### backtest_service.py (~200 lines)
- `run_backtest(strategy_rules, ticker, period='1y', initial_balance=100000, commission=0.001, slippage=0.001)`:
  1. Fetch historical OHLCV via yfinance for period
  2. Calculate indicators (SMA/RSI/MACD/Bollinger) for each day
  3. Simulate strategy: for each day, evaluate conditions, execute trades with slippage + commission
  4. Track: balance, positions, trades, daily portfolio value
  5. Calculate metrics vs benchmark (SPY)
  6. Return full results

### Performance metrics
- Total return %, annualized return
- Sharpe ratio (risk-adjusted return)
- Max drawdown (worst peak-to-trough)
- Win rate (% profitable trades)
- Profit factor (gross profit / gross loss)
- Total trades, avg trade duration
- Benchmark comparison (strategy return vs SPY return for same period)
- Equity curve (daily portfolio values for charting)

### Results stored in `stock_backtest_results` table

## Database: 2 new tables

stock_news_cache (ticker, source, headline, url, sentiment_score, published_at, analyzed_at).
stock_backtest_results (user_id, strategy_name, ticker, period, metrics JSONB, equity_curve JSONB, created_at).

## Routes: 4 new

GET /api/sentiment/<ticker> — current sentiment + recent headlines
POST /api/backtest — run backtest (body: strategy_rules, ticker, period)
GET /api/backtest/results — user's past backtest results
GET /api/backtest/<id> — single result with equity curve

## Frontend

Sentiment panel on Charts tab: overall score gauge (-1 to +1), headline list with per-headline scores, source badges.
Backtest tab (new, 7th tab): strategy selector (from existing strategies or custom rules), ticker + period inputs, Run Backtest button, results panel (metrics table + equity curve chart via lightweight-charts line series + benchmark overlay).

## Files: ~350 lines new services, ~60 lines routes, ~120 lines JS, ~20 lines CSS. Migration 168.

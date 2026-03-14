# StockBot Phase 1: Foundation — Design Spec

## Overview

Transform StockBot from an AI chat shell into a real trading platform. Add market data via yfinance with DB caching, persistent watchlist with price alerts, portfolio tracking with P&L, professional candlestick charts via lightweight-charts, and technical indicators. LCARS-themed tabbed dashboard.

## Database: 6 tables

stock_watchlist (user_id, ticker, notes, alert_above/below), stock_portfolio (user_id, ticker, shares, avg_cost, current_price), stock_transactions (user_id, ticker, action, shares, price, total, paper_trade), stock_price_cache (ticker, price, change_pct, volume, market_cap, pe_ratio, data JSONB, cached 5min), stock_history_cache (ticker, period, ohlcv JSONB, cached 1h/24h), stock_alerts (user_id, ticker, condition, threshold, triggered).

## Services

market_data_service.py (~200 lines): get_quote (cached), get_history (OHLCV), get_company_info, get_financials, batch_update_prices, search_tickers, calculate_indicators (SMA/EMA/RSI/MACD/Bollinger).

portfolio_service.py (~120 lines): watchlist CRUD, portfolio with P&L calc, record_transaction (updates avg_cost), get_portfolio_summary, create/check_alerts.

## Routes: 12 endpoints

Market: quote, history, search, company. Watchlist: list/add/remove. Portfolio: holdings/trade/transactions. Alerts: create/list.

## APScheduler: Job #27

Stock price updater every 5 min. Collects all watchlist+portfolio tickers, batch updates, checks alerts.

## Frontend

LCARS tabs: Dashboard (overview + sparklines), Watchlist (prices + alerts), Portfolio (holdings + P&L + trade form), Charts (lightweight-charts candlesticks + indicators), AI Chat (upgraded with market context). Orange accent. sb- CSS prefix.

## Dependencies: yfinance, lightweight-charts CDN

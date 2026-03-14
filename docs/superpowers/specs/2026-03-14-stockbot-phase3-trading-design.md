# StockBot Phase 3: Paper Trading + Strategies + Alpaca — Design Spec

## Overview

Add paper trading engine with $100K virtual cash, automated strategy builder with condition/action rules, and Alpaca broker integration for live trading. APScheduler evaluates strategies against real prices.

## Paper Trading

Virtual $100K starting balance. Buy/sell at real market prices. P&L tracking (unrealized + realized). Trade history with running balance. Uses existing stock_transactions + stock_portfolio tables, adds paper account balance tracking.

## Strategy Builder

User-defined rules: conditions (RSI < X, price above SMA, MACD crossover, price change %) → actions (buy N shares, sell N shares, sell all). Stored in DB. APScheduler evaluates active strategies every 5 min against cached prices. Logs each evaluation + execution.

## Alpaca Integration

Connect API key via settings. When connected, trades route to Alpaca API instead of local ledger. Account sync pulls positions + balance. Paper or live mode. Graceful fallback without API key.

## Database: 3 new tables

stock_paper_accounts (user_id UNIQUE, balance, starting_balance, created_at). stock_strategies (user_id, name, ticker, rules JSONB, is_active, last_evaluated, created_at). stock_strategy_logs (strategy_id, action_taken, details, executed_at).

## Services

trading_service.py (~150 lines): paper_buy, paper_sell, get_paper_account, reset_paper_account, get_pnl_summary.
strategy_service.py (~100 lines): create/list/delete/toggle strategies, evaluate_strategies (check conditions against indicators), execute_strategy_action.
alpaca_service.py (~80 lines): connect, get_account, submit_order, get_positions, sync_portfolio. Conditional on alpaca-trade-api package.

## Routes: 8 new

POST /api/paper/buy, POST /api/paper/sell, GET /api/paper/account, POST /api/paper/reset.
POST /api/strategies, GET /api/strategies, DELETE /api/strategies/<id>, POST /api/strategies/<id>/toggle.

## APScheduler

Upgrade job #27: after price update + alerts + scan, also evaluate active strategies.

## Frontend

New "Trading" tab: paper account balance, buy/sell form, strategy builder (condition selects + action selects + create button), active strategies list with toggle/delete, strategy execution log.

## Files: ~450 lines new, ~50 modified. Dependencies: alpaca-trade-api (optional).

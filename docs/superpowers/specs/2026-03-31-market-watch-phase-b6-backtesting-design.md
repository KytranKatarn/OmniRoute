# Market Watch — Phase B6: Backtesting Upgrades Design

**Date:** 2026-03-31
**Project:** Market Watch — Full Product, Phase B6
**Status:** Approved

---

## Overview

Upgrade backtesting from single SMA crossover to a full strategy library (5 strategies), Monte Carlo simulation, walk-forward analysis, and parameter optimization with overfitting protection. Public showcase of best strategy performance on landing page.

## Components

1. **Monte Carlo** — Randomize trade sequences (1000+ sims), probability distributions of returns/drawdown/Sharpe, ruin probability
2. **Walk-Forward** — Train/test sliding windows, OOS Sharpe, consistency ratio, overfitting detection
3. **Parameter Optimization** — Grid/random search with walk-forward validation per combo
4. **Strategy Library** — SMA Crossover, RSI Mean Reversion, MACD Momentum, Bollinger Bounce, W.A.T.C.H. Replay
5. **Public Showcase** — Best strategy stats on landing page

## Schema

monte_carlo_results (backtest_id, simulations, data JSON), walk_forward_results (strategy, tickers, windows JSON, avg_oos_sharpe, consistency_ratio, overfitting_score)

## API

POST /api/backtest/monte-carlo (ai), POST /api/backtest/walk-forward (ai), POST /api/backtest/optimize (ai), GET /api/backtest/strategies (viewer), GET /api/public/backtest-showcase (public)

## Files

Create: services/monte_carlo.py, services/walk_forward.py, services/strategy_library.py, services/optimizer.py
Modify: services/backtest_engine.py, routes/backtest.py, schema.sql, templates/landing.html

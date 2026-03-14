# StockBot Phase 2: AI Multi-Agent Analysis — Design Spec

## Overview

Add 5 specialized trading agents (Technical, Fundamental, Sentiment, Risk, Synthesizer) that analyze stocks in parallel via Bridge dispatch. Results displayed as chart overlays (support/resistance zones, price targets, signal markers) + analysis panel with per-agent reasoning and confidence scores. Watchlist auto-scan + context-aware AI chat.

## 5 New Agents

Registered in agents table, assigned to ANALYTICS station:
- Quinn Park (quant) — Technical Analyst: patterns, indicators, support/resistance
- Victor Chen (value) — Fundamental Analyst: valuation, financials, outlook
- Priya Sharma (pulse) — Sentiment Analyst: momentum, volume, market psychology
- Sam Torres (shield) — Risk Manager: volatility, position sizing, stop loss
- Olivia Reed (oracle) — Chief Strategist: synthesizes all 4 into unified recommendation

## Analysis Engine

stock_analysis_service.py (~200 lines). run_full_analysis(ticker): fetches market data, dispatches 4 agents in parallel threads (30s timeout), feeds results to Synthesizer, stores in stock_analyses table. Returns: overall_signal, confidence, price_target, entry, stop_loss, per-agent results.

## Database: 2 new tables

stock_analyses (user_id, ticker, technical/fundamental/sentiment/risk/synthesis JSONB, overall_signal, confidence, price_target). stock_scan_results (ticker, scan_type, signal, confidence, summary).

## Chart Overlays

Support zones (green bands), resistance zones (red bands) from Technical Agent. Price target (blue dashed) + stop loss (red dashed) from Synthesizer. Buy/sell signal markers on candlesticks.

## Analysis Panel

Right sidebar on Charts tab: synthesis header (signal badge + confidence + targets), 4 collapsible agent cards with individual results + confidence bars.

## Routes: 3 new

POST /api/analyze-full/<ticker>, GET /api/analysis/<ticker>, GET /api/analysis/<ticker>/history.

## Auto-scan

Job #27 upgraded: scan watchlist tickers without recent analysis (>4h), cap 5 per cycle.

## AI Chat upgrade

Detect tickers in messages, inject latest analysis context into Bridge prompt.

## Files: ~380 lines new, ~80 modified

# Market Watch — Phase B5: Advanced Order Types Design

**Date:** 2026-03-31
**Project:** Market Watch — Full Product, Phase B5
**Status:** Approved

---

## Overview

Replace local stop/target tracking with Alpaca-native bracket orders, add trailing stops, and enable short selling. All order types use Alpaca's server-side order management for instant execution. Short selling is opt-in with separate risk gates.

## 1. Bracket Orders
- `place_bracket_order(ticker, qty, take_profit, stop_loss)` via Alpaca API
- Alpaca manages stop-loss and take-profit legs server-side
- Position manager still tracks locally for dashboard display
- Execution engine uses bracket by default when BRACKET_ORDERS_ENABLED=true

## 2. Trailing Stops
- `place_trailing_stop(ticker, qty, trail_percent)` via Alpaca API
- Trail percent from ATR calculation or default (3%)
- Used when volatility is moderate; fixed stop when volatile

## 3. Short Selling
- Oracle "sell" on unheld ticker → potential short entry
- direction column: 'long' or 'short' on open_positions
- Short P&L: (entry - exit) * quantity
- Short exits: stop-loss (price UP), target (price DOWN), time expiry
- Separate risk gates: max 2 shorts, 5% position cap, opt-in via MW_SHORTS_ENABLED

## 4. Schema Changes
```sql
ALTER TABLE open_positions ADD COLUMN direction TEXT DEFAULT 'long';
ALTER TABLE open_positions ADD COLUMN order_type TEXT DEFAULT 'market';
ALTER TABLE open_positions ADD COLUMN trail_percent REAL;
```

## 5. Config
```bash
MW_SHORTS_ENABLED=false
MW_MAX_SHORT_POSITIONS=2
MW_SHORT_POSITION_PCT=5.0
MW_DEFAULT_TRAIL_PERCENT=3.0
MW_BRACKET_ORDERS_ENABLED=true
```

## 6. Files
| Action | File | Purpose |
|--------|------|---------|
| Modify | `services/alpaca_client.py` | Bracket, trailing stop, short order functions |
| Modify | `services/execution_engine.py` | Short evaluation, order type selection |
| Modify | `services/position_manager.py` | Direction-aware P&L and exits |
| Modify | `schema.sql` | New columns on open_positions |
| Modify | `services/risk_config.py` | Short selling config vars |
| Modify | `docker-compose.yml` + `.env.example` | New env vars |

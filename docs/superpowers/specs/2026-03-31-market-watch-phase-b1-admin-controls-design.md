# Market Watch — Phase B1: Admin Trading Controls Design

**Date:** 2026-03-31
**Project:** Market Watch — Full Product, Phase B1
**Status:** Approved
**Depends on:** Phase A (autonomous trading loop) — COMPLETE

---

## Overview

Add a full Trading Operations console to the Market Watch dashboard settings area. Admin-only controls for: dry-run/live toggles, manual cycle trigger, pause autonomy, close positions (individual + bulk + emergency), risk gate config editing with DB persistence, portfolio snapshot, and last cycle results.

## Requirements

- All controls admin-only (`data-tier="admin"`)
- Lives inside existing dashboard settings area (not a new tab/page)
- Risk config overrides stored in DB, survive restarts, env vars act as initial defaults
- Toggle changes take effect immediately (no restart needed)
- Position close operations execute via Alpaca and log to trade_journal
- Confirmation modals for destructive actions (close positions, disable dry run, live trading)

---

## 1. Trading Ops Settings Panel

Located in the dashboard settings area. Only visible to admin users.

### Layout Sections

1. **Mode Controls** — Three toggles: Dry Run (ON/OFF), Trading Enabled (ON/OFF), Live Trading (ON/OFF)
2. **Actions** — Run Cycle Now, Pause Autonomy, Close All Positions
3. **Portfolio Snapshot** — Cash, value, P&L, open positions count, drawdown, win rate, last/next cycle
4. **Open Positions** — List with unrealized P&L, individual [CLOSE] button per position
5. **Risk Gate Config** — Editable fields for all 9 thresholds + Save + Reset to Defaults
6. **Last Cycle Results** — Analyzed, executed, skipped, closed, dry_run flag, portfolio value, daily P&L

---

## 2. API Endpoints

| Method | Route | Auth | Purpose |
|--------|-------|------|---------|
| GET | `/api/trading/config` | admin | Current risk config + mode toggles + validation ranges |
| PUT | `/api/trading/config` | admin | Update risk thresholds, save to DB |
| POST | `/api/trading/config/reset` | admin | Reset to env var defaults |
| POST | `/api/trading/toggle-dry-run` | admin | Toggle DRY_RUN on/off |
| POST | `/api/trading/toggle-enabled` | admin | Toggle TRADING_ENABLED on/off |
| POST | `/api/trading/toggle-live` | admin | Toggle LIVE_TRADING (requires env var double-lock) |
| POST | `/api/trading/close-position/<id>` | admin | Close a single position at market |
| POST | `/api/trading/close-all` | admin | Emergency close all open positions |
| POST | `/api/trading/pause-autonomy` | admin | Set paused flag — run-cycle checks and skips |
| GET | `/api/trading/cycle-status` | admin | Last cycle results + paused state |

---

## 3. Toggle & Safety Logic

### Mode Toggles

| Toggle | Effect | Default | Safety |
|--------|--------|---------|--------|
| Dry Run | ON = pipeline runs, place_order() skipped. OFF = real paper trades. | ON | Flipping OFF requires confirmation modal |
| Trading Enabled | ON = run-cycle accepts requests. OFF = returns 503 (kill switch). | ON | Open positions still monitored for exits when OFF |
| Live Trading | ON = Alpaca live URL. OFF = Alpaca paper URL. | OFF | Requires admin role AND `MW_LIVE_TRADING=true` env var. UI warns if env var is false |

Toggle state stored in `trading_config` table. Env vars are initial defaults (first boot only).

### Close Position

1. Admin clicks [CLOSE] → confirmation modal with ticker, shares, current P&L
2. `POST /api/trading/close-position/<id>`
3. Server calls `place_order(sell)`, updates position status to 'closed', logs to trade_journal
4. Returns result, UI refreshes

### Close All

1. Admin clicks [CLOSE ALL] → red confirmation modal listing all positions
2. `POST /api/trading/close-all`
3. Server iterates all open positions, closes each, returns summary

### Pause Autonomy

- Sets `paused` flag in `trading_config` table
- `run-cycle` endpoint checks flag, returns `{"skipped": true, "reason": "paused"}` if set
- No hub modification needed — flag is local to Market Watch

---

## 4. Risk Config Persistence

### Load Order (on boot)

1. `risk_config.py` loads env var defaults
2. Checks `trading_config` table for overrides
3. DB values override env vars for any key present

### Save Flow

1. Admin edits values → [SAVE] → `PUT /api/trading/config`
2. Server validates ranges
3. Stores in `trading_config.config` JSON column
4. Updates in-memory `risk_config` module values immediately

### Reset Flow

1. Admin clicks [RESET TO DEFAULTS] → confirmation
2. `POST /api/trading/config/reset`
3. Clears DB overrides, reloads from env vars
4. UI refreshes with default values

### Validation Rules

| Field | Type | Min | Max |
|-------|------|-----|-----|
| MIN_ORACLE_CONFIDENCE | float | 0.0 | 1.0 |
| MAX_DAILY_LOSS_PCT | float | 0.5 | 20.0 |
| MAX_DRAWDOWN_PCT | float | 1.0 | 50.0 |
| MAX_POSITIONS | int | 1 | 20 |
| MAX_POSITION_PCT | float | 1.0 | 50.0 |
| MAX_SECTOR_POSITIONS | int | 1 | 10 |
| VOLATILITY_ATR_LIMIT | float | 1.0 | 20.0 |
| COOLOFF_LOSS_PCT | float | 0.5 | 10.0 |
| DEFAULT_HOLD_DAYS | int | 1 | 30 |

---

## 5. Database

### New Table: `trading_config`

```sql
CREATE TABLE IF NOT EXISTS trading_config (
    id INTEGER PRIMARY KEY,
    config JSON NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO trading_config (id, config) VALUES (1, '{}');
```

Single row. `config` JSON stores:
```json
{
    "dry_run": true,
    "trading_enabled": true,
    "live_trading": false,
    "paused": false,
    "risk_gates": {
        "min_oracle_confidence": 0.65,
        "max_daily_loss_pct": 3.0,
        ...
    }
}
```

Empty `{}` means "use env var defaults for everything."

---

## 6. Files to Create / Modify

| Action | File | Purpose |
|--------|------|---------|
| Create | `services/trading_config_service.py` | DB-backed config CRUD, load/save/reset, validation |
| Modify | `services/risk_config.py` | On import, check DB for overrides. Add `reload()` function. |
| Modify | `routes/trading.py` | Add 9 new admin endpoints |
| Modify | `schema.sql` | Add `trading_config` table |
| Modify | `static/index.html` | Add Trading Ops panel in settings area (admin-only) |

## Out of Scope

- Hub-side Autonomy job pause (using local flag instead)
- Audit log of config changes (future enhancement)
- Multi-user config (single admin config for now)

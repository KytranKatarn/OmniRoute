# Market Watch — Phase B5: Advanced Order Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace local stop/target tracking with Alpaca-native bracket orders, add trailing stops, and enable short selling with separate risk gates.

**Architecture:** Extend `alpaca_client.py` with bracket/trailing/short functions. Execution engine selects order type based on volatility. Position manager handles direction-aware P&L. Short selling is opt-in.

**Tech Stack:** Flask 3.1, alpaca-py, SQLite

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `schema.sql` | Add direction, order_type, trail_percent columns |
| Modify | `services/risk_config.py` | Add short selling + order type config vars |
| Modify | `services/alpaca_client.py` | Bracket, trailing stop, short order functions |
| Modify | `services/execution_engine.py` | Short evaluation, order type selection logic |
| Modify | `services/position_manager.py` | Direction-aware P&L, short exit logic |
| Modify | `docker-compose.yml` + `.env.example` | New env vars |

---

### Task 1: Schema + Config

**Files:**
- Modify: `schema.sql`
- Modify: `services/risk_config.py`

- [ ] **Step 1: Add columns to schema.sql**

Append to end of `/mnt/archie_brain/market-watch/schema.sql`:

```sql
-- Advanced order types (B5) — add columns if not exist
-- SQLite doesn't support ALTER TABLE ADD COLUMN IF NOT EXISTS,
-- so these are handled via migration in db.py init
```

Since SQLite doesn't support `ADD COLUMN IF NOT EXISTS`, create a migration file instead. Create `/mnt/archie_brain/market-watch/migrations/003_advanced_orders.sql`:

```sql
-- Add direction, order_type, trail_percent to open_positions
ALTER TABLE open_positions ADD COLUMN direction TEXT DEFAULT 'long';
ALTER TABLE open_positions ADD COLUMN order_type TEXT DEFAULT 'market';
ALTER TABLE open_positions ADD COLUMN trail_percent REAL;
```

- [ ] **Step 2: Add config vars to risk_config.py**

Read `/mnt/archie_brain/market-watch/services/risk_config.py` and append before the `reload()` function:

```python
# Short selling
SHORTS_ENABLED = _bool("MW_SHORTS_ENABLED", False)
MAX_SHORT_POSITIONS = _int("MW_MAX_SHORT_POSITIONS", 2)
SHORT_POSITION_PCT = _float("MW_SHORT_POSITION_PCT", 5.0)

# Order types
DEFAULT_TRAIL_PERCENT = _float("MW_DEFAULT_TRAIL_PERCENT", 3.0)
BRACKET_ORDERS_ENABLED = _bool("MW_BRACKET_ORDERS_ENABLED", True)
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/migrations/003_advanced_orders.sql market-watch/services/risk_config.py market-watch/schema.sql
git commit -m "feat(orders): schema migration + config for bracket, trailing, short orders"
```

---

### Task 2: Alpaca Client — Bracket, Trailing, Short Orders

**Files:**
- Modify: `services/alpaca_client.py`

- [ ] **Step 1: Read current alpaca_client.py**

Read `/mnt/archie_brain/market-watch/services/alpaca_client.py` to see the existing `place_order()` function.

- [ ] **Step 2: Add three new order functions**

Add these functions after the existing `place_order()`:

```python
def place_bracket_order(ticker, qty, side="buy", take_profit=None, stop_loss=None):
    """Place a bracket order — entry + stop-loss + take-profit managed by Alpaca.

    Args:
        ticker: stock ticker
        qty: number of shares
        side: 'buy' or 'sell' (sell for short entry)
        take_profit: target price for profit leg
        stop_loss: stop price for loss leg

    Returns:
        dict with success, order_id, status, legs
    """
    try:
        from alpaca.trading.requests import (
            MarketOrderRequest, TakeProfitRequest, StopLossRequest,
        )
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        order_data = MarketOrderRequest(
            symbol=ticker.upper(),
            qty=int(qty),
            side=order_side,
            time_in_force=TimeInForce.DAY,
            order_class="bracket",
            take_profit=TakeProfitRequest(limit_price=round(take_profit, 2)) if take_profit else None,
            stop_loss=StopLossRequest(stop_price=round(stop_loss, 2)) if stop_loss else None,
        )
        order = client.submit_order(order_data)
        return {
            "success": True,
            "order_id": str(order.id),
            "status": str(order.status),
            "order_type": "bracket",
            "ticker": ticker,
            "side": side,
            "qty": qty,
        }
    except Exception as e:
        logger.error("Bracket order failed for %s: %s", ticker, e)
        return {"success": False, "error": str(e)}


def place_trailing_stop(ticker, qty, side="buy", trail_percent=None):
    """Place a trailing stop order.

    Args:
        ticker: stock ticker
        qty: number of shares
        side: 'buy' or 'sell'
        trail_percent: trailing percentage (e.g., 3.0 for 3%)

    Returns:
        dict with success, order_id, status
    """
    try:
        from alpaca.trading.requests import TrailingStopOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        order_side = OrderSide.BUY if side == "buy" else OrderSide.SELL
        order_data = TrailingStopOrderRequest(
            symbol=ticker.upper(),
            qty=int(qty),
            side=order_side,
            time_in_force=TimeInForce.GTC,
            trail_percent=str(round(trail_percent, 2)),
        )
        order = client.submit_order(order_data)
        return {
            "success": True,
            "order_id": str(order.id),
            "status": str(order.status),
            "order_type": "trailing_stop",
            "ticker": ticker,
            "side": side,
            "qty": qty,
            "trail_percent": trail_percent,
        }
    except Exception as e:
        logger.error("Trailing stop order failed for %s: %s", ticker, e)
        return {"success": False, "error": str(e)}


def place_short_order(ticker, qty, order_type="market", take_profit=None, stop_loss=None, trail_percent=None):
    """Place a short sell order.

    Args:
        ticker: stock ticker
        qty: number of shares to short
        order_type: 'market', 'bracket', or 'trailing_stop'

    Returns:
        dict with success, order_id, status
    """
    if order_type == "bracket" and take_profit and stop_loss:
        return place_bracket_order(ticker, qty, side="sell",
                                    take_profit=take_profit, stop_loss=stop_loss)
    elif order_type == "trailing_stop" and trail_percent:
        return place_trailing_stop(ticker, qty, side="sell", trail_percent=trail_percent)
    else:
        return place_order(ticker, qty, "sell")
```

- [ ] **Step 3: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.alpaca_client import place_bracket_order, place_trailing_stop, place_short_order; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/services/alpaca_client.py
git commit -m "feat(orders): Alpaca bracket orders, trailing stops, short selling"
```

---

### Task 3: Execution Engine — Short Evaluation + Order Type Selection

**Files:**
- Modify: `services/execution_engine.py`

- [ ] **Step 1: Read current execution_engine.py**

Read `/mnt/archie_brain/market-watch/services/execution_engine.py`.

- [ ] **Step 2: Add order type selection logic**

At the end of the `evaluate()` function, just before the final return (where the approved order dict is built), add order type selection:

```python
    # Select order type
    from services import risk_config as rc
    if rc.BRACKET_ORDERS_ENABLED:
        order_type = "bracket"
    else:
        order_type = "market"

    # Use trailing stop for moderate volatility (ATR between 2-4%)
    if atr_pct and 2.0 <= atr_pct <= 4.0:
        order_type = "trailing_stop"
        trail_percent = rc.DEFAULT_TRAIL_PERCENT
    else:
        trail_percent = None
```

Update the returned order dict to include:
```python
    "order_type": order_type,
    "trail_percent": trail_percent,
    "direction": "long",
```

- [ ] **Step 3: Add evaluate_short() function**

Add a new function after `evaluate()`:

```python
def evaluate_short(analysis, portfolio_state):
    """Evaluate a short selling opportunity.

    Same risk gates as long, plus short-specific limits.
    Only called when recommendation is 'sell' and no existing position.
    """
    if not rc.SHORTS_ENABLED:
        return _reject("Short selling disabled", [])

    gates_log = []
    ticker = analysis.get("ticker", "")

    def gate(name, passed, value, detail=""):
        gates_log.append({"gate": name, "passed": passed, "value": value, "detail": detail})
        return passed

    # Gate S1: Shield approval
    risk_approved = analysis.get("risk_approved", False)
    if not gate("shield_approval", bool(risk_approved), risk_approved):
        return _reject("Failed: Shield did not approve short", gates_log)

    # Gate S2: Oracle confidence
    confidence = analysis.get("oracle_confidence") or analysis.get("confidence", 0)
    if not gate("oracle_confidence", confidence >= rc.MIN_ORACLE_CONFIDENCE, confidence):
        return _reject(f"Failed: oracle_confidence {confidence} < {rc.MIN_ORACLE_CONFIDENCE}", gates_log)

    # Gate S3: Max short positions
    conn = get_db()
    try:
        short_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM open_positions WHERE status = 'open' AND direction = 'short'"
        ).fetchone()
        count = short_count["cnt"] if short_count else 0
    finally:
        conn.close()
    if not gate("max_short_positions", count < rc.MAX_SHORT_POSITIONS, count,
                f"limit={rc.MAX_SHORT_POSITIONS}"):
        return _reject(f"Failed: {count} shorts >= max {rc.MAX_SHORT_POSITIONS}", gates_log)

    # Gate S4: Short position size
    portfolio_value = portfolio_state.get("portfolio_value", 100000)
    max_short_value = portfolio_value * (rc.SHORT_POSITION_PCT / 100)
    quote = get_quote(ticker)
    current_price = quote.get("price", 0)
    if current_price <= 0:
        return _reject(f"Failed: cannot get price for {ticker}", gates_log)

    order_value = min(portfolio_value / (rc.MAX_POSITIONS * 2), max_short_value)
    quantity = int(order_value / current_price)
    if quantity <= 0:
        return _reject(f"Failed: short quantity is 0", gates_log)
    gate("short_position_size", True, order_value, f"limit={max_short_value:.0f}")

    # Gate S5: Duplicate check
    conn = get_db()
    try:
        existing = conn.execute(
            "SELECT id FROM open_positions WHERE ticker = ? AND status = 'open'", (ticker,)
        ).fetchone()
    finally:
        conn.close()
    if not gate("duplicate_ticker", existing is None, ticker):
        return _reject(f"Failed: already holding {ticker}", gates_log)

    # Gate S6: Daily loss limit (shared with longs)
    daily_pnl_pct = portfolio_state.get("daily_pnl_pct", 0)
    if not gate("daily_loss_limit", daily_pnl_pct > -rc.MAX_DAILY_LOSS_PCT, daily_pnl_pct):
        return _reject(f"Failed: daily P&L {daily_pnl_pct}% exceeds limit", gates_log)

    stop_loss = analysis.get("stop_loss") or (current_price * 1.05)  # 5% above for shorts
    target_price = analysis.get("target_price") or (current_price * 0.90)  # 10% below for shorts

    return {
        "approved": True,
        "reason": "All short gates passed",
        "gates_log": gates_log,
        "order": {
            "ticker": ticker,
            "action": "sell",
            "quantity": quantity,
            "price": current_price,
            "stop_loss": round(stop_loss, 2),
            "target_price": round(target_price, 2),
            "max_hold_days": rc.DEFAULT_HOLD_DAYS,
            "sector": analysis.get("sector", "unknown"),
            "thesis_id": analysis.get("analysis_id"),
            "direction": "short",
            "order_type": "bracket" if rc.BRACKET_ORDERS_ENABLED else "market",
            "trail_percent": None,
        },
    }
```

- [ ] **Step 4: Verify syntax**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "import ast; ast.parse(open('services/execution_engine.py').read()); print('Syntax OK')"
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/services/execution_engine.py
git commit -m "feat(orders): short evaluation + order type selection in execution engine"
```

---

### Task 4: Position Manager — Direction-Aware Exits

**Files:**
- Modify: `services/position_manager.py`

- [ ] **Step 1: Read current position_manager.py**

Read `/mnt/archie_brain/market-watch/services/position_manager.py`.

- [ ] **Step 2: Update check_price_exits for short positions**

In the `check_price_exits()` function, find the exit trigger logic and make it direction-aware:

Replace the stop-loss/target check with:

```python
            direction = pos["direction"] if "direction" in pos.keys() else "long"

            if direction == "long":
                # Long exits: stop when price drops, target when price rises
                if current_price <= pos["stop_loss"]:
                    exit_reason = "stopped"
                elif current_price >= pos["target_price"]:
                    exit_reason = "target_hit"
            else:
                # Short exits: stop when price rises, target when price drops
                if current_price >= pos["stop_loss"]:
                    exit_reason = "stopped"
                elif current_price <= pos["target_price"]:
                    exit_reason = "target_hit"
```

- [ ] **Step 3: Update _close_position for short P&L**

In `_close_position()`, make P&L direction-aware:

Replace:
```python
    pnl = (sell_price - entry_price) * quantity
    pnl_pct = ((sell_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
```

With:
```python
    direction = pos["direction"] if "direction" in pos.keys() else "long"
    if direction == "short":
        pnl = (entry_price - sell_price) * quantity  # Short profits when price drops
        pnl_pct = ((entry_price - sell_price) / entry_price * 100) if entry_price > 0 else 0.0
    else:
        pnl = (sell_price - entry_price) * quantity
        pnl_pct = ((sell_price - entry_price) / entry_price * 100) if entry_price > 0 else 0.0
```

Also update the sell order — for short positions, closing means buying back:
```python
    if direction == "short":
        close_side = "buy"  # Buy to cover
    else:
        close_side = "sell"
```

And use `close_side` in the `place_order()` call.

- [ ] **Step 4: Update open_position to store direction and order_type**

In the `open_position()` function, update the INSERT to include the new columns:

```python
        cur = conn.execute(
            """INSERT INTO open_positions
               (ticker, quantity, entry_price, stop_loss, target_price, max_hold_days,
                sector, thesis_id, alpaca_order_id, direction, order_type, trail_percent)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                order["ticker"],
                order["quantity"],
                order["price"],
                order["stop_loss"],
                order["target_price"],
                order.get("max_hold_days", rc.DEFAULT_HOLD_DAYS),
                order.get("sector"),
                order.get("thesis_id"),
                alpaca_order_id,
                order.get("direction", "long"),
                order.get("order_type", "market"),
                order.get("trail_percent"),
            ),
        )
```

- [ ] **Step 5: Verify syntax**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "import ast; ast.parse(open('services/position_manager.py').read()); print('Syntax OK')"
```

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/services/position_manager.py
git commit -m "feat(orders): direction-aware exits, short P&L, bracket/trailing in position manager"
```

---

### Task 5: Wire Short Selling into Run-Cycle + Docker Config

**Files:**
- Modify: `routes/trading.py`
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Update run-cycle to evaluate shorts**

In the `run_cycle()` function in `routes/trading.py`, find the section that processes recommendations. After the existing "buy" evaluation block, add short evaluation:

```python
            if result.get("recommendation") == "sell":
                # Evaluate as potential short entry
                from services.execution_engine import evaluate_short
                short_decision = evaluate_short(analysis, portfolio_state)
                if short_decision["approved"]:
                    if rc.DRY_RUN:
                        logger.info("[DRY RUN] Would short %d %s at %.2f",
                                    short_decision["order"]["quantity"],
                                    short_decision["order"]["ticker"],
                                    short_decision["order"]["price"])
                        trades_executed += 1
                    else:
                        order = short_decision["order"]
                        from services.alpaca_client import place_short_order
                        alpaca_result = place_short_order(
                            order["ticker"], order["quantity"],
                            order_type=order.get("order_type", "market"),
                            take_profit=order.get("target_price"),
                            stop_loss=order.get("stop_loss"),
                        )
                        if alpaca_result.get("success"):
                            order["gates_log"] = short_decision["gates_log"]
                            open_position(order, alpaca_result.get("order_id"))
                            trades_executed += 1
                        else:
                            errors += 1
                    portfolio_state = get_portfolio_state()
                continue
```

- [ ] **Step 2: Also update the buy block to use bracket/trailing orders**

In the existing buy execution block, replace the `place_order()` call with order-type-aware execution:

```python
                        from services.alpaca_client import place_bracket_order, place_trailing_stop
                        order = decision["order"]
                        otype = order.get("order_type", "market")
                        if otype == "bracket":
                            alpaca_result = place_bracket_order(
                                order["ticker"], order["quantity"],
                                take_profit=order.get("target_price"),
                                stop_loss=order.get("stop_loss"),
                            )
                        elif otype == "trailing_stop" and order.get("trail_percent"):
                            alpaca_result = place_trailing_stop(
                                order["ticker"], order["quantity"],
                                trail_percent=order["trail_percent"],
                            )
                        else:
                            alpaca_result = place_order(order["ticker"], order["quantity"], "buy")
```

- [ ] **Step 3: Add env vars to docker-compose.yml**

Add to environment section:

```yaml
      # Advanced Orders
      - MW_SHORTS_ENABLED=${MW_SHORTS_ENABLED:-false}
      - MW_MAX_SHORT_POSITIONS=${MW_MAX_SHORT_POSITIONS:-2}
      - MW_SHORT_POSITION_PCT=${MW_SHORT_POSITION_PCT:-5.0}
      - MW_DEFAULT_TRAIL_PERCENT=${MW_DEFAULT_TRAIL_PERCENT:-3.0}
      - MW_BRACKET_ORDERS_ENABLED=${MW_BRACKET_ORDERS_ENABLED:-true}
```

- [ ] **Step 4: Add to .env.example**

```bash

# Advanced Orders
MW_SHORTS_ENABLED=false
MW_MAX_SHORT_POSITIONS=2
MW_SHORT_POSITION_PCT=5.0
MW_DEFAULT_TRAIL_PERCENT=3.0
MW_BRACKET_ORDERS_ENABLED=true
```

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain
git add market-watch/routes/trading.py market-watch/docker-compose.yml market-watch/.env.example
git commit -m "feat(orders): short selling in run-cycle, bracket/trailing order routing, config"
```

---

### Task 6: Rebuild + Test + VPS Deploy

- [ ] **Step 1: Run migration on existing DB**

```bash
docker exec kytran_market_api python3 -c "
from db import get_db
conn = get_db()
try:
    conn.execute('ALTER TABLE open_positions ADD COLUMN direction TEXT DEFAULT \"long\"')
except: pass
try:
    conn.execute('ALTER TABLE open_positions ADD COLUMN order_type TEXT DEFAULT \"market\"')
except: pass
try:
    conn.execute('ALTER TABLE open_positions ADD COLUMN trail_percent REAL')
except: pass
conn.commit()
conn.close()
print('Migration OK')
"
```

- [ ] **Step 2: Rebuild + restart**

```bash
cd /mnt/archie_brain/market-watch
docker compose build --no-cache && docker compose up -d
```

- [ ] **Step 3: Test**

```bash
docker exec kytran_market_api python3 -c "
from app import create_app
import json
app = create_app()
with app.test_client() as c:
    r = c.post('/api/trading/run-cycle', json={'source':'test','force':True})
    d = json.loads(r.data)
    print(f'Cycle: {r.status_code} analyzed={d.get(\"tickers_analyzed\")} executed={d.get(\"trades_executed\")}')
"
```

- [ ] **Step 4: Deploy to VPS**

```bash
sshpass -p 'ArchieOutpost2026' rsync -az --exclude='.env' --exclude='market.db' --exclude='__pycache__' --exclude='.git' /mnt/archie_brain/market-watch/ kytran@76.13.107.109:/opt/kytran-market-watch/
sshpass -p 'ArchieOutpost2026' ssh kytran@76.13.107.109 "cd /opt/kytran-market-watch && docker compose build --no-cache && docker compose up -d"
```

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | Schema migration + config vars | migrations/, risk_config.py | 1 |
| 2 | Alpaca bracket/trailing/short | services/alpaca_client.py | 1 |
| 3 | Short evaluation + order type selection | services/execution_engine.py | 1 |
| 4 | Direction-aware position manager | services/position_manager.py | 1 |
| 5 | Run-cycle wiring + Docker config | routes/trading.py, docker-compose.yml | 1 |
| 6 | Rebuild + test + VPS deploy | Migration + Docker | 0 |

**Total: 6 tasks, ~5 commits, 1 new file, 6 modified files**

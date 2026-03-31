# Market Watch — Phase B1: Admin Trading Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full Trading Operations console to the Market Watch dashboard settings area with mode toggles, risk config editing, position management, and cycle control — all admin-only.

**Architecture:** New `trading_config_service.py` handles DB-backed config CRUD. Modified `risk_config.py` loads DB overrides on boot and exposes a `reload()` function. New admin endpoints in `routes/trading.py`. Frontend adds a settings panel visible only to admins.

**Tech Stack:** Flask 3.1, SQLite, vanilla HTML/JS (existing SPA)

**Spec:** `docs/superpowers/specs/2026-03-31-market-watch-phase-b1-admin-controls-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `services/trading_config_service.py` | DB-backed config CRUD, load/save/reset, validation |
| Modify | `services/risk_config.py` | Add `reload()`, `get_all()`, `update_from_db()` — load DB overrides on import |
| Modify | `routes/trading.py` | Add 9 admin endpoints (config, toggles, close, pause, cycle-status) |
| Modify | `schema.sql` | Add `trading_config` table |
| Modify | `static/index.html` | Add Trading Ops panel in settings area |

---

### Task 1: Schema — Add trading_config Table

**Files:**
- Modify: `schema.sql`

- [ ] **Step 1: Append trading_config table to schema.sql**

Append to the end of `/mnt/archie_brain/market-watch/schema.sql`:

```sql
-- Trading configuration (single row, DB overrides env var defaults)
CREATE TABLE IF NOT EXISTS trading_config (
    id INTEGER PRIMARY KEY,
    config JSON NOT NULL DEFAULT '{}',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO trading_config (id, config) VALUES (1, '{}');
```

- [ ] **Step 2: Verify schema**

```bash
cd /mnt/archie_brain/market-watch
rm -f /tmp/test_schema.db
sqlite3 /tmp/test_schema.db < schema.sql
sqlite3 /tmp/test_schema.db "SELECT config FROM trading_config WHERE id = 1"
```

Expected: `{}`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add schema.sql
git commit -m "feat(admin): add trading_config table for DB-backed risk overrides"
```

---

### Task 2: Trading Config Service — DB CRUD + Validation

**Files:**
- Create: `services/trading_config_service.py`

- [ ] **Step 1: Create trading_config_service.py**

Create `/mnt/archie_brain/market-watch/services/trading_config_service.py`:

```python
"""Trading config service — DB-backed config CRUD with validation."""

import json
import logging

from db import get_db

logger = logging.getLogger(__name__)

# Validation rules: field -> (type, min, max)
VALIDATION_RULES = {
    "min_oracle_confidence": (float, 0.0, 1.0),
    "max_daily_loss_pct": (float, 0.5, 20.0),
    "max_drawdown_pct": (float, 1.0, 50.0),
    "max_positions": (int, 1, 20),
    "max_position_pct": (float, 1.0, 50.0),
    "max_sector_positions": (int, 1, 10),
    "volatility_atr_limit": (float, 1.0, 20.0),
    "cooloff_loss_pct": (float, 0.5, 10.0),
    "default_hold_days": (int, 1, 30),
}

TOGGLE_FIELDS = {"dry_run", "trading_enabled", "live_trading", "paused"}


def load_config():
    """Load config from DB. Returns dict (empty = use env defaults)."""
    conn = get_db()
    try:
        row = conn.execute("SELECT config FROM trading_config WHERE id = 1").fetchone()
        if row and row["config"]:
            return json.loads(row["config"]) if isinstance(row["config"], str) else row["config"]
        return {}
    except Exception as e:
        logger.warning("Failed to load trading config: %s", e)
        return {}
    finally:
        conn.close()


def save_config(config):
    """Save config to DB."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE trading_config SET config = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (json.dumps(config),),
        )
        conn.commit()
    finally:
        conn.close()


def update_risk_gates(updates):
    """Validate and merge risk gate updates into config.

    Args:
        updates: dict of field_name -> value

    Returns:
        (success: bool, errors: list[str])
    """
    errors = []
    validated = {}

    for field, value in updates.items():
        if field not in VALIDATION_RULES:
            errors.append(f"Unknown field: {field}")
            continue

        expected_type, min_val, max_val = VALIDATION_RULES[field]
        try:
            cast_value = expected_type(value)
        except (ValueError, TypeError):
            errors.append(f"{field}: must be {expected_type.__name__}")
            continue

        if cast_value < min_val or cast_value > max_val:
            errors.append(f"{field}: must be between {min_val} and {max_val}")
            continue

        validated[field] = cast_value

    if errors:
        return False, errors

    config = load_config()
    risk_gates = config.get("risk_gates", {})
    risk_gates.update(validated)
    config["risk_gates"] = risk_gates
    save_config(config)

    return True, []


def set_toggle(field, value):
    """Set a boolean toggle field.

    Args:
        field: one of dry_run, trading_enabled, live_trading, paused
        value: bool

    Returns:
        (success: bool, error: str or None)
    """
    if field not in TOGGLE_FIELDS:
        return False, f"Unknown toggle: {field}"

    config = load_config()
    config[field] = bool(value)
    save_config(config)
    return True, None


def get_toggle(field, default=None):
    """Get a toggle value from DB config."""
    config = load_config()
    return config.get(field, default)


def reset_config():
    """Clear all DB overrides — reverts to env var defaults."""
    save_config({})


def get_full_config():
    """Return merged config: env defaults + DB overrides."""
    from services import risk_config as rc

    db_config = load_config()
    risk_gates = db_config.get("risk_gates", {})

    return {
        "toggles": {
            "dry_run": db_config.get("dry_run", rc.DRY_RUN),
            "trading_enabled": db_config.get("trading_enabled", rc.TRADING_ENABLED),
            "live_trading": db_config.get("live_trading", rc.LIVE_TRADING),
            "paused": db_config.get("paused", False),
        },
        "risk_gates": {
            "min_oracle_confidence": risk_gates.get("min_oracle_confidence", rc.MIN_ORACLE_CONFIDENCE),
            "max_daily_loss_pct": risk_gates.get("max_daily_loss_pct", rc.MAX_DAILY_LOSS_PCT),
            "max_drawdown_pct": risk_gates.get("max_drawdown_pct", rc.MAX_DRAWDOWN_PCT),
            "max_positions": risk_gates.get("max_positions", rc.MAX_POSITIONS),
            "max_position_pct": risk_gates.get("max_position_pct", rc.MAX_POSITION_PCT),
            "max_sector_positions": risk_gates.get("max_sector_positions", rc.MAX_SECTOR_POSITIONS),
            "volatility_atr_limit": risk_gates.get("volatility_atr_limit", rc.VOLATILITY_ATR_LIMIT),
            "cooloff_loss_pct": risk_gates.get("cooloff_loss_pct", rc.COOLOFF_LOSS_PCT),
            "default_hold_days": risk_gates.get("default_hold_days", rc.DEFAULT_HOLD_DAYS),
        },
        "validation": {k: {"type": v[0].__name__, "min": v[1], "max": v[2]} for k, v in VALIDATION_RULES.items()},
    }
```

- [ ] **Step 2: Verify import**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.trading_config_service import load_config, save_config, get_full_config, update_risk_gates, set_toggle, reset_config; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add services/trading_config_service.py
git commit -m "feat(admin): trading config service — DB CRUD, validation, merge with env defaults"
```

---

### Task 3: Update risk_config.py — DB Override + Reload

**Files:**
- Modify: `services/risk_config.py`

- [ ] **Step 1: Read current risk_config.py**

Read `/mnt/archie_brain/market-watch/services/risk_config.py`.

- [ ] **Step 2: Add reload() and update_from_db() functions**

Append to the end of `/mnt/archie_brain/market-watch/services/risk_config.py`:

```python


def reload():
    """Reload config from DB overrides. Call after saving config changes."""
    global MIN_ORACLE_CONFIDENCE, MAX_DAILY_LOSS_PCT, MAX_DRAWDOWN_PCT
    global MAX_POSITIONS, MAX_POSITION_PCT, MAX_SECTOR_POSITIONS
    global VOLATILITY_ATR_LIMIT, COOLOFF_LOSS_PCT, DEFAULT_HOLD_DAYS
    global CYCLE_DEDUP_MINUTES, DRY_RUN, TRADING_ENABLED, LIVE_TRADING

    try:
        from services.trading_config_service import load_config
        config = load_config()
    except Exception:
        return  # DB not ready yet (first boot)

    # Toggles
    if "dry_run" in config:
        DRY_RUN = bool(config["dry_run"])
    if "trading_enabled" in config:
        TRADING_ENABLED = bool(config["trading_enabled"])
    if "live_trading" in config:
        LIVE_TRADING = bool(config["live_trading"])

    # Risk gates
    gates = config.get("risk_gates", {})
    if "min_oracle_confidence" in gates:
        MIN_ORACLE_CONFIDENCE = float(gates["min_oracle_confidence"])
    if "max_daily_loss_pct" in gates:
        MAX_DAILY_LOSS_PCT = float(gates["max_daily_loss_pct"])
    if "max_drawdown_pct" in gates:
        MAX_DRAWDOWN_PCT = float(gates["max_drawdown_pct"])
    if "max_positions" in gates:
        MAX_POSITIONS = int(gates["max_positions"])
    if "max_position_pct" in gates:
        MAX_POSITION_PCT = float(gates["max_position_pct"])
    if "max_sector_positions" in gates:
        MAX_SECTOR_POSITIONS = int(gates["max_sector_positions"])
    if "volatility_atr_limit" in gates:
        VOLATILITY_ATR_LIMIT = float(gates["volatility_atr_limit"])
    if "cooloff_loss_pct" in gates:
        COOLOFF_LOSS_PCT = float(gates["cooloff_loss_pct"])
    if "default_hold_days" in gates:
        DEFAULT_HOLD_DAYS = int(gates["default_hold_days"])


# Load DB overrides on import (if DB is available)
try:
    reload()
except Exception:
    pass  # DB not ready on first import
```

- [ ] **Step 3: Verify**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "from services.risk_config import reload, MAX_POSITIONS; print(f'MAX_POSITIONS={MAX_POSITIONS}'); reload(); print('reload OK')"
```

Expected: `MAX_POSITIONS=5` then `reload OK`

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add services/risk_config.py
git commit -m "feat(admin): risk_config reload() — loads DB overrides over env defaults"
```

---

### Task 4: Admin API Endpoints

**Files:**
- Modify: `routes/trading.py`

- [ ] **Step 1: Read current trading.py**

Read `/mnt/archie_brain/market-watch/routes/trading.py` to see all existing routes.

- [ ] **Step 2: Add admin endpoint imports and routes**

Add these imports near the top of `routes/trading.py` (after existing imports):

```python
from services.trading_config_service import (
    get_full_config, update_risk_gates, set_toggle, get_toggle, reset_config,
)
```

Then add these new routes. Replace the existing `toggle_live_trading` stub with the real implementation, and add the other endpoints:

```python
# --- Admin Trading Controls ---

@trading_bp.route("/api/trading/config")
@tier_required("ai")
@admin_required
def get_config():
    """Return current risk config + mode toggles + validation ranges."""
    return jsonify({"success": True, **get_full_config()})


@trading_bp.route("/api/trading/config", methods=["PUT"])
@tier_required("ai")
@admin_required
def update_config():
    """Update risk gate thresholds. Saves to DB, applies immediately."""
    data = request.get_json() or {}
    risk_gates = data.get("risk_gates", {})
    if not risk_gates:
        return jsonify({"success": False, "error": "No risk_gates provided"}), 400

    success, errors = update_risk_gates(risk_gates)
    if not success:
        return jsonify({"success": False, "errors": errors}), 400

    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "message": "Config updated", **get_full_config()})


@trading_bp.route("/api/trading/config/reset", methods=["POST"])
@tier_required("ai")
@admin_required
def reset_config_endpoint():
    """Reset all risk gates to env var defaults."""
    reset_config()
    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "message": "Config reset to defaults", **get_full_config()})


@trading_bp.route("/api/trading/toggle-dry-run", methods=["POST"])
@tier_required("ai")
@admin_required
def toggle_dry_run():
    """Toggle DRY_RUN mode."""
    data = request.get_json() or {}
    enabled = data.get("enabled", True)
    set_toggle("dry_run", enabled)
    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "dry_run": enabled})


@trading_bp.route("/api/trading/toggle-enabled", methods=["POST"])
@tier_required("ai")
@admin_required
def toggle_trading_enabled():
    """Toggle TRADING_ENABLED (kill switch)."""
    data = request.get_json() or {}
    enabled = data.get("enabled", True)
    set_toggle("trading_enabled", enabled)
    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "trading_enabled": enabled})


@trading_bp.route("/api/trading/pause-autonomy", methods=["POST"])
@tier_required("ai")
@admin_required
def pause_autonomy():
    """Pause/resume autonomous trading cycles."""
    data = request.get_json() or {}
    paused = data.get("paused", True)
    set_toggle("paused", paused)
    return jsonify({"success": True, "paused": paused})


@trading_bp.route("/api/trading/close-position/<int:position_id>", methods=["POST"])
@tier_required("ai")
@admin_required
def close_position(position_id):
    """Close a single open position at market price."""
    conn = get_db()
    try:
        pos = conn.execute(
            "SELECT * FROM open_positions WHERE id = ? AND status = 'open'", (position_id,)
        ).fetchone()
        if not pos:
            return jsonify({"success": False, "error": "Position not found or already closed"}), 404

        from services.market_data import get_quote
        from services.position_manager import _close_position

        quote = get_quote(pos["ticker"])
        current_price = quote.get("price", pos["entry_price"])
        result = _close_position(conn, pos, current_price, "closed")
        conn.commit()

        if result:
            return jsonify({"success": True, "closed": result})
        return jsonify({"success": False, "error": "Failed to close position"}), 500
    finally:
        conn.close()


@trading_bp.route("/api/trading/close-all", methods=["POST"])
@tier_required("ai")
@admin_required
def close_all_positions():
    """Emergency close all open positions."""
    conn = get_db()
    closed = []
    errors = []
    try:
        positions = conn.execute(
            "SELECT * FROM open_positions WHERE status = 'open'"
        ).fetchall()

        if not positions:
            return jsonify({"success": True, "message": "No open positions", "closed": []})

        from services.market_data import get_quote
        from services.position_manager import _close_position

        for pos in positions:
            quote = get_quote(pos["ticker"])
            current_price = quote.get("price", pos["entry_price"])
            result = _close_position(conn, pos, current_price, "closed")
            if result:
                closed.append(result)
            else:
                errors.append(pos["ticker"])

        conn.commit()
        return jsonify({
            "success": True,
            "closed": closed,
            "errors": errors,
            "total_closed": len(closed),
        })
    finally:
        conn.close()


@trading_bp.route("/api/trading/cycle-status")
@tier_required("ai")
@admin_required
def cycle_status():
    """Return last cycle results + paused state."""
    conn = get_db()
    try:
        last_cycle = conn.execute(
            "SELECT * FROM cycle_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        paused = get_toggle("paused", False)

        result = {
            "success": True,
            "paused": paused,
            "last_cycle": None,
        }
        if last_cycle:
            result["last_cycle"] = {
                "id": last_cycle["id"],
                "status": last_cycle["status"],
                "stocks_analyzed": last_cycle["stocks_analyzed"],
                "trades_made": last_cycle["trades_made"],
                "trades_skipped": last_cycle["trades_skipped"],
                "errors": last_cycle["errors"],
                "started_at": str(last_cycle["started_at"]) if last_cycle["started_at"] else None,
                "completed_at": str(last_cycle["completed_at"]) if last_cycle["completed_at"] else None,
            }
        return jsonify(result)
    finally:
        conn.close()
```

Also replace the existing `toggle_live_trading` stub with:

```python
@trading_bp.route("/api/trading/toggle-live", methods=["POST"])
@tier_required("ai")
@admin_required
def toggle_live_trading():
    """Toggle between paper and live Alpaca trading.
    Requires both admin role AND MW_LIVE_TRADING=true env var (double-lock).
    """
    import os
    data = request.get_json() or {}
    enabled = data.get("enabled", False)

    env_allows = os.environ.get("MW_LIVE_TRADING", "false").lower() in ("true", "1", "yes")
    if enabled and not env_allows:
        return jsonify({
            "success": False,
            "error": "Live trading blocked — MW_LIVE_TRADING env var is not set to true",
        }), 403

    set_toggle("live_trading", enabled)
    from services import risk_config as rc
    rc.reload()
    return jsonify({"success": True, "live_trading": enabled, "env_allows": env_allows})
```

- [ ] **Step 3: Update run-cycle to check paused flag**

Find the dedup check section in the `run_cycle()` function and add a paused check right after the kill switch check:

```python
    # Paused check
    if get_toggle("paused", False):
        return jsonify({"success": True, "skipped": True, "reason": "Trading is paused"})
```

Add this right after the `if not rc.TRADING_ENABLED:` block, before the dedup check.

Also add `get_toggle` to the import from `trading_config_service` at the top.

- [ ] **Step 4: Verify syntax**

```bash
cd /mnt/archie_brain/market-watch
python3 -c "import ast; ast.parse(open('routes/trading.py').read()); print('Syntax OK')"
```

Expected: `Syntax OK`

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add routes/trading.py
git commit -m "feat(admin): 9 admin endpoints — config CRUD, toggles, close positions, cycle status"
```

---

### Task 5: Frontend — Trading Ops Settings Panel

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: Read current index.html structure**

Read `/mnt/archie_brain/market-watch/static/index.html` to understand where the settings area is and the existing HTML structure.

- [ ] **Step 2: Add Trading Ops panel HTML**

Add this admin-only panel to the dashboard. Place it inside a section that's visible only to admins. Find the appropriate location in the HTML (after the main dashboard content, before the auth init script) and add:

```html
<!-- Admin Trading Operations Panel -->
<div id="trading-ops-panel" data-tier="admin" style="display:none; padding: 20px; margin-top: 20px;">
    <h2 style="font-family:'Orbitron',sans-serif; color:#fbbf24; margin-bottom:16px;">TRADING OPERATIONS</h2>

    <!-- Mode Controls -->
    <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:20px;">
        <div style="background:#111827; border:1px solid #1f2937; border-radius:8px; padding:16px;">
            <h3 style="color:#00e5ff; font-size:0.9rem; margin-bottom:12px;">MODE CONTROLS</h3>
            <div style="display:flex; flex-direction:column; gap:8px;">
                <label style="display:flex; justify-content:space-between; align-items:center; color:#e0e0e0;">
                    Dry Run <input type="checkbox" id="toggle-dry-run" onchange="toggleMode('dry-run', this.checked)">
                </label>
                <label style="display:flex; justify-content:space-between; align-items:center; color:#e0e0e0;">
                    Trading Enabled <input type="checkbox" id="toggle-enabled" onchange="toggleMode('enabled', this.checked)">
                </label>
                <label style="display:flex; justify-content:space-between; align-items:center; color:#e0e0e0;">
                    Live Trading <input type="checkbox" id="toggle-live" onchange="toggleMode('live', this.checked)">
                </label>
                <label style="display:flex; justify-content:space-between; align-items:center; color:#e0e0e0;">
                    Paused <input type="checkbox" id="toggle-paused" onchange="toggleMode('paused', this.checked)">
                </label>
            </div>
        </div>
        <div style="background:#111827; border:1px solid #1f2937; border-radius:8px; padding:16px;">
            <h3 style="color:#00e5ff; font-size:0.9rem; margin-bottom:12px;">ACTIONS</h3>
            <div style="display:flex; flex-direction:column; gap:8px;">
                <button onclick="runCycleNow()" style="background:#10b981; color:#000; border:none; padding:8px 16px; border-radius:4px; cursor:pointer; font-weight:700;">RUN CYCLE NOW</button>
                <button onclick="closeAllPositions()" style="background:#ef4444; color:#fff; border:none; padding:8px 16px; border-radius:4px; cursor:pointer; font-weight:700;">CLOSE ALL POSITIONS</button>
            </div>
        </div>
    </div>

    <!-- Portfolio Snapshot -->
    <div id="admin-portfolio-snapshot" style="background:#111827; border:1px solid #1f2937; border-radius:8px; padding:16px; margin-bottom:20px;">
        <h3 style="color:#00e5ff; font-size:0.9rem; margin-bottom:12px;">PORTFOLIO SNAPSHOT</h3>
        <div id="portfolio-stats" style="display:grid; grid-template-columns:repeat(3, 1fr); gap:8px; color:#e0e0e0; font-size:0.85rem;"></div>
    </div>

    <!-- Open Positions -->
    <div style="background:#111827; border:1px solid #1f2937; border-radius:8px; padding:16px; margin-bottom:20px;">
        <h3 style="color:#00e5ff; font-size:0.9rem; margin-bottom:12px;">OPEN POSITIONS</h3>
        <div id="admin-positions-list" style="color:#e0e0e0; font-size:0.85rem;"></div>
    </div>

    <!-- Risk Gate Config -->
    <div style="background:#111827; border:1px solid #1f2937; border-radius:8px; padding:16px; margin-bottom:20px;">
        <h3 style="color:#00e5ff; font-size:0.9rem; margin-bottom:12px;">RISK GATE CONFIG</h3>
        <div id="risk-gate-fields" style="display:grid; grid-template-columns:1fr 1fr; gap:8px;"></div>
        <div style="margin-top:12px; display:flex; gap:8px;">
            <button onclick="saveRiskConfig()" style="background:#00e5ff; color:#000; border:none; padding:8px 16px; border-radius:4px; cursor:pointer; font-weight:700;">SAVE</button>
            <button onclick="resetRiskConfig()" style="background:#6b7280; color:#fff; border:none; padding:8px 16px; border-radius:4px; cursor:pointer; font-weight:700;">RESET TO DEFAULTS</button>
        </div>
    </div>

    <!-- Last Cycle Results -->
    <div style="background:#111827; border:1px solid #1f2937; border-radius:8px; padding:16px;">
        <h3 style="color:#00e5ff; font-size:0.9rem; margin-bottom:12px;">LAST CYCLE RESULTS</h3>
        <div id="last-cycle-info" style="color:#e0e0e0; font-size:0.85rem;"></div>
    </div>
</div>
```

- [ ] **Step 3: Add admin JavaScript**

Add this script block before the closing `</body>` tag (after the auth init script):

```html
<script>
// --- Admin Trading Ops ---
async function loadAdminPanel() {
    if (!window.MW_IS_ADMIN) return;

    // Load config
    try {
        var resp = await fetch('/api/trading/config');
        var data = await resp.json();
        if (!data.success) return;

        // Toggles
        document.getElementById('toggle-dry-run').checked = data.toggles.dry_run;
        document.getElementById('toggle-enabled').checked = data.toggles.trading_enabled;
        document.getElementById('toggle-live').checked = data.toggles.live_trading;
        document.getElementById('toggle-paused').checked = data.toggles.paused;

        // Risk gate fields
        var fieldsDiv = document.getElementById('risk-gate-fields');
        fieldsDiv.textContent = '';
        var labels = {
            min_oracle_confidence: 'Oracle Confidence',
            max_daily_loss_pct: 'Max Daily Loss %',
            max_drawdown_pct: 'Max Drawdown %',
            max_positions: 'Max Positions',
            max_position_pct: 'Position Size %',
            max_sector_positions: 'Sector Limit',
            volatility_atr_limit: 'Volatility ATR %',
            cooloff_loss_pct: 'Cool-off Loss %',
            default_hold_days: 'Hold Days',
        };
        Object.keys(data.risk_gates).forEach(function(key) {
            var label = document.createElement('label');
            label.style.cssText = 'display:flex; justify-content:space-between; align-items:center; color:#e0e0e0;';
            label.textContent = labels[key] || key;
            var input = document.createElement('input');
            input.type = 'number';
            input.id = 'rg-' + key;
            input.value = data.risk_gates[key];
            input.step = data.validation[key] && data.validation[key].type === 'float' ? '0.01' : '1';
            input.min = data.validation[key] ? data.validation[key].min : '';
            input.max = data.validation[key] ? data.validation[key].max : '';
            input.style.cssText = 'width:80px; background:#0a0a1a; color:#e0e0e0; border:1px solid #374151; border-radius:4px; padding:4px 8px; text-align:right;';
            label.appendChild(input);
            fieldsDiv.appendChild(label);
        });
    } catch (e) { console.error('Failed to load admin config:', e); }

    // Load portfolio snapshot
    try {
        var resp2 = await fetch('/api/trading/positions');
        var pos = await resp2.json();
        var statsDiv = document.getElementById('portfolio-stats');
        statsDiv.textContent = 'Loading...';
        // Fetch full state via public track record for stats
        var resp3 = await fetch('/api/public/track-record');
        var tr = await resp3.json();
        if (tr.success) {
            var t = tr.track_record;
            statsDiv.textContent = '';
            var items = [
                'Cash: $' + (t.cash_balance || 0).toLocaleString(),
                'P&L: $' + (t.total_pnl || 0).toFixed(2),
                'Win Rate: ' + (t.win_rate_pct || 0) + '%',
                'Open: ' + (t.open_positions || 0) + ' positions',
                'Trades: ' + (t.total_trades || 0),
                'Return: ' + (t.total_return_pct || 0) + '%',
            ];
            items.forEach(function(text) {
                var span = document.createElement('span');
                span.textContent = text;
                statsDiv.appendChild(span);
            });
        }

        // Positions list
        var listDiv = document.getElementById('admin-positions-list');
        listDiv.textContent = '';
        if (pos.success && pos.positions && pos.positions.length > 0) {
            pos.positions.forEach(function(p) {
                var row = document.createElement('div');
                row.style.cssText = 'display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid #1f2937;';
                var info = document.createElement('span');
                info.textContent = p.ticker + '  ' + p.quantity + ' @ $' + p.entry_price.toFixed(2) + ' → $' + p.current_price.toFixed(2) + '  P&L: $' + p.pnl.toFixed(2);
                var btn = document.createElement('button');
                btn.textContent = 'CLOSE';
                btn.style.cssText = 'background:#ef4444; color:#fff; border:none; padding:4px 12px; border-radius:3px; cursor:pointer; font-size:0.75rem;';
                btn.onclick = function() { closePosition(p.ticker, p.position_id || 0); };
                row.appendChild(info);
                row.appendChild(btn);
                listDiv.appendChild(row);
            });
        } else {
            listDiv.textContent = 'No open positions';
        }
    } catch (e) { console.error('Failed to load positions:', e); }

    // Load cycle status
    try {
        var resp4 = await fetch('/api/trading/cycle-status');
        var cs = await resp4.json();
        var cycleDiv = document.getElementById('last-cycle-info');
        if (cs.success && cs.last_cycle) {
            var c = cs.last_cycle;
            cycleDiv.textContent = 'Analyzed: ' + c.stocks_analyzed + ' | Traded: ' + c.trades_made + ' | Skipped: ' + c.trades_skipped + ' | Errors: ' + c.errors + ' | Status: ' + c.status + (cs.paused ? ' | PAUSED' : '');
        } else {
            cycleDiv.textContent = 'No cycles yet' + (cs.paused ? ' | PAUSED' : '');
        }
    } catch (e) { console.error('Failed to load cycle status:', e); }
}

async function toggleMode(mode, enabled) {
    var endpoints = {
        'dry-run': '/api/trading/toggle-dry-run',
        'enabled': '/api/trading/toggle-enabled',
        'live': '/api/trading/toggle-live',
        'paused': '/api/trading/pause-autonomy',
    };
    var body = mode === 'paused' ? {paused: enabled} : {enabled: enabled};
    if (mode === 'dry-run' && !enabled && !confirm('Disable dry run? Trades will execute on paper account.')) {
        document.getElementById('toggle-dry-run').checked = true;
        return;
    }
    if (mode === 'live' && enabled && !confirm('WARNING: Enable LIVE trading? This uses real money.')) {
        document.getElementById('toggle-live').checked = false;
        return;
    }
    var resp = await fetch(endpoints[mode], {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
    var data = await resp.json();
    if (!data.success) alert(data.error || 'Toggle failed');
}

async function runCycleNow() {
    if (!confirm('Run a trading cycle now?')) return;
    var resp = await fetch('/api/trading/run-cycle', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({source:'admin_manual', force:true})});
    var data = await resp.json();
    if (data.success) {
        alert('Cycle complete: ' + data.tickers_analyzed + ' analyzed, ' + data.trades_executed + ' executed');
        loadAdminPanel();
    } else {
        alert('Cycle failed: ' + (data.error || 'unknown'));
    }
}

async function closePosition(ticker, posId) {
    if (!confirm('Close ' + ticker + ' position?')) return;
    var resp = await fetch('/api/trading/close-position/' + posId, {method:'POST'});
    var data = await resp.json();
    if (data.success) loadAdminPanel();
    else alert('Failed: ' + (data.error || 'unknown'));
}

async function closeAllPositions() {
    if (!confirm('EMERGENCY: Close ALL open positions?')) return;
    var resp = await fetch('/api/trading/close-all', {method:'POST'});
    var data = await resp.json();
    if (data.success) {
        alert('Closed ' + data.total_closed + ' positions');
        loadAdminPanel();
    } else {
        alert('Failed: ' + (data.error || 'unknown'));
    }
}

async function saveRiskConfig() {
    var gates = {};
    document.querySelectorAll('[id^="rg-"]').forEach(function(el) {
        var key = el.id.replace('rg-', '');
        gates[key] = parseFloat(el.value);
    });
    var resp = await fetch('/api/trading/config', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({risk_gates: gates})});
    var data = await resp.json();
    if (data.success) alert('Config saved');
    else alert('Errors: ' + (data.errors || []).join(', '));
}

async function resetRiskConfig() {
    if (!confirm('Reset all risk gates to env var defaults?')) return;
    var resp = await fetch('/api/trading/config/reset', {method:'POST'});
    var data = await resp.json();
    if (data.success) { alert('Reset to defaults'); loadAdminPanel(); }
}

// Load admin panel after auth resolves
var _origInitAuth = window._origInitAuth;
setTimeout(function() { if (window.MW_IS_ADMIN) loadAdminPanel(); }, 1000);
</script>
```

- [ ] **Step 4: Verify HTML parses**

Open the file and ensure no unclosed tags or syntax errors in the script block.

- [ ] **Step 5: Commit**

```bash
cd /mnt/archie_brain/market-watch
git add static/index.html
git commit -m "feat(admin): Trading Ops settings panel — toggles, risk config, positions, cycle status"
```

---

### Task 6: Rebuild + Integration Test

- [ ] **Step 1: Rebuild Docker**

```bash
cd /mnt/archie_brain/market-watch
docker compose build --no-cache
docker compose up -d
```

- [ ] **Step 2: Verify container starts**

```bash
sleep 5 && docker logs kytran_market_api 2>&1 | tail -3
```

- [ ] **Step 3: Test admin endpoints**

```bash
docker exec kytran_market_api python3 -c "
from app import create_app
import json
app = create_app()
with app.test_client() as c:
    # Config endpoint (no auth = 401)
    r1 = c.get('/api/trading/config')
    print(f'Config (no auth): {r1.status_code}')

    # Cycle status (no auth = 401)
    r2 = c.get('/api/trading/cycle-status')
    print(f'Cycle status (no auth): {r2.status_code}')

    # Close all (no auth = 401)
    r3 = c.post('/api/trading/close-all')
    print(f'Close all (no auth): {r3.status_code}')
"
```

Expected: All 401.

- [ ] **Step 4: Browser test**

Open `http://192.168.1.200:8101/dashboard`, log in as admin, verify:
- Trading Ops panel visible at bottom of settings
- Toggles load correctly
- Risk gate fields show current values
- Portfolio snapshot shows data
- Last cycle results display

- [ ] **Step 5: Deploy to VPS**

```bash
rsync -az --exclude='.env' --exclude='market.db' --exclude='__pycache__' --exclude='.git' /mnt/archie_brain/market-watch/ kytran@76.13.107.109:/opt/kytran-market-watch/
ssh kytran@76.13.107.109 "cd /opt/kytran-market-watch && docker compose build --no-cache && docker compose up -d"
```

---

## Summary

| Task | What | Files | Commits |
|------|------|-------|---------|
| 1 | trading_config table | schema.sql | 1 |
| 2 | Config service (CRUD + validation) | services/trading_config_service.py | 1 |
| 3 | risk_config reload from DB | services/risk_config.py | 1 |
| 4 | 9 admin API endpoints | routes/trading.py | 1 |
| 5 | Frontend Trading Ops panel | static/index.html | 1 |
| 6 | Rebuild + test + VPS deploy | Docker + rsync | 0 |

**Total: 6 tasks, ~5 commits, 1 new file, 4 modified files**

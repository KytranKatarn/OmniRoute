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

"""Centralized risk configuration — all thresholds loaded from env vars."""

import os


def _float(key, default):
    return float(os.environ.get(key, default))


def _int(key, default):
    return int(os.environ.get(key, default))


def _bool(key, default):
    return os.environ.get(key, str(default)).lower() in ("true", "1", "yes")


# Risk gates
MIN_ORACLE_CONFIDENCE = _float("MW_MIN_ORACLE_CONFIDENCE", 0.65)
MAX_DAILY_LOSS_PCT = _float("MW_MAX_DAILY_LOSS_PCT", 3.0)
MAX_DRAWDOWN_PCT = _float("MW_MAX_DRAWDOWN_PCT", 5.0)
MAX_POSITIONS = _int("MW_MAX_POSITIONS", 5)
MAX_POSITION_PCT = _float("MW_MAX_POSITION_PCT", 10.0)
MAX_SECTOR_POSITIONS = _int("MW_MAX_SECTOR_POSITIONS", 2)
VOLATILITY_ATR_LIMIT = _float("MW_VOLATILITY_ATR_LIMIT", 5.0)
COOLOFF_LOSS_PCT = _float("MW_COOLOFF_LOSS_PCT", 2.0)

# Position management
DEFAULT_HOLD_DAYS = _int("MW_DEFAULT_HOLD_DAYS", 5)

# Cycle control
CYCLE_DEDUP_MINUTES = _int("MW_CYCLE_DEDUP_MINUTES", 15)

# Safety
DRY_RUN = _bool("MW_DRY_RUN", False)
TRADING_ENABLED = _bool("MW_TRADING_ENABLED", True)
LIVE_TRADING = _bool("MW_LIVE_TRADING", False)


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

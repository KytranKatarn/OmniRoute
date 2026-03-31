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

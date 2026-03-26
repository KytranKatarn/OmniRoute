import os
import pytest

from core.config import Config


def test_config_defaults():
    """Config uses sensible defaults when no env vars are set."""
    # Unset any test-overridden vars temporarily
    env_backup = {}
    keys_to_clear = [
        "KBS_DB_HOST", "KBS_DB_PORT", "KBS_DB_NAME", "KBS_DB_USER", "KBS_DB_PASSWORD",
        "KBS_REDIS_URL", "KBS_SECRET_KEY", "KBS_DOMAIN", "KBS_DEFAULT_TIER",
        "KBS_PORT", "KBS_DEBUG", "KBS_BRIDGE_URL", "KBS_BRIDGE_API_KEY",
        "KBS_MAIL_PROVIDER", "KBS_SMTP_HOST", "KBS_SMTP_PORT", "KBS_SMTP_USER",
        "KBS_SMTP_PASSWORD", "KBS_MAIL_FROM", "KBS_GOOGLE_CLIENT_ID",
        "KBS_GOOGLE_CLIENT_SECRET", "KBS_STRIPE_SECRET_KEY",
        "KBS_STRIPE_WEBHOOK_SECRET", "KBS_STRIPE_PUBLISHABLE_KEY",
    ]
    for k in keys_to_clear:
        env_backup[k] = os.environ.pop(k, None)

    try:
        cfg = Config()

        assert cfg.KBS_DB_HOST == "kbs-postgres"
        assert cfg.KBS_DB_PORT == 5432
        assert cfg.KBS_DB_NAME == "kbs"
        assert cfg.KBS_DB_USER == "kbs"
        assert cfg.KBS_DB_PASSWORD == ""
        assert cfg.KBS_REDIS_URL == "redis://kbs-redis:6379/0"
        assert cfg.KBS_SECRET_KEY == "dev-only-change-me"
        assert cfg.KBS_DOMAIN == "localhost"
        assert cfg.KBS_DEFAULT_TIER == "free"
        assert cfg.KBS_PORT == 8090
        assert cfg.KBS_DEBUG is False
        assert cfg.KBS_BRIDGE_URL == ""
        assert cfg.KBS_BRIDGE_API_KEY == ""
        assert cfg.KBS_MAIL_PROVIDER == "smtp"
        assert cfg.KBS_SMTP_PORT == 587
        assert cfg.KBS_MAIL_FROM == "noreply@kytranempowerment.com"
        assert cfg.KBS_GOOGLE_CLIENT_ID == ""
        assert cfg.KBS_STRIPE_SECRET_KEY == ""
    finally:
        # Restore env
        for k, v in env_backup.items():
            if v is not None:
                os.environ[k] = v


def test_config_loads_from_env(monkeypatch):
    """Config reads values from environment variables."""
    monkeypatch.setenv("KBS_DB_HOST", "my-db-host")
    monkeypatch.setenv("KBS_DB_PORT", "5433")
    monkeypatch.setenv("KBS_DB_NAME", "mydb")
    monkeypatch.setenv("KBS_DB_USER", "myuser")
    monkeypatch.setenv("KBS_DB_PASSWORD", "supersecret")
    monkeypatch.setenv("KBS_PORT", "9000")
    monkeypatch.setenv("KBS_DEBUG", "true")
    monkeypatch.setenv("KBS_DEFAULT_TIER", "enterprise")
    monkeypatch.setenv("KBS_DOMAIN", "example.com")
    monkeypatch.setenv("KBS_STRIPE_SECRET_KEY", "sk_test_abc123")

    cfg = Config()

    assert cfg.KBS_DB_HOST == "my-db-host"
    assert cfg.KBS_DB_PORT == 5433
    assert cfg.KBS_DB_NAME == "mydb"
    assert cfg.KBS_DB_USER == "myuser"
    assert cfg.KBS_DB_PASSWORD == "supersecret"
    assert cfg.KBS_PORT == 9000
    assert cfg.KBS_DEBUG is True
    assert cfg.KBS_DEFAULT_TIER == "enterprise"
    assert cfg.KBS_DOMAIN == "example.com"
    assert cfg.KBS_STRIPE_SECRET_KEY == "sk_test_abc123"


def test_config_debug_false_variants(monkeypatch):
    """KBS_DEBUG only becomes True for 'true' (case-insensitive)."""
    for falsy in ("false", "0", "no", "FALSE", ""):
        monkeypatch.setenv("KBS_DEBUG", falsy)
        cfg = Config()
        assert cfg.KBS_DEBUG is False, f"Expected False for KBS_DEBUG={falsy!r}"

    monkeypatch.setenv("KBS_DEBUG", "TRUE")
    cfg = Config()
    assert cfg.KBS_DEBUG is True

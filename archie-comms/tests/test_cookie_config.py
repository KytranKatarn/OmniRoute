"""Tests for the env-driven session-cookie config (mesh-only cockpit).

A .kytranempowerment.com-scoped Secure cookie can't bind to a raw-IP http host,
which broke the OAuth state/PKCE round-trip over mesh. The cookie domain/secure
flags are now env-overridable; default to host-only + non-Secure for mesh http.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _load(monkeypatch, **env):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    for k in ("COMMS_COOKIE_DOMAIN", "COMMS_COOKIE_SECURE"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("app_comms", None)  # re-import to re-read env at module load
    import app_comms

    return app_comms.app


class TestCookieConfig:
    def test_defaults_host_only_non_secure(self, monkeypatch):
        app = _load(monkeypatch)
        assert app.config["SESSION_COOKIE_DOMAIN"] is None
        assert app.config["SESSION_COOKIE_SECURE"] is False
        assert app.config["SESSION_COOKIE_NAME"] == "archie_comms_session"
        assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"

    def test_env_override_secure_domain(self, monkeypatch):
        app = _load(
            monkeypatch,
            COMMS_COOKIE_DOMAIN=".kytranempowerment.com",
            COMMS_COOKIE_SECURE="true",
        )
        assert app.config["SESSION_COOKIE_DOMAIN"] == ".kytranempowerment.com"
        assert app.config["SESSION_COOKIE_SECURE"] is True

    def test_empty_domain_coerced_to_none(self, monkeypatch):
        # An empty/whitespace env value must become None (host-only), not "".
        app = _load(monkeypatch, COMMS_COOKIE_DOMAIN="   ")
        assert app.config["SESSION_COOKIE_DOMAIN"] is None

    def test_secure_only_true_for_literal_true(self, monkeypatch):
        app = _load(monkeypatch, COMMS_COOKIE_SECURE="yes")
        assert app.config["SESSION_COOKIE_SECURE"] is False

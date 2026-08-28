"""Auth contract for the compliance rule-packs endpoint gate (Tier-0).

The endpoint exposes host remediation *fix command* strings, so it must not be
anonymous. It is reachable with the shared INTERNAL_API_KEY (KSO sync) or an
admin session. This pins the key check; the admin-session branch is exercised
by the live drive.
"""

import os
import sys

from flask import Flask

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.security_network.compliance_routes import _internal_key_ok  # noqa: E402

app = Flask(__name__)


def test_no_env_key_denies_even_with_header(monkeypatch):
    monkeypatch.delenv("INTERNAL_API_KEY", raising=False)
    with app.test_request_context(headers={"X-Internal-Key": "anything"}):
        assert _internal_key_ok() is False


def test_missing_header_denied(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "s3cret-key")
    with app.test_request_context():
        assert _internal_key_ok() is False


def test_wrong_key_denied(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "s3cret-key")
    with app.test_request_context(headers={"X-Internal-Key": "wrong"}):
        assert _internal_key_ok() is False


def test_correct_x_internal_key_allowed(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "s3cret-key")
    with app.test_request_context(headers={"X-Internal-Key": "s3cret-key"}):
        assert _internal_key_ok() is True


def test_correct_bearer_allowed(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "s3cret-key")
    with app.test_request_context(headers={"Authorization": "Bearer s3cret-key"}):
        assert _internal_key_ok() is True


def test_empty_bearer_denied(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "s3cret-key")
    with app.test_request_context(headers={"Authorization": "Bearer "}):
        assert _internal_key_ok() is False

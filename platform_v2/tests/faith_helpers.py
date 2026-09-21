"""Shared fixtures and helpers for the Faith module test files.

The Faith test suite is split across ``test_faith_routes.py`` and
``test_faith_care_routes.py`` to keep each file under the Code Health
LARGE_FILE (600-line) threshold. The pieces that must stay identical in
both — the minimal Flask client, the DHQ dispatcher stub, and the
``get_db_cursor`` mock of the right shape (#6015) — live here.

Import them into a test module with:

    from tests.faith_helpers import _login, _logout, _patched_db, faith_client
"""

from __future__ import annotations

import types
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from flask import Flask
from flask_login import LoginManager, UserMixin

from tests.modstub import stub_module_scoped


@pytest.fixture(autouse=True, scope="module")
def _stub_department_dispatcher():
    """Stub the DHQ dispatcher for this module (#272154).

    routes.py imports `dispatch` at module import time, and the real module
    pulls `from db import _get_db_password` from a module that is not
    importable under the coder-lane pytest invocation (--noconftest). Every
    LLM-facing test here mocks archie_bridge, so the stub is never invoked.
    """
    stub = types.ModuleType("tools.department_hq.services.department_dispatcher")
    stub.dispatch = lambda *args, **kwargs: {"success": False, "response": "(dispatcher stubbed)"}
    stub.__file__ = __file__
    stub.__package__ = "tools.department_hq.services"
    with stub_module_scoped("tools.department_hq.services.department_dispatcher", stub):
        yield stub


@contextmanager
def _patched_db():
    """Patch `get_db_cursor` with a mock of the RIGHT SHAPE (#6015).

    Production does `with get_db_cursor(commit=True) as (_conn, cur):` — the context
    manager yields a (connection, cursor) PAIR. A bare `patch("...get_db_cursor")` hands
    back a plain MagicMock whose `__enter__` yields an *empty iterator*, so that unpack
    raises `ValueError: not enough values to unpack (expected 2, got 0)` INSIDE the route.

    That surfaces as an HTTP 500 and reads exactly like a production defect — it was the
    only 500-family in the whole suite, and the reason #6015 existed. The code under test
    is correct; the mock was the wrong shape.
    """
    with patch("tools.faith.routes.get_db_cursor") as m:
        m.return_value.__enter__.return_value = (MagicMock(), MagicMock())
        yield m


@pytest.fixture(scope="module")
def faith_client():
    """Minimal Flask test client with only the faith blueprint mounted."""
    mini_app = Flask(__name__, template_folder="/app/templates")
    mini_app.config["SECRET_KEY"] = "test-secret"
    mini_app.config["TESTING"] = True
    mini_app.config["WTF_CSRF_ENABLED"] = False

    login_manager = LoginManager(mini_app)

    class _User(UserMixin):
        def __init__(self, uid):
            self.id = uid

    @login_manager.user_loader
    def load_user(uid):
        return _User(int(uid))

    from tools.faith import faith_bp

    mini_app.register_blueprint(faith_bp)

    return mini_app.test_client()


def _login(client):
    """Inject a Flask-Login session for user 1."""
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True


def _logout(client):
    """Clear Flask-Login session state for auth-gate assertions."""
    with client.session_transaction() as sess:
        sess.clear()
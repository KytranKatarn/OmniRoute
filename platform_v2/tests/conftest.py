"""
ARCHIE Platform Test Fixtures
"""

import importlib.util
import os
import sys
import pytest

# /app contains __init__.py making it a package, so `from app import app`
# resolves to the package init rather than app.py.  Load app.py directly
# via importlib so the Flask application object is always found correctly.
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

# Allow packages installed to /tmp/pip_pkgs (e.g. `responses` for mocked tests)
# when the container filesystem is read-only and pip cannot write to site-packages.
if "/tmp/pip_pkgs" not in sys.path and os.path.isdir("/tmp/pip_pkgs"):
    sys.path.insert(1, "/tmp/pip_pkgs")

# Override DB settings for testing before importing app
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "archie_test")
os.environ.setdefault("DB_USER", "archie")
os.environ.setdefault("DB_PASSWORD", "test_password")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")


def _load_flask_app():
    """Load app.py directly to avoid __init__.py package shadowing."""
    spec = importlib.util.spec_from_file_location("flask_app_module", "/app/app.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.app


@pytest.fixture
def app():
    """Create Flask application for testing."""
    flask_app = _load_flask_app()
    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    yield flask_app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()

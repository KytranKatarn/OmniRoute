"""
ARCHIE Platform Test Fixtures
"""

import os
import pytest

# Override DB settings for testing before importing app
os.environ.setdefault("DB_HOST", "localhost")
os.environ.setdefault("DB_NAME", "archie_test")
os.environ.setdefault("DB_USER", "archie")
os.environ.setdefault("DB_PASSWORD", "test_password")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("FLASK_SECRET_KEY", "test-secret-key")


@pytest.fixture
def app():
    """Create Flask application for testing."""
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    flask_app.config["WTF_CSRF_ENABLED"] = False
    yield flask_app


@pytest.fixture
def client(app):
    """Create Flask test client."""
    return app.test_client()

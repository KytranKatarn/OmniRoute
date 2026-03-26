import os

import pytest

# Point tests at the ARCHIE dev database
os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))


@pytest.fixture(scope="session")
def app():
    """Create the Flask app for the test session."""
    from core.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application


@pytest.fixture()
def client(app):
    """Yield a test client for each test."""
    with app.test_client() as c:
        yield c

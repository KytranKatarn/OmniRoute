# tests/test_fleet_ota_file_serve.py
"""Tests for the OTA node file-serve endpoint."""
import json
import os
import sys

import pytest
from flask import Flask

# We test the route in isolation using a minimal Flask app
# rather than the full platform app, avoiding import complexity.


def _make_test_app():
    """Create a minimal Flask app with just the file-serve route registered."""
    # We need to import the route function directly and register it
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "platform_v2"))

    from tools.department_hq.fleet_ota_routes import register_ota_routes

    mini_app = Flask(__name__)
    mini_app.config["TESTING"] = True

    from flask import Blueprint

    bp = Blueprint("fleet", __name__)

    # No-op auth decorator for testing
    def no_auth(f):
        return f

    register_ota_routes(bp, no_auth)
    mini_app.register_blueprint(bp)
    return mini_app


@pytest.fixture
def client():
    app = _make_test_app()
    with app.test_client() as c:
        yield c


def test_serve_node_api_py_returns_source(client):
    resp = client.get("/api/nodes/ota/node_api.py")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "raw" in data
    assert "skills_push" in data["raw"]   # our new endpoint must be present
    assert data["filename"] == "node_api.py"


def test_serve_node_sync_py_returns_source(client):
    resp = client.get("/api/nodes/ota/node_sync.py")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "raw" in data
    assert "poll_syncs" in data["raw"]
    assert data["filename"] == "node_sync.py"


def test_serve_blocks_unlisted_file(client):
    resp = client.get("/api/nodes/ota/malicious.py")
    assert resp.status_code == 403
    data = resp.get_json()
    assert data["success"] is False


def test_serve_blocks_path_traversal(client):
    # With plain <filename> converter, Flask returns 404 for paths with slashes.
    # The allowlist catches everything else.
    resp = client.get("/api/nodes/ota/node_api.py")   # valid — 200
    assert resp.status_code == 200
    resp2 = client.get("/api/nodes/ota/evil.py")       # not in allowlist — 403
    assert resp2.status_code == 403

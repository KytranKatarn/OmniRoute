"""Static pins for the branded 404 (design wtf-404). Source-level on purpose:
renders need a live DB-backed app, and these assert the two things that must
not regress — the handler exists, and it never returns HTML to /api/ clients."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "consumer"


def test_template_extends_shell_and_is_noindex():
    t = (ROOT / "templates" / "404.html").read_text()
    assert '{% extends "base.html" %}' in t
    assert 'name="robots" content="noindex"' in t


def test_handler_registered_and_returns_404_status():
    s = (ROOT / "app.py").read_text()
    assert "@app.errorhandler(404)" in s
    assert 'render_template("404.html"), 404' in s


def test_api_paths_keep_default_response():
    s = (ROOT / "app.py").read_text()
    assert 'request.path.startswith("/api/")' in s

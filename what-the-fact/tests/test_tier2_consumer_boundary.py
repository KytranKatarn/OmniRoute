"""Legacy upgrade delegates work; exercise route code without a database."""
import ast
import io
import json
from pathlib import Path
import urllib.error
import urllib.request

from flask import Flask, Response
import pytest

SOURCE = Path(__file__).resolve().parents[1] / "consumer" / "routes.py"


def route_namespace():
    tree = ast.parse(SOURCE.read_text())
    functions = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {
            "upgrade_tier2", "proxy_article_analyze", "_proxy_tech"
        }:
            node.decorator_list = []
            functions.append(node)
    import os
    ns = dict(Response=Response, urllib=urllib, json=json, os=os,
              is_subscriber=lambda: True, _api_rate_check=lambda: None)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), ns)
    return ns


def test_subscriber_required_before_proxy():
    ns = route_namespace()
    ns["is_subscriber"] = lambda: False
    ns["proxy_article_analyze"] = lambda _: pytest.fail("unauthorized dispatch")
    with Flask(__name__).test_request_context():
        response, status = ns["upgrade_tier2"](12)
        assert status == 402
        assert response.json["error"] == "subscriber_required"


def test_rate_limit_prevents_dispatch():
    ns = route_namespace()
    ns["_api_rate_check"] = lambda: ("limited", 429)
    ns["_proxy_tech"] = lambda *a, **k: pytest.fail("rate-limited dispatch")
    assert ns["upgrade_tier2"](12) == ("limited", 429)


def test_upgrade_delegates_without_consumer_db():
    ns = route_namespace()
    calls = []
    ns["_proxy_tech"] = lambda *a, **k: calls.append((a, k)) or "queued"
    assert ns["upgrade_tier2"](12) == "queued"
    assert calls == [(("/api/v1/articles/12/analyze",),
                      dict(method="POST", body=b"{}", timeout=10))]


@pytest.mark.parametrize("status", [404, 429, 503])
def test_proxy_preserves_tech_errors(monkeypatch, status):
    ns = route_namespace()
    def reject(req, **kwargs):
        raise urllib.error.HTTPError(req.full_url, status, "failure",
                                     {"Retry-After": "30"}, io.BytesIO(b'{"ok":false}'))
    monkeypatch.setattr(urllib.request, "urlopen", reject)
    response = ns["_proxy_tech"]("/api/v1/articles/12/analyze", method="POST")
    assert response.status_code == status
    assert response.headers["Retry-After"] == "30"
    assert response.json == {"ok": False}

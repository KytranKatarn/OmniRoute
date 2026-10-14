"""Session signing behavior without application database initialization."""

import pytest
from itsdangerous import BadSignature, URLSafeSerializer
from shared.session_security import session_signing_key


def test_configured_key_remains_stable():
    env = {"FLASK_SECRET_KEY": "test-configured-key"}
    first = URLSafeSerializer(session_signing_key(env))
    second = URLSafeSerializer(session_signing_key(env))
    assert second.loads(first.dumps({"user_id": 123})) == {"user_id": 123}


@pytest.mark.parametrize("env", [{}, {"FLASK_SECRET_KEY": ""}, {"WTF_ALLOW_INSECURE_SECRET": "true"}])
def test_missing_key_still_fails_closed_without_explicit_dev_opt_in(env):
    with pytest.raises(RuntimeError, match="FLASK_SECRET_KEY"):
        session_signing_key(env)


def test_explicit_development_keys_are_random_and_cannot_sign_each_others_sessions():
    env = {"WTF_ALLOW_INSECURE_SECRET": "1"}
    first_key = session_signing_key(env)
    second_key = session_signing_key(env)
    assert first_key != second_key and len(first_key) >= 64
    signed = URLSafeSerializer(first_key).dumps({"user_id": 123})
    with pytest.raises(BadSignature):
        URLSafeSerializer(second_key).loads(signed)


def test_configured_key_wins_even_in_explicit_dev_mode():
    assert session_signing_key({"WTF_ALLOW_INSECURE_SECRET": "1", "FLASK_SECRET_KEY": "test-key"}) == "test-key"


@pytest.mark.parametrize("service", ["consumer", "tech"])
def test_actual_factory_key_initialization_keeps_production_fail_closed(service, monkeypatch):
    import ast
    from pathlib import Path
    from flask import Flask
    from werkzeug.middleware.proxy_fix import ProxyFix

    # Execute the real startup statements through key assignment, stopping before
    # unrelated route registration and billing database initialization.
    source = Path(__file__).parents[1] / service / "app.py"
    tree = ast.parse(source.read_text())
    factory = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "create_app")
    index = next(
        i
        for i, n in enumerate(factory.body)
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == "secret_key" for t in n.targets)
    )
    factory.body = factory.body[: index + 1] + [ast.Return(value=ast.Name(id="app", ctx=ast.Load()))]
    module = ast.fix_missing_locations(ast.Module(body=[factory], type_ignores=[]))
    import os

    namespace = {
        "Flask": Flask,
        "ProxyFix": ProxyFix,
        "session_signing_key": session_signing_key,
        "__name__": __name__,
        "os": os,
    }
    exec(compile(module, str(source), "exec"), namespace)
    monkeypatch.delenv("FLASK_SECRET_KEY", raising=False)
    monkeypatch.delenv("WTF_ALLOW_INSECURE_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="FLASK_SECRET_KEY"):
        namespace["create_app"]()
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-factory-key")
    assert namespace["create_app"]().secret_key == "test-factory-key"

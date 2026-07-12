"""Public landing-page stats endpoint — GET /api/public/stats (no auth). Live agent + KB
counts from the shared DB so the marketing landing shows real numbers instead of '—'/stale
hardcodes. Fail-soft: nulls when the DB is unavailable."""
import contextlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _fresh_app(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    sys.modules.pop("app_comms", None)  # fresh import with the test SECRET_KEY
    import app_comms

    app_comms.app.config["TESTING"] = True
    return app_comms


def test_public_stats_returns_live_counts(monkeypatch):
    app_comms = _fresh_app(monkeypatch)

    from datetime import datetime, timedelta, timezone

    class _Cur:
        def execute(self, sql):
            self._q = "tg" if "telegram_message_log" in sql else ("kb" if "knowledge_base" in sql else "agents")

        def fetchone(self):
            if self._q == "kb":
                return {"total": 36592, "emb": 36400}
            if self._q == "tg":
                return {"last": datetime.now(timezone.utc) - timedelta(hours=1)}
            return {"n": 54, "depts": 17}

    @contextlib.contextmanager
    def _fake_cursor(*a, **k):
        yield (None, _Cur())

    monkeypatch.setattr("database.get_db_cursor", _fake_cursor)
    with app_comms.app.test_client() as c:
        d = c.get("/api/public/stats").get_json()
    assert d["agents_active"] == 54 and d["departments"] == 17
    assert d["kb_entries"] == 36592 and d["kb_coverage_pct"] == 99  # round(36400/36592*100)
    assert d["telegram_recency"] == "today"  # coarse recency only — no precise timestamp/content


def test_public_stats_failsoft(monkeypatch):
    app_comms = _fresh_app(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("database.get_db_cursor", _boom)
    with app_comms.app.test_client() as c:
        r = c.get("/api/public/stats")
        d = r.get_json()
    assert r.status_code == 200 and d["agents_active"] is None and d["kb_entries"] is None

"""#5297 — the F.O.R.G.E. fallback-rate metric WITH a consumer.

#5287 proved the freeform fallback is where false verdicts come from, and that the
pipeline already KNEW (quality=blocking_issue_without_evidence sat on review rows for
weeks, consumed by nothing). This metric exists only together with its consumer: a
send_system alert when the trailing fallback rate crosses a platform_settings
threshold — a mostly-degraded review pipeline means every verdict is worth less than
it appears.

Measurement caveat pinned here on purpose: pr_reviews stores the LATEST review per
PR, so the stats are a current-verdict inventory, not per-run telemetry.
"""

import os
import sys
from contextlib import contextmanager

_TREE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _TREE_ROOT not in sys.path:
    sys.path.insert(0, _TREE_ROOT)

import tools.repair_bay.services.pr_review_service as prs  # noqa: E402


JSON_META = "SUMMARY\nok\nVERDICT: APPROVE\n[review-meta] structured=json model=default confidence=1.0"
GATED_META = "SUMMARY\nok\nVERDICT: APPROVE\n[review-meta] structured=freeform-gated quality=freeform_fallback"
LEGACY_TEXT = "SUMMARY\nok\nVERDICT: APPROVE"


class _StubDB:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    @contextmanager
    def __call__(self, *a, **k):
        db = self

        class _Cur:
            def execute(self, sql, params=None):
                db.executed.append((sql, params))

            def fetchall(self):
                return db.rows

            def fetchone(self):
                return db.rows[0] if db.rows else None

        yield None, _Cur()


class TestClassification:
    def test_paths_classified_by_meta_marker(self):
        assert prs._classify_review_path(JSON_META) == "structured_json"
        assert prs._classify_review_path(GATED_META) == "freeform_gated"
        assert prs._classify_review_path(LEGACY_TEXT) == "legacy"
        assert prs._classify_review_path(None) == "legacy"
        assert prs._classify_review_path("") == "legacy"


class TestStats:
    def test_counts_and_fallback_rate(self, monkeypatch):
        rows = [{"ai_summary": JSON_META}] * 3 + [{"ai_summary": GATED_META}] + [{"ai_summary": LEGACY_TEXT}]
        monkeypatch.setattr(prs, "get_db_cursor", _StubDB(rows))
        s = prs.review_path_stats(days=7)
        assert s["total"] == 5
        assert s["structured_json"] == 3
        assert s["freeform_gated"] == 1
        assert s["legacy"] == 1
        assert s["fallback_rate"] == 0.4

    def test_empty_window_yields_none_rate(self, monkeypatch):
        monkeypatch.setattr(prs, "get_db_cursor", _StubDB([]))
        s = prs.review_path_stats(days=7)
        assert s["total"] == 0
        assert s["fallback_rate"] is None


class TestConsumer:
    def _arm(self, monkeypatch, stats, threshold=0.5):
        monkeypatch.setattr(prs, "review_path_stats", lambda days=7: dict(stats))
        monkeypatch.setattr(prs, "_fallback_rate_warn_threshold", lambda: threshold)
        calls = []
        monkeypatch.setattr(prs, "_send_system_alert", lambda title, message: calls.append((title, message)))
        return calls

    def test_alerts_above_threshold(self, monkeypatch):
        calls = self._arm(monkeypatch, {"total": 10, "fallback_rate": 0.6, "structured_json": 4})
        out = prs.check_review_path_health()
        assert out["alerted"] is True
        assert len(calls) == 1
        title, message = calls[0]
        assert title == "F.O.R.G.E. reviews degrading to freeform fallback"
        assert "60%" in message

    def test_silent_below_threshold(self, monkeypatch):
        calls = self._arm(monkeypatch, {"total": 10, "fallback_rate": 0.2, "structured_json": 8})
        out = prs.check_review_path_health()
        assert out["alerted"] is False
        assert calls == []

    def test_small_sample_never_alerts(self, monkeypatch):
        """3 reviews all-freeform is noise, not a trend — the min_total guard holds."""
        calls = self._arm(monkeypatch, {"total": 3, "fallback_rate": 1.0, "structured_json": 0})
        out = prs.check_review_path_health(min_total=5)
        assert out["alerted"] is False
        assert calls == []

    def test_none_rate_never_alerts(self, monkeypatch):
        calls = self._arm(monkeypatch, {"total": 0, "fallback_rate": None, "structured_json": 0})
        out = prs.check_review_path_health()
        assert out["alerted"] is False
        assert calls == []

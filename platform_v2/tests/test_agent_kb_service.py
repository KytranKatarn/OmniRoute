"""Unit tests for services.agent_kb_service (#3534 Phase 3).

Covers the pure guards (PII) and the auto-review verdict routing without a live
DB. The full write→quarantine→approve path is covered by live verification.
"""

import os
import sys
from contextlib import contextmanager

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import services.agent_kb_service as akb


def test_detect_pii():
    assert akb._detect_pii("email me at a@b.com") == "email"
    assert akb._detect_pii("call 416-555-1234 today") == "phone"
    assert akb._detect_pii("ssn 123-45-6789") == "ssn"
    assert akb._detect_pii("passport AB1234567") == "passport"
    assert akb._detect_pii("just a normal sentence about fleet nodes and routing") is None


def test_propose_rejects_short_content():
    out = akb.propose_agent_memory(1, "D.A.R.W.I.N.", "too short")
    assert out["ok"] is False
    assert "short" in out["reason"]


def test_propose_rejects_pii(monkeypatch):
    # PII is checked before any DB write; stub the best-effort audit.
    monkeypatch.setattr(akb, "_audit", lambda *a, **k: None)
    out = akb.propose_agent_memory(
        1, "D.A.R.W.I.N.", "Please contact me at secret@example.com about the fleet routing details right now"
    )
    assert out["ok"] is False
    assert "PII" in out["reason"]


def test_auto_review_routes_verdicts(monkeypatch):
    rows = [{"id": 1, "title": "t1", "content": "c1"}, {"id": 2, "title": "t2", "content": "c2"}]

    @contextmanager
    def fake_cursor(commit=False):
        class _Cur:
            def execute(self, *a, **k):
                pass

            def fetchall(self):
                return rows

        yield (None, _Cur())

    monkeypatch.setattr(akb, "get_db_cursor", fake_cursor)
    monkeypatch.setattr(
        akb,
        "_review_one",
        lambda row: {"decision": "approve" if row["id"] == 1 else "reject", "quality_score": 0.8, "reason": "x"},
    )
    recorded = []
    monkeypatch.setattr(akb, "_set_status", lambda kid, status, qs, reason: recorded.append((kid, status)))

    res = akb.auto_review_pending_writes(limit=10)
    assert res["reviewed"] == 2
    assert res["promoted"] == 1
    assert res["rejected"] == 1
    assert (1, "approved") in recorded
    assert (2, "rejected") in recorded


def test_auto_review_counts_dispatch_errors(monkeypatch):
    rows = [{"id": 9, "title": "t", "content": "c"}]

    @contextmanager
    def fake_cursor(commit=False):
        class _Cur:
            def execute(self, *a, **k):
                pass

            def fetchall(self):
                return rows

        yield (None, _Cur())

    monkeypatch.setattr(akb, "get_db_cursor", fake_cursor)
    monkeypatch.setattr(akb, "_review_one", lambda row: None)  # dispatch failed / non-dict
    monkeypatch.setattr(akb, "_set_status", lambda *a, **k: None)

    res = akb.auto_review_pending_writes(limit=10)
    assert res["errors"] == 1
    assert res["promoted"] == 0
    assert res["rejected"] == 0

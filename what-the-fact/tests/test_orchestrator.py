"""Tests for orchestrator.py priority scoring."""
import pytest
from unittest.mock import MagicMock, patch


def test_score_priority_breaking_keyword():
    from ingest.orchestrator import score_priority
    assert score_priority("BREAKING: fire downtown", 0.1, 0) == 1


def test_score_priority_high_bias():
    from ingest.orchestrator import score_priority
    assert score_priority("Normal headline", 0.7, 0) == 2


def test_score_priority_cross_source():
    from ingest.orchestrator import score_priority
    assert score_priority("Normal headline", 0.1, 3) == 3


def test_score_priority_all_signals():
    from ingest.orchestrator import score_priority
    assert score_priority("BREAKING: crisis hits", 0.8, 4) == 6


def test_score_priority_no_signals():
    from ingest.orchestrator import score_priority
    assert score_priority("Weather today", 0.1, 0) == 0


def test_pick_priority_articles_empty():
    from ingest.orchestrator import pick_priority_articles
    engine = MagicMock()
    result = pick_priority_articles(engine, "wtf", [])
    assert result == []


def test_pick_priority_articles_invalid_schema():
    from ingest.orchestrator import pick_priority_articles
    engine = MagicMock()
    with pytest.raises(ValueError, match="disallowed schema"):
        pick_priority_articles(engine, "malicious_schema", [1, 2, 3])

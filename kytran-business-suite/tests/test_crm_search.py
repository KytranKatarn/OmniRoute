"""Tests for CRM search condition builder."""

from plugins.kbs_crm.search import build_search_conditions


def test_build_search_query_with_term():
    conditions, params = build_search_conditions(search="jane")
    assert len(conditions) > 0
    assert "%jane%" in params


def test_build_search_query_with_segment():
    conditions, params = build_search_conditions(segment_id=5)
    assert len(conditions) > 0
    assert 5 in params


def test_build_search_query_with_both():
    conditions, params = build_search_conditions(search="jane", segment_id=5)
    assert len(conditions) == 2


def test_build_search_query_empty():
    conditions, params = build_search_conditions()
    assert conditions == []
    assert params == []

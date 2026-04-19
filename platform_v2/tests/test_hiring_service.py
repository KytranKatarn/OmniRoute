"""Unit tests for hiring_service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_shortlist_returns_top_3_decommissioned_by_proficiency():
    from services import hiring_service

    fake_rows = [
        {
            "agent_id": 1,
            "display_name": "A",
            "proficiency_level": 5,
            "department": "X",
            "decommissioned_at": None,
            "primary_model": "m",
        },
        {
            "agent_id": 2,
            "display_name": "B",
            "proficiency_level": 4,
            "department": "Y",
            "decommissioned_at": None,
            "primary_model": "m",
        },
        {
            "agent_id": 3,
            "display_name": "C",
            "proficiency_level": 3,
            "department": "Z",
            "decommissioned_at": None,
            "primary_model": "m",
        },
    ]
    with patch("services.hiring_service._fetch_shortlist_rows", return_value=fake_rows):
        out = hiring_service.get_shortlist("translate", limit=3)
    assert len(out) == 3
    assert [e["proficiency_level"] for e in out] == [5, 4, 3]


def test_shortlist_limits_result_size():
    from services import hiring_service

    fake_rows = [
        {
            "agent_id": i,
            "display_name": f"A{i}",
            "proficiency_level": 5,
            "department": "X",
            "decommissioned_at": None,
            "primary_model": "m",
        }
        for i in range(10)
    ]
    with patch("services.hiring_service._fetch_shortlist_rows", return_value=fake_rows):
        out = hiring_service.get_shortlist("translate", limit=3)
    assert len(out) == 3


def test_shortlist_empty_when_no_decommissioned_matches():
    from services import hiring_service

    with patch("services.hiring_service._fetch_shortlist_rows", return_value=[]):
        out = hiring_service.get_shortlist("nonexistent_skill", limit=3)
    assert out == []


def test_propose_for_gap_inserts_pending_row():
    from services import hiring_service

    cur = MagicMock()
    cur.fetchone.side_effect = [None, {"id": 17}]  # no dedup hit, then INSERT returning id
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    shortlist = [
        {
            "agent_id": 1,
            "display_name": "A",
            "proficiency_level": 5,
            "department": "X",
            "decommissioned_at": None,
            "primary_model": "m",
        }
    ]
    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur), __exit__=lambda self, *a: False),
    ):
        out = hiring_service.propose_for_gap(
            capability="translate",
            gap_reason="only 2 active",
            gap_alert_id=None,
            shortlist=shortlist,
            narrative="why these 3",
            proposed_by_agent_id=145,
        )
    assert out == 17


def test_propose_for_gap_dedups_on_pending_capability():
    from services import hiring_service

    cur = MagicMock()
    cur.fetchone.return_value = {"id": 99}  # existing pending row
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur), __exit__=lambda self, *a: False),
    ):
        out = hiring_service.propose_for_gap(
            capability="translate",
            gap_reason="only 2 active",
            gap_alert_id=None,
            shortlist=[{"agent_id": 1}],
            narrative=None,
            proposed_by_agent_id=145,
        )
    assert out is None


def test_approve_candidate_precheck_model_missing_blocks_transition():
    """Pre-check fails → row stays pending, 'model_missing' persisted."""
    from services import hiring_service

    row = {
        "id": 17,
        "status": "pending",
        "shortlist": [{"agent_id": 7, "display_name": "Oracle", "primary_model": "mistral:7b"}],
    }
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur), __exit__=lambda self, *a: False),
    ), patch(
        "services.hiring_service._verify_model_available",
        return_value=(False, "Model 'mistral:7b' not present"),
    ), patch(
        "services.hiring_service._transition_agent",
    ) as mock_transition:
        result = hiring_service.approve_candidate(hire_id=17, chosen_agent_id=7, decided_by_user_id=1, notes="")
    assert result["ok"] is False
    assert result["reason"] == "model_missing"
    mock_transition.assert_not_called()


def test_approve_candidate_invalid_chosen_agent_rejected():
    from services import hiring_service

    row = {
        "id": 17,
        "status": "pending",
        "shortlist": [{"agent_id": 7, "display_name": "Oracle"}],
    }
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur), __exit__=lambda self, *a: False),
    ):
        result = hiring_service.approve_candidate(hire_id=17, chosen_agent_id=999, decided_by_user_id=1, notes="")
    assert result["ok"] is False
    assert result["reason"] == "candidate_not_in_shortlist"


def test_approve_candidate_already_decided_rejected():
    from services import hiring_service

    row = {"id": 17, "status": "approved", "shortlist": []}
    cur = MagicMock()
    cur.fetchone.return_value = row
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur), __exit__=lambda self, *a: False),
    ):
        result = hiring_service.approve_candidate(hire_id=17, chosen_agent_id=7, decided_by_user_id=1, notes="")
    assert result["ok"] is False
    assert result["reason"] == "already_decided"


def test_reject_candidate_flips_status_and_writes_notes():
    from services import hiring_service

    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": 17, "status": "pending"},  # initial SELECT
        {"id": 17},  # UPDATE ... RETURNING
    ]
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(
            __enter__=lambda self: (conn, cur),
            __exit__=lambda self, *a: False,
        ),
    ), patch("services.hiring_service._audit") as mock_audit:
        result = hiring_service.reject_candidate(hire_id=17, decided_by_user_id=1, notes="not a fit right now")
    assert result["ok"] is True
    mock_audit.assert_called_once()


def test_expire_stale_updates_old_pending_rows():
    from services import hiring_service

    cur = MagicMock()
    cur.rowcount = 4
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(
            __enter__=lambda self: (conn, cur),
            __exit__=lambda self, *a: False,
        ),
    ):
        out = hiring_service.expire_stale_proposals(max_age_days=14)
    assert out == 4


def test_propose_for_gap_serializes_datetime_in_shortlist():
    """Regression test: shortlist contains decommissioned_at datetimes;
    json.dumps must not crash on them. Bug surfaced during PR1 smoke."""
    from services import hiring_service
    import datetime as _dt

    cur = MagicMock()
    cur.fetchone.side_effect = [None, {"id": 99}]
    cur.__enter__ = lambda self: self
    cur.__exit__ = lambda self, *a: False
    conn = MagicMock()
    conn.cursor.return_value = cur

    shortlist_with_dt = [
        {
            "agent_id": 7,
            "display_name": "Oracle",
            "proficiency_level": 4,
            "department": "Medical",
            "decommissioned_at": _dt.datetime(2026, 1, 1, 12, 0, 0),
            "primary_model": "mistral:7b",
        }
    ]

    with patch(
        "services.hiring_service.get_db_cursor",
        return_value=MagicMock(__enter__=lambda self: (conn, cur), __exit__=lambda self, *a: False),
    ):
        out = hiring_service.propose_for_gap(
            capability="translate",
            gap_reason="only 2 active",
            shortlist=shortlist_with_dt,
            narrative=None,
            proposed_by_agent_id=145,
        )
    assert out == 99

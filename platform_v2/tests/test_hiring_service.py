"""Unit tests for hiring_service."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

# `from services import agent_service` (deferred inside _create_new_hire) can pull
# ai_bridge.agent_loop; stub it so the import resolves cleanly under pytest.
# Mirrors the shim in test_hiring_acronym_persist.py.
_stub_pkg = sys.modules.setdefault("ai_bridge", types.ModuleType("ai_bridge"))
_stub_agent_loop = types.ModuleType("ai_bridge.agent_loop")
_stub_agent_loop.request_approval = MagicMock(return_value=None)
# PEP 562 catch-all — see #5665. This stub replaces ai_bridge.agent_loop for the WHOLE
# session, so any name a later-collected module needs must resolve or collection aborts
# for all 3,332 tests. test_media_drain_welfare_gate does `al.AgentLoop` and died here,
# even though the real ai_bridge/agent_loop.py DOES define it (line 523).
# The explicit request_approval mock above still wins.
_stub_agent_loop.__getattr__ = lambda _n: MagicMock()
sys.modules["ai_bridge.agent_loop"] = _stub_agent_loop
_stub_pkg.agent_loop = _stub_agent_loop


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
        "capability": "translate",
        "gap_reason": "only 2 active",
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
        "capability": "translate",
        "gap_reason": "only 2 active",
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

    row = {"id": 17, "status": "approved", "shortlist": [], "capability": "translate", "gap_reason": "n/a"}
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


def test_create_new_hire_persists_complete_identity(monkeypatch):
    """Approving a net-new hire with no rich fields still yields a complete agent."""
    from services import hiring_service, agent_service, agent_identity_builder

    calls = {}
    monkeypatch.setattr(
        agent_identity_builder,
        "build_identity",
        lambda cap, **k: {
            "name": k.get("existing_name") or "N.O.V.A.",
            "expansion": "New Operations Virtual Agent",
            "title": "Ops Analyst",
            "bio": "A backstory.",
            "personality": "calm",
            "system_prompt": "S" * 500,
            "portrait_prompt": "sci-fi portrait",
            "source": "fallback",
        },
    )
    monkeypatch.setattr(agent_service, "create_agent", lambda **kw: (calls.update(create=kw) or 9991))
    monkeypatch.setattr(agent_service, "add_skill", lambda *a, **k: None)
    monkeypatch.setattr(agent_service, "init_budget", lambda *a, **k: None)
    monkeypatch.setattr(agent_service, "log_creation_event", lambda **k: None)
    monkeypatch.setattr(agent_service, "update_agent", lambda aid, **f: calls.setdefault("update", f))
    monkeypatch.setattr(
        agent_service, "add_portrait", lambda aid, prompt, **k: calls.setdefault("portrait", (aid, prompt))
    )
    monkeypatch.setattr(hiring_service, "_verify_model_available", lambda m: (True, "ok"))
    monkeypatch.setattr(hiring_service, "_audit", lambda *a, **k: None)

    # cur stub (reuses the MagicMock + fetchone.side_effect pattern already
    # established in test_hiring_acronym_persist.py): the name-collision SELECT
    # returns None (no clash), the approve UPDATE ... RETURNING returns a row.
    cur = MagicMock()
    cur.fetchone.side_effect = [None, {"id": 1}]

    res = hiring_service._create_new_hire(
        cur,
        hire_id=1,
        capability="analyze",
        gap_reason="gap",
        new_agent={"name": "N.O.V.A.", "model": "qwen2.5:7b"},
        decided_by_user_id=4,
        notes="",
    )
    assert res["ok"]
    assert len(calls["create"]["system_prompt"]) >= 400  # rich prompt, not the 90-char stub
    assert calls["update"]["bio"] and calls["update"]["personality_prompt"]
    assert calls["update"]["acronym_expansion"] and calls["update"]["title"]
    assert calls["update"]["portrait_prompt"]
    assert calls["portrait"][0] == 9991  # portrait queued for the new agent


def test_create_new_hire_rebuilds_identity_when_prompt_names_stale_agent(monkeypatch):
    """Regression: Generate built a rich identity for name Q.U.A.R.T.Z., then the
    admin hand-edited the name field to N.O.V.A. before Approve. The stale rich
    fields (system_prompt/bio/personality/portrait_prompt) still describe
    Q.U.A.R.T.Z. The consistency guard must detect the mismatch and discard the
    stale fields so build_identity() rebuilds a fresh identity for the real
    name — the persisted agent must never have a name/system_prompt mismatch."""
    from services import hiring_service, agent_service, agent_identity_builder

    _BUILT_IDENTITY = {
        "name": "N.O.V.A.",
        "expansion": "New Operations Virtual Agent",
        "title": "Ops Analyst",
        "bio": "Freshly built bio for N.O.V.A.",
        "personality": "calm",
        "system_prompt": "You are N.O.V.A. (New Operations Virtual Agent), " + "n" * 400,
        "portrait_prompt": "sci-fi portrait of N.O.V.A.",
        "source": "fallback",
    }
    calls = {}
    monkeypatch.setattr(
        agent_identity_builder,
        "build_identity",
        lambda cap, **k: dict(_BUILT_IDENTITY, name=k.get("existing_name") or _BUILT_IDENTITY["name"]),
    )
    monkeypatch.setattr(agent_service, "create_agent", lambda **kw: (calls.update(create=kw) or 9992))
    monkeypatch.setattr(agent_service, "add_skill", lambda *a, **k: None)
    monkeypatch.setattr(agent_service, "init_budget", lambda *a, **k: None)
    monkeypatch.setattr(agent_service, "log_creation_event", lambda **k: None)
    monkeypatch.setattr(agent_service, "update_agent", lambda aid, **f: calls.setdefault("update", f))
    monkeypatch.setattr(
        agent_service, "add_portrait", lambda aid, prompt, **k: calls.setdefault("portrait", (aid, prompt))
    )
    monkeypatch.setattr(hiring_service, "_verify_model_available", lambda m: (True, "ok"))
    monkeypatch.setattr(hiring_service, "_audit", lambda *a, **k: None)

    cur = MagicMock()
    cur.fetchone.side_effect = [None, {"id": 1}]

    # Name was hand-edited to N.O.V.A. AFTER Generate built a rich identity for
    # a different name (Q.U.A.R.T.Z.) — simulates the client not clearing the
    # cached fields (defense-in-depth for direct API callers; the frontend fix
    # clears these client-side, but the server must not trust it blindly).
    stale_new_agent = {
        "name": "N.O.V.A.",
        "model": "qwen2.5:7b",
        "expansion": "Quantum Analytics Reasoning Tool",
        "title": "Data Specialist",
        "bio": "Q.U.A.R.T.Z. was forged in the analytics division.",
        "personality": "precise",
        "system_prompt": "You are Q.U.A.R.T.Z. (Quantum Analytics Reasoning Tool), " + "z" * 400,
        "portrait_prompt": "sci-fi portrait of Q.U.A.R.T.Z.",
    }

    res = hiring_service._create_new_hire(
        cur,
        hire_id=1,
        capability="analyze",
        gap_reason="gap",
        new_agent=stale_new_agent,
        decided_by_user_id=4,
        notes="",
    )
    assert res["ok"]
    # Persisted identity must be the freshly-built one for N.O.V.A. — the stale
    # Q.U.A.R.T.Z. prompt/bio must never leak into the created agent.
    assert calls["create"]["system_prompt"] == _BUILT_IDENTITY["system_prompt"]
    assert "Q.U.A.R.T.Z." not in calls["create"]["system_prompt"]
    # #4951: a net-new pool hire is an AI acronym specialist, not an 'internal' worker
    assert calls["create"]["worker_type"] == "ai"
    assert calls["update"]["bio"] == _BUILT_IDENTITY["bio"]
    assert calls["update"]["personality_prompt"] == _BUILT_IDENTITY["personality"]
    assert calls["update"]["acronym_expansion"] == _BUILT_IDENTITY["expansion"]
    assert calls["update"]["portrait_prompt"] == _BUILT_IDENTITY["portrait_prompt"]


def test_department_for_capability_resolves_real_department_not_engineering_default():
    """Bug #4982: the create path defaulted EVERY net-new hire to
    'Engineering & Technology' because the local resolver imported
    CAPABILITY_DEPARTMENT_MAP from a non-existent module. The canonical resolver
    maps 'analyze' -> Analytics & Intelligence; only genuinely-unmapped
    capabilities keep the documented Engineering fallback.
    """
    from services import hiring_service

    assert hiring_service._department_for_capability("analyze") == "Analytics & Intelligence"
    # a genuinely-unknown capability keeps the documented Engineering fallback
    assert hiring_service._department_for_capability("totally_unknown_capability_xyz") == "Engineering & Technology"

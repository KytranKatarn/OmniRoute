"""Unit tests: _create_new_hire persists acronym/expansion/title (name generator).

Covers the net-new hire persist path added for the Generate-name feature — a
generated hire stores its acronym metadata via the agents single-writer
(agent_service.update_agent). Since Task 3 (Complete Agent Hire, project #388),
a manually-named hire with no reviewed rich fields ALSO gets update_agent
called — agent_identity_builder.build_identity fills the gaps server-side so
every hire is complete, not just Generate-button hires.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

if "/app" not in sys.path:
    sys.path.insert(0, "/app")

# `from services import agent_service` (deferred inside _create_new_hire) can pull
# ai_bridge.agent_loop; stub it so the import resolves cleanly under pytest.
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


_BUILT_IDENTITY = {
    "name": "",  # overwritten per-call by build_identity's existing_name kwarg in prod;
    # the test double below ignores it and returns fixed content deterministically.
    "expansion": "Built Expansion",
    "title": "Built Title",
    "bio": "Built bio.",
    "personality": "Built personality.",
    "system_prompt": "B" * 450,
    "portrait_prompt": "Built portrait prompt.",
    "source": "fallback",
}


def _run_create_new_hire(new_agent, agent_id):
    """Drive _create_new_hire with all agent_service writes mocked. Returns
    (result, update_agent_mock). agent_identity_builder.build_identity and
    agent_service.add_portrait are mocked too — every hire calls them now
    that _create_new_hire guarantees a complete identity (Task 3)."""
    from services import hiring_service

    cur = MagicMock()
    # fetchone: 1) name-collision check -> None; 2) hiring_candidates RETURNING -> row.
    cur.fetchone.side_effect = [None, {"id": 1}]
    with patch.object(hiring_service, "_verify_model_available", return_value=(True, "ok")), patch(
        "services.agent_service.create_agent", return_value=agent_id
    ), patch("services.agent_service.add_skill"), patch("services.agent_service.init_budget"), patch(
        "services.agent_service.log_creation_event"
    ), patch(
        "services.agent_service.update_agent"
    ) as mock_update, patch(
        "services.agent_service.add_portrait"
    ), patch(
        "services.agent_identity_builder.build_identity", return_value=dict(_BUILT_IDENTITY)
    ), patch.object(
        hiring_service, "_audit"
    ):
        out = hiring_service._create_new_hire(
            cur,
            hire_id=7,
            capability="fact_check",
            gap_reason="pool maxed",
            new_agent=new_agent,
            decided_by_user_id=4,
            notes="",
        )
    return out, mock_update


def test_create_new_hire_persists_acronym_metadata():
    out, mock_update = _run_create_new_hire(
        {
            "name": "V.E.R.I.F.Y.",
            "model": "qwen2.5:7b",
            "display_name": "V.E.R.I.F.Y.",
            "expansion": "Validation Engine ...",
            "title": "Fact Checker",
        },
        agent_id=4242,
    )
    assert out["ok"] is True and out["agent_id"] == 4242
    mock_update.assert_called_once()
    args, kwargs = mock_update.call_args
    assert args[0] == 4242
    assert kwargs.get("acronym") == "V.E.R.I.F.Y."
    assert kwargs.get("acronym_expansion") == "Validation Engine ..."
    assert kwargs.get("title") == "Fact Checker"


def test_create_new_hire_builds_complete_identity_when_no_metadata():
    """Manual path (no expansion/title/system_prompt in new_agent) must still
    end up with a COMPLETE identity — _create_new_hire falls back to
    agent_identity_builder.build_identity to fill every gap, so update_agent
    IS called with acronym + the built bio/personality/portrait_prompt (Task 3,
    project #388: no hire is ever left incomplete just because the operator
    typed a name manually instead of using Generate)."""
    out, mock_update = _run_create_new_hire(
        {"name": "Q.U.I.L.L.", "model": "mistral:7b"},
        agent_id=5555,
    )
    assert out["ok"] is True
    mock_update.assert_called_once()
    args, kwargs = mock_update.call_args
    assert args[0] == 5555
    assert kwargs.get("acronym") == "Q.U.I.L.L."
    assert kwargs.get("acronym_expansion") == "Built Expansion"
    assert kwargs.get("title") == "Built Title"
    assert kwargs.get("bio") == "Built bio."
    assert kwargs.get("personality_prompt") == "Built personality."
    assert kwargs.get("portrait_prompt") == "Built portrait prompt."

"""Unit tests: _create_new_hire persists acronym/expansion/title (name generator).

Covers the net-new hire persist path added for the Generate-name feature — a
generated hire stores its acronym metadata via the agents single-writer
(agent_service.update_agent); a manually-named hire does not issue the update.
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
sys.modules["ai_bridge.agent_loop"] = _stub_agent_loop
_stub_pkg.agent_loop = _stub_agent_loop


def _run_create_new_hire(new_agent, agent_id):
    """Drive _create_new_hire with all agent_service writes mocked. Returns
    (result, update_agent_mock)."""
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
    ) as mock_update, patch.object(
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


def test_create_new_hire_skips_update_when_no_metadata():
    """Manual path (no expansion/title) must NOT call update_agent."""
    out, mock_update = _run_create_new_hire(
        {"name": "Q.U.I.L.L.", "model": "mistral:7b"},
        agent_id=5555,
    )
    assert out["ok"] is True
    mock_update.assert_not_called()

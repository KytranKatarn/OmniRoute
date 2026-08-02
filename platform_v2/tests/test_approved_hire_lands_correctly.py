"""An approved hire must land in its filed department, on duty, under its filed name.

MEASURED 2026-08-02 on S.I.F.T. (agent 432), hired for ``beat_classification`` after an
explicit owner approval. The proposal filed department="News & Media" and
display_name="Sift — Beat Classification Specialist". What was created:

    department   = Engineering & Technology   (wrong)
    shift_state  = barracked                  (never selected)
    display_name = Beat Classification Specialist  (filed name discarded)

and ``select_agent('beat_classification', 'News & Media')`` returned the incumbent
P.U.B.L.I.S.H., not the new hire. The agent existed, held the right skills and a budget,
and appeared in the roster — while being incapable of receiving a single dispatch.

THREE INDEPENDENT CAUSES, each sufficient on its own:

1. ``department_dispatcher`` kept a hardcoded COPY of ``DEPARTMENT_FLOOR_MAP`` that had
   drifted — 16 entries vs agent_service's 17, missing "News & Media" (added 2026-04-14).
   ``_create_agent_from_approval`` reads "not in the map" as "this is a legacy STATION
   CODE" and runs it through a _LEGACY lookup defaulting to "Engineering & Technology".
2. ``create_agent`` defaults ``shift_state='barracked'`` and this path never overrode it.
   A barracked agent is woken only by ``_wake_barracked_specialist``, which fires ONLY
   when no ACTIVE candidate scores > 0 — so while the incumbent it was hired to relieve
   is active (always, that being the reason for hiring) the new agent is never chosen.
3. ``display_name=title`` unconditionally synthesised the name and discarded the filed one.

This is the same defect family as the ``worker_type='internal'`` fix already recorded in
that function: an approved hire that is present in the roster but absent from the work.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services import agent_service  # noqa: E402

# department_dispatcher does `from db import _get_db_password` at module scope, which needs
# ai_bridge on sys.path. Without this the import fails and every assertion below reads as a
# code defect rather than a broken harness (KB #272154).
from services.signal_calendar_service import _ensure_import_paths  # noqa: E402

_ensure_import_paths()


def _dispatcher():
    """A BridgeDispatcher instance without running __init__ (no DB/model setup)."""
    from tools.department_hq.services.department_dispatcher import DepartmentDispatcher

    return DepartmentDispatcher.__new__(DepartmentDispatcher)


def _run_create(payload):
    """Call _create_agent_from_approval with all DB writers mocked; return create kwargs."""
    created = {}

    def _fake_create(**kwargs):
        created.update(kwargs)
        return 999

    with patch.object(agent_service, "create_agent", side_effect=_fake_create), patch.object(
        agent_service, "update_agent", return_value=True
    ), patch.object(agent_service, "add_skill", return_value=True, create=True), patch(
        "database.get_db_cursor"
    ) as _cur:
        _cur.return_value.__enter__ = MagicMock(return_value=(MagicMock(), MagicMock()))
        _cur.return_value.__exit__ = MagicMock(return_value=False)
        try:
            _dispatcher()._create_agent_from_approval(payload)
        except Exception as exc:
            # Downstream lineage/audit writes are not what these tests assert on and may
            # fail against mocks — but ONLY once create_agent has actually been reached.
            # A swallow here previously hid a module-import error and made every
            # assertion below look like a code defect instead of a broken harness.
            if not created:
                raise AssertionError(f"create_agent was never reached: {type(exc).__name__}: {exc}") from exc
    return created


PAYLOAD = {
    "capability": "beat_classification",
    "department": "News & Media",
    "display_name": "Sift — Beat Classification Specialist",
    "suggested_name": "S.I.F.T.",
    "suggested_model": "mistral:7b",
    "suggested_skills": ["beat_classification"],
    "reason": "second holder",
}


def test_the_floor_map_is_not_duplicated():
    """The root cause: two copies, one stale. Identity makes drift impossible.

    Asserting `is` rather than `==` deliberately — an equal-but-separate dict would pass
    today and drift again the next time a department is added, which is exactly what
    happened with News & Media.
    """
    from tools.department_hq.services import department_dispatcher as dd

    assert dd.DEPARTMENT_FLOOR_MAP is agent_service.DEPARTMENT_FLOOR_MAP


def test_news_and_media_is_mapped():
    """The specific key whose absence misfiled the hire."""
    assert agent_service.DEPARTMENT_FLOOR_MAP.get("News & Media") == "CREATIVE"


def test_an_approved_hire_keeps_its_filed_department():
    assert _run_create(PAYLOAD).get("department") == "News & Media"


def test_an_approved_hire_starts_on_duty_not_barracked():
    """A human approved this hire because capacity is needed now.

    'barracked' is not merely suboptimal — it makes the agent unreachable by dispatch
    while the incumbent is active, which is the only situation a hire is made in.
    """
    assert _run_create(PAYLOAD).get("shift_state") == "active"


def test_an_approved_hire_keeps_its_filed_display_name():
    assert _run_create(PAYLOAD).get("display_name") == "Sift — Beat Classification Specialist"


def test_display_name_falls_back_for_proposals_that_file_none():
    """Auto-generated proposals carry no display_name — they must still get a sane title."""
    payload = {k: v for k, v in PAYLOAD.items() if k != "display_name"}
    assert _run_create(payload).get("display_name") == "Beat Classification Specialist"


def test_a_legacy_station_code_still_maps():
    """The _LEGACY branch is for real station codes and must keep working."""
    payload = {**PAYLOAD, "department": "ENGINEERING"}
    assert _run_create(payload).get("department") == "Engineering & Technology"


def test_every_department_in_use_has_a_floor():
    """Catch the NEXT department added without updating the map.

    News & Media existed with 21 agents for ~4 months while absent from the dispatcher's
    map. Any department present on a live agent must be mappable.
    """
    from database import get_db_cursor

    try:
        with get_db_cursor() as (_conn, cur):
            cur.execute(
                """
                SELECT DISTINCT department FROM agents
                WHERE department IS NOT NULL AND shift_state <> 'decommissioned'
                """
            )
            depts = {r["department"] for r in cur.fetchall() if r["department"]}
    except Exception as exc:  # noqa: BLE001
        depts = set()
        pytest.skip(f"no DB reachable from this runner: {type(exc).__name__}: {exc}")

    # SKIP, never pass, on no data. A green tick here with an empty result set would be a
    # test that reports "all departments mapped" while having checked nothing — the exact
    # "unmonitored while appearing monitored" shape this file exists to prevent. A skip is
    # visible in the run summary; a vacuous pass is not.
    if not depts:
        pytest.skip("query returned no departments — cannot verify, not asserting a pass")
    unmapped = sorted(d for d in depts if d not in agent_service.DEPARTMENT_FLOOR_MAP)
    assert not unmapped, f"departments in use with no floor mapping: {unmapped}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

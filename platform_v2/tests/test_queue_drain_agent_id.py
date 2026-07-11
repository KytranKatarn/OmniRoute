"""Tests for the queue-drain attribution fix
(model_dispatch_service._queue_attributed_agent_id).

The cold-load queue worker (_log_to_tel) bypasses request_work(), so it builds a
DispatchResult by hand. It previously set agent_name but NOT agent_id → ~half of
queue-drained rows logged agent_id=NULL (invisible to per-agent budget/welfare/K.I.N.).
The queue row carries agent_id, so we pass it through — EXCEPT warm-up keep-alive, which
must stay unattributed (recal excludes it only via agent_id IS NULL, so attributing
keep-warm pings would inflate the agent's budget). Pure function — no DB.
"""

from __future__ import annotations

from services.model_dispatch_service import _queue_attributed_agent_id


def test_passes_selected_agent_id_for_real_work():
    assert _queue_attributed_agent_id({"agent_id": 137}, "archie_platform") == 137
    assert _queue_attributed_agent_id({"agent_id": 8}, "mailbox_story") == 8
    assert _queue_attributed_agent_id({"agent_id": 416}, "wtf_hub") == 416


def test_warmup_stays_unattributed():
    # Warm-up keep-alive must NOT be billed to an agent — recal/budget exclude it only
    # via agent_id IS NULL, so this preserves that (the 'warm-up pseudo-agent' question
    # is separate).
    assert _queue_attributed_agent_id({"agent_id": 145}, "kin_warmth") is None
    assert _queue_attributed_agent_id({"agent_id": 363}, "fleet_warmup") is None


def test_none_when_queue_row_has_no_agent_id():
    assert _queue_attributed_agent_id({}, "archie_platform") is None
    assert _queue_attributed_agent_id({"agent_id": None}, "memory_vault_extract") is None

"""Unit tests for the HUB→STANDALONE welfare emitter (project #379 Phase 3).

build_welfare_events / decide_emissions are PURE (no DB) → run on the host. They
assert the per-dimension event payload (category/event_type/metadata.dimension/
severity) aligns with the standalone welfare_engine's scoring contract, and that
the de-dupe logic does not re-emit an unchanged state inside the heartbeat window.
"""

from datetime import datetime, timedelta, timezone

from services.welfare_emit import (
    DIMENSIONS,
    WELFARE_CATEGORY,
    build_welfare_events,
    decide_emissions,
)
from services.welfare_governance import governance_limits

# Governance thresholds: token line raised to the budget (1.0), the production
# config the daily/intraday jobs use. hours_cap 4h, action/stress break lines.
GC = governance_limits({"hours_cap": 4.0, "token_pct": 0.60, "action_pct": 0.90, "stress": 0.45})


def _by_dim(events, agent_id):
    return {e["dedupe_dimension"]: e for e in events if e["agent_id"] == agent_id}


# ── PURE payload builder: contract alignment with welfare_engine ──────────────

def test_healthy_agent_emits_all_info_dimensions():
    """A within-bounds agent emits welfare_<dim>=info for ALL 4 dims (weight 0 →
    perfect dimension score on the standalone)."""
    snap = {"agent_id": 1, "name": "HEALTHY", "hours": 1.0,
            "token_ratio": 0.2, "action_ratio": 0.1, "stress": 0.2, "rested_today": 0}
    events = build_welfare_events([snap], GC)
    dims = _by_dim(events, 1)
    assert set(d for d in dims if d in DIMENSIONS) == set(DIMENSIONS)
    for d in DIMENSIONS:
        ev = dims[d]
        assert ev["category"] == WELFARE_CATEGORY          # 'welfare', NOT accountability
        assert ev["event_type"] == f"welfare_{d}"          # exact standalone event_type
        assert ev["metadata"]["dimension"] == d            # metadata.dimension wins resolution
        assert ev["severity"] == "info"                    # weight 0 → 100 dimension score
    # No break event for a fully-healthy agent.
    assert "break_honored" not in dims and "break_violated" not in dims


def test_token_over_budget_emits_warning_then_violation():
    """Token overage is throttle-managed (#4123): warning up to 2x, violation beyond."""
    over = {"agent_id": 2, "name": "OVER", "hours": 1.0,
            "token_ratio": 1.3, "action_ratio": 0.1, "stress": 0.2, "rested_today": 0}
    way_over = {**over, "agent_id": 3, "name": "WAYOVER", "token_ratio": 2.5}
    events = build_welfare_events([over, way_over], GC)
    assert _by_dim(events, 2)["tokens"]["severity"] == "warning"
    assert _by_dim(events, 3)["tokens"]["severity"] == "violation"
    # token overage alone (a non-rest dimension) produces NO break_violated event.
    assert "break_violated" not in _by_dim(events, 2)


def test_unrested_hours_overage_is_critical_with_break_violated():
    """Over the hours cap with no rest = the worst welfare state: critical hours
    event + a welfare_break_violated event (feeds break_honor_rate)."""
    snap = {"agent_id": 4, "name": "TIRED", "hours": 9.0,
            "token_ratio": 0.2, "action_ratio": 0.1, "stress": 0.2, "rested_today": 0}
    dims = _by_dim(build_welfare_events([snap], GC), 4)
    assert dims["hours"]["severity"] == "critical"
    assert "break_violated" in dims
    assert dims["break_violated"]["event_type"] == "welfare_break_violated"
    assert dims["break_violated"]["severity"] == "violation"


def test_rested_stress_overage_is_honored():
    """Over a rest dimension (stress) but rested today → warning on the dim + a
    welfare_break_honored event (info)."""
    snap = {"agent_id": 5, "name": "RESTED", "hours": 1.0,
            "token_ratio": 0.2, "action_ratio": 0.1, "stress": 0.9, "rested_today": 1}
    dims = _by_dim(build_welfare_events([snap], GC), 5)
    assert dims["stress"]["severity"] == "warning"
    assert "break_honored" in dims
    assert dims["break_honored"]["event_type"] == "welfare_break_honored"
    assert dims["break_honored"]["severity"] == "info"
    assert "break_violated" not in dims


# ── PURE de-dupe ──────────────────────────────────────────────────────────────

def _candidate(agent_id, dim, sev):
    return {"agent_id": agent_id, "dedupe_dimension": dim, "event_type": f"welfare_{dim}",
            "category": WELFARE_CATEGORY, "severity": sev, "metadata": {"dimension": dim},
            "description": "x"}


def test_dedupe_skips_unchanged_inside_heartbeat():
    now = datetime.now(timezone.utc)
    cands = [_candidate(1, "tokens", "info")]
    prior = {(1, "tokens"): {"last_severity": "info", "last_emit_at": now - timedelta(minutes=30)}}
    to_emit, to_skip = decide_emissions(cands, prior, now, heartbeat_hours=6.0)
    assert to_emit == [] and len(to_skip) == 1   # unchanged + fresh → skipped


def test_dedupe_emits_on_state_change():
    now = datetime.now(timezone.utc)
    cands = [_candidate(1, "tokens", "violation")]
    prior = {(1, "tokens"): {"last_severity": "info", "last_emit_at": now - timedelta(minutes=5)}}
    to_emit, to_skip = decide_emissions(cands, prior, now, heartbeat_hours=6.0)
    assert len(to_emit) == 1 and to_emit[0]["_reason"] == "changed" and to_skip == []


def test_dedupe_emits_heartbeat_when_aged():
    now = datetime.now(timezone.utc)
    cands = [_candidate(1, "tokens", "info")]
    prior = {(1, "tokens"): {"last_severity": "info", "last_emit_at": now - timedelta(hours=7)}}
    to_emit, _ = decide_emissions(cands, prior, now, heartbeat_hours=6.0)
    assert len(to_emit) == 1 and to_emit[0]["_reason"] == "heartbeat"


def test_dedupe_emits_first_ever():
    now = datetime.now(timezone.utc)
    to_emit, _ = decide_emissions([_candidate(9, "stress", "info")], {}, now)
    assert len(to_emit) == 1 and to_emit[0]["_reason"] == "first"


def test_dedupe_prevents_flood():
    """54 agents × 4 dims, all healthy + already emitted info recently → 0 re-emits."""
    now = datetime.now(timezone.utc)
    snaps = [{"agent_id": i, "name": f"A{i}", "hours": 1.0, "token_ratio": 0.1,
              "action_ratio": 0.1, "stress": 0.1, "rested_today": 0} for i in range(54)]
    cands = build_welfare_events(snaps, GC)
    assert len(cands) == 54 * 4                      # 4 info dims each, no break events
    prior = {(e["agent_id"], e["dedupe_dimension"]):
             {"last_severity": "info", "last_emit_at": now - timedelta(minutes=10)} for e in cands}
    to_emit, to_skip = decide_emissions(cands, prior, now, heartbeat_hours=6.0)
    assert to_emit == [] and len(to_skip) == 54 * 4  # nothing changed → nothing flooded

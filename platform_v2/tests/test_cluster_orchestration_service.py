"""Tests for cluster orchestration score engine."""

import pytest


class TestComputeOverflowScore:

    def _cfg(self, **overrides):
        cfg = {
            "idle_threshold_minutes": 5,
            "utilization_threshold_pct": 60.0,
            "queue_pressure_threshold": 10,
            "idle_weight": 0.3,
            "utilization_weight": 0.3,
            "queue_pressure_weight": 0.4,
        }
        cfg.update(overrides)
        return cfg

    def test_all_signals_maxed_returns_one(self):
        from services.cluster_orchestration_service import compute_overflow_score

        score = compute_overflow_score(idle_minutes=10, util_pct=0.0, queue_depth=20, config=self._cfg())
        assert score == pytest.approx(1.0)

    def test_all_signals_zero_returns_zero(self):
        from services.cluster_orchestration_service import compute_overflow_score

        score = compute_overflow_score(idle_minutes=0, util_pct=100.0, queue_depth=0, config=self._cfg())
        assert score == pytest.approx(0.0)

    def test_only_idle_weight_active(self):
        from services.cluster_orchestration_service import compute_overflow_score

        cfg = self._cfg(idle_weight=1.0, utilization_weight=0.0, queue_pressure_weight=0.0)
        score = compute_overflow_score(idle_minutes=2.5, util_pct=100.0, queue_depth=0, config=cfg)
        assert score == pytest.approx(0.5)

    def test_idle_capped_at_one(self):
        from services.cluster_orchestration_service import compute_overflow_score

        cfg = self._cfg(idle_weight=1.0, utilization_weight=0.0, queue_pressure_weight=0.0)
        score = compute_overflow_score(idle_minutes=100, util_pct=100.0, queue_depth=0, config=cfg)
        assert score == pytest.approx(1.0)


class TestResolveConfig:

    def _row(self, scope, **fields):
        base = {
            "scope": scope,
            "agent_id": None,
            "capability": None,
            "node_id": None,
            "idle_threshold_minutes": 5,
            "utilization_threshold_pct": 60.0,
            "queue_pressure_threshold": 10,
            "idle_weight": 0.3,
            "utilization_weight": 0.3,
            "queue_pressure_weight": 0.4,
            "overflow_enabled": True,
            "overflow_paused": False,
            "priority_boost": 0,
            "max_overflow_concurrent": 3,
        }
        base.update(fields)
        return base

    def test_agent_override_beats_global(self):
        from services.cluster_orchestration_service import resolve_config

        rows = [
            self._row("global", idle_threshold_minutes=5),
            self._row("agent", agent_id=42, idle_threshold_minutes=2),
        ]
        result = resolve_config(rows, agent_id=42, capability=None, node_id=None)
        assert result["idle_threshold_minutes"] == 2

    def test_global_used_when_no_override(self):
        from services.cluster_orchestration_service import resolve_config

        rows = [self._row("global", idle_threshold_minutes=7)]
        result = resolve_config(rows, agent_id=99, capability="research", node_id=None)
        assert result["idle_threshold_minutes"] == 7

    def test_paused_true_at_agent_scope(self):
        from services.cluster_orchestration_service import resolve_config

        rows = [
            self._row("global", overflow_paused=False),
            self._row("agent", agent_id=1, overflow_paused=True),
        ]
        result = resolve_config(rows, agent_id=1, capability=None, node_id=None)
        assert result["overflow_paused"] is True


class TestGetOverflowBonus:

    def test_active_agent_returns_bonus(self):
        import time
        import services.cluster_orchestration_service as svc
        from services.cluster_orchestration_service import update_overflow_cache, get_overflow_bonus

        update_overflow_cache(
            [{"agent_id": 10, "capability": "fact_check_backlog", "is_active": True, "overflow_score": 0.8}]
        )
        svc._cache_built_at = time.monotonic()
        bonus = get_overflow_bonus(10, "fact_check_backlog")
        assert bonus == pytest.approx(0.4)

    def test_inactive_agent_returns_zero(self):
        import time
        import services.cluster_orchestration_service as svc
        from services.cluster_orchestration_service import update_overflow_cache, get_overflow_bonus

        update_overflow_cache([{"agent_id": 11, "capability": "research", "is_active": False, "overflow_score": 0.2}])
        svc._cache_built_at = time.monotonic()
        assert get_overflow_bonus(11, "research") == 0.0

    def test_stale_cache_returns_zero(self):
        import time
        import services.cluster_orchestration_service as svc
        from services.cluster_orchestration_service import update_overflow_cache, get_overflow_bonus

        # Populate cache with an active agent
        update_overflow_cache([{"agent_id": 12, "capability": "fact_check", "is_active": True, "overflow_score": 0.9}])
        # Make cache appear stale (91 seconds old)
        svc._cache_built_at = time.monotonic() - 91
        # Should return 0 because cache is stale
        assert get_overflow_bonus(12, "fact_check") == 0.0

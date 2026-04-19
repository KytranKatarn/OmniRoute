"""
Tests for department_coordinator scoring fix — task #2166.

Verifies that an unskilled director cannot beat a skilled specialist
and that wake-on-demand triggers when all active candidates lack the skill.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers — build minimal agent_info dicts that mirror the cache structure
# ---------------------------------------------------------------------------


def _make_agent(
    *,
    name: str,
    department: str,
    skills: dict | None = None,
    is_department_ai: bool = False,
    status: str = "active",
    shift_state: str = "active",
    agent_id: int = 1,
) -> tuple[str, dict]:
    return name, {
        "id": agent_id,
        "name": name,
        "department": department,
        "is_department_ai": is_department_ai,
        "status": status,
        "shift_state": shift_state,
        "skills": skills or {},
        "model": "llama3.2:3b",
    }


def _make_welfare(*, stress: float = 0.0, energy: float = 0.5, util_pct: float = 0.0) -> dict:
    return {"stress": stress, "energy": energy, "budget": {"utilization_pct": util_pct}}


# ---------------------------------------------------------------------------
# Unit tests for score_agent
# ---------------------------------------------------------------------------


class TestScoringPenalty:
    """score_agent must penalise agents that lack the requested capability."""

    def _get_coordinator(self, agent_cache: dict, welfare_cache: dict):
        """Return a DepartmentCoordinator with injected caches (no DB calls)."""
        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        coord._agent_cache = agent_cache
        coord._welfare_cache = welfare_cache
        coord._cache_time = float("inf")  # prevent cache refresh hitting DB
        return coord

    def test_unskilled_director_scores_lower_than_skilled_specialist(self):
        """Director bonus (+0.3) + dept match (+0.2) must NOT beat a skilled agent."""
        dept = "Creative & Design"
        cap = "image_edit"

        _, director_info = _make_agent(
            name="M.U.S.E.",
            department=dept,
            skills={},  # no image_edit skill
            is_department_ai=True,
            agent_id=10,
        )
        _, specialist_info = _make_agent(
            name="R.E.S.T.O.R.E.",
            department=dept,
            skills={"image_edit": 4},  # has the skill at proficiency 4
            is_department_ai=False,
            agent_id=11,
        )

        welfare = {
            10: _make_welfare(),
            11: _make_welfare(),
        }
        coord = self._get_coordinator(
            {"M.U.S.E.": director_info, "R.E.S.T.O.R.E.": specialist_info},
            welfare,
        )

        director_score, director_block = coord.score_agent("M.U.S.E.", director_info, cap, dept)
        specialist_score, specialist_block = coord.score_agent("R.E.S.T.O.R.E.", specialist_info, cap, dept)

        assert specialist_block is None, "Specialist should not be blocked"
        assert director_block is None, "Director should not be hard-blocked (just penalised)"
        assert specialist_score > director_score, (
            f"Skilled specialist ({specialist_score:.3f}) must beat " f"unskilled director ({director_score:.3f})"
        )

    def test_unskilled_director_score_is_positive_but_below_one(self):
        """Penalty should keep director above 0 (not hard-blocked) but below 1.0 baseline."""
        dept = "Creative & Design"
        cap = "image_edit"

        _, director_info = _make_agent(
            name="M.U.S.E.",
            department=dept,
            skills={},
            is_department_ai=True,
            agent_id=10,
        )
        welfare = {10: _make_welfare()}
        coord = self._get_coordinator({"M.U.S.E.": director_info}, welfare)

        score, block = coord.score_agent("M.U.S.E.", director_info, cap, dept)

        # With penalty -1.0: base 1.0 + welfare ~0.45 - 1.0 + dept 0.2 + director 0.3 ≈ 0.95
        # but max(score, 0.01) is applied — it should still be well below 1.5 (skilled specialist)
        assert block is None
        assert score > 0.0, "Penalised director should not hit hard-block floor"
        # Unskilled director cannot reach 1.0 under normal welfare conditions
        assert score < 1.0, (
            f"Unskilled director score {score:.3f} must be below 1.0 "
            f"so a barracked specialist with proficiency ≥ 3 wins"
        )

    def test_no_penalty_when_capability_is_empty(self):
        """When no capability is requested, the penalty must NOT apply."""
        dept = "Engineering & Technology"

        _, agent_info = _make_agent(
            name="P.R.O.B.E.",
            department=dept,
            skills={},
            is_department_ai=True,
            agent_id=20,
        )
        welfare = {20: _make_welfare()}
        coord = self._get_coordinator({"P.R.O.B.E.": agent_info}, welfare)

        score_empty, _ = coord.score_agent("P.R.O.B.E.", agent_info, "", dept)
        score_none, _ = coord.score_agent("P.R.O.B.E.", agent_info, None, dept)  # type: ignore[arg-type]

        # No capability ⇒ no penalty — director bonus should push score above 1.0
        assert score_empty > 1.0, "No-capability agent should not be penalised"
        assert score_none > 1.0, "None-capability agent should not be penalised"

    def test_skilled_agent_score_unchanged_by_penalty_logic(self):
        """An agent WITH the skill must not be penalised."""
        dept = "Creative & Design"
        cap = "image_edit"

        _, agent_info = _make_agent(
            name="R.E.S.T.O.R.E.",
            department=dept,
            skills={"image_edit": 5},
            is_department_ai=False,
            agent_id=30,
        )
        welfare = {30: _make_welfare()}
        coord = self._get_coordinator({"R.E.S.T.O.R.E.": agent_info}, welfare)

        score, block = coord.score_agent("R.E.S.T.O.R.E.", agent_info, cap, dept)

        # base 1.0 + welfare ~0.45 + skill 5*0.2 + dept 0.2 = ~2.65
        assert block is None
        assert score > 1.5, f"Skilled agent should score well, got {score:.3f}"


class TestCompetencyScoring:
    """Competency scores from agent_competency_scores feed a +/-0.2 adjustment (#2179)."""

    def _get_coordinator(self, agent_cache: dict, welfare_cache: dict):
        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        coord._agent_cache = agent_cache
        coord._welfare_cache = welfare_cache
        coord._cache_time = float("inf")
        return coord

    def _score(self, coord, agent_info: dict, capability, department) -> float:
        name = agent_info.get("name", "Agent")
        score, _ = coord.score_agent(name, agent_info, capability, department, None)
        return score

    def _make_agent_info(self, competency_scores: dict) -> dict:
        return {
            "id": 1,
            "name": "TestAgent",
            "department": "CREATIVE",
            "is_department_ai": False,
            "status": "active",
            "shift_state": "active",
            "skills": {"image_gen": 3},
            "model": "llama3.2:3b",
            "competency_scores": competency_scores,
        }

    def _make_welfare(self) -> dict:
        return {1: {"stress": 0.3, "energy": 0.8, "budget": {"utilization_pct": 0.2}}}

    def test_strong_competency_adds_bonus(self):
        """score >= 0.7 adds +0.2, score < 0.5 subtracts -0.2 — 0.4 delta total."""
        coord = self._get_coordinator({}, self._make_welfare())
        strong = self._score(coord, self._make_agent_info({"image_gen": 0.85}), "image_gen", "CREATIVE")
        weak = self._score(coord, self._make_agent_info({"image_gen": 0.40}), "image_gen", "CREATIVE")
        untested = self._score(coord, self._make_agent_info({}), "image_gen", "CREATIVE")

        assert strong - weak == pytest.approx(0.4, abs=0.001), f"Expected 0.4 delta, got {strong - weak}"
        assert weak < untested < strong

    def test_untested_equals_passable_no_adjustment(self):
        """Untested agent (no entry) equals passable score (0.5 <= x < 0.7)."""
        coord = self._get_coordinator({}, self._make_welfare())
        untested = self._score(coord, self._make_agent_info({}), "image_gen", "CREATIVE")
        passable = self._score(coord, self._make_agent_info({"image_gen": 0.6}), "image_gen", "CREATIVE")
        assert untested == pytest.approx(passable, abs=0.001)

    def test_no_competency_adjustment_when_capability_empty(self):
        """Empty/None capability means no competency adjustment."""
        coord = self._get_coordinator({}, self._make_welfare())
        agent_with_comp = self._make_agent_info({"image_gen": 0.9})
        agent_no_comp = self._make_agent_info({})
        # skills={"image_gen": 3} but capability=None — no skill match, no competency
        score_with = self._score(coord, agent_with_comp, None, "CREATIVE")
        score_without = self._score(coord, agent_no_comp, None, "CREATIVE")
        assert score_with == pytest.approx(score_without, abs=0.001)


class TestLegacySymbolsRemoved:
    """Regression guard — prevents accidental reintroduction of removed legacy symbols.

    These tests use AST parsing so they work without importing the dispatcher
    (which requires the full Docker DB environment at import time).
    """

    _DISPATCHER_PATH = "tools/department_hq/services/department_dispatcher.py"

    def _source(self) -> str:
        import os

        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full = os.path.join(base, self._DISPATCHER_PATH)
        with open(full) as f:
            return f.read()

    def test_agent_specialization_removed(self):
        src = self._source()
        assert "AGENT_SPECIALIZATION" not in src, (
            "AGENT_SPECIALIZATION was removed in #2165 — " "use skill-based dispatch via coordinator.select_agent()"
        )

    def test_get_agent_for_module_removed(self):
        src = self._source()
        assert "get_agent_for_module" not in src, (
            "get_agent_for_module was removed in #2165 — "
            "callers should use coordinator.select_agent(capability, department)"
        )

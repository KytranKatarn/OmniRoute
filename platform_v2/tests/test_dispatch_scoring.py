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


def _make_welfare(
    *,
    stress: float = 0.0,
    energy: float = 0.5,
    util_pct: float | None = None,
    token_ratio: float = 0.0,
    task_count: int = 0,
    task_limit: int = 10,
) -> dict:
    """Mirror the budget dict that agent_service.get_welfare_cache() now emits.

    ``token_ratio`` = 24h rolling tokens / daily budget (the #4090 throttle signal).
    ``util_pct`` defaults to max(task_ratio, token_ratio) like the real cache; pass
    it explicitly only to exercise the legacy utilisation field directly.
    """
    task_ratio = (task_count / task_limit) if task_limit else 0.0
    if util_pct is None:
        util_pct = max(task_ratio, token_ratio)
    return {
        "stress": stress,
        "energy": energy,
        "budget": {
            "utilization_pct": util_pct,
            "token_ratio": token_ratio,
            "task_ratio": task_ratio,
            "current_task_count": task_count,
            "task_queue_limit": task_limit,
        },
    }


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


def test_iris_beats_spectra_for_classify_via_model_affinity():
    """I.R.I.S. (qwen25-classify) should outscore S.P.E.C.T.R.A. (mistral:7b)
    for classify capability due to model-name affinity bonus."""
    from services.department_coordinator import DepartmentCoordinator

    coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
    coord._welfare_cache = {}
    coord._cache_time = float("inf")  # prevent _refresh_caches from hitting DB
    coord._agent_cache = {}

    iris_info = {
        "id": 8,
        "status": "active",
        "shift_state": "active",
        "model": "qwen25-classify",
        "department": "Analytics & Intelligence",
        "is_department_ai": False,
        "skills": {"classify": 5},
        "competency_scores": {},
    }
    spectra_info = {
        "id": 137,
        "status": "active",
        "shift_state": "active",
        "model": "mistral:7b",
        "department": "Analytics & Intelligence",
        "is_department_ai": True,
        "skills": {"classify": 5},
        "competency_scores": {},
    }

    iris_score, _ = coord.score_agent("I.R.I.S.", iris_info, "classify", "Analytics & Intelligence")
    spectra_score, _ = coord.score_agent("S.P.E.C.T.R.A.", spectra_info, "classify", "Analytics & Intelligence")

    assert iris_score > spectra_score, (
        f"I.R.I.S. ({iris_score:.2f}) should beat S.P.E.C.T.R.A. ({spectra_score:.2f}) "
        f"for classify — model affinity bonus missing"
    )


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


class TestModelIsGpuClass:
    """GPU-overflow follow-up (RCA KB #278774): _model_is_gpu_class scopes the
    saturation-driven GPU escalation to the contended mid/large models only.

    Execs the REAL source definitions (marker tuple + fn) so no dispatcher import
    is needed — same rationale as TestLegacySymbolsRemoved (heavy DB import at
    module load). A false positive here would push small warm-set models off the
    hub under load; a false negative would leave a 7B stuck thrashing hub CPU.
    """

    _DISPATCHER_PATH = "tools/department_hq/services/department_dispatcher.py"

    def _fn(self):
        import ast
        import os

        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, self._DISPATCHER_PATH)) as f:
            src = f.read()
        tree = ast.parse(src)
        ns: dict = {"Optional": __import__("typing").Optional}
        for node in tree.body:
            targets = getattr(node, "targets", [])
            is_markers = isinstance(node, ast.Assign) and any(
                getattr(t, "id", None) == "_SMALL_MODEL_MARKERS" for t in targets
            )
            is_fn = isinstance(node, ast.FunctionDef) and node.name == "_model_is_gpu_class"
            if is_markers or is_fn:
                exec(compile(ast.Module(body=[node], type_ignores=[]), "<dispatcher>", "exec"), ns)
        return ns["_model_is_gpu_class"]

    def test_seven_b_and_larger_are_gpu_class(self):
        fn = self._fn()
        for m in ("qwen2.5:7b", "mistral:7b", "gemma3:12b", "dolphin3:latest"):
            assert fn(m) is True, f"{m} should be GPU-class (contended)"

    def test_small_warm_set_is_not_gpu_class(self):
        fn = self._fn()
        for m in ("qwen2.5:1.5b", "llama3.2:3b", "nomic-embed-text", "moondream"):
            assert fn(m) is False, f"{m} should NOT be GPU-class (runs fine on hub CPU)"

    def test_empty_or_none_model_is_not_gpu_class(self):
        fn = self._fn()
        assert fn("") is False
        assert fn(None) is False

    def test_coordinator_and_small_candidates_are_not_gpu_class(self):
        """Isolation linchpin (KB #278774 f/u): the coordinator model and the
        Phase-3 small candidates must classify as small/non-GPU-class so the
        hub admission gate doesn't shed them and mis-escalate to GPU nodes.
        """
        fn = self._fn()
        for m in ("qwen25-classify", "gemma2:2b", "phi4-mini"):
            assert fn(m) is False, f"{m} must be small/non-GPU-class"


class TestHubAdmissionGeneralized:
    """RCA KB #278774 generalization f/u: the _execute_llm hub-admission guard must gate on
    MODEL CLASS (_model_is_gpu_class(model)) — NOT a fixed capability tuple — so a future 7B
    producer is auto-covered. Source-inspects the dispatcher (heavy DB import at module load,
    same rationale as TestModelIsGpuClass) to lock the generalized shape and prevent a revert.
    """

    _DISPATCHER_PATH = "tools/department_hq/services/department_dispatcher.py"

    def _admission_block(self):
        import os

        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, self._DISPATCHER_PATH)) as f:
            src = f.read()
        idx = src.index("Hub admission control")
        return src[idx : idx + 2200]

    def test_gate_uses_model_class_not_capability_tuple(self):
        block = self._admission_block()
        assert "_model_is_gpu_class(model)" in block, "gate must use model-class, not a tuple"
        assert "capability in HUB_CONTENDED_LANES" not in block, "must not revert to the fixed tuple"

    def test_gate_preserves_backpressure_shape(self):
        block = self._admission_block()
        assert '"backpressure": True' in block
        assert '"success": False' in block

    def test_gate_passes_classification_for_reservation(self):
        # The shed-gate must hand capability+module_id to hub_lane_over_cap so the slot
        # reservation (#5132 f/u) can favour the diverted domain. A revert to the no-arg
        # blanket call silently disables the reservation while still "gating".
        block = self._admission_block()
        assert (
            "hub_lane_over_cap(capability=capability, module_id=module_id)" in block
        ), "shed-gate must pass classification so the reservation applies"


class TestLaneReservation:
    """Slot reservation (#5132 follow-up): while a mobility diversion is active, NON-prioritised
    7B work is admitted only up to cap-reserve, holding `reserve` slots for the favoured domain
    to actually EXECUTE in — not merely queue first. Pure math is fully unit-testable via
    reserved_cap_for(); the DB path is exercised live in the PR."""

    def _rc(self):
        from services.welfare_governance_service import reserved_cap_for

        return reserved_cap_for

    def test_auto_never_reserves(self):
        rc = self._rc()
        assert rc(8, 3, "auto", False) == 8
        assert rc(8, 3, "auto", True) == 8

    def test_prioritised_job_gets_full_cap(self):
        rc = self._rc()
        assert rc(8, 3, "platform", True) == 8
        assert rc(8, 3, "news", True) == 8

    def test_non_prioritised_job_is_reserved_down(self):
        rc = self._rc()
        assert rc(8, 3, "platform", False) == 5  # news under platform mode
        assert rc(8, 3, "news", False) == 5  # platform under news mode

    def test_reserve_never_locks_the_lane(self):
        # A diversion favours a domain; it must never totally starve the other.
        rc = self._rc()
        for reserve in (7, 8, 20, 999):
            assert rc(8, reserve, "platform", False) >= 1

    def test_bad_reserve_value_is_safe(self):
        rc = self._rc()
        assert rc(8, None, "platform", False) == 8  # unparseable → reserve 0 → full cap
        assert rc(8, "x", "platform", False) == 8

    def test_unknown_mode_is_full_cap(self):
        rc = self._rc()
        assert rc(8, 3, "", False) == 8
        assert rc(8, 3, "bogus", False) == 8


class TestAgentNameConsistency:
    """Regression guard for task #2164 Phase 1.

    Verifies that no Python file passes a plain-form agent name (e.g. 'heritage',
    'scroll', 'quill') to a dispatch parameter (prefer_agent / agent_name /
    target_agent). After Phase 2 the agents.name column will contain dotted
    forms only, so any plain-form reference would silently miss its target.

    Add the SKIP_AGENT_NAME_AUDIT=1 env-var to suppress this during the
    Phase 2 DB migration window itself.
    """

    # Plain-form names confirmed by:
    #   SELECT name FROM agents WHERE worker_type='ai'
    #     AND shift_state != 'decommissioned' AND name != display_name;
    # (2026-04-19 — 33 rows)
    PLAIN_FORMS = [
        "ACCORD",
        "ARCHIE",
        "ARMADA",
        "BASE",
        "bias",
        "CARGO",
        "CODEX",
        "DARWIN",
        "draft",
        "EMBER",
        "ethos",
        "fact",
        "FORGE",
        "GAVEL",
        "heritage",
        "ink",
        "KIN",
        "LEDGER",
        "MARKET",
        "MUSE",
        "publish",
        "quill",
        "RESOLVE",
        "restore",
        "scroll",
        "SHIELD",
        "SIGNAL",
        "SPECTRA",
        "verify",
        "VIGIL",
        "visage",
        "VITAL",
    ]

    # Directories to scan (relative to the repo root, as seen inside the container)
    _SCAN_DIRS = [
        "tools",
        "services",
        "ai_bridge",
    ]

    @pytest.mark.skipif(
        __import__("os").environ.get("SKIP_AGENT_NAME_AUDIT") == "1",
        reason="Skipped during Phase 2 agents.name migration window",
    )
    def test_no_plain_form_prefer_agent_calls(self):
        """No Python file may pass a plain-form name to prefer_agent / agent_name /
        target_agent. If this test fails, someone introduced a new plain-form
        reference after Phase 1 was merged — fix it by using the dotted form."""
        import os
        import re
        import subprocess

        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        scan_paths = [os.path.join(base, d) for d in self._SCAN_DIRS if os.path.isdir(os.path.join(base, d))]

        failures = []
        pattern = re.compile(
            r'(prefer_agent|agent_name|target_agent)\s*=\s*["\']('
            + "|".join(re.escape(p) for p in self.PLAIN_FORMS)
            + r')["\']'
        )

        # Exclude the dispatcher itself — it uses agent_name as an *output* field
        # (DispatchResult, fallback defaults) not as a lookup key.
        EXCLUDE_FILES = {
            os.path.join(base, "tools/department_hq/services/department_dispatcher.py"),
        }

        for scan_dir in scan_paths:
            result = subprocess.run(
                [
                    "grep",
                    "-rn",
                    "--include=*.py",
                    "-P",
                    r'(prefer_agent|agent_name|target_agent)\s*=\s*["\']('
                    + "|".join(re.escape(p) for p in self.PLAIN_FORMS)
                    + r')["\']',
                    scan_dir,
                ],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                # Filter out excluded files
                lines = [
                    line
                    for line in result.stdout.strip().splitlines()
                    if not any(line.startswith(excl) for excl in EXCLUDE_FILES)
                ]
                if lines:
                    failures.append("\n".join(lines))

        assert not failures, (
            "Found plain-form agent name(s) in dispatch call(s) — use the dotted form "
            "(e.g. 'H.E.R.I.T.A.G.E.' not 'heritage'). Phase 2 will rename agents.name "
            "to the dotted form, so plain-form references will silently miss their target.\n\n" + "\n".join(failures)
        )


# ---------------------------------------------------------------------------
# Cross-department skill fallback (Project #276 Task #2217)
# ---------------------------------------------------------------------------


class TestCrossDepartmentSkillFallback:
    """When the resolved home department has zero agents with the requested
    skill, the coordinator must fall back to a skilled agent in another
    department instead of picking an unskilled dept-director.

    Found live 2026-04-21: capability='documentation' routed to F.O.R.G.E.
    (Engineering, no skill) instead of C.O.D.E.X. (Documentation & Knowledge,
    skill Lv5) because select_agent scored within one department only.
    """

    def _coord_with_cache(self, agent_cache, welfare_cache=None):
        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        coord._agent_cache = agent_cache
        coord._welfare_cache = welfare_cache or {}
        coord._cache_time = float("inf")
        coord._reserved_agents = {}
        import threading

        coord._lock = threading.Lock()
        return coord

    def test_capability_documentation_is_mapped_to_documentation_dept(self):
        """CAPABILITY_DEPARTMENT_MAP must resolve doc-family capabilities."""
        from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

        assert CAPABILITY_DEPARTMENT_MAP.get("documentation") == "Documentation & Knowledge"
        assert CAPABILITY_DEPARTMENT_MAP.get("consolidation_research") == "Documentation & Knowledge"
        assert CAPABILITY_DEPARTMENT_MAP.get("module_audit") == "Documentation & Knowledge"

    def test_unskilled_director_loses_to_skilled_agent_in_other_dept(self):
        """F.O.R.G.E. (Engineering, no doc skill) must lose to
        C.O.D.E.X. (Documentation & Knowledge, doc skill Lv5) when the
        caller passes department='Engineering & Technology' but nobody
        in Engineering has the skill. This is the regression for #2217.
        """
        _, forge_info = _make_agent(
            name="F.O.R.G.E.",
            department="Engineering & Technology",
            skills={"code": 5, "debug": 5},  # no 'documentation'
            is_department_ai=True,
            agent_id=136,
        )
        _, codex_info = _make_agent(
            name="C.O.D.E.X.",
            department="Documentation & Knowledge",
            skills={"documentation": 5, "summarize": 4},
            is_department_ai=True,
            agent_id=146,
        )
        coord = self._coord_with_cache(
            {
                "F.O.R.G.E.": forge_info,
                "C.O.D.E.X.": codex_info,
            }
        )

        selected = coord.select_agent(
            capability="documentation",
            department="Engineering & Technology",
        )
        assert selected is not None
        assert (
            selected["name"] == "C.O.D.E.X."
        ), f"expected cross-dept fallback to C.O.D.E.X., got {selected.get('name')}"

    def test_skilled_home_dept_agent_still_wins_over_cross_dept(self):
        """Fallback must NOT fire when the home dept has a skilled agent."""
        _, forge_info = _make_agent(
            name="F.O.R.G.E.",
            department="Engineering & Technology",
            skills={"code": 5, "code_review": 5},
            is_department_ai=True,
            agent_id=136,
        )
        _, probe_info = _make_agent(
            name="P.R.O.B.E.",
            department="Engineering & Technology",
            skills={"code_review": 4},
            is_department_ai=False,
            agent_id=137,
        )
        _, codex_info = _make_agent(
            name="C.O.D.E.X.",
            department="Documentation & Knowledge",
            skills={"code_review": 3},
            is_department_ai=True,
            agent_id=146,
        )
        coord = self._coord_with_cache(
            {
                "F.O.R.G.E.": forge_info,
                "P.R.O.B.E.": probe_info,
                "C.O.D.E.X.": codex_info,
            }
        )

        selected = coord.select_agent(
            capability="code_review",
            department="Engineering & Technology",
        )
        assert selected is not None
        assert selected["department"] == "Engineering & Technology"

    def test_resolve_department_still_uses_map_when_capability_known(self):
        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        assert coord.resolve_department("documentation") == "Documentation & Knowledge"
        assert coord.resolve_department("code") == "Engineering & Technology"
        # Unknown capabilities still default to Engineering (legacy behavior);
        # the select_agent-layer fallback compensates by cross-dept routing.
        assert coord.resolve_department("totally_made_up_capability") == "Engineering & Technology"


# ---------------------------------------------------------------------------
# Multi-agent multi-skill dispatch coverage (Project #276 Task #2217)
# ---------------------------------------------------------------------------
#
# Verifies routing across the full director roster — not just the C.O.D.E.X. /
# documentation case. Each director lives in their home department with
# domain skills; dispatch for every mapped capability should pick the right
# director (or a skilled specialist if present).


_FULL_ROSTER = {
    # (name, department, skills, is_department_ai, agent_id)
    "A.R.C.H.I.E.": (
        "Executive Office",
        {"governance": 5, "dispatch": 5, "social_post_approve": 5},
        True,
        2,
    ),
    "F.O.R.G.E.": (
        "Engineering & Technology",
        {"code": 5, "code_review": 5, "debug": 5, "code_generation": 4},
        True,
        136,
    ),
    "V.I.G.I.L.": ("Security & Compliance", {"security": 5, "compliance": 5}, True, 200),
    "D.A.R.W.I.N.": ("Research & Development", {"research": 5, "research_synthesis": 4}, True, 201),
    "M.U.S.E.": ("Creative & Design", {"creative": 5, "image_generation": 4, "visual_design": 4}, True, 202),
    "P.I.X.E.L.": (
        "Creative & Design",
        {"vision": 5, "ux_scoring": 4, "image_generation": 5, "multimodal": 4},
        False,
        203,
    ),
    "S.I.G.N.A.L.": ("Marketing & Communications", {"creative_writing": 3}, True, 204),
    "C.O.D.E.X.": (
        "Documentation & Knowledge",
        {
            "documentation": 5,
            "summarize": 4,
            "translate": 5,
            "embedding": 3,
            "knowledge_analysis": 4,
            "module_audit": 3,
            "consolidation_research": 4,
            "summarization": 4,
        },
        True,
        146,
    ),
    "R.E.S.O.L.V.E.": ("Customer Success & Support", {"support": 5}, True, 205),
    "K.I.N.": ("Human Resources & Culture", {"welfare": 5}, True, 206),
    "V.I.T.A.L.": ("Medical & Wellness", {"medical": 5}, True, 207),
    "G.A.V.E.L.": ("Legal & Regulatory", {"legal": 5, "documentation": 4}, True, 208),
    "A.C.C.O.R.D.": ("Diplomatic & External Relations", {"diplomatic": 5}, True, 209),
    "S.P.E.C.T.R.A.": ("Analytics & Intelligence", {"classify": 5, "analyze": 5, "knowledge_analysis": 5}, True, 210),
    "F.A.C.T.": ("News & Media", {"news": 5}, True, 211),
    "B.A.S.E.": ("Operations & Infrastructure", {"infrastructure": 5}, True, 212),
    "C.A.R.G.O.": ("Logistics & Supply Chain", {"logistics": 5}, True, 213),
    "L.E.D.G.E.R.": ("Finance & Accounting", {"finance": 5}, True, 214),
}


def _roster_cache():
    """Build an agent_cache with the full 17-director roster."""
    cache = {}
    for name, (dept, skills, is_ai, agent_id) in _FULL_ROSTER.items():
        _, info = _make_agent(
            name=name,
            department=dept,
            skills=skills,
            is_department_ai=is_ai,
            agent_id=agent_id,
        )
        cache[name] = info
    return cache


class TestMultiAgentDispatchCoverage:
    """Full-roster dispatch coverage — each mapped capability must reach the
    right director (or at minimum, an agent in the right department with
    the matching skill)."""

    def _coord(self):
        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        coord._agent_cache = _roster_cache()
        coord._welfare_cache = {}
        coord._cache_time = float("inf")
        coord._reserved_agents = {}
        import threading

        coord._lock = threading.Lock()
        return coord

    # Every entry in CAPABILITY_DEPARTMENT_MAP should resolve to a department
    # that has at least one active agent in our roster. This catches
    # accidental deletions or typos in the map.
    def test_every_mapped_capability_has_a_department_in_roster(self):
        from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

        roster_departments = {info[0] for info in _FULL_ROSTER.values()}
        missing = []
        for capability, dept in CAPABILITY_DEPARTMENT_MAP.items():
            if dept not in roster_departments:
                missing.append(f"{capability} → {dept}")
        assert not missing, (
            f"CAPABILITY_DEPARTMENT_MAP references departments not in the " f"roster test fixture: {missing}"
        )

    # These are the capability → expected agent selections that the real
    # routing must produce. If any regresses, one of the canonical flows
    # is broken.
    _CAPABILITY_EXPECTATIONS = [
        # (capability, caller_dept, expected_agent)
        ("documentation", "Engineering & Technology", "C.O.D.E.X."),
        ("consolidation_research", "Engineering & Technology", "C.O.D.E.X."),
        ("module_audit", "Engineering & Technology", "C.O.D.E.X."),
        ("translate", "Engineering & Technology", "C.O.D.E.X."),
        ("summarize", "Engineering & Technology", "C.O.D.E.X."),
        ("knowledge_analysis", "Creative & Design", "S.P.E.C.T.R.A."),
        ("classify", "Engineering & Technology", "S.P.E.C.T.R.A."),
        ("analyze", "Documentation & Knowledge", "S.P.E.C.T.R.A."),
        ("security", "Engineering & Technology", "V.I.G.I.L."),
        ("compliance", "Engineering & Technology", "V.I.G.I.L."),
        ("research", "Engineering & Technology", "D.A.R.W.I.N."),
        ("research_synthesis", "Documentation & Knowledge", "D.A.R.W.I.N."),
        ("visual_design", "Engineering & Technology", "M.U.S.E."),
        # When multiple agents in the home dept have the skill, home wins:
        ("code", "Engineering & Technology", "F.O.R.G.E."),
        ("debug", "Engineering & Technology", "F.O.R.G.E."),
        ("support", "Engineering & Technology", "R.E.S.O.L.V.E."),
    ]

    @pytest.mark.parametrize("capability,caller_dept,expected_agent", _CAPABILITY_EXPECTATIONS)
    def test_dispatch_reaches_the_right_agent(self, capability, caller_dept, expected_agent):
        coord = self._coord()
        selected = coord.select_agent(capability=capability, department=caller_dept)
        assert selected is not None, (
            f"capability={capability!r} caller_dept={caller_dept!r}: "
            f"coordinator returned None — expected {expected_agent}"
        )
        assert selected["name"] == expected_agent, (
            f"capability={capability!r} caller_dept={caller_dept!r}: "
            f"expected {expected_agent} but got {selected['name']} "
            f"(dept={selected.get('department')})"
        )

    def test_pixel_preferred_over_muse_for_vision(self):
        """Within Creative & Design, skilled specialist (P.I.X.E.L. with
        vision Lv5) should beat the director (M.U.S.E., no vision skill)."""
        coord = self._coord()
        selected = coord.select_agent(capability="vision", department="Creative & Design")
        assert selected is not None
        assert selected["name"] == "P.I.X.E.L.", (
            f"P.I.X.E.L. Lv5 vision must beat M.U.S.E. (no vision skill); " f"got {selected.get('name')}"
        )

    def test_codex_wins_documentation_over_gavel_despite_both_having_skill(self):
        """C.O.D.E.X. (Doc&K director, Lv5) beats G.A.V.E.L. (Legal, Lv4 doc skill)
        because Documentation & Knowledge is the mapped home department."""
        coord = self._coord()
        selected = coord.select_agent(
            capability="documentation",
            department="Documentation & Knowledge",  # correct home dept
        )
        assert selected is not None
        assert selected["name"] == "C.O.D.E.X."

    def test_unmapped_capability_with_no_skilled_agent_picks_home_best(self):
        """Truly unknown capability, nobody has the skill anywhere — the
        home-dept best (F.O.R.G.E. default) is acceptable as the fallback
        of last resort."""
        coord = self._coord()
        selected = coord.select_agent(
            capability="totally_made_up_capability_xyz",
            department="Engineering & Technology",
        )
        assert selected is not None
        # Some Engineering agent picked — F.O.R.G.E. in this roster
        assert selected["department"] == "Engineering & Technology"


class TestSpecialistPreference:
    """Capability → specialist preference (#3977).

    Found live 2026-06-10: capability='translate' always routed to
    C.O.D.E.X. (Documentation & Knowledge director, translate Lv5) and never
    reached R.O.S.E.T.T.A. (the translation specialist, translate Lv5 +
    French Translation Lv5) because the director's is_department_ai bonus
    (+0.3) wins every equal-proficiency tie. CAPABILITY_SPECIALIST_MAP must
    flip that — as a preference, not a pin.
    """

    DEPT = "Documentation & Knowledge"

    def _coord_with_cache(self, agent_cache, welfare_cache=None):
        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        coord._agent_cache = agent_cache
        coord._welfare_cache = welfare_cache or {}
        coord._cache_time = float("inf")
        coord._reserved_agents = {}
        import threading

        coord._lock = threading.Lock()
        return coord

    def _rosetta_and_codex(self):
        _, rosetta_info = _make_agent(
            name="R.O.S.E.T.T.A.",
            department=self.DEPT,
            skills={"translate": 5, "localization": 5},
            is_department_ai=False,
            agent_id=134,
        )
        _, codex_info = _make_agent(
            name="C.O.D.E.X.",
            department=self.DEPT,
            skills={"translate": 5, "documentation": 5},
            is_department_ai=True,
            agent_id=146,
        )
        return rosetta_info, codex_info

    def test_translate_has_rosetta_as_specialist(self):
        from services.department_coordinator import CAPABILITY_SPECIALIST_MAP

        assert CAPABILITY_SPECIALIST_MAP.get("translate") == "R.O.S.E.T.T.A."

    def test_specialist_outscores_director_at_equal_proficiency(self):
        rosetta_info, codex_info = self._rosetta_and_codex()
        coord = self._coord_with_cache(
            {"R.O.S.E.T.T.A.": rosetta_info, "C.O.D.E.X.": codex_info},
            {134: _make_welfare(), 146: _make_welfare()},
        )

        rosetta_score, rosetta_block = coord.score_agent("R.O.S.E.T.T.A.", rosetta_info, "translate", self.DEPT)
        codex_score, codex_block = coord.score_agent("C.O.D.E.X.", codex_info, "translate", self.DEPT)

        assert rosetta_block is None and codex_block is None
        assert rosetta_score > codex_score, (
            f"specialist R.O.S.E.T.T.A. ({rosetta_score:.3f}) must beat "
            f"director C.O.D.E.X. ({codex_score:.3f}) for translate"
        )

    def test_select_agent_picks_rosetta_for_translate(self):
        rosetta_info, codex_info = self._rosetta_and_codex()
        coord = self._coord_with_cache(
            {"R.O.S.E.T.T.A.": rosetta_info, "C.O.D.E.X.": codex_info},
            {134: _make_welfare(), 146: _make_welfare()},
        )

        selected = coord.select_agent(capability="translate", department=self.DEPT)
        assert selected is not None
        assert selected["name"] == "R.O.S.E.T.T.A.", f"expected R.O.S.E.T.T.A., got {selected.get('name')}"

    def test_preference_not_pin_blocked_specialist_falls_back_to_director(self):
        """A specialist over its 24h token budget must NOT hold the work hostage —
        the healthy director wins (ADR-004 #4090 throttle, not a hard block)."""
        rosetta_info, codex_info = self._rosetta_and_codex()
        coord = self._coord_with_cache(
            {"R.O.S.E.T.T.A.": rosetta_info, "C.O.D.E.X.": codex_info},
            {134: _make_welfare(token_ratio=1.3), 146: _make_welfare()},
        )

        selected = coord.select_agent(capability="translate", department=self.DEPT)
        assert selected is not None
        assert selected["name"] == "C.O.D.E.X.", f"expected fallback to C.O.D.E.X., got {selected.get('name')}"

    def test_distress_opt_out_overrides_specialist_preference(self):
        """The -1.5 distress penalty must beat the +0.75 specialist bonus."""
        rosetta_info, codex_info = self._rosetta_and_codex()
        coord = self._coord_with_cache(
            {"R.O.S.E.T.T.A.": rosetta_info, "C.O.D.E.X.": codex_info},
            {134: _make_welfare(), 146: _make_welfare()},
        )
        coord._distress = {(134, "translate")}
        coord._distress_time = float("inf")

        selected = coord.select_agent(capability="translate", department=self.DEPT)
        assert selected is not None
        assert selected["name"] == "C.O.D.E.X.", f"distressed specialist must step back, got {selected.get('name')}"

    def test_no_bonus_for_other_capabilities(self):
        """R.O.S.E.T.T.A. gets no specialist bonus on a non-mapped capability."""
        rosetta_info, codex_info = self._rosetta_and_codex()
        rosetta_info["skills"]["documentation"] = 5
        coord = self._coord_with_cache(
            {"R.O.S.E.T.T.A.": rosetta_info, "C.O.D.E.X.": codex_info},
            {134: _make_welfare(), 146: _make_welfare()},
        )

        selected = coord.select_agent(capability="documentation", department=self.DEPT)
        assert selected is not None
        assert selected["name"] == "C.O.D.E.X.", "director should still win unmapped capabilities"


class TestNewsBeatClassificationSpecialist:
    """News beat-classification ownership (#4702 Part B).

    WTF beat-classification (wtf_hub ``classify_beat`` task, ~153/day) used to
    dispatch the *generic* ``classify`` capability → Analytics & Intelligence
    (I.R.I.S./W.A.T.C.H.), overloading the Analytics coordinator pool with news
    work. Part B gives News & Media its own ``beat_classification`` capability,
    owned by the beat specialist P.U.B.L.I.S.H. (repurposed to qwen2.5:1.5b), so
    the news team owns its own beat work and the specialist beats the News
    director F.A.C.T. — the same #3977 pattern that flipped translate to
    R.O.S.E.T.T.A.
    """

    DEPT = "News & Media"

    def _coord_with_cache(self, agent_cache, welfare_cache=None):
        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        coord._agent_cache = agent_cache
        coord._welfare_cache = welfare_cache or {}
        coord._cache_time = float("inf")
        coord._reserved_agents = {}
        import threading

        coord._lock = threading.Lock()
        return coord

    def _publish_and_fact(self, *, fact_has_skill: bool = True):
        # P.U.B.L.I.S.H. (#58) — the news beat specialist (small model, not director)
        _, publish_info = _make_agent(
            name="P.U.B.L.I.S.H.",
            department=self.DEPT,
            skills={"beat_classification": 4, "content_classification": 3},
            is_department_ai=False,
            agent_id=58,
        )
        # F.A.C.T. (#2) — the News & Media director (+0.3 is_department_ai bonus)
        fact_skills = {"editorial": 5}
        if fact_has_skill:
            fact_skills["beat_classification"] = 4
        _, fact_info = _make_agent(
            name="F.A.C.T.",
            department=self.DEPT,
            skills=fact_skills,
            is_department_ai=True,
            agent_id=2,
        )
        return publish_info, fact_info

    def test_beat_classification_mapped_to_news(self):
        from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

        assert CAPABILITY_DEPARTMENT_MAP.get("beat_classification") == "News & Media"

    def test_beat_classification_has_publish_as_specialist(self):
        from services.department_coordinator import CAPABILITY_SPECIALIST_MAP

        assert CAPABILITY_SPECIALIST_MAP.get("beat_classification") == "P.U.B.L.I.S.H."

    def test_publish_specialist_outscores_fact_director_at_equal_proficiency(self):
        """Even when the News director F.A.C.T. also holds beat_classification at
        equal proficiency, the +0.75 specialist bonus flips the director's +0.3."""
        publish_info, fact_info = self._publish_and_fact(fact_has_skill=True)
        coord = self._coord_with_cache(
            {"P.U.B.L.I.S.H.": publish_info, "F.A.C.T.": fact_info},
            {58: _make_welfare(), 2: _make_welfare()},
        )

        publish_score, publish_block = coord.score_agent(
            "P.U.B.L.I.S.H.", publish_info, "beat_classification", self.DEPT
        )
        fact_score, fact_block = coord.score_agent("F.A.C.T.", fact_info, "beat_classification", self.DEPT)

        assert publish_block is None and fact_block is None
        assert publish_score > fact_score, (
            f"specialist P.U.B.L.I.S.H. ({publish_score:.3f}) must beat "
            f"director F.A.C.T. ({fact_score:.3f}) for beat_classification"
        )

    def test_select_agent_picks_publish_for_beat(self):
        """Realistic roster — only P.U.B.L.I.S.H. holds the beat skill, so it
        wins over the unskilled director F.A.C.T. (who takes the -1.0 unskilled
        penalty)."""
        publish_info, fact_info = self._publish_and_fact(fact_has_skill=False)
        coord = self._coord_with_cache(
            {"P.U.B.L.I.S.H.": publish_info, "F.A.C.T.": fact_info},
            {58: _make_welfare(), 2: _make_welfare()},
        )

        selected = coord.select_agent(capability="beat_classification", department=self.DEPT)
        assert selected is not None
        assert selected["name"] == "P.U.B.L.I.S.H.", f"expected P.U.B.L.I.S.H., got {selected.get('name')}"


class TestTokenBudgetThrottle:
    """#4090 / ADR-004 — an agent over its 24h token budget is THROTTLED (a healthy
    peer is preferred) but never STARVED.

    The token signal is the 24h rolling ``budget.token_ratio`` (not the stale
    since-midnight ``tokens_used_today`` column). Invariants:
      - over-budget is a score penalty, NOT a hard block (no block_reason);
      - a healthy peer beats an over-budget peer;
      - a SOLE skilled over-budget agent is still selected (F.O.R.G.E. code_review
        must not lose the PR-merge path);
      - a throttled SKILLED agent still beats a healthy UNSKILLED peer (expertise
        outweighs budget);
      - task-queue saturation stays a HARD block.
    """

    DEPT = "Engineering & Technology"

    def _coord(self, agent_cache, welfare_cache):
        import threading

        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        coord._agent_cache = agent_cache
        coord._welfare_cache = welfare_cache
        coord._cache_time = float("inf")
        coord._reserved_agents = {}
        coord._lock = threading.Lock()
        coord._distress = set()
        coord._distress_time = float("inf")
        return coord

    def _forge(self, agent_id=200):
        return _make_agent(
            name="F.O.R.G.E.",
            department=self.DEPT,
            skills={"code_review": 5},
            is_department_ai=True,
            agent_id=agent_id,
        )[1]

    def test_over_budget_agent_is_penalised_not_hard_blocked(self):
        forge = self._forge()
        coord = self._coord({"F.O.R.G.E.": forge}, {200: _make_welfare(token_ratio=1.5)})
        score, block = coord.score_agent("F.O.R.G.E.", forge, "code_review", self.DEPT)
        assert block is None, "over-budget must be a throttle, not a hard block"
        assert score > 0, "max(score, 0.01) floor keeps a sole agent selectable"

    def test_healthy_peer_beats_over_budget_peer(self):
        forge = self._forge(200)
        _, probe = _make_agent(
            name="P.R.O.B.E.",
            department=self.DEPT,
            skills={"code_review": 5},
            is_department_ai=False,
            agent_id=201,
        )
        coord = self._coord(
            {"F.O.R.G.E.": forge, "P.R.O.B.E.": probe},
            {200: _make_welfare(token_ratio=1.5), 201: _make_welfare()},
        )
        selected = coord.select_agent(capability="code_review", department=self.DEPT)
        assert selected is not None
        assert selected["name"] == "P.R.O.B.E.", f"healthy peer must win, got {selected.get('name')}"

    def test_sole_over_budget_skilled_agent_still_selected(self):
        forge = self._forge()
        coord = self._coord({"F.O.R.G.E.": forge}, {200: _make_welfare(token_ratio=2.0)})
        selected = coord.select_agent(capability="code_review", department=self.DEPT)
        assert selected is not None, "a sole over-budget agent must NOT be starved"
        assert selected["name"] == "F.O.R.G.E."

    def test_over_budget_skilled_beats_healthy_unskilled(self):
        forge = self._forge(200)
        _, helper = _make_agent(
            name="HELPER",
            department=self.DEPT,
            skills={},
            is_department_ai=False,
            agent_id=202,
        )
        coord = self._coord(
            {"F.O.R.G.E.": forge, "HELPER": helper},
            {200: _make_welfare(token_ratio=1.3), 202: _make_welfare()},
        )
        selected = coord.select_agent(capability="code_review", department=self.DEPT)
        assert selected is not None
        assert (
            selected["name"] == "F.O.R.G.E."
        ), f"skilled-but-throttled must beat healthy-unskilled, got {selected.get('name')}"

    def test_task_queue_full_remains_hard_block(self):
        forge = self._forge()
        coord = self._coord({"F.O.R.G.E.": forge}, {200: _make_welfare(task_count=10, task_limit=10)})
        score, block = coord.score_agent("F.O.R.G.E.", forge, "code_review", self.DEPT)
        assert score == 0.0
        assert block is not None and "task queue" in block


class TestNewsDedicationWall:
    """News & Media (WTF) dedication wall — #4126 / ADR-010 (#741).

    News is the ONLY dedicated team:
      (1) a News capability never cross-routes OUT of News & Media, and
      (2) a News & Media agent is never pulled cross-department onto non-news
          work (the shared pool covers everything else).
    Enforced in coordinator.find_cross_department_agent + _is_news_capability.
    """

    def _coord_with_cache(self, agent_cache, welfare_cache=None):
        from services.department_coordinator import DepartmentCoordinator

        coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
        coord._agent_cache = agent_cache
        coord._welfare_cache = welfare_cache or {}
        coord._cache_time = float("inf")
        coord._reserved_agents = {}
        import threading

        coord._lock = threading.Lock()
        return coord

    # ---- _is_news_capability classification --------------------------------

    def test_is_news_capability_classification(self):
        from services.department_coordinator import _is_news_capability

        # Core WTF capabilities → news
        for cap in ("fact_check", "bias_analysis", "geo_extraction", "clustering"):
            assert _is_news_capability(cap) is True, f"{cap} should be a news capability"
        # Generic / non-news capabilities
        for cap in ("code", "research", "documentation", "security"):
            assert _is_news_capability(cap) is False, f"{cap} should NOT be a news capability"
        # M.A.V.E.N.'s media-hub caps were re-homed to Operations (#4126)
        for cap in ("media_hub_troubleshoot", "library_search", "library_curation"):
            assert _is_news_capability(cap) is False, f"{cap} is Media Hub (Operations), not news"
        # Edge cases
        assert _is_news_capability(None) is False
        assert _is_news_capability("") is False

    # ---- capability re-home (M.A.V.E.N. → Operations) ----------------------

    def test_media_hub_caps_route_to_operations_not_news(self):
        from services.department_coordinator import CAPABILITY_DEPARTMENT_MAP

        for cap in (
            "media_hub_troubleshoot",
            "media_recommendation",
            "library_search",
            "library_curation",
            "duplicate_triage",
        ):
            assert (
                CAPABILITY_DEPARTMENT_MAP[cap] == "Operations & Infrastructure"
            ), f"{cap} must route to Operations & Infrastructure (M.A.V.E.N. re-home, #4126)"
        # Shared WTF caps STAY in News & Media (held by P.U.B.L.I.S.H./I.N.K.)
        for cap in (
            "fact_check",
            "bias_analysis",
            "geo_extraction",
            "clustering",
            "metadata_enrichment",
            "content_classification",
        ):
            assert CAPABILITY_DEPARTMENT_MAP[cap] == "News & Media", f"{cap} must stay in News & Media"

    # ---- (1) inbound: news work never escapes News & Media ------------------

    def test_news_capability_never_cross_routes_out(self):
        """Even when a non-News agent holds the news skill, news work must not
        cross-route out of News & Media."""
        cache = dict(
            [
                _make_agent(
                    name="F.O.R.G.E.",
                    department="Engineering & Technology",
                    skills={"fact_check": 5},
                    is_department_ai=True,
                    agent_id=200,
                ),
            ]
        )
        coord = self._coord_with_cache(cache)
        result = coord.find_cross_department_agent("fact_check", blocked_department="News & Media")
        assert result is None, "fact_check must never cross-route out of News & Media"

    def test_news_capability_blocked_dept_returns_none(self):
        """A news capability is refused cross-routing regardless of the
        non-news agent pool."""
        cache = dict(
            [
                _make_agent(
                    name="S.P.E.C.T.R.A.",
                    department="Analytics & Intelligence",
                    skills={"bias_analysis": 4},
                    agent_id=210,
                ),
            ]
        )
        coord = self._coord_with_cache(cache)
        assert coord.find_cross_department_agent("bias_analysis", "News & Media") is None

    # ---- (2) outbound: News agents never pulled onto non-news work ----------

    def test_news_agent_not_pulled_for_generic_capability(self):
        """A News & Media agent that happens to hold a generic skill must NOT
        be pulled cross-dept; the shared-pool agent wins instead."""
        cache = dict(
            [
                _make_agent(name="I.N.K.", department="News & Media", skills={"research": 5}, agent_id=23),
                _make_agent(
                    name="D.A.R.W.I.N.",
                    department="Research & Development",
                    skills={"research": 5},
                    is_department_ai=True,
                    agent_id=300,
                ),
            ]
        )
        coord = self._coord_with_cache(cache)
        result = coord.find_cross_department_agent("research", blocked_department="Engineering & Technology")
        assert result is not None
        assert (
            result["name"] == "D.A.R.W.I.N."
        ), f"shared-pool agent must win; News agent must not be pulled, got {result.get('name')}"

    def test_sole_news_holder_of_generic_skill_returns_none(self):
        """If the ONLY holder of a non-news skill is a News agent, cross-dept
        returns None (the News agent stays walled off) rather than leaking."""
        cache = dict(
            [
                _make_agent(name="I.N.K.", department="News & Media", skills={"research": 5}, agent_id=23),
            ]
        )
        coord = self._coord_with_cache(cache)
        result = coord.find_cross_department_agent("research", blocked_department="Engineering & Technology")
        assert result is None, "News agent must not be pulled cross-dept even as sole skill holder"


def test_select_agents_returns_top_n_home_department_only():
    """All Hands #2586: select_agents() returns up to N welfare-gated agents by
    score (home-department only), and n<=0 → []. (score_agent's welfare/K.I.N.
    blocking is covered by the score_agent tests above; here we verify the new
    N-cap + department filter + guard.)"""
    import threading

    from services.department_coordinator import DepartmentCoordinator

    dept = "Research & Development"
    cap = "research"
    _, a1 = _make_agent(name="D.A.R.W.I.N.", department=dept, skills={cap: 5}, is_department_ai=True, agent_id=1)
    _, a2 = _make_agent(name="W.A.T.C.H.", department=dept, skills={cap: 4}, agent_id=2)
    _, a3 = _make_agent(name="S.C.O.U.T.", department=dept, skills={cap: 3}, agent_id=3)
    _, a4 = _make_agent(name="F.O.R.G.E.", department="Engineering & Technology", skills={cap: 5}, agent_id=4)

    welfare = {1: _make_welfare(), 2: _make_welfare(), 3: _make_welfare(), 4: _make_welfare()}
    coord = DepartmentCoordinator.__new__(DepartmentCoordinator)
    coord._agent_cache = {"D.A.R.W.I.N.": a1, "W.A.T.C.H.": a2, "S.C.O.U.T.": a3, "F.O.R.G.E.": a4}
    coord._welfare_cache = welfare
    coord._cache_time = float("inf")
    coord._reserved_agents = {}
    coord._lock = threading.Lock()
    coord._refresh_distress = lambda: None  # no DB

    # n=2 → exactly 2, home-dept only (F.O.R.G.E. is in another dept → never selected)
    top2 = coord.select_agents(cap, 2, department=dept)
    names2 = [a["name"] for a in top2]
    assert len(top2) == 2
    assert "F.O.R.G.E." not in names2

    # n greater than the pool → all 3 in-dept eligible, still no cross-dept
    allc = {a["name"] for a in coord.select_agents(cap, 10, department=dept)}
    assert allc == {"D.A.R.W.I.N.", "W.A.T.C.H.", "S.C.O.U.T."}

    # n<=0 → empty
    assert coord.select_agents(cap, 0, department=dept) == []

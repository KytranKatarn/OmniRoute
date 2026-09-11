"""#6688 — the loadability observer must catch the 2026-09-11 hub freeze.

The incident (KB #315235): the hub could not cold-load any non-resident model
for 2+ days. Repair Bay code-gen was dead in production and NOTHING alerted,
because the already-loaded models kept succeeding and every dashboard read green.

The headline test is `test_fires_on_the_REAL_incident_numbers` — it feeds the
observer the actual measured rows from the incident window. If that ever goes
green-by-vacuity or red, this module has stopped doing the one job it exists for.

Every other test pins ONE clause of the rule as load-bearing: drop the clause and
the observer either misses the incident or alarms on healthy fleets.
"""

from services import model_loadability_monitor as mlm

# Measured on the hub, 2026-09-10 08:00 -> 2026-09-11 08:00 (the 24h before the
# restart that fixed it). qwen2.5-coder:7b was the ONLY model at 0%.
# ``success_seconds`` = how long this model takes on this node WHEN IT WORKS
# (the 30-day LATERAL in _SQL). All four are measured post-restart on
# 2026-09-11: coder 3.7s, gemma3:12b 8.9s, qwen2.5:7b 33.2s median,
# mistral:7b 16.5s. It is the discriminator between the two faults.
INCIDENT_HUB_ROWS = [
    {
        "node_name": "Archie Starbase",
        "model_used": "qwen2.5-coder:7b",
        "attempts": 2,
        "successes": 0,
        "avg_fail_seconds": 401.4,
        "hours_since_success": 56.7,
        "node_success_pct": 94.0,
        "success_seconds": 3.7,
    },
    {
        "node_name": "Archie Starbase",
        "model_used": "gemma3:12b",
        "attempts": 90,
        "successes": 79,
        "avg_fail_seconds": 240.0,
        "hours_since_success": 0.2,
        "node_success_pct": 94.0,
        "success_seconds": 8.9,
    },
    {
        "node_name": "Archie Starbase",
        "model_used": "qwen2.5:7b",
        "attempts": 1832,
        "successes": 1721,
        "avg_fail_seconds": 300.0,
        "hours_since_success": 0.0,
        "node_success_pct": 94.0,
        "success_seconds": 33.2,
    },
    {
        "node_name": "Archie Starbase",
        "model_used": "mistral:7b",
        "attempts": 537,
        "successes": 531,
        "avg_fail_seconds": 120.0,
        "hours_since_success": 0.0,
        "node_success_pct": 94.0,
        "success_seconds": 16.5,
    },
]


def _only(findings):
    assert len(findings) == 1, f"expected exactly one finding, got {findings}"
    return findings[0]


def test_fires_on_the_REAL_incident_numbers():
    """THE regression guard. These are the measured rows, not invented ones."""
    f = _only(mlm.derive_findings(INCIDENT_HUB_ROWS))
    assert f["model"] == "qwen2.5-coder:7b"
    assert f["node_name"] == "Archie Starbase"
    assert f["attempts"] == 2
    assert f["hours_since_success"] == 56.7
    assert f["kind"] == "cannot_load"
    assert "can no longer load this model" in f["detail"]
    # the healthy models must NOT be reported
    assert "gemma3" not in str(findings_text := [x["model"] for x in mlm.derive_findings(INCIDENT_HUB_ROWS)])
    assert findings_text == ["qwen2.5-coder:7b"]


def test_healthy_fleet_is_silent():
    """The normal result is an empty list. An observer that always speaks is noise."""
    healthy = [r for r in INCIDENT_HUB_ROWS if r["model_used"] != "qwen2.5-coder:7b"]
    assert mlm.derive_findings(healthy) == []


class TestEachClauseIsLoadBearing:
    """Drop any one clause and the observer becomes wrong. Proven per clause."""

    def _row(self, **over):
        base = dict(INCIDENT_HUB_ROWS[0])
        base.update(over)
        return [base]

    def test_a_model_that_NEVER_succeeded_here_is_not_reported(self):
        """Without this, a model simply not pulled on a node alarms forever —
        the node_has_model fail-open trap in reverse."""
        assert mlm.derive_findings(self._row(hours_since_success=None)) == []

    def test_a_recent_success_means_it_is_not_stuck(self):
        assert mlm.derive_findings(self._row(hours_since_success=0.5)) == []

    def test_fast_failures_are_a_DIFFERENT_fault(self):
        """MODEL_NOT_FOUND / bad request fail in milliseconds. The freeze times
        out. Reporting the former as a freeze sends people to the wrong place."""
        assert mlm.derive_findings(self._row(avg_fail_seconds=0.3)) == []

    def test_a_sick_NODE_is_not_a_per_model_finding(self):
        """If everything on the node is failing, fleet health owns it."""
        assert mlm.derive_findings(self._row(node_success_pct=20.0)) == []

    def test_any_success_clears_it(self):
        assert mlm.derive_findings(self._row(successes=1)) == []

    def test_a_single_attempt_is_not_yet_evidence(self):
        assert mlm.derive_findings(self._row(attempts=1)) == []

    def test_but_TWO_attempts_IS_enough(self):
        """⚠️ Deliberately low. A frozen model is one almost nothing asks for —
        that is WHY it stays broken. Requiring 3+ would have missed the real
        incident, where the coder managed 2 attempts on the hub in 24 hours."""
        assert len(mlm.derive_findings(self._row(attempts=2))) == 1


class TestTheTwoFaultsAreNamedApart:
    """cannot_load and too_slow are DIFFERENT faults with DIFFERENT fixes.

    Both were live on this fleet on 2026-09-11 at the same time:

      cannot_load  qwen2.5-coder:7b on the hub — nothing completes, VRAM never
                   moves. A ``systemctl restart ollama`` cleared it (420s -> 3.7s).
      too_slow     dolphin3:latest on USS-246 — it DOES complete, measured at
                   325-392s, against a 300s wall. Its failures sit at 300.1s
                   because that IS the deadline. A restart changes nothing.

    Before this split the observer told the truth about WHICH model was failing
    and lied about WHY: it said dolphin3 "can no longer load", which would have
    sent someone to restart a scheduler that was working correctly.

    The discriminator is the success DURATION vs the failure wall — not the
    error text, which is ``timeout after 300s`` in BOTH cases and therefore
    cannot tell them apart.
    """

    # Measured on USS-246, 2026-09-11: successes 325-392s, failures pinned to
    # the 300s wall, the node itself healthy on everything else.
    DOLPHIN_USS246 = {
        "node_name": "Starship - Defiant - USS-246",
        "model_used": "dolphin3:latest",
        "attempts": 6,
        "successes": 0,
        "avg_fail_seconds": 300.1,
        "success_seconds": 358.0,
        "hours_since_success": 19.0,
        "node_success_pct": 96.0,
    }

    def test_a_model_that_runs_but_misses_its_wall_is_too_slow(self):
        f = _only(mlm.derive_findings([dict(self.DOLPHIN_USS246)]))
        assert f["kind"] == "too_slow"
        assert f["success_seconds"] == 358.0

    def test_too_slow_says_a_restart_will_not_help(self):
        """The whole point of the split. If the wording still sends the reader
        to the scheduler, the classification bought nothing."""
        f = _only(mlm.derive_findings([dict(self.DOLPHIN_USS246)]))
        assert "restarting will not help" in f["detail"]
        assert "can no longer load" not in f["detail"]

    def test_cannot_load_does_NOT_claim_to_be_a_deadline_problem(self):
        f = _only(mlm.derive_findings([dict(INCIDENT_HUB_ROWS[0])]))
        assert f["kind"] == "cannot_load"
        assert "restarting will not help" not in f["detail"]

    def test_an_unknown_success_duration_falls_back_to_cannot_load(self):
        """FAIL-SAFE direction. ``success_seconds`` is NULL when the 30-day
        LATERAL finds no successful row to average — and the rule already
        required a prior success, so this is a data gap, not a fast model.
        Guessing 'too slow' from a NULL would tell someone not to restart a
        scheduler that is genuinely frozen: the #6688 incident, un-fixed."""
        row = dict(self.DOLPHIN_USS246, success_seconds=None)
        assert _only(mlm.derive_findings([row]))["kind"] == "cannot_load"

    def test_a_fast_model_on_a_long_wall_is_cannot_load(self):
        """The hub coder ran at 3.7s and its failures sat at 401s. Nothing about
        that is a deadline problem — 3.7s is nowhere near the wall."""
        row = dict(self.DOLPHIN_USS246, success_seconds=3.7, avg_fail_seconds=401.4)
        assert _only(mlm.derive_findings([row]))["kind"] == "cannot_load"

    def test_the_sql_actually_selects_the_discriminator(self):
        """⚠️ The classification is only as good as its input. If _SQL stops
        returning success_seconds every finding silently becomes cannot_load —
        which still LOOKS correct, because that is the fail-safe direction."""
        assert "success_seconds" in mlm._SQL
        assert "avg(t2.duration_ms)" in mlm._SQL, "success duration must come from SUCCESSFUL rows"

    def test_the_alert_title_carries_the_kind(self):
        """send_system dedups on (title, source). If both faults shared a title,
        a node flipping between them would be muted by the other's cooldown —
        the same trap the per-tier backup alarm hit (#5094)."""
        import inspect

        src = inspect.getsource(mlm.check_model_loadability)
        assert "too slow for deadline" in src and "cannot load" in src
        assert 'title=f"Model {_what}' in src, "the kind must be in the TITLE, not only the body"


class TestPerNodeScoping:
    def test_fleet_wide_shaped_data_would_MISS_it_which_is_why_we_scope_per_node(self):
        """During the incident llama3.2:3b read 19 attempts / 17 ok (89%)
        FLEET-WIDE because it succeeded on the Starships while failing on the
        hub. Rows must arrive already split per node."""
        fleet_wide_blend = [
            {
                "node_name": "Archie Starbase",
                "model_used": "llama3.2:3b",
                "attempts": 19,
                "successes": 17,  # the blend hides the hub-only failure
                "avg_fail_seconds": 401.0,
                "hours_since_success": 40.2,
                "node_success_pct": 94.0,
            }
        ]
        assert mlm.derive_findings(fleet_wide_blend) == [], "a blended row must not fire"

        hub_only = dict(fleet_wide_blend[0], attempts=2, successes=0)
        assert len(mlm.derive_findings([hub_only])) == 1, "the per-node split must fire"

    def test_each_finding_names_its_node_so_alerts_do_not_mute_each_other(self):
        """send_system dedups on (title, source) — a shared title would mute
        every node after the first (the tier trap in backup_posture_monitor)."""
        two_nodes = [
            dict(INCIDENT_HUB_ROWS[0]),
            dict(INCIDENT_HUB_ROWS[0], node_name="Starship - Defiant - USS-246"),
        ]
        got = mlm.derive_findings(two_nodes)
        assert len(got) == 2
        assert len({f["node_name"] for f in got}) == 2


class TestFailSafe:
    def test_garbage_rows_are_skipped_never_guessed_at(self):
        assert mlm.derive_findings([{"attempts": "not-a-number"}]) == []
        assert mlm.derive_findings([{}]) == []

    def test_empty_and_none_input(self):
        assert mlm.derive_findings([]) == []
        assert mlm.derive_findings(None) == []

    def test_thresholds_are_overridable_without_a_deploy(self):
        """platform_settings 'loadability:*' tunes it live."""
        row = dict(INCIDENT_HUB_ROWS[0])
        # raising the timeout floor above the observed mean silences it
        assert mlm.derive_findings([row], {"min_fail_seconds": 999.0}) == []
        # lowering it keeps the finding
        assert len(mlm.derive_findings([row], {"min_fail_seconds": 10.0})) == 1


def test_check_never_raises_even_when_the_db_is_gone(monkeypatch):
    """Same contract as residency_monitor.check_residency: an observer that can
    break its caller is worse than no observer."""

    def _boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr(mlm, "_load_rows", _boom)
    out = mlm.check_model_loadability()
    assert out["ok"] is False and out["findings"] == [] and "db down" in out["error"]


def test_the_sql_excludes_admission_gate_sheds():
    """.claude/rules/fleet.md: shed rows carry a model_used with ZERO inference.
    Counting them measures the GATE, not the model, and would manufacture
    findings during any traffic burst."""
    for needle in ("hub saturated", "admission cap", "shed to relieve", "backpressure"):
        assert needle in mlm._SQL, f"{needle} filter missing from the query"


class TestBothObserversAreActuallyScheduled:
    """THE POINT OF #6688. residency_monitor.py was complete and correct since
    #2987 and had ZERO callers — while two sibling docstrings asserted it was
    "already live". A monitor nobody runs is worse than no monitor, because the
    claim stops anyone from looking. These tests fail if either job is dropped.
    """

    def _agent_loop_source(self):
        import pathlib

        # Read the file rather than importing it: agent_loop pulls in the whole
        # scheduler stack, and this assertion is about REGISTRATION, not runtime.
        for p in (
            pathlib.Path("/app/../ai_bridge/agent_loop.py"),
            pathlib.Path("/mnt/archie_brain/ai_bridge/agent_loop.py"),
        ):
            if p.exists():
                return p.read_text()
        import pytest

        pytest.skip("agent_loop.py not reachable from this test root")

    def test_loadability_monitor_is_registered(self):
        src = self._agent_loop_source()
        assert "from services.model_loadability_monitor import check_model_loadability" in src
        assert 'id="model_loadability_monitor"' in src

    def test_residency_observer_is_registered(self):
        src = self._agent_loop_source()
        assert "from services.residency_monitor import check_residency" in src
        assert 'id="residency_monitor"' in src

    def test_the_false_already_live_docstrings_are_corrected(self):
        import pathlib

        for rel in ("services/residency_activation.py", "services/residency_profiles.py"):
            for root in ("/app", "/mnt/archie_brain/platform_v2"):
                p = pathlib.Path(root) / rel
                if p.exists():
                    txt = p.read_text()
                    assert "is already live" not in txt, f"{rel} still claims the observer is live"
                    break


class TestProducerConsumerSplit:
    """#6688 — the PANEL must never compute this.

    Measured on the live table, the query takes 10-16s: hours_since_success is a
    correlated subquery over task_execution_log run once per (node, model), and
    bounding it to 30 days barely moved the number because the table is enormous
    even over 30 days. A per-worker TTL cache does not save you — it just means
    every gunicorn worker eats the 12s once per window, on a request an operator
    is waiting on. So the 30-minute job PRODUCES and the panel READS one row.
    """

    def test_the_display_read_does_not_touch_the_expensive_query(self, monkeypatch):
        """THE regression guard. If findings_for_display ever calls _load_rows
        again, the Cluster tab goes back to blocking for 12 seconds."""
        called = []
        monkeypatch.setattr(mlm, "_load_rows", lambda *a, **k: called.append(1) or [])
        mlm.findings_for_display()
        assert not called, "findings_for_display must NOT run the slow query"

    def test_the_job_persists_before_it_alerts(self):
        """Order matters: the panel must reflect the latest state even when
        Telegram is down, and a failed alert must not cost the panel its data."""
        import inspect

        src = inspect.getsource(mlm.check_model_loadability)
        assert "_persist(findings)" in src
        assert src.index("_persist(findings)") < src.index("send_system"), "persist must come BEFORE alerting"

    def test_an_empty_result_clears_a_previous_finding(self):
        """Writing [] is deliberate — once the fault is fixed the badge must go
        away. A producer that only ever writes findings leaves a stale warning up
        forever, which is the same 'confidently wrong panel' class being fixed."""
        import inspect

        src = inspect.getsource(mlm.check_model_loadability)
        # _persist is called unconditionally, not guarded by `if findings:`
        i = src.index("_persist(findings)")
        preceding = src[:i].rstrip().splitlines()[-1]
        assert "if findings" not in preceding, "persist must be unconditional so [] clears"

    def test_display_read_fails_safe_to_empty(self, monkeypatch):
        def _boom(*_a, **_k):
            raise RuntimeError("db down")

        monkeypatch.setattr(mlm, "_SETTING_LAST", "loadability:does_not_exist")
        assert mlm.findings_for_display() == []

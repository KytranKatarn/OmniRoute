"""The patient-model escalation must reach the patient model, or not claim its window (#6779).

THE DEFECT, measured live 2026-09-16.

  can_node_run_model('gemma3:12b') -> ['Archie Starbase']      (the hub, only)
  _review_preferred_nodes()        -> [Runabout, Defiant]      (the 7B cluster)
  OVERLAP                          -> set()

_dispatch_json_review passed BOTH — prefer_model=gemma3:12b and preferred_node=<7B cluster>.
The pin won. The probe returned status='parsed' having been "served on Starship - Runabout -
USS-245", a node that cannot hold a 12B. So the escalation did not fail; it SUCCEEDED carrying
the wrong model, and nothing reported the substitution.

The damage is not the wrong model per se — it is that `_review_is_strong` is the ONE definition
shared by the model choice and the coverage note's cap. It answered "does this DESERVE the
patient model?" while every consumer needed "will this GET it?". So the prompt was built at the
18,768 strong cap, served by a 7B (slow enough to fail), and the freeform retry re-truncated to
9,000 — producing the 89% / 49% partial-coverage demotions that made two PRs unmergeable.

_review_preferred_nodes' own docstring had already carved this out for the gemma3:12b
self-refute auditor ("the 4GB Runabout cannot hold a 12B ... so it keeps Defiant+hub"). The
knowledge existed; it was not wired at THIS call site — the same shape as #5194 / #5862 / #2738.
"""

import inspect
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.repair_bay.services import pr_diff_analyzer as A  # noqa: E402

_BIG = "x" * 12000  # comfortably over the 9,000 weak cap


class TestStrongMeansReachable(unittest.TestCase):
    """The semantic fix. Everything else follows from this one word."""

    def test_unreachable_patient_model_is_not_strong(self):
        with mock.patch.object(A, "_nodes_for_model", return_value=[]):
            self.assertFalse(A._review_is_strong({"title": "t"}, _BIG))

    def test_unreachable_beats_even_a_tier3_pr(self):
        """Tier 3 is the RISK reason to escalate. It cannot conjure a model onto a node."""
        with mock.patch.object(A, "_nodes_for_model", return_value=[]), mock.patch(
            "tools.repair_bay.services.pr_review_service.classify_pr_tier", return_value=3
        ):
            self.assertFalse(A._review_is_strong({"title": "t"}, _BIG))

    def test_reachable_still_escalates(self):
        """NON-VACUITY. A fix that simply disabled escalation would pass every test above
        while quietly deleting the wide window for good."""
        with mock.patch.object(A, "_nodes_for_model", return_value=["archie-starbase"]):
            self.assertTrue(A._review_is_strong({"title": "t"}, _BIG))

    def test_the_cap_follows_the_same_answer(self):
        """The note, the prompt and the model must not be able to disagree — that drift IS
        the bug. Same input, three consumers, one source."""
        with mock.patch.object(A, "_nodes_for_model", return_value=[]):
            self.assertEqual(
                A._diff_cap_for_model(A._review_is_strong({"title": "t"}, _BIG)),
                A._diff_cap_for_model(False),
            )
        with mock.patch.object(A, "_nodes_for_model", return_value=["archie-starbase"]):
            self.assertEqual(
                A._diff_cap_for_model(A._review_is_strong({"title": "t"}, _BIG)),
                A._diff_cap_for_model(True),
            )


class TestThePinFollowsTheModel(unittest.TestCase):
    # The 7B cluster, fixed here so the assertions do not depend on live fleet state.
    SEVEN_B = ["starship_5501c2766526e746", "starship_76583490e36955ab"]

    def _capture_dispatch(self, kw, capable):
        """Run _dispatch_json_review with ONLY `dispatch` stubbed; return its kwargs.

        Deliberately NOT a sys.modules stub of the whole dispatcher: _review_preferred_nodes
        imports _REVIEW_CLUSTER from that module, so replacing it wholesale made the pin
        resolve differently inside the patch than outside and the test measured the mock
        rather than the code. Patch the one function under test's control.
        """
        seen = {}

        class _R:
            queued = False
            success = True
            response = '{"issues": [], "verdict": "APPROVE", "confidence": 1.0}'

        def _fake_dispatch(**kwargs):
            seen.update(kwargs)
            return _R()

        with mock.patch(
            "tools.department_hq.services.department_dispatcher.dispatch", _fake_dispatch
        ), mock.patch.object(A, "_nodes_for_model", return_value=capable), mock.patch.object(
            A, "_review_preferred_nodes", return_value=list(self.SEVEN_B)
        ):
            A._dispatch_json_review("p", dict(kw))
        return seen

    def test_a_model_request_pins_to_nodes_that_can_serve_it(self):
        seen = self._capture_dispatch({"prefer_model": "gemma3:12b"}, capable=["archie-starbase"])
        self.assertEqual(seen["preferred_node"], ["archie-starbase"])
        self.assertEqual(seen["prefer_model"], "gemma3:12b")

    def test_never_pins_a_model_request_to_the_7b_cluster(self):
        """THE REGRESSION GUARD. This is the exact live failure."""
        seen = self._capture_dispatch({"prefer_model": "gemma3:12b"}, capable=["archie-starbase"])
        for node in self.SEVEN_B:
            if node != "archie-starbase":
                self.assertNotIn(node, seen["preferred_node"], f"pinned {node}, which cannot hold a 12B")

    def test_an_unplaceable_model_is_not_requested_at_all(self):
        """Asking for a model nothing can serve buys a doomed slow dispatch and then a
        fallback. Drop the ask; take the honest 7B review."""
        seen = self._capture_dispatch({"prefer_model": "gemma3:12b"}, capable=[])
        self.assertNotIn("prefer_model", seen)
        self.assertEqual(seen["preferred_node"], self.SEVEN_B)

    def test_the_default_7b_path_is_unchanged(self):
        """NON-REGRESSION: no prefer_model -> the Runabout-first pin (#5861/#6099) stands."""
        seen = self._capture_dispatch({}, capable=["archie-starbase"])
        self.assertEqual(seen["preferred_node"], self.SEVEN_B)
        self.assertNotIn("prefer_model", seen)


class TestNodeResolutionIsSafe(unittest.TestCase):
    def test_empty_model_resolves_to_nothing(self):
        self.assertEqual(A._nodes_for_model(""), [])
        self.assertEqual(A._nodes_for_model(None), [])

    def test_it_fails_closed_not_open(self):
        """Fail-OPEN would restore the doomed dispatch this exists to prevent."""
        A._TIER3_PLACEABLE_CACHE.update({"at": 0.0, "nodes": None, "model": None})
        with mock.patch("database.get_db_cursor", side_effect=RuntimeError("db down")):
            self.assertEqual(A._nodes_for_model("gemma3:12b"), [])

    def test_it_requires_capacity_AND_presence(self):
        """can_node_run_model and node_has_model disagree on real nodes (#5862); a pin to a
        node that fits the model but has not pulled it is the same wasted dispatch."""
        src = inspect.getsource(A._nodes_for_model)
        self.assertIn("can_node_run_model", src)
        self.assertIn("node_has_model", src)


if __name__ == "__main__":
    unittest.main()


class TestItUsesTheParameterThatActuallyBinds(unittest.TestCase):
    """prefer_model vs model_override — the difference is the whole bug.

    The dispatcher's own docstring for prefer_model:

        "Resolved to the first matching agent in the roster; IF NO AGENT USES THE MODEL,
         routing falls back to capability-based selection."

    Silently. Measured 2026-09-16: the only non-decommissioned agents carrying gemma3:12b
    are K.I.N. (Human Resources) and V.I.G.I.L. (Security). Neither serves the `code_review`
    capability — V.I.G.I.L.'s 'gh:code-review' is a GitHub-ingested skill NAME, not the
    capability. So every escalation resolved to no agent, fell back to F.O.R.G.E., and ran
    qwen2.5:7b. The patient-model path had never once run the patient model.

    model_override binds to the agent actually selected (`model = model_override or
    agent.get("model") or "qwen2.5:7b"`), and the coordinator model-floor explicitly yields
    to a caller-pinned model, so it survives the rest of the pipeline.
    """

    def test_the_escalation_sets_model_override(self):
        src = inspect.getsource(A._structured_review)
        self.assertIn("model_override", src)

    def test_it_does_not_use_the_parameter_that_silently_falls_back(self):
        """THE REGRESSION GUARD. Reverting to prefer_model restores a silent no-op."""
        src = inspect.getsource(A._structured_review)
        self.assertNotIn('kw["prefer_model"]', src)

    def test_the_pin_recognises_either_spelling(self):
        """_dispatch_json_review must compute the node pin from whichever key carries the
        model, or a future caller using the other one re-opens the wrong-node bug."""
        src = inspect.getsource(A._dispatch_json_review)
        self.assertIn("model_override", src)
        self.assertIn("prefer_model", src)

    def test_no_code_review_agent_carries_the_tier3_model(self):
        """The standing fact this fix works around. If someone later gives a code_review
        agent gemma3:12b, prefer_model would start working and this test should be REVISITED
        (not deleted) — the override still binds harder, so the fix stays correct either way.
        Skips without DB access rather than passing vacuously."""
        try:
            from database import get_db_cursor

            with get_db_cursor() as (_c, cur):
                cur.execute(
                    "SELECT count(*) AS n FROM agents a JOIN agent_skills s ON s.agent_id=a.id "
                    "WHERE a.model ILIKE %s AND s.skill_name = %s "
                    "AND a.shift_state <> 'decommissioned'",
                    ("%gemma%", "code_review"),
                )
                row = cur.fetchone()
        except Exception:
            self.skipTest("no DB access from this test environment")
        self.assertEqual(row["n"], 0, "a code_review agent now carries gemma3:12b — revisit this fix's rationale")


class TestAQueuedEscalationIsAwaitedNotAbandoned(unittest.TestCase):
    """Returning 'queued' on an escalation GUARANTEES the demotion it was avoiding.

    The freeform fallback runs at the WEAK cap — the very cap that could not cover the
    diff that triggered the escalation. So abandoning a queued escalation is not a
    graceful degradation; it is the coverage demotion, with extra steps.

    dispatch_awaiting_queue was built for exactly this and says so: "The F.O.R.G.E.
    review path is the caller that never got the workaround — so an escalated review
    silently degraded to the weak model on a truncated diff (#6023)." It was wired into
    the freeform path (#6247) and not this one.
    """

    def _run(self, kw, *, queued_text=None):
        seen = {"awaited": False, "await_kw": None}

        class _Q:
            queued = True
            success = False
            response = ""

        def _fake_dispatch(**kwargs):
            return _Q()

        def _fake_await(**kwargs):
            seen["awaited"] = True
            seen["await_kw"] = kwargs
            return queued_text

        with mock.patch("tools.department_hq.services.department_dispatcher.dispatch", _fake_dispatch), mock.patch(
            "tools.department_hq.services.department_dispatcher.dispatch_awaiting_queue",
            _fake_await,
        ), mock.patch.object(A, "_nodes_for_model", return_value=["archie-starbase"]), mock.patch.object(
            A, "_review_preferred_nodes", return_value=["starship_5501c2766526e746"]
        ):
            parsed, status = A._dispatch_json_review("p", dict(kw))
        return parsed, status, seen

    def test_an_escalation_waits_and_can_still_succeed(self):
        parsed, status, seen = self._run(
            {"model_override": "gemma3:12b"},
            queued_text='{"issues": [], "verdict": "APPROVE", "confidence": 1.0}',
        )
        self.assertTrue(seen["awaited"], "a queued escalation was abandoned")
        self.assertEqual(status, "parsed")
        self.assertTrue(parsed)

    def test_the_wait_carries_the_model_and_the_matching_pin(self):
        _p, _s, seen = self._run({"model_override": "gemma3:12b"}, queued_text="{}")
        self.assertEqual(seen["await_kw"]["model_override"], "gemma3:12b")
        self.assertEqual(seen["await_kw"]["preferred_node"], ["archie-starbase"])

    def test_the_default_7b_path_does_NOT_block(self):
        """NON-REGRESSION, and the reason this is conditional: the single-pass 7B path
        returns fast and lands its verdict via the async callback. Waiting there would
        stall every ordinary review for no gain."""
        parsed, status, seen = self._run({})
        self.assertFalse(seen["awaited"], "the default path now blocks on the queue")
        self.assertEqual(status, "queued")
        self.assertIsNone(parsed)

    def test_a_wait_that_yields_nothing_degrades_honestly(self):
        """It must report 'queued' so the coverage note tells the truth about the cap."""
        parsed, status, seen = self._run({"model_override": "gemma3:12b"}, queued_text=None)
        self.assertTrue(seen["awaited"])
        self.assertEqual(status, "queued")
        self.assertIsNone(parsed)

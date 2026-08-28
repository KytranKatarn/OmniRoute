"""Social video generation must be welfare-gated and honestly attributed (#5346).

`social_video_worker.process_queue` called `_generate_local` / `_generate_cloud`
directly — ZERO dispatcher references, no welfare, C.R.E.E.D. or cost gating — and
hardcoded its task_execution_log row to `(13, "P.I.X.E.L.")` **unconditionally**.
That is worse than #5345's fallback: it credited an agent that may have had no
capacity at all, which makes the Token Economy's per-agent view fiction.

Same fix, same shape as #5345: `coordinator.select_agent` already scores on
stress / energy / utilisation and returns None when nothing qualifies, so asking
it and HONOURING the answer is the whole gate.

⚠️ SAME TRAP AS #5345: this path ALREADY writes attribution (3 task_execution_log
references). Adding telemetry_writer.log_marker alongside would double-count
social video generation. The assertions below exist to catch that.
"""

import inspect
import re


import tools.media_studio.services.social_video_worker as svw

QUEUE_SRC = inspect.getsource(svw.process_queue)
LOG_SRC = inspect.getsource(svw._write_task_log)
MOD_SRC = inspect.getsource(svw)


class TestWelfareGate:
    def test_queue_asks_dhq_for_an_agent(self):
        assert "select_agent" in QUEUE_SRC
        assert '"video_generation"' in QUEUE_SRC
        assert '"Creative & Design"' in QUEUE_SRC

    def test_no_agent_defers_without_processing(self):
        """Assert on CODE, not prose — `"failed"` also appears in the comment
        explaining that nothing is failed, which a bare substring check flags."""
        m = re.search(r"if not agent:(.*?)return", QUEUE_SRC, re.S)
        assert m, "no deferral guard found"
        block = m.group(1)
        assert "_process_item" not in block, "deferring must not process items"
        assert 'status="failed"' not in block, "deferring is not failing"
        assert "update_queue_item" not in block, "deferring must not mutate the queue at all"

    def test_deferral_precedes_fetching_and_processing(self):
        """Items keep status='generating' and are re-queried next cycle."""
        assert QUEUE_SRC.index("if not agent:") < QUEUE_SRC.index("get_queue_items")
        assert QUEUE_SRC.index("if not agent:") < QUEUE_SRC.index("_process_item")

    def test_lookup_error_fails_open(self):
        """A coordinator fault must not stall ALL social video generation."""
        m = re.search(r"except Exception as exc:(.*?)(?=\n    \w)", QUEUE_SRC, re.S)
        assert m, "except block not found"
        assert "return" not in m.group(1), "an ERROR is not a capacity refusal — fail open"


class TestAttributionIsHonest:
    def test_agent_is_threaded_to_the_log_writer(self):
        assert "agent=agent" in inspect.getsource(svw._process_item) or "agent=agent" in MOD_SRC
        assert "agent=None" in inspect.getsource(
            svw._write_task_log.__wrapped__ if hasattr(svw._write_task_log, "__wrapped__") else svw._write_task_log
        )

    def test_hardcoded_agent_is_now_only_a_fallback(self):
        assert '(agent or {}).get("id") or 13' in LOG_SRC
        assert '(agent or {}).get("name") or "P.I.X.E.L."' in LOG_SRC

    def test_unconditional_hardcode_is_gone(self):
        assert (
            '(13, "P.I.X.E.L.", model' not in MOD_SRC
        ), "attribution must not be hardcoded regardless of who DHQ selected"


class TestNoDoubleCounting:
    """Assert against CODE, not prose.

    A first draft of these tests counted the bare words "task_execution_log" and
    "log_marker" across the module source — and failed on the docstrings that
    WARN about double-counting. A predicate that matches its own documentation is
    not testing anything; target the executable form instead.
    """

    def test_exactly_one_attribution_insert(self):
        assert (
            MOD_SRC.count("INSERT INTO task_execution_log") == 1
        ), "this path must write exactly ONE attribution row per generation"

    def test_log_marker_is_never_CALLED(self):
        assert "log_marker(" not in MOD_SRC, (
            "this path already INSERTs its own row — a log_marker CALL would "
            "double-count social video generation on the Token Economy"
        )

    def test_attribution_write_is_still_non_fatal(self):
        assert "except Exception" in LOG_SRC, "a telemetry failure must not break generation"

"""The chunk loop: worst-wins verdict, union coverage, killswitch at 1 (#5848)."""

import sys
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from tools.repair_bay.services import pr_diff_analyzer as pda  # noqa: E402


def test_default_is_one_chunk():
    """The killswitch default. At 1, nothing about today's behaviour changes."""
    with mock.patch.object(pda, "_get_setting", return_value=None):
        assert pda._review_max_chunks() == 1


def test_setting_is_clamped_to_three():
    with mock.patch.object(pda, "_get_setting", return_value="99"):
        assert pda._review_max_chunks() == 3


def test_garbage_setting_falls_back_to_one():
    with mock.patch.object(pda, "_get_setting", return_value="banana"):
        assert pda._review_max_chunks() == 1


def test_one_chunk_calls_structured_review_exactly_once():
    calls = []
    with mock.patch.object(pda, "_review_max_chunks", return_value=1), mock.patch.object(
        pda, "_structured_review", side_effect=lambda *a, **k: calls.append(k) or "VERDICT: APPROVE"
    ):
        pda._obtain_review_summary({"title": "t"}, "diff --git a/a.py b/a.py\n+x\n", 1, "r")
    assert len(calls) == 1


def test_every_chunk_is_grounded_against_the_full_diff():
    seen = []

    def fake(review, diff, pr_number=None, repo=None, ground_diff=None, dockerfile_findings=None):
        seen.append((diff, ground_diff))
        return "VERDICT: APPROVE"

    full = "".join(f"diff --git a/f{i}.py b/f{i}.py\n@@ -1 +1 @@\n+{'z'*400}\n" for i in range(6))
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=500
    ), mock.patch.object(pda, "_structured_review", side_effect=fake):
        pda._obtain_review_summary({"title": "t"}, full, 1, "r")
    assert len(seen) > 1, "a diff over the cap must produce multiple passes"
    for shown, ground in seen:
        assert ground == full, "grounding must ALWAYS be the full diff"
        assert len(shown) <= len(full)


def test_a_truncated_chunk_does_not_swallow_the_next_chunks_first_file():
    """Union coverage must survive a mid-line cut at a chunk boundary.

    _truncate_diff cuts an oversized chunk mid-line. Joining the chunks with "" glues that
    cut line straight onto the next chunk's "diff --git" header, so the ^diff --git MULTILINE
    regex stops matching and a file that WAS reviewed is reported as dropped.
    """
    big = "diff --git a/big.py b/big.py\n--- a/big.py\n+++ b/big.py\n@@ -1 +1 @@\n+" + ("q" * 12000) + "\n"
    small = "".join(f"diff --git a/s{i}.py b/s{i}.py\n@@ -1 +1 @@\n+{'y' * 200}\n" for i in range(3))
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), mock.patch.object(
        pda, "_diff_cap_for_model", return_value=9000
    ), mock.patch.object(pda, "_structured_review", return_value="VERDICT: APPROVE"):
        out = pda._obtain_review_summary({"title": "t"}, big + small, 1, "r") or ""
    assert "s0.py" not in out, "s0.py sat in a later chunk and was reviewed — it must not read as dropped"


# --------------------------------------------------------------- #6247: queued != lost
#
# A cold-loading chunk used to return None, which _merge_chunk_summaries could not
# distinguish from a lost pass — so the fail-closed lattice demoted a clean APPROVE to
# NEEDS REVIEW, and parse_verdict reads the demotion. Reliability got WORSE as chunk
# count rose, which is very likely why max_chunks was flipped 1->3 and rolled back the
# same day (#5861). Fail-closed itself is CORRECT and must stay; the bug was only ever
# calling live queued work "unparseable" (KB #276153).


def test_single_pass_does_NOT_await_the_queue():
    """The default path must stay byte-identical: fast return + async callback.

    Making the single-pass blocking would hold a web worker for the poll timeout —
    the "never sync-dispatch on the web thread" rule.
    """
    seen = {}

    def _fake_run(prompt, pr_number=None, repo=None, diff=None, await_queue=False):
        seen["await_queue"] = await_queue
        return "SUMMARY\nx\n\nVERDICT: APPROVE"

    with mock.patch.object(pda, "_review_max_chunks", return_value=1), \
         mock.patch.object(pda, "_structured_review", return_value=None), \
         mock.patch.object(pda, "_run_forge_review", side_effect=_fake_run), \
         mock.patch.object(pda, "_gate_freeform_review", side_effect=lambda s, *a, **k: s):
        pda._obtain_review_summary({"pr_number": 1, "title": "t", "body": ""}, "diff --git a/x b/x\n+1\n", 1, "o/r")

    assert seen.get("await_queue") is False, "single-pass must not block on the queue"


def test_chunked_DOES_await_the_queue():
    """>1 pass: the merge needs every pass in hand, so a cold model must be waited for."""
    seen = []

    def _fake_run(prompt, pr_number=None, repo=None, diff=None, await_queue=False):
        seen.append(await_queue)
        return "SUMMARY\nx\n\nVERDICT: APPROVE"

    big = "\n".join(f"diff --git a/f{i} b/f{i}\n--- a/f{i}\n+++ b/f{i}\n" + "+x\n" * 400
                    for i in range(6))
    with mock.patch.object(pda, "_review_max_chunks", return_value=3), \
         mock.patch.object(pda, "_structured_review", return_value=None), \
         mock.patch.object(pda, "_run_forge_review", side_effect=_fake_run), \
         mock.patch.object(pda, "_gate_freeform_review", side_effect=lambda s, *a, **k: s):
        pda._obtain_review_summary({"pr_number": 2, "title": "t", "body": ""}, big, 2, "o/r")

    assert seen, "the freeform fallback should have run for each chunk"
    if len(seen) > 1:
        assert all(seen), "every chunked pass must await the queue"


def test_await_path_keeps_num_ctx_AND_preferred_node():
    """🔴 The regression this nearly shipped.

    dispatch_awaiting_queue's signature carries neither num_ctx nor preferred_node.
    Routing the reviewer through it without widening the helper would silently drop
    the QW-5 review window and the #5861 Runabout-first routing — trading a
    fail-closed verdict for a quietly DEGRADED one, which is strictly worse because
    nothing reports it.
    """
    captured = {}

    def _fake_await(**kw):
        captured.update(kw)
        return "SUMMARY\nx\n\nVERDICT: APPROVE"

    import tools.department_hq.services.department_dispatcher as dd
    with mock.patch.object(dd, "dispatch_awaiting_queue", side_effect=_fake_await), \
         mock.patch.object(pda, "_review_num_ctx", return_value=8192), \
         mock.patch.object(pda, "_review_preferred_nodes", return_value=["node-a"]), \
         mock.patch.object(pda, "_gate_freeform_review", side_effect=lambda s, *a, **k: s):
        out = pda._run_forge_review("p", 3, "o/r", diff="d", await_queue=True)

    assert out and "APPROVE" in out
    assert captured.get("num_ctx") == 8192, "the review window must survive the await path"
    assert captured.get("preferred_node") == ["node-a"], "routing must survive the await path"
    assert captured.get("capability") == "code_review"


def test_await_timeout_still_fails_closed():
    """A pass we genuinely cannot read must still fail closed — that behaviour is correct.

    None here does NOT mean the work was lost: the queue row survives for the worker.
    It means THIS pass has no content to merge.
    """
    import tools.department_hq.services.department_dispatcher as dd
    with mock.patch.object(dd, "dispatch_awaiting_queue", return_value=None), \
         mock.patch.object(pda, "_review_num_ctx", return_value=4096), \
         mock.patch.object(pda, "_review_preferred_nodes", return_value=[]):
        assert pda._run_forge_review("p", 4, "o/r", diff="d", await_queue=True) is None


def test_dispatch_awaiting_queue_FORWARDS_the_kwargs():
    """The other half of the guard above.

    The previous test mocks dispatch_awaiting_queue, so it proves the REVIEWER passes
    num_ctx/preferred_node — not that the DISPATCHER forwards them to request_work.
    A helper that accepted and silently dropped them would pass that test and still
    ship the degraded review. Assert the forwarding itself.
    """
    import tools.department_hq.services.department_dispatcher as dd

    captured = {}

    class _R:
        success, response, queued = True, "ok", False

    class _D:
        def request_work(self, **kw):
            captured.update(kw)
            return _R()

    with mock.patch.object(dd, "get_dispatcher", return_value=_D()):
        out = dd.dispatch_awaiting_queue(
            capability="code_review", prompt="p", module_id="repair_bay",
            num_ctx=8192, preferred_node=["node-a"],
        )
    assert out == "ok"
    assert captured.get("num_ctx") == 8192
    assert captured.get("preferred_node") == ["node-a"]


def test_dispatch_awaiting_queue_is_UNCHANGED_for_callers_that_omit_them():
    """Byte-identical for every pre-existing caller: the keys must not appear at all.

    Passing num_ctx=None / preferred_node=None explicitly is NOT the same as omitting
    them — request_work's defaults and any downstream `in kwargs` check would see a key
    that was never there before.
    """
    import tools.department_hq.services.department_dispatcher as dd

    captured = {}

    class _R:
        success, response, queued = True, "ok", False

    class _D:
        def request_work(self, **kw):
            captured.update(kw)
            return _R()

    with mock.patch.object(dd, "get_dispatcher", return_value=_D()):
        dd.dispatch_awaiting_queue(capability="summarize", prompt="p", module_id="m")

    assert "num_ctx" not in captured, "must not appear for callers that never passed it"
    assert "preferred_node" not in captured, "must not appear for callers that never passed it"

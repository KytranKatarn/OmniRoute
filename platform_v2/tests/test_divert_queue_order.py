"""#5372 — the DIVERT mobility profile must reach the dispatch_pending_queue drain.

The A.R.M.A.D.A. profile moved warmth, node routing and backlog promotion since
#5132, but the queue drain claimed rows in pure priority order — a NEWS divert
left the news backlog waiting behind platform rows. These tests pin the
stable-split ordering in model_dispatch_service._profile_ordered_ids:
profile-matching rows first, DB order preserved within each group, and — the
critical property — it is a SPLIT, never a FILTER (a non-matching row still
drains; a filtering implementation starves whole domains).
"""

from unittest import mock

from services import model_dispatch_service as mds


def _row(rid, module_id=None, capability=None):
    return {"id": rid, "capability": capability, "module_id": module_id}


# module_id keyword matching in fleet_dispatch_profile.NEWS_MODULE_KEYWORDS is
# deterministic ('wtf' → news); capability→department mapping can drift, so the
# fixtures use module_id as the news signal.
NEWS = lambda rid: _row(rid, module_id="wtf_quality_scorer")  # noqa: E731
PLAT = lambda rid: _row(rid, module_id="email_manager")  # noqa: E731


def test_news_mode_promotes_news_rows_stably():
    rows = [PLAT(1), NEWS(2), PLAT(3), NEWS(4)]
    assert mds._profile_ordered_ids(rows, "news", 4) == [2, 4, 1, 3]


def test_platform_mode_promotes_non_news_stably():
    rows = [PLAT(1), NEWS(2), PLAT(3), NEWS(4)]
    assert mds._profile_ordered_ids(rows, "platform", 4) == [1, 3, 2, 4]


def test_split_is_not_a_filter():
    # platform mode over an ALL-news pool: nothing matches the profile, but the
    # rows MUST still be claimed in original order. A filtering implementation
    # returns [] here and starves the news domain entirely.
    rows = [NEWS(1), NEWS(2), NEWS(3)]
    assert mds._profile_ordered_ids(rows, "platform", 2) == [1, 2]


def test_auto_mode_is_identity_order():
    rows = [PLAT(1), NEWS(2), PLAT(3)]
    assert mds._profile_ordered_ids(rows, "auto", 3) == [1, 2, 3]


def test_truncates_to_limit_after_split():
    rows = [PLAT(1), PLAT(2), NEWS(3), NEWS(4)]
    # news mode, limit 2: the two news rows win the window even though they
    # were queued behind two platform rows.
    assert mds._profile_ordered_ids(rows, "news", 2) == [3, 4]


def test_fail_open_falls_back_to_priority_order():
    rows = [PLAT(1), NEWS(2), PLAT(3)]
    with mock.patch(
        "services.fleet_dispatch_profile.queue_row_gets_priority",
        side_effect=RuntimeError("boom"),
    ):
        assert mds._profile_ordered_ids(rows, "news", 2) == [1, 2]

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


# ── #6080 AUX POWER: module-family focus under PLATFORM mode ─────────────────
#
# The focus narrows the platform boost to ONE module family ("auxiliary power
# to Repair Bay"). Pins: family classification is module_id-only with the
# warm-up producers excluded outright; focus is inert outside platform mode;
# the default focus='' keeps every pre-#6080 caller byte-identical; and the
# promotion stays a SPLIT, never a filter.

from services import fleet_dispatch_profile as fdp

RB = lambda rid: _row(rid, module_id="repair_bay")  # noqa: E731
WARM = lambda rid: _row(rid, module_id="kin_warmth", capability="code_review")  # noqa: E731


def test_focus_promotes_only_the_family():
    # repair_bay focus: family rows first; other platform rows AND news rows
    # keep plain priority order behind them.
    assert fdp.queue_row_gets_priority(None, "repair_bay", "platform", "repair_bay") is True
    assert fdp.queue_row_gets_priority(None, "email_manager", "platform", "repair_bay") is False
    assert fdp.queue_row_gets_priority(None, "wtf_hub", "platform", "repair_bay") is False


def test_focus_never_boosts_warmup_producers():
    # kin_warmth rows carry real capabilities (code_review) — the module_id-only
    # rule + NEVER_BOOST_MODULES keeps 6k+ keep-warm pings out of the boost.
    assert fdp.is_family_queue_row("kin_warmth", "repair_bay") is False
    assert fdp.is_family_queue_row("fleet_warmup", "repair_bay") is False
    assert fdp.queue_row_gets_priority("code_review", "kin_warmth", "platform", "repair_bay") is False


def test_focus_is_inert_outside_platform_mode():
    assert fdp.queue_row_gets_priority(None, "repair_bay", "auto", "repair_bay") is False
    # news mode keeps its own rule regardless of focus
    assert fdp.queue_row_gets_priority(None, "wtf_hub", "news", "repair_bay") is True
    assert fdp.queue_row_gets_priority(None, "repair_bay", "news", "repair_bay") is False


def test_default_focus_is_byte_identical_platform_behaviour():
    # No focus arg (every pre-#6080 caller): platform == non-news first.
    assert fdp.queue_row_gets_priority(None, "email_manager", "platform") is True
    assert fdp.queue_row_gets_priority(None, "wtf_hub", "platform") is False


def test_unknown_focus_falls_back_to_plain_platform():
    assert fdp.queue_row_gets_priority(None, "email_manager", "platform", "not_a_family") is True


def test_focus_split_is_not_a_filter_in_the_drain():
    rows = [PLAT(1), RB(2), NEWS(3), RB(4), WARM(5)]
    with mock.patch.object(mds, "_get_profile_focus", return_value="repair_bay"):
        # family rows jump the queue; everyone else (platform, news, warm-up)
        # still drains in original order — nothing is dropped.
        assert mds._profile_ordered_ids(rows, "platform", 5) == [2, 4, 1, 3, 5]


def test_every_family_keyword_set_is_nonempty_and_disjoint_from_never_boost():
    for family, keywords in fdp.MODULE_FAMILIES.items():
        assert keywords, f"family {family} has no keywords"
        for k in keywords:
            for banned in fdp.NEVER_BOOST_MODULES:
                assert banned not in k, f"family {family} keyword {k} collides with never-boost"


# ── #6081 AUX POWER phase 2: warm-pin + slot reserve ─────────────────────────


def test_every_family_has_a_warm_model():
    assert set(fdp.FAMILY_WARM_MODELS) == set(fdp.MODULE_FAMILIES)
    assert all(fdp.FAMILY_WARM_MODELS.values())


def test_focus_warm_model_is_gated_on_platform_plus_focus():
    with mock.patch.object(fdp, "get_dispatch_mode", return_value="platform"), mock.patch.object(
        fdp, "get_dispatch_focus", return_value="repair_bay"
    ):
        assert fdp.get_focus_warm_model() == "qwen2.5-coder:7b"
    with mock.patch.object(fdp, "get_dispatch_mode", return_value="auto"):
        assert fdp.get_focus_warm_model() == ""
    with mock.patch.object(fdp, "get_dispatch_mode", return_value="platform"), mock.patch.object(
        fdp, "get_dispatch_focus", return_value=""
    ):
        assert fdp.get_focus_warm_model() == ""


def test_aux_reserve_applies_only_to_non_family_non_warmup_under_focus():
    # binds for other work while a focus is active…
    assert fdp.aux_reserve_applies("email_manager", "platform", "repair_bay") is True
    assert fdp.aux_reserve_applies("wtf_hub", "platform", "repair_bay") is True
    # …but never for the family itself (the reserve exists FOR it),
    assert fdp.aux_reserve_applies("repair_bay", "platform", "repair_bay") is False
    assert fdp.aux_reserve_applies("audit_pipeline", "platform", "repair_bay") is False
    # …never for keep-warm infrastructure (incl. the focus warm ping itself),
    assert fdp.aux_reserve_applies("kin_warmth", "platform", "repair_bay") is False
    assert fdp.aux_reserve_applies("fleet_warmup", "platform", "repair_bay") is False
    # …and never without an active platform focus.
    assert fdp.aux_reserve_applies("email_manager", "auto", "repair_bay") is False
    assert fdp.aux_reserve_applies("email_manager", "platform", "") is False
    assert fdp.aux_reserve_applies("email_manager", "news", "repair_bay") is False


def test_dispatcher_aux_reserve_fail_safe_and_family_exempt():
    """_aux_focus_reserve via an unbound call — no live dispatcher, no live DB.
    A broken settings read falls back to size 1; the family stays exempt; and
    any unexpected exception returns 0 (a reserve must never break dispatch)."""
    import types

    from tools.department_hq.services.department_dispatcher import DepartmentDispatcher

    def _boom():
        raise RuntimeError("no db in this test")

    fake = types.SimpleNamespace(_get_db=_boom)
    with mock.patch.object(fdp, "get_dispatch_mode", return_value="platform"), mock.patch.object(
        fdp, "get_dispatch_focus", return_value="repair_bay"
    ):
        assert DepartmentDispatcher._aux_focus_reserve(fake, "email_manager") == 1
        assert DepartmentDispatcher._aux_focus_reserve(fake, "repair_bay") == 0
    fake2 = types.SimpleNamespace(_get_db=_boom)
    with mock.patch.object(fdp, "get_dispatch_mode", return_value="auto"), mock.patch.object(
        fdp, "get_dispatch_focus", return_value=""
    ):
        assert DepartmentDispatcher._aux_focus_reserve(fake2, "email_manager") == 0

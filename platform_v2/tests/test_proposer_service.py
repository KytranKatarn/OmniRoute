"""Gathering is bounded PER SOURCE, and unassignable items never survive."""

import logging

import services.maintenance_schedule_service as maintenance_schedule_service
import services.proposer_service as ps
import services.scan_service as scan_service

LANES = {"codex": ("platform_v2/tools/fitness/",), "engine": ("platform_v2/", "ai_bridge/")}


def test_each_source_is_capped_independently(monkeypatch):
    """A global cap lets one noisy source crowd out every other (#5002)."""
    many = [{"id": i, "title": f"t{i}", "file_path": "ai_bridge/x.py"} for i in range(500)]
    monkeypatch.setattr(ps, "_fetch_tasks", lambda limit: many[:limit])
    monkeypatch.setattr(ps, "_fetch_proposals", lambda limit: many[:limit])
    monkeypatch.setattr(ps, "_fetch_code_issues", lambda limit, prefixes: many[:limit])
    out = ps.gather_candidates(LANES, per_source_cap=10)
    for src in ("unified_task", "proposal", "code_issue"):
        assert len([c for c in out if c["source"] == src]) <= 10


def test_kernel_items_are_dropped_before_the_manifest(monkeypatch):
    monkeypatch.setattr(
        ps,
        "_fetch_tasks",
        lambda limit: [{"id": 1, "title": "k", "file_path": "platform_v2/services/agent_service.py"}],
    )
    monkeypatch.setattr(ps, "_fetch_proposals", lambda limit: [])
    monkeypatch.setattr(ps, "_fetch_code_issues", lambda limit, prefixes: [])
    assert ps.gather_candidates(LANES) == []


def test_a_failing_source_yields_fewer_items_never_an_exception(monkeypatch):
    """Fail closed: one broken source must not take the whole proposer down."""

    def boom(limit):
        raise RuntimeError("db down")

    monkeypatch.setattr(ps, "_fetch_tasks", boom)
    monkeypatch.setattr(ps, "_fetch_proposals", lambda limit: [{"id": 2, "title": "ok", "file_path": "ai_bridge/y.py"}])
    monkeypatch.setattr(ps, "_fetch_code_issues", lambda limit, prefixes: [])
    out = ps.gather_candidates(LANES)
    assert [c["source"] for c in out] == ["proposal"]


def test_fetch_code_issues_unwraps_the_service_dict(monkeypatch):
    """scan_service.get_issues returns {"success":..., "issues":[...]}, never a bare list.

    Round 1 returned that dict straight through; gather_candidates then sliced it
    (rows[:per_source_cap]) OUTSIDE _safe(), so every run crashed with
    'TypeError: unhashable type: slice' instead of degrading gracefully.
    """
    fake_issues = [{"id": 1, "title": "x", "file_path": "ai_bridge/z.py"}]
    monkeypatch.setattr(scan_service, "get_issues", lambda **kwargs: {"success": True, "issues": fake_issues})
    result = ps._fetch_code_issues(10, ("ai_bridge/",))
    assert isinstance(result, list)
    assert result == fake_issues


def test_fetch_code_issues_with_no_prefixes_returns_nothing_not_everything(monkeypatch):
    """MINOR (#380 review round 2): scan_service.get_issues treats an EMPTY
    path_prefixes list exactly like None (both falsy) and fetches unfiltered.
    'no scope given' must return no rows, not every row -- proven here by
    asserting get_issues is never even called."""
    called = []
    monkeypatch.setattr(scan_service, "get_issues", lambda **kwargs: called.append(kwargs) or {"issues": []})
    assert ps._fetch_code_issues(10, ()) == []
    assert called == [], "get_issues must not be called at all when scope is empty"


def test_proposal_file_path_resolution_branches():
    """metadata['file_path'] wins; else synthesize from module_name; else None.

    Measured 2026-08-23: only 3/1361 approved proposals carry module_name, but
    812/1361 carry metadata->>'file_path'. Values like '[AI_BRIDGE]/x.py' or
    'standalone_kytran_business_suite/...' are passed through UNTRANSLATED —
    they simply won't match any lane prefix, and fail-closed filtering (not
    this function) is what drops them.
    """
    assert (
        ps._proposal_file_path("consciousness", {"file_path": "platform_v2/tools/consciousness/x.py"})
        == "platform_v2/tools/consciousness/x.py"
    )
    assert ps._proposal_file_path("fitness", {}) == "platform_v2/tools/fitness/"
    assert ps._proposal_file_path("fitness", None) == "platform_v2/tools/fitness/"
    assert ps._proposal_file_path(None, None) is None
    assert ps._proposal_file_path("", {}) is None
    # Placeholder/cross-repo values pass through verbatim — no translation.
    assert (
        ps._proposal_file_path(None, {"file_path": "[AI_BRIDGE]/voice_synthesis.py"})
        == "[AI_BRIDGE]/voice_synthesis.py"
    )


def test_gather_logs_a_per_source_gathered_vs_kept_summary(monkeypatch, caplog):
    """A source that gathers rows but keeps none must be VISIBLE, not silent.

    The real unified_tasks case: 339 pending rows exist, but 0/339 carry a
    metadata.file_path, so every one drops with lane=None — "no path" — and
    gather_candidates silently advertised three sources while delivering two.
    Same shape as the phantom `backups` table (#2366): unmonitored while
    appearing monitored.
    """
    monkeypatch.setattr(ps, "_fetch_tasks", lambda limit: [{"id": 1, "title": "no path"}])
    monkeypatch.setattr(ps, "_fetch_proposals", lambda limit: [{"id": 2, "title": "ok", "file_path": "ai_bridge/y.py"}])
    monkeypatch.setattr(ps, "_fetch_code_issues", lambda limit, prefixes: [])
    with caplog.at_level(logging.INFO, logger="services.proposer_service"):
        ps.gather_candidates(LANES)
    assert "unified_task gathered=1 kept=0" in caplog.text
    assert "proposal gathered=1 kept=1" in caplog.text
    assert "code_issue gathered=0 kept=0" in caplog.text


def test_a_bad_row_is_skipped_not_fatal(monkeypatch, caplog):
    """One malformed row must not crash gather_candidates.

    _safe() wraps the three FETCHERS, but the per-row classify()/dict-build
    loop was unguarded — the identical failure class as round 1's dict-slice
    crash, just one loop iteration deeper. Fail-closed means SKIP the bad
    item, not abort the run, and the skip must be counted so it is visible
    (same "unmonitored while appearing monitored" shape as everything else
    in this file).
    """
    good = {"id": 1, "title": "ok", "file_path": "ai_bridge/y.py"}
    bad = object()  # no .get() -> classify() raises AttributeError
    monkeypatch.setattr(ps, "_fetch_tasks", lambda limit: [good, bad])
    monkeypatch.setattr(ps, "_fetch_proposals", lambda limit: [])
    monkeypatch.setattr(ps, "_fetch_code_issues", lambda limit, prefixes: [])
    with caplog.at_level(logging.INFO, logger="services.proposer_service"):
        out = ps.gather_candidates(LANES)
    assert [c["ref"] for c in out] == ["1"]
    assert "unified_task gathered=2 kept=1 skipped=1" in caplog.text


def test_fetchers_return_the_documented_shape_against_the_real_db():
    """Nothing else in this suite exercises the real SQL — every other test
    monkeypatches the fetchers, and only the round-1 contract test reaches
    the get_issues boundary (via a stub, not the real table). A column
    rename on unified_tasks or improvement_proposals would pass the entire
    rest of the suite and fail silently in production, which is exactly what
    has hit this file twice today.

    Asserts SHAPE ONLY — never row counts or specific data — so this stays
    green against an empty table. If a table is empty, the per-element
    assertions simply never run; that is correct, not a false pass.
    """
    tasks = ps._fetch_tasks(5)
    assert isinstance(tasks, list)
    for row in tasks:
        assert isinstance(row, dict)
        assert "id" in row
        assert "title" in row

    proposals = ps._fetch_proposals(5)
    assert isinstance(proposals, list)
    for row in proposals:
        assert isinstance(row, dict)
        assert "id" in row
        assert "title" in row
        assert "file_path" in row  # value may legitimately be None

    issues = ps._fetch_code_issues(5, ("platform_v2/",))
    assert isinstance(issues, list)
    for row in issues:
        assert isinstance(row, dict)
        assert "file_path" in row


def test_manifest_is_capped_and_reports_what_it_dropped(monkeypatch):
    """Silent truncation reads as 'covered everything'. Always report the drop."""
    cands = [
        {
            "source": "proposal",
            "ref": str(i),
            "title": f"t{i}",
            "file_path": "ai_bridge/x.py",
            "lane": "engine",
            "tier": 1,
            "reason": "r",
        }
        for i in range(40)
    ]
    monkeypatch.setattr(ps, "gather_candidates", lambda p, per_source_cap=25: cands)
    out = ps.propose_manifest(LANES, repo="KytranKatarn/archie-platform", max_items=15, dry_run=True)
    assert len(out["items"]) == 15
    assert out["dropped"] == 25
    assert out["window_id"] is None and out["dry_run"] is True


def test_every_manifest_item_carries_its_repo(monkeypatch):
    """Task 1 made repo mandatory for authority; an entry without one authorises nothing.

    Two candidates + an explicit item-count assertion — with a single candidate,
    `all(...)` passes trivially on an empty (i.e. dropped-to-nothing) result, so it
    can't tell "every item has the repo" apart from "there were no items to check".
    """
    cands = [
        {
            "source": "proposal",
            "ref": "1",
            "title": "t1",
            "file_path": "ai_bridge/x.py",
            "lane": "engine",
            "tier": 1,
            "reason": "r",
        },
        {
            "source": "proposal",
            "ref": "2",
            "title": "t2",
            "file_path": "ai_bridge/y.py",
            "lane": "engine",
            "tier": 1,
            "reason": "r",
        },
    ]
    monkeypatch.setattr(ps, "gather_candidates", lambda p, per_source_cap=25: cands)
    out = ps.propose_manifest(LANES, repo="KytranKatarn/archie-platform", dry_run=True)
    assert len(out["items"]) == 2
    assert all(i["repo"] == "KytranKatarn/archie-platform" for i in out["items"])


def test_an_empty_candidate_set_creates_no_window(monkeypatch):
    """A window with nothing on it is noise the owner has to dismiss."""
    monkeypatch.setattr(ps, "gather_candidates", lambda p, per_source_cap=25: [])
    out = ps.propose_manifest(LANES, repo="KytranKatarn/archie-platform")
    assert out["ok"] is True and out["window_id"] is None and out["items"] == []


def test_manifest_writes_exactly_one_window_and_one_add_item_per_item(monkeypatch):
    """The write path (dry_run=False, items present) is the feature's real output — it
    calls schedule_window() and add_item() and is otherwise completely unexercised by the
    other tests, which all stay on the dry_run/empty branches.

    That manifest is an authority artifact: approving the window it creates is what
    authorises unattended merges of the PRs on it, so a bug here ships silently. Assert
    schedule_window is called ONCE (not once per item), add_item is called once PER
    chosen item, and every add_item call carries the repo that was passed in — on the
    captured kwargs, not merely that the call happened.
    """
    cands = [
        {
            "source": "proposal",
            "ref": "1",
            "title": "t1",
            "file_path": "ai_bridge/x.py",
            "lane": "engine",
            "tier": 1,
            "reason": "r",
        },
        {
            "source": "proposal",
            "ref": "2",
            "title": "t2",
            "file_path": "ai_bridge/y.py",
            "lane": "engine",
            "tier": 1,
            "reason": "r",
        },
    ]
    monkeypatch.setattr(ps, "gather_candidates", lambda p, per_source_cap=25: cands)

    schedule_calls = []
    add_item_calls = []

    def fake_schedule_window(*args, **kwargs):
        schedule_calls.append((args, kwargs))
        return {"id": 777}

    def fake_add_item(*args, **kwargs):
        add_item_calls.append((args, kwargs))
        return {"id": len(add_item_calls)}

    # propose_manifest imports schedule_window/add_item locally from
    # maintenance_schedule_service at call time — they are NOT module-level attributes
    # of ps, so they must be patched on the real module, or the write path silently
    # falls through to the REAL functions and inserts a real row.
    monkeypatch.setattr(maintenance_schedule_service, "schedule_window", fake_schedule_window)
    monkeypatch.setattr(maintenance_schedule_service, "add_item", fake_add_item)

    out = ps.propose_manifest(LANES, repo="KytranKatarn/archie-platform", dry_run=False)

    assert len(schedule_calls) == 1  # once for the whole manifest, never once per item
    assert len(add_item_calls) == 2
    for _args, kwargs in add_item_calls:
        assert kwargs.get("repo") == "KytranKatarn/archie-platform"
    assert out["window_id"] == 777
    assert out["dry_run"] is False


def test_the_proposed_window_start_is_in_the_future_not_now(monkeypatch):
    """CRITICAL (#380 review round 2): schedule_window(now_utc(), ...) meant the
    proposed window's scheduled_start was already in the past the instant it was
    created. maintenance_window_driver (dept_hq/jobs.py) announces a 'planned'
    window once now >= start - lead_min and OPENS an 'announced' window once
    now >= start -- with start == now, BOTH conditions are already true on the
    very first driver tick (every 5 min), so a window would announce AND open
    completely unattended, with zero time for the owner to review the manifest.
    The proposed start must sit comfortably beyond the driver's own announce
    lead (MAINTENANCE_ANNOUNCE_LEAD_MIN, default 60 min) so the driver cannot
    sweep it open before a human acts.
    """
    from datetime import timedelta

    from services.time_utils import now_utc

    cands = [
        {
            "source": "proposal",
            "ref": "1",
            "title": "t1",
            "file_path": "ai_bridge/x.py",
            "lane": "engine",
            "tier": 1,
            "reason": "r",
        }
    ]
    monkeypatch.setattr(ps, "gather_candidates", lambda p, per_source_cap=25: cands)

    schedule_calls = []

    def fake_schedule_window(*args, **kwargs):
        schedule_calls.append((args, kwargs))
        return {"id": 778}

    monkeypatch.setattr(maintenance_schedule_service, "schedule_window", fake_schedule_window)
    monkeypatch.setattr(maintenance_schedule_service, "add_item", lambda *a, **k: {"id": 1})

    before = now_utc()
    ps.propose_manifest(LANES, repo="KytranKatarn/archie-platform", dry_run=False)
    after = now_utc()

    assert len(schedule_calls) == 1
    scheduled_start = schedule_calls[0][0][0]
    # Comfortably in the future -- at least the module's own documented lead --
    # and not some unbounded/accidental value either.
    assert scheduled_start >= before + timedelta(minutes=ps.PROPOSED_WINDOW_LEAD_MINUTES)
    assert scheduled_start <= after + timedelta(minutes=ps.PROPOSED_WINDOW_LEAD_MINUTES)


def test_the_proposer_is_registered_as_a_scheduled_job():
    """A proposer nobody schedules is exactly the dormancy this design exists to fix.

    Registers against a REAL BackgroundScheduler rather than grepping text: a
    module-level scheduler.add_job (NameError) or a positional trigger (TypeError)
    both leave the right strings sitting in the file, so only an actual
    registration call can catch either failure. Never .start() the scheduler --
    registration alone is what's under test, and next_run_time is not populated
    until start.
    """
    from apscheduler.schedulers.background import BackgroundScheduler

    import tools.department_hq.jobs as jobs_module

    class FakeApp:
        pass

    sched = BackgroundScheduler()
    jobs_module.register_department_hq_jobs(sched, FakeApp())

    jobs_by_id = {j.id: j for j in sched.get_jobs()}
    assert "proposer_draft" in jobs_by_id, "proposer is never scheduled"
    assert str(jobs_by_id["proposer_draft"].trigger.timezone) == "America/Toronto"


def test_the_proposed_manifest_endpoint_is_on_the_internal_key_surface():
    """The cockpit is a separate container: it carries the internal key, not a session.
    #2781 shipped exactly this bug -- a registry gated so its only consumer 401'd.

    Asserts BOTH directions: the internal-key decorator IS present (an undecorated,
    wide-open route would otherwise still pass this test) and login_required is
    absent. The window is bounded at THIS route's own "def" line -- a wider,
    fixed-size window bleeds into the NEXT route's decorators (verified: the
    original 1200-char window reached clean past this function's body into
    "/api/internal/repair/count"'s own @_require_internal_key, so the assertion
    passed even with the decorator stripped from this route).
    """
    import pathlib

    text = pathlib.Path("/app/app.py").read_text()
    assert "/api/internal/proposed-manifest" in text
    idx = text.index("/api/internal/proposed-manifest")
    def_idx = text.index("\ndef ", idx)
    window = text[idx:def_idx]
    assert "require_internal_scope(" in window, "internal route must be internal-key-gated (#6657: scoped)"
    assert "login_required" not in window, "internal route must not be session-gated"


def test_the_proposed_manifest_endpoint_validates_repo(client, monkeypatch):
    """propose_manifest performs no validation of its own -- a repo string typed
    verbatim onto every item in an authority artifact needs a guard somewhere,
    and that guard belongs at the endpoint, not inside propose_manifest's contract."""
    monkeypatch.setenv("INTERNAL_API_KEY", "k")
    headers = {"Authorization": "Bearer k"}

    r_ok = client.get(
        "/api/internal/proposed-manifest?repo=KytranKatarn/archie-platform",
        headers=headers,
    )
    assert r_ok.status_code == 200

    r_bad = client.get(
        "/api/internal/proposed-manifest?repo=../../etc/passwd; DROP TABLE x",
        headers=headers,
    )
    assert r_bad.status_code == 400

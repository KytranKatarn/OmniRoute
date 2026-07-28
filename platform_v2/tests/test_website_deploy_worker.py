"""The daily website-deploy worker must report what actually happened (#5364).

This loop had ZERO coverage until now, which is not an academic gap: the defect
F.O.R.G.E. caught on PR #2533 lived exactly here. The "nothing changed since the
last confirmed push" branch used an early ``continue``, which skipped the run
timestamp write at the bottom of the loop — so a perfectly healthy no-op run
would freeze ``website_deploy_last_run_*`` and "when did the deploy worker last
run?" would answer with a stale timestamp. A code reviewer reading prose found
it; no test did.

The invariants pinned here are all one idea — **a status may only claim what is
true**:

  * the run timestamp is stamped on EVERY run, because the run happened;
  * the status is written ONLY when there is something to say (a real failure);
  * the worker QUEUES, so it may never write 'success' or 'deployed' — only
    ``deploy_service.mark_deploy_pushed`` may say bytes landed;
  * one site failing must not silence the other.

``_website_deploy_worker`` never touches ``self`` (the only "self." in its source
is the word "itself" in the docstring), so it is called unbound with a dummy.
"""

import datetime
import importlib
import sys
import types
from contextlib import contextmanager

import pytest

agent_loop = importlib.import_module("agent_loop")
AgentLoop = agent_loop.AgentLoop

KYTRAN = "kytranempowerment.com"
CREED = "creed-ai.org"


class _Result:
    """Stand-in for the pipeline's DispatchResult."""

    def __init__(self, success=True, error=None):
        self.success = success
        self.error = error


class Harness:
    """Captures every system_config write the worker makes."""

    def __init__(self):
        self.writes = []  # (key, value)
        self.pipeline_calls = []  # payload dicts
        self.changed = {}  # domain -> list
        self.since = {}  # domain -> iso str or None
        self.pipeline_result = _Result(True)
        self.pipeline_raises = None

    # -- fakes the worker's function-local imports resolve to ----------------
    def last_push_iso(self, domain):
        return self.since.get(domain)

    def changed_files_since(self, source, since):
        domain = KYTRAN if KYTRAN in source else CREED
        return self.changed.get(domain, [])

    def run_deploy_pipeline(self, capability, payload):
        self.pipeline_calls.append(payload)
        if self.pipeline_raises:
            raise self.pipeline_raises
        return self.pipeline_result

    @contextmanager
    def get_db_cursor(self, commit=False):
        writes = self.writes

        class _Cur:
            def execute(self, sql, params=None):
                if params and len(params) == 2:
                    writes.append((params[0], params[1]))

        yield None, _Cur()

    # -- assertions ----------------------------------------------------------
    def value_for(self, key):
        for k, v in self.writes:
            if k == key:
                return v
        return None

    def keys(self):
        return [k for k, _ in self.writes]


@pytest.fixture
def h(monkeypatch):
    harness = Harness()

    ds = types.ModuleType("services.deploy_service")
    ds.last_push_iso = harness.last_push_iso
    ds.changed_files_since = harness.changed_files_since
    ds.run_deploy_pipeline = harness.run_deploy_pipeline
    monkeypatch.setitem(sys.modules, "services.deploy_service", ds)

    db = types.ModuleType("database")
    db.get_db_cursor = harness.get_db_cursor
    monkeypatch.setitem(sys.modules, "database", db)

    return harness


def run(h):
    AgentLoop._website_deploy_worker(object())


def ts_key(domain):
    return f"website_deploy_last_run_{domain}"


def st_key(domain):
    return f"website_deploy_last_status_{domain}"


class TestRunTimestampIsAlwaysStamped:
    """The run HAPPENED — that fact is not conditional on the outcome."""

    def test_no_op_run_still_stamps_the_timestamp(self, h):
        """THE #2533 REGRESSION. An early `continue` here froze last_run."""
        h.since = {KYTRAN: "2026-07-27T03:00:00+00:00", CREED: "2026-07-27T03:00:00+00:00"}
        h.changed = {KYTRAN: [], CREED: []}

        run(h)

        assert h.pipeline_calls == [], "nothing changed — must not queue a deploy"
        for d in (KYTRAN, CREED):
            assert h.value_for(ts_key(d)) is not None, (
                f"{d}: a healthy no-op run must STILL stamp last_run — otherwise "
                "'when did the worker last run?' answers with a stale timestamp"
            )

    def test_timestamp_stamped_when_work_is_queued(self, h):
        h.since = {KYTRAN: "2026-07-27T03:00:00+00:00", CREED: "2026-07-27T03:00:00+00:00"}
        h.changed = {KYTRAN: ["data/translations.json"], CREED: ["data/translations.json"]}

        run(h)

        assert len(h.pipeline_calls) == 2
        for d in (KYTRAN, CREED):
            assert h.value_for(ts_key(d)) is not None

    def test_timestamp_stamped_even_when_the_pipeline_fails(self, h):
        h.since = {KYTRAN: "2026-07-27T03:00:00+00:00", CREED: "2026-07-27T03:00:00+00:00"}
        h.changed = {KYTRAN: ["data/x.json"], CREED: ["data/x.json"]}
        h.pipeline_result = _Result(False, "boom")

        run(h)

        for d in (KYTRAN, CREED):
            assert h.value_for(ts_key(d)) is not None
            assert h.value_for(st_key(d)) == "failed"

    def test_timestamp_stamped_when_the_pipeline_raises(self, h):
        """An exception is caught per-site; the run still happened."""
        h.since = {KYTRAN: "2026-07-27T03:00:00+00:00", CREED: "2026-07-27T03:00:00+00:00"}
        h.changed = {KYTRAN: ["data/x.json"], CREED: ["data/x.json"]}
        h.pipeline_raises = RuntimeError("network died")

        run(h)

        for d in (KYTRAN, CREED):
            assert h.value_for(ts_key(d)) is not None
            assert h.value_for(st_key(d)) == "failed"

    def test_stamped_value_is_a_parseable_utc_timestamp(self, h):
        h.since = {KYTRAN: None, CREED: None}
        run(h)
        raw = h.value_for(ts_key(KYTRAN))
        parsed = datetime.datetime.fromisoformat(raw)
        assert parsed.tzinfo is not None, "storage layer is UTC-aware (timezone.md)"


class TestTheWorkerNeverClaimsADeploy:
    """It QUEUES. Only mark_deploy_pushed may say bytes landed."""

    def test_success_is_never_written_on_a_queued_run(self, h):
        h.since = {KYTRAN: "2026-07-27T03:00:00+00:00", CREED: "2026-07-27T03:00:00+00:00"}
        h.changed = {KYTRAN: ["data/x.json"], CREED: ["data/x.json"]}

        run(h)

        assert st_key(KYTRAN) not in h.keys(), (
            "a queued deploy must not write a status — the worker cannot know "
            "bytes landed. It used to write a bare 'success'."
        )
        assert "success" not in [v for _, v in h.writes]
        assert "deployed" not in [v for _, v in h.writes]

    def test_no_op_writes_no_status_at_all(self, h):
        h.since = {KYTRAN: "2026-07-27T03:00:00+00:00", CREED: "2026-07-27T03:00:00+00:00"}
        h.changed = {KYTRAN: [], CREED: []}

        run(h)

        assert st_key(KYTRAN) not in h.keys()
        assert st_key(CREED) not in h.keys()

    def test_deployed_is_never_written_by_this_worker_on_any_path(self, h):
        for since, changed, result in (
            (None, [], _Result(True)),
            ("2026-07-27T03:00:00+00:00", ["a.json"], _Result(True)),
            ("2026-07-27T03:00:00+00:00", [], _Result(True)),
            ("2026-07-27T03:00:00+00:00", ["a.json"], _Result(False, "e")),
        ):
            h.writes.clear()
            h.pipeline_calls.clear()
            h.since = {KYTRAN: since, CREED: since}
            h.changed = {KYTRAN: changed, CREED: changed}
            h.pipeline_result = result

            run(h)

            assert "deployed" not in [v for _, v in h.writes]


class TestChangeDetectionFeedsRealPaths:
    """classify_risk needs file paths; the constants always read as risky."""

    def test_no_recorded_push_falls_back_to_the_directory_list(self, h):
        h.since = {KYTRAN: None, CREED: None}

        run(h)

        assert len(h.pipeline_calls) == 2, "unknown contents must still be queued"
        assert h.pipeline_calls[0]["changed_files"] == ["assets/portraits/", "data/"]

    def test_real_changed_files_are_passed_through(self, h):
        h.since = {KYTRAN: "2026-07-27T03:00:00+00:00", CREED: "2026-07-27T03:00:00+00:00"}
        h.changed = {KYTRAN: ["data/translations.json", "index.html"], CREED: ["data/translations.json"]}

        run(h)

        by_domain = {c["domain"]: c for c in h.pipeline_calls}
        assert by_domain[KYTRAN]["changed_files"] == ["data/translations.json", "index.html"]
        assert by_domain[CREED]["changed_files"] == ["data/translations.json"]

    def test_payload_carries_what_the_pipeline_needs(self, h):
        h.since = {KYTRAN: None, CREED: None}

        run(h)

        p = h.pipeline_calls[0]
        assert p["domain"] == KYTRAN
        assert p["source_path"].endswith(KYTRAN)
        assert p["verify_url"].startswith("https://")


class TestSitesAreIndependent:
    """One site's failure must not silence the other — both are public."""

    def test_both_sites_are_processed(self, h):
        h.since = {KYTRAN: None, CREED: None}

        run(h)

        domains = {c["domain"] for c in h.pipeline_calls}
        assert domains == {KYTRAN, CREED}

    def test_a_raising_site_does_not_prevent_the_other_from_running(self, h):
        h.since = {KYTRAN: "2026-07-27T03:00:00+00:00", CREED: "2026-07-27T03:00:00+00:00"}
        h.changed = {KYTRAN: ["a.json"], CREED: ["b.json"]}

        calls = {"n": 0}
        original = h.run_deploy_pipeline

        def flaky(capability, payload):
            calls["n"] += 1
            if payload["domain"] == KYTRAN:
                raise RuntimeError("first site exploded")
            return original(capability, payload)

        h.run_deploy_pipeline = flaky
        sys.modules["services.deploy_service"].run_deploy_pipeline = flaky

        run(h)

        assert h.value_for(st_key(KYTRAN)) == "failed"
        assert h.value_for(ts_key(CREED)) is not None, "second site must still run"
        assert st_key(CREED) not in h.keys(), "second site succeeded — no status"

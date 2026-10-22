"""Media Studio Dashboard tab: failed (24h) + bulk retry, tuning tests hidden from approvals, dated timestamps, GPU strip."""

import contextlib
import json
import pathlib
import shutil
import subprocess

import pytest

from tools.media_studio.services import queue_overview as qo

MS = pathlib.Path(__file__).resolve().parents[1] / "tools" / "media_studio"
GEN = (MS / "services" / "generation_service.py").read_text(encoding="utf-8")
ROUTES = (MS / "routes.py").read_text(encoding="utf-8")
JS = (MS / "static" / "js" / "ms-dashboard.js").read_text(encoding="utf-8")
TAB = (MS / "templates" / "tools" / "media_studio" / "_tab_dashboard.html").read_text(encoding="utf-8")


class Cur:
    def __init__(self, rows=None):
        self.rows, self.log = rows or [], []

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows


def factory(cur):
    @contextlib.contextmanager
    def get(*a, **k):
        yield (None, cur)

    return get


# --- recent_failed / retry_recent_failed ------------------------------------------------------------------------


def test_recent_failed_uses_the_queue_scope_and_bound_clamped_values():
    cur = Cur(rows=[{"id": 1, "owner_type": "agent", "owner_id": 9}])
    out = qo.recent_failed(7, hours=99999, limit=9999, get_cursor=factory(cur))
    sql, params = cur.log[0]
    assert out == [{"id": 1, "owner_type": "agent", "owner_id": 9}]
    assert "status = 'failed'" in sql and "owner_type = 'agent' OR (owner_type = 'user' AND owner_id = %s)" in sql
    assert "make_interval(hours => %s)" in sql and params == (7, 168, 50)  # hours clamped to a week, limit to 50
    assert qo.recent_failed(7, hours=0, limit=0, get_cursor=factory(Cur())) == []


def test_retry_counts_what_was_actually_requeued_and_survives_a_bad_row():
    rows = [{"id": i, "owner_type": "agent", "owner_id": i} for i in (1, 2, 3, 4)]
    seen = []

    def retry(qid, owner_type, owner_id):
        seen.append((qid, owner_type, owner_id))
        if qid == 2:
            return False  # not failed any more / not found
        if qid == 3:
            raise RuntimeError("dispatch down")
        return True

    out = qo.retry_recent_failed(7, get_cursor=factory(Cur(rows=rows)), retry=retry)
    assert out == {"found": 4, "retried": 2} and [s[0] for s in seen] == [1, 2, 3, 4]  # row 3 raised, 4 still ran


def test_retry_with_nothing_failed_does_nothing():
    out = qo.retry_recent_failed(7, get_cursor=factory(Cur()), retry=lambda *a: pytest.fail("must not retry"))
    assert out == {"found": 0, "retried": 0}


# --- the dashboard stats SQL --------------------------------------------------------------------------------------


def test_needs_approval_hides_tuning_tests_unless_asked():
    assert "def get_dashboard_stats(user_id: int, include_dismissed: bool = False, include_tests: bool = False)" in GEN
    assert "(%(include_tests)s = true OR COALESCE(ml.metadata->>'tuning_test', 'false') <> 'true')" in GEN
    assert '{"include_dismissed": include_dismissed, "include_tests": include_tests}' in GEN


def test_the_dashboard_stats_sql_actually_runs_in_both_modes():
    """Executes the real queries against the (empty) test database: catches a syntax or parameter slip the
    string checks above cannot. Skipped where there is no database (e.g. a host run with --noconftest)."""
    try:
        from tools.media_studio.services.generation_service import get_dashboard_stats

        quiet = get_dashboard_stats(1)
        loud = get_dashboard_stats(1, include_tests=True)
    except Exception as exc:  # noqa: BLE001
        if "could not translate host name" in str(exc) or "connect" in str(exc).lower():
            pytest.skip(f"no database: {exc}")
        raise
    for d in (quiet, loud):
        assert d["queue_failed_24h"] == 0 and d["queue_completed_24h"] == 0 and d["pending_approvals"] == []


def test_the_retry_route_validates_hours_and_uses_the_shared_service():
    blk = ROUTES[ROUTES.index("def api_queue_retry_failed") :][:900]
    assert (
        "isinstance(hours, int)" in blk
        and "1 <= hours <= 168" in blk
        and "retry_recent_failed(current_user.id, hours=hours)" in blk
    )
    assert 'methods=["POST"]' in ROUTES[ROUTES.index("/api/queue/retry-failed") - 5 :][:120]


def test_the_dashboard_route_passes_include_tests():
    assert 'include_tests=(request.args.get("include_tests") == "1")' in ROUTES


# --- template + JS wiring ------------------------------------------------------------------------------------------


def test_the_failed_tile_is_24h_and_has_a_retry_link_that_does_not_trigger_the_tile_jump():
    assert "Failed (24h)" in TAB and "Failed (all)" not in TAB
    assert "event.stopPropagation();msDashboard.retryFailed()" in TAB


def test_show_tests_toggle_and_gpu_strip_exist():
    assert 'id="msDashShowTests"' in TAB and 'id="msDashGpuStrip"' in TAB


def test_load_sends_include_tests_and_reads_the_24h_failed_count():
    body = JS[JS.index("load: function ()") : JS.index("_renderSubLabels: function")]
    assert "include_tests=1" in body and "d.queue_failed_24h" in body and "_loadGpuStrip()" in body


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")

HARNESS = """
const els = {}; const calls = []; const timers = [];
global.window = {}; Object.defineProperty(global, 'msDashboard', { get: () => window.msDashboard }); global.setInterval = () => 1; global.clearInterval = () => {};
global.document = { getElementById: (id) => (els[id] = els[id] || { style: {}, textContent: '' }) };
global.fetch = (url, opts) => { calls.push({ url, body: opts && opts.body }); return Promise.resolve({ ok: true, json: () => Promise.resolve({ retried: 2, found: 3 }) }); };
global.setTimeout = (fn) => { timers.push(fn); return timers.length; };
%s
const d = window.msDashboard; d._failed24h = 3; const link = () => els['msDashRetryFailed'].textContent;
const out = {};
d.retryFailed(); out.after_click1 = { fetches: calls.length, armed: d._retryArmed, text: link() };
d.retryFailed(); out.after_click2 = { fetches: calls.length, armed: d._retryArmed, url: calls[0] && calls[0].url, body: calls[0] && calls[0].body };
d.retryFailed(); timers[0](); out.disarmed = d._retryArmed;
console.log(JSON.stringify(out));
"""


def run_harness():
    out = subprocess.run(["node", "-e", HARNESS % JS], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr[-600:]  # only the error, not the whole script
    return json.loads(out.stdout)


@needs_node
def test_retry_needs_two_clicks_and_the_first_one_only_arms_it():
    r = run_harness()
    assert (
        r["after_click1"]["fetches"] == 0 and r["after_click1"]["armed"] is True
    )  # first click must NOT re-run the GPU
    assert "Click again to confirm" in r["after_click1"]["text"] and "3 jobs" in r["after_click1"]["text"]
    assert r["after_click2"]["fetches"] == 1 and r["after_click2"]["armed"] is False
    assert r["after_click2"]["url"] == "/tools/media-studio/api/queue/retry-failed" and json.loads(
        r["after_click2"]["body"]
    ) == {"hours": 24}


@needs_node
def test_an_armed_retry_disarms_itself_after_the_timeout():
    assert run_harness()["disarmed"] is False


def test_the_gpu_strip_never_uses_innerhtml():
    assert "innerHTML" not in JS[JS.index("_loadGpuStrip: function") : JS.index("_renderShowDismissedToggle: function")]


# --- the real _when() helper, run in node ---------------------------------------------------------------------------


def run_when(iso):
    src = JS[JS.index("function _when(") : JS.index("window.msDashboard = {")]
    out = subprocess.run(
        ["node", "-e", src + f"\nconsole.log(JSON.stringify(_when({json.dumps(iso)})))"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)


@needs_node
def test_when_shows_only_the_time_for_today_and_the_date_for_older_rows():
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    today = run_when(now.isoformat())
    old = run_when((now - timedelta(days=3)).isoformat())
    assert "," not in today and ":" in today
    assert "," in old and ":" in old  # "Oct 19, 6:25 PM": a date AND a time


@needs_node
@pytest.mark.parametrize("bad", [None, "", "not a date"])
def test_when_is_empty_for_missing_or_invalid_input(bad):
    assert run_when(bad) == ""

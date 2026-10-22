"""Queue tab: one scope for list + counters, wait-vs-run timing, per-node GPU panel (task #7427)."""

import contextlib
import json
import pathlib
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from tools.media_studio.services import queue_overview as qo

MS = pathlib.Path(__file__).resolve().parents[1] / "tools" / "media_studio"
HTML = (MS / "templates" / "tools" / "media_studio" / "media_studio.html").read_text(encoding="utf-8")
ROUTES = (MS / "routes.py").read_text(encoding="utf-8")

T0 = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)


# --- status parsing --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, []),
        ("", []),
        ("failed", ["failed"]),
        ("failed,completed,cancelled", ["failed", "completed", "cancelled"]),
        (" Failed , COMPLETED ", ["failed", "completed"]),
        ("failed,failed", ["failed"]),
        ("completed,drop table x;--,pending", ["completed", "pending"]),  # unknown values never reach SQL
    ],
)
def test_parse_statuses(raw, expected):
    assert qo.parse_statuses(raw) == expected


# --- wait vs run -----------------------------------------------------------------------------------------------


def row(**kw):
    base = {
        "status": "completed",
        "created_at": T0,
        "started_at": T0 + timedelta(minutes=2),
        "completed_at": T0 + timedelta(minutes=2, seconds=41),
        "params": {},
    }
    base.update(kw)
    return base


def test_a_finished_job_reports_wait_and_run_separately():
    r = qo.annotate_timing(row(), now=T0 + timedelta(hours=7))
    assert r["wait_ms"] == 120_000 and r["run_ms"] == 41_000  # NOT "7h": the time since it started is irrelevant


def test_a_pending_job_is_waiting_so_far_and_has_no_run_time():
    r = qo.annotate_timing(row(status="pending", started_at=None, completed_at=None), now=T0 + timedelta(minutes=5))
    assert r["wait_ms"] == 300_000 and r["run_ms"] is None


def test_a_generating_job_is_running_so_far():
    r = qo.annotate_timing(row(status="generating", completed_at=None), now=T0 + timedelta(minutes=2, seconds=10))
    assert r["wait_ms"] == 120_000 and r["run_ms"] == 10_000


def test_a_job_that_failed_before_starting_has_no_run_time_not_zero():
    r = qo.annotate_timing(row(status="failed", started_at=None, completed_at=T0 + timedelta(seconds=3)))
    assert r["run_ms"] is None


def test_naive_and_string_timestamps_are_treated_as_utc():
    r = qo.annotate_timing(
        row(
            created_at="2026-10-21T12:00:00",
            started_at="2026-10-21T12:01:00Z",
            completed_at=datetime(2026, 10, 21, 12, 1, 30),
        )
    )
    assert r["wait_ms"] == 60_000 and r["run_ms"] == 30_000


def test_a_clock_skewed_negative_interval_is_clamped_to_zero():
    r = qo.annotate_timing(row(started_at=T0 - timedelta(seconds=5), completed_at=T0 - timedelta(seconds=9)))
    assert r["wait_ms"] == 0 and r["run_ms"] == 0


def test_model_and_node_come_from_params():
    r = qo.annotate_timing(
        row(params={"model": "juggernautXL_v9.safetensors", "fleet_node": "Starship - Defiant - USS-246"})
    )
    assert (r["model"], r["node"]) == ("juggernautXL_v9.safetensors", "Starship - Defiant - USS-246")
    assert qo.annotate_timing(row(params=None))["model"] is None


# --- SQL scope -------------------------------------------------------------------------------------------------


class Cur:
    def __init__(self, rows=None, one=None, log=None):
        self.rows, self.one, self.log = rows or [], one, log if log is not None else []

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one


def cursor_factory(cur):
    @contextlib.contextmanager
    def get(*a, **k):
        yield (None, cur)

    return get


def test_the_list_and_the_counters_share_one_scope():
    log = []
    cur = Cur(one={"total": 3}, rows=[], log=log)
    qo.list_queue(7, ["failed"], 25, 0, get_cursor=cursor_factory(cur))
    qo.get_overview(
        7,
        get_cursor=cursor_factory(
            Cur(
                one={
                    "pending": 0,
                    "running": 0,
                    "completed": 0,
                    "failed": 0,
                    "completed_24h": 0,
                    "failed_24h": 0,
                    "avg_run_ms": None,
                    "avg_wait_ms": None,
                },
                log=log,
            )
        ),
    )
    scope = "owner_type = 'agent' OR (q.owner_type = 'user' AND q.owner_id = %s)"
    assert all(
        scope in sql or "owner_type = 'agent' OR (owner_type = 'user' AND owner_id = %s)" in sql for sql, _ in log
    )
    assert len(log) == 3 and all(p[0] == 7 for _, p in log)  # the user id is the first bound value in each


def test_list_queue_binds_statuses_limit_and_offset_and_clamps():
    log = []
    cur = Cur(one={"total": 9}, rows=[{"id": 1, **row()}], log=log)
    out = qo.list_queue(7, ["failed", "completed"], 5000, -4, get_cursor=cursor_factory(cur))
    assert out["total"] == 9 and out["items"][0]["run_ms"] == 41_000
    _count, (sql, params) = log[0], log[1]
    assert params == (7, ["failed", "completed"], ["failed", "completed"], 200, 0)  # limit clamped to 200, offset to 0
    assert "LIMIT %s OFFSET %s" in sql


def test_an_empty_status_list_means_any():
    log = []
    qo.list_queue(7, [], 10, 0, get_cursor=cursor_factory(Cur(one={"total": 0}, log=log)))
    assert "cardinality(%s::text[]) = 0" in log[0][0] and log[0][1][1] == []


def test_the_module_builds_no_sql_by_string_formatting():
    src = (MS / "services" / "queue_overview.py").read_text(encoding="utf-8")
    assert "execute(f" not in src and ".format(" not in src and "sql-safe" not in src


def test_overview_has_24h_counts_and_keeps_the_legacy_keys():
    row_ = {
        "pending": 1,
        "running": 0,
        "completed": 302,
        "failed": 87,
        "completed_24h": 40,
        "failed_24h": 2,
        "avg_run_ms": 41234.6,
        "avg_wait_ms": None,
    }
    o = qo.get_overview(7, get_cursor=cursor_factory(Cur(one=row_)))
    assert (o["completed_24h"], o["failed_24h"], o["completed"], o["failed"]) == (40, 2, 302, 87)
    assert o["avg_run_ms"] == 41235 and o["avg_wait_ms"] == 0 and o["avg_duration_ms"] == 41235


# --- per-node GPU panel ----------------------------------------------------------------------------------------

NODES = [
    {"name": "Starship - Defiant - USS-246", "url": "http://d", "hub": False},
    {"name": "Starship - Runabout - USS-245", "url": "http://r", "hub": False},
    {"name": qo.HUB_LABEL, "url": "http://h", "hub": True},
]


def fake_fetch(table):
    def fetch(url):
        v = table[url]
        if isinstance(v, Exception):
            raise v
        return v

    return fetch


def test_each_node_reports_its_own_depth_and_the_totals_add_up():
    fetch = fake_fetch(
        {
            "http://d": {"running": 1, "pending": 2},
            "http://r": {"running": 0, "pending": 0},
            "http://h": OSError("refused"),
        }
    )
    out = qo.gpu_nodes_status(NODES, [], fetch)
    by = {n["name"]: n for n in out["nodes"]}
    assert by["Starship - Defiant - USS-246"]["state"] == "busy"
    assert by["Starship - Runabout - USS-245"]["state"] == "idle"
    assert (out["running"], out["pending"]) == (1, 2)


def test_an_unreachable_hub_is_idle_but_an_unreachable_fleet_node_is_flagged():
    fetch = fake_fetch(
        {"http://d": OSError("timed out"), "http://r": {"running": 0, "pending": 0}, "http://h": OSError("refused")}
    )
    by = {n["name"]: n for n in qo.gpu_nodes_status(NODES, [], fetch)["nodes"]}
    assert by["Starship - Defiant - USS-246"]["state"] == "unreachable"
    assert by[qo.HUB_LABEL]["state"] == "idle" and "on demand" in by[qo.HUB_LABEL]["note"]


def test_the_lease_holder_is_shown_on_the_node_that_holds_it():
    fetch = fake_fetch(
        {"http://d": {"running": 1, "pending": 0}, "http://r": {"running": 0, "pending": 0}, "http://h": OSError("x")}
    )
    leases = [{"node_name": "Starship - Defiant - USS-246", "holder": "media-worker:42"}]
    by = {n["name"]: n for n in qo.gpu_nodes_status(NODES, leases, fetch)["nodes"]}
    assert by["Starship - Defiant - USS-246"]["lease_holder"] == "media-worker:42"
    assert by["Starship - Runabout - USS-245"]["lease_holder"] is None


def test_a_hub_lease_recorded_under_the_starbase_row_name_matches_the_hub_entry():
    fetch = fake_fetch(
        {
            "http://d": {"running": 0, "pending": 0},
            "http://r": {"running": 0, "pending": 0},
            "http://h": {"running": 1, "pending": 0},
        }
    )
    leases = [{"node_name": "Starbase - A.R.C.H.I.E.", "holder": "media-worker:7"}]
    by = {n["name"]: n for n in qo.gpu_nodes_status(NODES, leases, fetch)["nodes"]}
    assert by[qo.HUB_LABEL]["lease_holder"] == "media-worker:7"


def test_comfyui_nodes_lists_online_fleet_nodes_then_the_hub():
    cur = Cur(rows=[{"node_name": "Starship - Defiant - USS-246", "url": "http://100.64.0.3:8188"}])
    nodes = qo.comfyui_nodes(get_cursor=cursor_factory(cur))
    assert [n["name"] for n in nodes] == ["Starship - Defiant - USS-246", qo.HUB_LABEL] and nodes[-1]["hub"] is True


def test_a_database_failure_still_lists_the_hub():
    @contextlib.contextmanager
    def boom(*a, **k):
        raise RuntimeError("db down")
        yield

    assert [n["name"] for n in qo.comfyui_nodes(get_cursor=boom)] == [qo.HUB_LABEL]


# --- routes + UI wiring ----------------------------------------------------------------------------------------


def block(src, marker, size=900):
    return src[src.index(marker) :][:size]


def test_the_three_endpoints_use_the_shared_module():
    assert "list_queue(current_user.id, parse_statuses(" in block(ROUTES, "def api_queue():")
    assert "get_overview(current_user.id)" in block(ROUTES, "def api_queue_stats():")
    assert "gpu_nodes_status()" in block(ROUTES, "def api_comfyui_queue():")


def test_the_history_loads_with_one_request_and_an_exact_total():
    body = block(HTML, "window.loadQueueItems = function()", 4000)
    assert "failed,completed,cancelled" in body and "_renderHistoryPager(history.length, r.total || 0)" in body
    assert "histStatuses.map" not in body  # the old per-status fan-out + merge is gone


def test_the_gpu_panel_renders_per_node_and_the_cards_keep_a_fixed_thumbnail_slot():
    assert "var nodes = data.nodes || [];" in block(HTML, "function loadComfyQueue()", 1500)
    assert "ms-queue-thumb-slot" in block(HTML, "function _createQueueCard", 1500)


# --- the real UI helpers, run in node ---------------------------------------------------------------------------

pytestmark_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run_js(expr):
    start = HTML.index("function _fmtDur(")
    helpers = HTML[start : HTML.index("function _createQueueCard(", start)]
    out = subprocess.run(
        ["node", "-e", helpers + f"\nconsole.log(JSON.stringify({expr}))"], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


@pytestmark_node
@pytest.mark.parametrize(
    "ms,expected", [(None, "—"), (0, "0s"), (41_000, "41s"), (125_000, "2m 5s"), (3_780_000, "1h 3m")]
)
def test_js_fmt_dur(ms, expected):
    assert run_js(f"_fmtDur({json.dumps(ms)})") == expected


@pytestmark_node
def test_js_short_text_cuts_at_a_word_boundary_with_an_ellipsis():
    text = "Photorealistic cinematic head-and-shoulders portrait of A.R.C.H.I.E. with a glowing halo"
    out = run_js(f"_shortText({json.dumps(text)}, 60)")
    assert out.endswith("…") and len(out) <= 61
    assert all(tok in text.split(" ") for tok in out[:-1].split(" "))  # every token is a WHOLE word, none cut in half
    assert run_js("_shortText('short text', 60)") == "short text"


@pytestmark_node
def test_js_timing_text_for_active_and_finished_jobs():
    assert run_js("_queueTiming({status:'generating', run_ms: 41000}, 'active')") == "running 41s"
    assert run_js("_queueTiming({status:'pending', wait_ms: 125000}, 'active')") == "waiting 2m 5s"
    done = run_js(
        "_queueTiming({status:'completed', wait_ms: 120000, run_ms: 41000, completed_at: new Date(Date.now()-7*3600*1000).toISOString()}, 'recent')"
    )
    assert done == "waited 2m 0s · ran 41s · 7h ago"  # the 7 hours is "ago", never the duration
    assert (
        run_js("_queueTiming({status:'failed', wait_ms: 3000, run_ms: null, created_at: null}, 'failed')")
        == "waited 3s"
    )


@pytestmark_node
def test_js_short_node_and_model_labels():
    assert run_js("_shortNode('Starship - Defiant - USS-246')") == "Defiant"
    assert run_js("_shortModel('juggernautXL_v9.safetensors')") == "juggernautXL"


# --- thumbnails (follow-up): the stored thumbnail path is bare and never loaded --------------------------------


def test_the_queue_list_returns_browser_ready_thumbnail_and_file_paths():
    bare = {
        "id": 1,
        **row(),
        "thumbnail_path": "media/agents/2/x/thumb_1.png",
        "file_path": "/static/media/agents/2/x/m_1.png",
    }
    out = qo.list_queue(7, [], 10, 0, get_cursor=cursor_factory(Cur(one={"total": 1}, rows=[bare])))
    item = out["items"][0]
    assert item["thumbnail_path"] == "/static/media/agents/2/x/thumb_1.png"  # was bare: the <img> never loaded
    assert item["file_path"] == "/static/media/agents/2/x/m_1.png"  # already absolute: untouched


def test_a_missing_path_stays_missing():
    out = qo.list_queue(
        7,
        [],
        10,
        0,
        get_cursor=cursor_factory(
            Cur(one={"total": 1}, rows=[{"id": 1, **row(), "thumbnail_path": None, "file_path": None}])
        ),
    )
    assert out["items"][0]["thumbnail_path"] is None


def test_gallery_service_still_exposes_the_helper_for_its_existing_callers():
    assert "from .media_paths import normalize_static_path" in (MS / "services" / "gallery_service.py").read_text(
        encoding="utf-8"
    )


def test_a_failed_thumbnail_falls_back_to_the_full_image_once_before_the_slot_is_emptied():
    body = block(HTML, "function _createQueueCard", 2500)
    assert "img.dataset.tried" in body and "img.src = item.file_path" in body and "removeChild(img)" in body

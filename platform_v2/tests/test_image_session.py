"""Image sessions (#7400): SDXL stays warm across consecutive jobs, timeouts retry, the reaper is retry-aware.

Run with --noconftest (pure: fake clock, fake swap/restore, fake cursor).
"""

import contextlib
import inspect
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.media_studio.services import image_session as im  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeLease:
    def __init__(self):
        self.calls = []

    def acquire(self, node, holder):
        self.calls.append(("acquire", node))

    def heartbeat(self, node, holder):
        self.calls.append(("heartbeat", node))

    def release(self, node, holder):
        self.calls.append(("release", node))


def make(unloaded=("qwen2.5:7b",)):
    clock, swaps, restores = Clock(), [], []

    def swap(node_id):
        swaps.append(node_id)
        return list(unloaded)

    def restore(models, node_id):
        restores.append((tuple(models), node_id))

    return (
        im.ImageSessions(clock=clock, swap=swap, restore=restore, lease=FakeLease(), start_heartbeat=False),
        clock,
        swaps,
        restores,
    )


# ── session lifecycle ────────────────────────────────────────────────────────────────────────────────
def test_first_job_is_cold_and_swaps_once_later_jobs_are_warm_and_do_not_swap():
    s, _, swaps, restores = make()
    assert s.begin("Defiant", 115, 1) == {"cold": True}
    s.end("Defiant", 1)
    assert s.begin("Defiant", 115, 2) == {"cold": False}
    s.end("Defiant", 2)
    assert s.begin("Defiant", 115, 3) == {"cold": False}
    assert swaps == [115] and restores == []  # one swap for three jobs, and NO per-job restore


def test_no_restore_while_work_is_pending_or_before_the_grace_elapses():
    s, clock, _, restores = make()
    s.begin("Defiant", 115, 1)
    s.end("Defiant", 1)
    clock.t += 500
    assert s.restore_idle(pending_total=2, grace_s=180) == []  # queue not drained
    assert restores == []
    clock.t = 1000.0 + 100
    s2, c2, _, r2 = make()
    s2.begin("Defiant", 115, 1)
    s2.end("Defiant", 1)
    c2.t += 100
    assert s2.restore_idle(pending_total=0, grace_s=180) == []  # grace not elapsed
    assert r2 == []


def test_restore_runs_once_after_drain_and_grace_then_next_job_is_cold_again():
    s, clock, swaps, restores = make()
    s.begin("Defiant", 115, 1)
    s.end("Defiant", 1)
    clock.t += 181
    assert s.restore_idle(pending_total=0, grace_s=180) == ["Defiant"]
    assert restores == [(("qwen2.5:7b",), 115)]
    assert s.restore_idle(pending_total=0, grace_s=180) == []  # idempotent
    assert s.begin("Defiant", 115, 2) == {"cold": True} and swaps == [115, 115]


def test_a_job_still_running_keeps_the_session_open():
    s, clock, _, restores = make()
    s.begin("Defiant", 115, 1)  # never ended
    clock.t += 10_000
    assert s.restore_idle(pending_total=0, grace_s=0) == [] and restores == []


def test_nodes_are_independent():
    s, clock, swaps, restores = make()
    s.begin("Defiant", 115, 1)
    s.end("Defiant", 1)
    assert s.begin("Hub", 68, 2) == {"cold": True}
    s.end("Hub", 2)
    clock.t += 200
    assert sorted(s.restore_idle(0, 180)) == ["Defiant", "Hub"]
    assert swaps == [115, 68]


def test_swap_failure_does_not_block_generation_and_skips_restore():
    clock, restores = Clock(), []

    def boom(node_id):
        raise RuntimeError("node unreachable")

    s = im.ImageSessions(
        clock=clock, swap=boom, restore=lambda m, n: restores.append(n), lease=FakeLease(), start_heartbeat=False
    )
    assert s.begin("Defiant", 115, 1) == {"cold": True}
    s.end("Defiant", 1)
    clock.t += 500
    assert s.restore_idle(0, 180) == ["Defiant"] and restores == []  # nothing was unloaded, nothing to restore


def test_restore_failure_never_raises_and_still_closes_the_session():
    clock = Clock()

    def boom(models, node_id):
        raise RuntimeError("restore failed")

    s = im.ImageSessions(clock=clock, swap=lambda n: ["m"], restore=boom, lease=FakeLease(), start_heartbeat=False)
    s.begin("Defiant", 115, 1)
    s.end("Defiant", 1)
    clock.t += 500
    assert s.restore_idle(0, 180) == ["Defiant"] and s.open_nodes() == []


def test_running_ids_track_in_flight_jobs():
    s, *_ = make()
    s.begin("Defiant", 115, 7)
    assert s.running_ids() == {7}
    s.end("Defiant", 7)
    assert s.running_ids() == set()


# ── fake cursor ─────────────────────────────────────────────────────────────────────────────────────
class FakeCursor:
    def __init__(self, params=None):
        self.executed, self._params = [], params

    def execute(self, sql, args=None):
        self.executed.append((" ".join(sql.split()), args))

    def fetchone(self):
        return {"params": self._params}

    def fetchall(self):
        return [{"id": 1, "media_type": "image", "status": "pending", "model": "m"}]


def cursor_factory(cur):
    @contextlib.contextmanager
    def get_cursor(commit=False):
        yield (None, cur)

    return get_cursor


@pytest.fixture(autouse=True)
def fixed_settings(monkeypatch):
    values = {im.SETTING_MAX_RETRIES: 3, im.SETTING_COLD_TIMEOUT_S: 1200, im.SETTING_GRACE_S: 180}
    monkeypatch.setattr(im, "setting_int", lambda key, default, low, high: values.get(key, default))


# ── timeout retry ───────────────────────────────────────────────────────────────────────────────────
def test_timeout_requeues_and_counts_the_attempt():
    cur = FakeCursor(params={"model": "x"})
    assert im.requeue_or_fail(5, 1200, get_cursor=cursor_factory(cur)) == "requeued"
    sql, args = cur.executed[-1]
    assert "status = 'pending'" in sql and "started_at = NULL" in sql and args[0] == 1


def test_timeout_fails_for_good_once_retries_are_exhausted():
    cur = FakeCursor(params={"retry_count": 3})
    assert im.requeue_or_fail(5, 600, get_cursor=cursor_factory(cur)) == "failed"
    sql, args = cur.executed[-1]
    assert "status = 'failed'" in sql and "giving up" in args[0]


def test_timeout_with_no_params_row_is_a_first_attempt():
    cur = FakeCursor(params=None)
    assert im.requeue_or_fail(5, 600, get_cursor=cursor_factory(cur)) == "requeued"


# ── reaper ──────────────────────────────────────────────────────────────────────────────────────────
def test_reaper_covers_dispatched_rows_skips_running_ones_and_sits_above_the_cold_window():
    cur = FakeCursor()
    rows = im.reap_stuck(get_cursor=cursor_factory(cur), running={9, 4})
    sql, args = cur.executed[-1]
    assert rows and "status IN ('generating', 'dispatched')" in sql
    assert args["skip"] == [4, 9] and args["max"] == 3
    assert args["mins"] == 25  # cold window 1200s = 20 min, +5 min margin
    assert "retry_count" in sql and "'failed'" in sql
    assert "NOT (id = ANY(%(skip)s::int[]))" in sql  # rows the worker is running are never reaped


def test_reaper_threshold_never_drops_below_15_minutes():
    im_values = {im.SETTING_COLD_TIMEOUT_S: 60}
    cur = FakeCursor()
    im.setting_int = lambda key, default, low, high: im_values.get(key, default)  # noqa: E731
    im.reap_stuck(get_cursor=cursor_factory(cur), running=set())
    assert cur.executed[-1][1]["mins"] == 15


# ── wiring (source pins) ────────────────────────────────────────────────────────────────────────────
def _src(path):
    return (ROOT.parent / path).read_text()


def test_generate_via_comfyui_no_longer_swaps_and_restores_per_job():
    from tools.media_studio.services import generation_service as gs

    src = inspect.getsource(gs.generate_via_comfyui)
    assert "_vram_restore_after_comfyui" not in src and "_vram_swap_for_comfyui" not in src
    assert "get_sessions().begin(" in src and "get_sessions().end(" in src
    assert "requeue_or_fail(" in src and "will retry automatically" not in src


def test_worker_restores_idle_sessions_after_the_loop_and_when_the_queue_is_empty():
    src = _src("ai_bridge/agent_loop.py")
    assert src.count("self._media_restore_idle_sessions()") == 2
    assert "def _media_restore_idle_sessions" in src and "restore_idle(pending)" in src


def test_reaper_job_uses_reap_stuck():
    src = _src("platform_v2/tools/department_hq/jobs.py")
    assert "reap_stuck()" in src and "INTERVAL '15 minutes'" not in src.split("_run_media_generation_reaper")[1][:1500]

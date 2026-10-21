"""Per-node GPU lease (#7401): image sessions hold it, LLM dispatch yields when enforcement is on (default OFF).

Run with --noconftest: fake cursors, no database.
"""

import contextlib
import inspect
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "ai_bridge"))  # the dispatcher imports the db helper from ai_bridge

from services import node_gpu_lease as gl  # noqa: E402
from tools.media_studio.services import image_session as im  # noqa: E402


class Cur:
    def __init__(self, rows=None, one=None, raises=False):
        self.rows, self.one, self.raises, self.executed = rows or [], one, raises, []

    def execute(self, sql, args=None):
        if self.raises:
            raise RuntimeError("db down")
        self.executed.append((" ".join(sql.split()), args))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one


def factory(cur):
    @contextlib.contextmanager
    def get_cursor(commit=False):
        yield (None, cur)

    return get_cursor


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    gl.clear_cache()
    monkeypatch.setattr(gl, "_setting", lambda key, default: default)
    yield
    gl.clear_cache()


def set_settings(monkeypatch, **values):
    monkeypatch.setattr(gl, "_setting", lambda key, default: values.get(key, default))
    gl.clear_cache()


# ── enforcement flag ─────────────────────────────────────────────────────────────────────────────────
def test_enforcement_defaults_off_and_leased_ids_are_empty_even_with_live_leases():
    assert gl.enforcement_enabled() is False
    cur = Cur(rows=[{"id": 115}])
    assert gl.leased_node_db_ids(get_cursor=factory(cur)) == frozenset() and cur.executed == []  # never queried
    assert gl.is_node_leased(115) is False


@pytest.mark.parametrize(
    "raw,expected",
    [("true", True), ("1", True), ("YES", True), ("on", True), ("false", False), ("", False), ("nope", False)],
)
def test_only_explicit_truthy_strings_enable_enforcement(monkeypatch, raw, expected):
    set_settings(monkeypatch, **{gl.SETTING_ENABLED: raw})
    assert gl.enforcement_enabled() is expected


def test_when_enabled_leased_ids_come_from_live_leases_joined_to_remote_nodes(monkeypatch):
    set_settings(monkeypatch, **{gl.SETTING_ENABLED: "true"})
    cur = Cur(rows=[{"id": 115}, {"id": 120}])
    assert gl.leased_node_db_ids(get_cursor=factory(cur)) == frozenset({115, 120})
    sql, args = cur.executed[0]
    assert "JOIN remote_nodes" in sql and "heartbeat_at >" in sql and args == (180,)


def test_leased_ids_are_cached_briefly(monkeypatch):
    set_settings(monkeypatch, **{gl.SETTING_ENABLED: "true"})
    cur = Cur(rows=[{"id": 115}])
    f = factory(cur)
    gl.leased_node_db_ids(get_cursor=f)
    gl.leased_node_db_ids(get_cursor=f)
    assert len(cur.executed) == 1  # second call served from the 5s cache


def test_db_error_fails_open_to_no_lease(monkeypatch):
    set_settings(monkeypatch, **{gl.SETTING_ENABLED: "true"})
    assert gl.leased_node_db_ids(get_cursor=factory(Cur(raises=True))) == frozenset()


def test_junk_node_id_is_not_leased(monkeypatch):
    set_settings(monkeypatch, **{gl.SETTING_ENABLED: "true"})
    assert gl.is_node_leased(None) is False and gl.is_node_leased("abc") is False


# ── acquire / release ────────────────────────────────────────────────────────────────────────────────
def test_acquire_is_a_guarded_upsert_that_only_steals_a_dead_lease():
    cur = Cur(one={"node_name": "Defiant"})
    assert gl.acquire("Defiant", "w1", get_cursor=factory(cur)) is True
    sql, args = cur.executed[0]
    assert "ON CONFLICT (node_name) DO UPDATE" in sql
    assert "node_gpu_leases.holder = EXCLUDED.holder" in sql and "heartbeat_at < NOW() - make_interval" in sql
    assert args["node"] == "Defiant" and args["holder"] == "w1" and args["ttl"] == 180


def test_acquire_returns_false_when_another_live_holder_owns_it():
    assert gl.acquire("Defiant", "w2", get_cursor=factory(Cur(one=None))) is False


def test_acquire_fails_open_and_ignores_blank_node():
    assert gl.acquire("Defiant", "w1", get_cursor=factory(Cur(raises=True))) is False
    assert gl.acquire("", "w1") is False


def test_heartbeat_is_update_only_so_a_late_pulse_cannot_recreate_a_released_lease():
    cur = Cur(one=None)  # the row is gone (released): nothing to update
    assert gl.heartbeat("Defiant", "w1", get_cursor=factory(cur)) is False
    sql, args = cur.executed[0]
    assert sql.startswith("UPDATE node_gpu_leases SET heartbeat_at = NOW()") and "INSERT" not in sql
    assert args == ("Defiant", "w1")
    assert gl.heartbeat("", "w1") is False
    assert gl.heartbeat("Defiant", "w1", get_cursor=factory(Cur(raises=True))) is False  # fail-open


def test_release_only_deletes_the_callers_own_lease():
    cur = Cur(one={"node_name": "Defiant"})
    assert gl.release("Defiant", "w1", get_cursor=factory(cur)) is True
    sql, args = cur.executed[0]
    assert "DELETE FROM node_gpu_leases" in sql and "holder = %s" in sql and args == ("Defiant", "w1")


def test_ttl_is_bounded(monkeypatch):
    set_settings(monkeypatch, **{gl.SETTING_TTL_S: "5"})
    assert gl._ttl_s() == 30
    set_settings(monkeypatch, **{gl.SETTING_TTL_S: "999999"})
    assert gl._ttl_s() == 1800
    set_settings(monkeypatch, **{gl.SETTING_TTL_S: "junk"})
    assert gl._ttl_s() == gl.DEFAULT_TTL_S


# ── image session <-> lease ──────────────────────────────────────────────────────────────────────────
class FakeLease:
    def __init__(self, boom=False):
        self.calls, self.boom = [], boom

    def _do(self, what, node, holder):
        if self.boom:
            raise RuntimeError("lease db down")
        self.calls.append((what, node))

    def acquire(self, node, holder):
        self._do("acquire", node, holder)

    def heartbeat(self, node, holder):
        self._do("heartbeat", node, holder)

    def release(self, node, holder):
        self._do("release", node, holder)


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


def sessions(lease, order=None):
    clock = Clock()
    order = order if order is not None else []
    s = im.ImageSessions(
        clock=clock,
        swap=lambda n: ["qwen2.5:7b"],
        restore=lambda m, n: order.append("restore"),
        lease=lease,
        start_heartbeat=False,
    )
    return s, clock, order


def test_session_acquires_on_open_heartbeats_while_warm_and_releases_after_restore():
    lease = FakeLease()
    order = []
    original = lease.release
    lease.release = lambda node, holder: (order.append("release"), original(node, holder))
    s, clock, order = sessions(lease, order)
    s.begin("Defiant", 115, 1)
    s.end("Defiant", 1)
    s.begin("Defiant", 115, 2)
    s.end("Defiant", 2)
    assert [c[0] for c in lease.calls] == ["acquire", "heartbeat", "heartbeat", "heartbeat"]
    clock.t += 500
    s.restore_idle(0, 180)
    assert order == ["restore", "release"]  # Ollama is back BEFORE the node is handed back to LLM dispatch
    assert lease.calls[-1] == ("release", "Defiant")


def test_lease_failure_never_blocks_generation():
    s, clock, _ = sessions(FakeLease(boom=True))
    assert s.begin("Defiant", 115, 1) == {"cold": True}
    s.end("Defiant", 1)
    clock.t += 500
    assert s.restore_idle(0, 180) == ["Defiant"]


def test_a_session_that_never_ends_never_releases():
    lease = FakeLease()
    s, clock, _ = sessions(lease)
    s.begin("Defiant", 115, 1)
    clock.t += 10_000
    s.restore_idle(0, 0)
    assert ("release", "Defiant") not in lease.calls


def test_status_endpoint_exists_and_is_read_only():
    src = (ROOT / "tools" / "department_hq" / "fleet_dashboard_routes.py").read_text()
    i = src.index("/api/fleet/gpu-leases")
    block = src[i : i + 900]
    assert 'methods=["GET"]' in block and "active_leases" in block

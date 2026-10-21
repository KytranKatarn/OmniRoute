"""LLM-side enforcement of the per-node GPU lease (#7401, part 2): skip leased nodes, default OFF.

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


@pytest.fixture(autouse=True)
def reset(monkeypatch):
    gl.clear_cache()
    monkeypatch.setattr(gl, "_setting", lambda key, default: default)
    yield
    gl.clear_cache()


def set_settings(monkeypatch, **values):
    monkeypatch.setattr(gl, "_setting", lambda key, default: values.get(key, default))
    gl.clear_cache()


# ── LLM side honours the lease (and is a no-op when it is off) ───────────────────────────────────────
def test_dispatcher_lease_check_is_false_when_off_and_fail_open():
    from tools.department_hq.services.department_dispatcher import DepartmentDispatcher

    d = object.__new__(DepartmentDispatcher)
    assert d._node_gpu_leased(115) is False  # flag default off


def test_dispatcher_lease_check_follows_the_lease_service(monkeypatch):
    from tools.department_hq.services.department_dispatcher import DepartmentDispatcher

    monkeypatch.setattr(gl, "is_node_leased", lambda nid: nid == 115)
    d = object.__new__(DepartmentDispatcher)
    assert d._node_gpu_leased(115) is True and d._node_gpu_leased(120) is False

    def boom(nid):
        raise RuntimeError("x")

    monkeypatch.setattr(gl, "is_node_leased", boom)
    assert d._node_gpu_leased(115) is False  # fail-open


def test_dispatcher_wires_the_lease_into_every_node_choice():
    from tools.department_hq.services import department_dispatcher as dd

    src = inspect.getsource(dd.DepartmentDispatcher)
    assert src.count("self._node_gpu_leased(") >= 3  # preferred pin, node-preference, score-routing
    assert "rn.id NOT IN (" in src and "leased_node_db_ids" in src  # stationed-agent finder SQL filter


def test_router_skips_leased_nodes():
    from services import fleet_resource_router as fr

    src = inspect.getsource(fr.find_best_node_for_model)
    assert "leased_node_db_ids" in src and 'node.get("id") in _leased' in src


class WarmCur(Cur):
    def __init__(self, rows):
        super().__init__(rows=rows)


def test_warm_model_maps_drop_leased_nodes_and_are_unchanged_when_off(monkeypatch):
    from services import model_dispatch_service as mds

    rows = [{"id": 115, "model_name": "qwen2.5:7b"}, {"id": 120, "model_name": "qwen2.5:7b"}]
    monkeypatch.setattr(mds, "get_db_cursor", factory(WarmCur(rows)))
    assert mds._get_warm_models_nodes() == {"qwen2.5:7b": 115}  # off: first row wins, as before
    set_settings(monkeypatch, **{gl.SETTING_ENABLED: "true"})
    monkeypatch.setattr(gl, "leased_node_db_ids", lambda get_cursor=None: frozenset({115}))
    monkeypatch.setattr(mds, "get_db_cursor", factory(WarmCur(rows)))
    assert mds._get_warm_models_nodes() == {"qwen2.5:7b": 120}  # leased node skipped


def test_pinned_tasks_fall_back_to_the_hub_while_the_node_is_leased():
    from services import model_dispatch_service as mds

    src = inspect.getsource(mds._execute_task)
    assert "is_node_leased(preferred)" in src and "holds an image GPU lease" in src and "using hub" in src
    assert "elif _online:" in src  # un-leased online pin still routes to the node


def test_all_nodes_warm_map_skips_leased():
    from services import model_dispatch_service as mds

    src = inspect.getsource(mds._get_all_warm_nodes_for_models)
    assert 'row["id"] in _leased' in src

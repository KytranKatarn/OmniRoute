"""Fleet Command IMAGE LEASE switch: the POST that flips dispatch:gpu_lease:enabled, and the UI wiring."""

import contextlib
import pathlib

import pytest
from flask import Blueprint, Flask

ROOT = pathlib.Path(__file__).resolve().parents[1] / "tools" / "department_hq"


class FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))


@pytest.fixture
def client(monkeypatch):
    from tools.department_hq import fleet_dashboard_routes as mod
    from services import node_gpu_lease

    writes, cleared = [], []

    @contextlib.contextmanager
    def fake_cursor(commit=False):
        yield (None, FakeCursor(writes))

    monkeypatch.setattr(mod, "get_db_cursor", fake_cursor)
    monkeypatch.setattr(node_gpu_lease, "clear_cache", lambda: cleared.append(1))
    app = Flask(__name__)
    bp = Blueprint("t", __name__, url_prefix="/tools/department-hq")
    mod.register_dashboard_routes(bp, lambda f: f)
    app.register_blueprint(bp)
    return app.test_client(), writes, cleared


URL = "/tools/department-hq/api/fleet/gpu-leases/enforcement"


@pytest.mark.parametrize("value", [True, False])
def test_post_writes_the_setting_and_clears_the_cache(client, value):
    c, writes, cleared = client
    r = c.post(URL, json={"enabled": value})
    assert r.status_code == 200 and r.get_json() == {"success": True, "enforcement": value}
    assert len(writes) == 1
    sql, params = writes[0]
    assert "platform_settings" in sql and "ON CONFLICT" in sql
    assert params[0] == "dispatch:gpu_lease:enabled" and params[1] == str(value).lower()
    assert cleared == [1]


@pytest.mark.parametrize("body", [{}, {"enabled": "true"}, {"enabled": 1}, {"enabled": None}])
def test_a_non_boolean_is_refused_and_writes_nothing(client, body):
    c, writes, cleared = client
    r = c.post(URL, json=body)
    assert r.status_code == 400 and r.get_json()["success"] is False
    assert writes == [] and cleared == []


def test_the_get_status_route_stays_read_only():
    src = (ROOT / "fleet_dashboard_routes.py").read_text(encoding="utf-8")
    block = src[src.index('"/api/fleet/gpu-leases"') :][:200]
    assert 'methods=["GET"]' in block


def test_the_switch_sits_in_fleet_command_beside_the_lease_status():
    html = (ROOT / "templates" / "department_hq.html").read_text(encoding="utf-8")
    start = html.index('id="fleetCommandSection"')
    cmd = html[start : html.index('id="crBody"', start)]
    assert 'id="gpuLeaseToggle"' in cmd and "toggleGpuLeaseEnforcement(this.checked)" in cmd
    assert cmd.index('id="gpuLeaseToggle"') < cmd.index('id="fleetGpuLease"')


def test_the_painter_sets_the_switch_before_it_can_return_early():
    js = (ROOT / "static" / "js" / "department-hq.js").read_text(encoding="utf-8")
    body = js[js.index("function loadGpuLeases()") : js.index("function setFleetDispatchMode")]
    assert body.index("_applyGpuLeaseToggle(!!d.enforcement)") < body.index(
        "!d.leases.length"
    )  # also when no lease is held
    toggle = js[js.index("function toggleGpuLeaseEnforcement") :][:700]
    assert (
        "/api/fleet/gpu-leases/enforcement" in toggle and "_applyGpuLeaseToggle(!enabled)" in toggle
    )  # reverts on failure

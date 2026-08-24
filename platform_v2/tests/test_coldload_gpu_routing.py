"""Cold-load worker hub-last ordering (Fix B / task #3809).

The model_dispatch_worker drains each model's node list IN ORDER (first node
claims the tasks). The hub (None sentinel) must come LAST for any multi-node
model so a prefer_gpu 7B drains to a GPU fleet node first instead of the hub's
slow Quadro/CPU (which blows the 300s read-timeout — the F.O.R.G.E. code_review
failure). Models warm only on the hub (len-1) are never stranded.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest  # noqa: E402
from tests.modstub import stub_module_scoped  # noqa: E402

# model_dispatch_service pulls heavy deps at import (requests, dispatcher, db).
# Stub the ones not needed for the pure ordering helper so the import resolves.
for _name in ("requests",):
    sys.modules.setdefault(_name, MagicMock())
_pkg_tools = sys.modules.setdefault("tools", types.ModuleType("tools"))
_pkg_dhq = sys.modules.setdefault("tools.department_hq", types.ModuleType("tools.department_hq"))
_pkg_services = sys.modules.setdefault("tools.department_hq.services", types.ModuleType("tools.department_hq.services"))
_stub_disp = types.ModuleType("tools.department_hq.services.department_dispatcher")
_stub_disp.dispatch = MagicMock(return_value=MagicMock(success=False))
_stub_disp.get_dispatcher = MagicMock()

# PEP 562 catch-all: a sys.modules stub replaces the module for the WHOLE session, so
# ANY name a later-collected module imports from it must resolve or collection aborts
# for all 3,332 tests (#5665). Enumerating names is whack-a-mole — dispatch_json,
# DispatchResult and resolve_department_escalation_owner each surfaced in turn.
# Explicitly-set attributes above still win; this only catches the rest.
_stub_disp.__getattr__ = lambda _n: MagicMock()
# ── Scoped to THIS MODULE'S tests, not the whole session (#6018) ─────────────────────
# This was a bare, permanent assignment at import time. pytest imports every test module
# during COLLECTION, so from that point the stub was what the ENTIRE session saw and any
# later module wanting the real dispatcher silently got the stub instead (#6017).
_DISPATCHER = "tools.department_hq.services.department_dispatcher"


@pytest.fixture(scope="module", autouse=True)
def _dispatcher_stub():
    """Install the dispatcher stub for this module only; restore both bindings after."""
    with stub_module_scoped(_DISPATCHER, _stub_disp):
        yield


from services.model_dispatch_service import _order_nodes_hub_last  # noqa: E402


def _ordered(nodes):
    _order_nodes_hub_last(nodes)
    return nodes


def test_hub_moved_last_among_fleet_nodes():
    assert _ordered([None, 1, 2]) == [1, 2, None]
    assert _ordered([1, None, 2]) == [1, 2, None]
    assert _ordered([1, 2, None]) == [1, 2, None]  # already last


def test_hub_only_is_not_stranded():
    # len-1: a model warm ONLY on the hub must stay [None], never emptied.
    assert _ordered([None]) == [None]


def test_no_hub_is_noop():
    assert _ordered([1, 2]) == [1, 2]
    assert _ordered([]) == []


def test_single_fleet_node_is_noop():
    assert _ordered([5]) == [5]

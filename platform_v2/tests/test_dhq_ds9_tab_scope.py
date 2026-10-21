"""The Deep Space 9 tab is for EXTERNAL clients only. Local node tooling lives in Fleet.

The DS9 tab is the platform's view of the DS9 gateway: the external upstreams
(engineer_providers), their throttle/quota, their budgets, and the Codex
app-server connection. Local fleet-node tooling is a different subject and
belongs on the Fleet tab.

The three fleet-node modals - node detail, add node, repair node - were parked
in the DS9 panel, while their TRIGGERS (the two buttons in the fleet header)
were on the Fleet tab. That was not just untidy: an inactive .dhq-panel is
`display: none`, so markup parked in the DS9 panel made those modals
INVISIBLE when opened from the fleet tab. The buttons did nothing visible.

These tests pin the arrangement, because "it renders in the same file" is not a
property anyone can regress accidentally and then notice.
"""

from __future__ import annotations

import re
from pathlib import Path


PLATFORM = Path(__file__).resolve().parents[1]
TEMPLATE = PLATFORM / "tools" / "department_hq" / "templates" / "department_hq.html"


def _source() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def _panel_bounds(pid: str) -> tuple[int, int]:
    """The (start, end) line offsets of a dhq-panel, by its id."""
    lines = _source().split("\n")
    start = next(i for i, l in enumerate(lines) if f'id="{pid}"' in l)
    end = next(i for i in range(start + 1, len(lines)) if 'class="dhq-panel"' in lines[i])
    return start, end


def _panel_text(pid: str) -> str:
    lines = _source().split("\n")
    start, end = _panel_bounds(pid)
    return "\n".join(lines[start:end])


# The local node tooling that must NOT be in the DS9 tab.
LOCAL_NODE_MODALS = ("fleetNodeModal", "addNodeModal", "repairNodeModal")


def test_the_ds9_tab_holds_no_local_node_modals():
    """Local node tooling belongs to the Fleet tab, not the external-clients tab."""
    ds9 = _panel_text("panel-engineers")
    for modal in LOCAL_NODE_MODALS:
        assert f'id="{modal}"' not in ds9, f"{modal} is local fleet-node tooling and does not belong in the DS9 tab"


def test_the_fleet_modals_live_in_the_fleet_tab():
    """They must be in the panel that shows them: an inactive panel is display:none."""
    fleet = _panel_text("panel-fleet")
    for modal in LOCAL_NODE_MODALS:
        assert f'id="{modal}"' in fleet, f"{modal} must live in the Fleet tab, where its triggers are"


def test_the_fleet_triggers_and_their_modals_are_in_the_same_panel():
    """A modal whose trigger is on the Fleet tab but whose markup is not is
    invisible when opened - the button appears to do nothing."""
    fleet = _panel_text("panel-fleet")
    for opener in ("openAddNodeModal()", "openRepairNodeModal()"):
        assert opener in fleet, f"{opener} should still be reachable from the Fleet tab"
    for modal in LOCAL_NODE_MODALS:
        assert f'id="{modal}"' in fleet


def test_the_ds9_tab_still_shows_the_external_client_surface():
    """The cleanup must not take the tab's own content with it."""
    ds9 = _panel_text("panel-engineers")
    for element in (
        "cloudMasterToggle",  # the external cloud-AI master toggle
        "engineers-summary",  # external provider counts
        "ds9QuotaCard",  # per-upstream throttle (external)
        "ds9AppServerCard",  # the Codex app-server connection (external)
        "engineers-grid",  # the external providers grid
        "fleetUsageCalls",  # 30-day spend roll-up (external providers)
        "fleetUsageCost",
        "fleetUsageProviders",
        "fleetBudgetTableBody",  # per-provider budgets (external)
    ):
        assert f'id="{element}"' in ds9, f"{element} should still be in the DS9 tab"


def test_there_are_no_dead_empty_containers_left_in_the_ds9_tab():
    """engineerProvidersContent / engineerDefinitionsContent were empty divs
    that nothing ever painted."""
    ds9 = _panel_text("panel-engineers")
    for dead in ("engineerProvidersContent", "engineerDefinitionsContent"):
        assert f'id="{dead}"' not in ds9, f"{dead} is an empty container nothing paints"


def test_the_modals_are_still_well_formed():
    """Moving markup must not break the element structure."""
    src = _source()
    for modal in LOCAL_NODE_MODALS:
        assert src.count(f'id="{modal}"') >= 1, f"{modal} disappeared"
    # Every bm-overlay still has its close handler.
    for modal, closer in (
        ("fleetNodeModal", "closeFleetDetail()"),
        ("addNodeModal", "closeAddNodeModal()"),
        ("repairNodeModal", "closeRepairNodeModal()"),
    ):
        block = re.search(r'<div id="%s".*?</div>\s*</div>\s*</div>' % re.escape(modal), src, re.S)
        assert block, f"{modal} markup not found"
        assert closer in src, f"{modal} lost its close handler"


def test_the_panels_are_still_balanced():
    """A move that unbalanced the divs would break the whole page."""
    src = _source()
    opens = len(re.findall(r"<div\b", src))
    closes = len(re.findall(r"</div>", src))
    assert opens == closes, f"unbalanced: {opens} open vs {closes} close"

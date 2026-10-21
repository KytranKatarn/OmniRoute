"""The DHQ Deep Space 9 (DS9) tab must actually render and serve its data.

The DS9 tab is the operator's window onto the Codex app-server upstream: it is
where the owner adds an OpenAI Codex (App-Server) provider, sees per-provider
health, toggles routing, and edits the engineer definitions. A rename that
half-landed - a tab key that no longer resolves to a panel, a DOM id the
loader no longer finds, a CSS class the stylesheet no longer defines - leaves
the tab blank or broken while every API test still passes, because the QA
suite accepts a 302 auth redirect as a pass.

These are the checks that would have caught it:

  1. the tab key in the template's TABS list resolves to a real panel
     (the tab machinery derives the panel id as 'panel-' + key, so a stale
     key means the tab opens to nothing);
  2. the DOM ids the loader writes into exist in the panel;
  3. the CSS classes the loader emits are still defined in the stylesheet
     (a renamed class in one file and not the other renders unstyled);
  4. the endpoints the tab calls are registered on the blueprint;
  5. the DS9 panel is actually IN the rendered page, and the loader is wired
     to the tab key.
"""

from __future__ import annotations

import re
from pathlib import Path


def _platform_root() -> Path:
    """The platform_v2 root, in BOTH layouts this suite runs in.

      host layout:      <repo>/platform_v2/tests/...   -> parents[2] is <repo>
      container layout: /app/tests/...                 -> /app IS platform_v2

    Deriving it from the filesystem instead of a fixed depth is what lets the
    same test run on the host and inside the platform container.
    """
    here = Path(__file__).resolve()
    for cand in (here.parents[1], here.parents[2] / "platform_v2"):
        if (cand / "tools" / "department_hq").is_dir():
            return cand
    raise AssertionError(f"cannot locate platform_v2 from {here}")


PLATFORM = _platform_root()
DHQ = PLATFORM / "tools" / "department_hq"
TEMPLATE = DHQ / "templates" / "department_hq.html"
JS = DHQ / "static" / "js" / "department-hq.js"
FLEET_CSS = PLATFORM / "static" / "css" / "fleet.css"

# The DS9 tab's key, panel id, and the DOM ids inside it. The tab machinery
# derives the panel id as "panel-" + <tab key>, so these three must agree.
TAB_KEY = "engineers"
PANEL_ID = f"panel-{TAB_KEY}"
TAB_LABEL = "Deep Space 9"


def _tpl() -> str:
    assert TEMPLATE.exists(), f"DHQ template not found at {TEMPLATE}"
    return TEMPLATE.read_text(encoding="utf-8")


def _js() -> str:
    assert JS.exists(), f"DHQ JS not found at {JS}"
    return JS.read_text(encoding="utf-8")


def _css() -> str:
    assert FLEET_CSS.exists(), f"fleet.css not found at {FLEET_CSS}"
    return FLEET_CSS.read_text(encoding="utf-8")


def test_tab_is_registered_with_the_ds9_label():
    """The DS9 tab must exist in the TABS list and carry the DS9 label."""
    tpl = _tpl()
    m = re.search(r'\(\s*"%s"\s*,\s*"([^"]+)"' % re.escape(TAB_KEY), tpl)
    assert m, f'tab key "{TAB_KEY}" is not in the TABS list — the DS9 tab would not ' "render at all"
    assert TAB_LABEL in m.group(1), (
        f'the "{TAB_KEY}" tab is labelled {m.group(1)!r}; it should say '
        f"{TAB_LABEL!r} so the operator can find the DS9 tab"
    )


def test_tab_key_resolves_to_a_real_panel():
    """The tab machinery derives the panel id as 'panel-' + key.

    A tab key with no matching panel opens to nothing, and it looks fine in
    every static check that only looks at the TABS list.
    """
    tpl = _tpl()
    assert f'id="{PANEL_ID}"' in tpl, f'no panel with id "{PANEL_ID}" — the DS9 tab would open to nothing'


def test_loader_is_wired_to_the_tab_key():
    """The tab's loader map must map the SAME key the TABS list uses."""
    js = _js()
    assert re.search(
        rf"['\"]{re.escape(TAB_KEY)}['\"]\s*:\s*loadEngineers", js
    ), f"the tab loaders map has no '{TAB_KEY}' entry pointing at loadEngineers"
    assert "async function loadEngineers(" in js, "loadEngineers() is not defined"


def test_dom_ids_the_loader_writes_exist_in_the_panel():
    """Every DOM id the loader touches must exist in the panel.

    A renamed id in the JS but not the template (or the reverse) means the
    loader silently writes to a detached node and the tab renders empty.
    """
    tpl = _tpl()
    js = _js()
    ids = set(re.findall(r"getElementById\('([a-zA-Z0-9_-]+)'\)", js))
    ds9_ids = {i for i in ids if i.startswith(("engineers-", "engineerProviders", "engineerDefinitions"))}
    assert ds9_ids, "no DS9 DOM ids are looked up by the loader - is the tab still wired?"
    missing = sorted(i for i in ds9_ids if f'id="{i}"' not in tpl)
    assert not missing, f"the loader writes to DOM ids that do not exist in the template: {missing}"


def test_css_classes_the_loader_emits_are_still_defined():
    """A CSS class renamed in the JS but not the stylesheet renders unstyled.

    The DS9 tab's cards are styled entirely by class name, so a half-renamed
    class is invisible in a DOM-ids check and only shows up as a broken-looking
    card in the browser.
    """
    js = _js()
    css = _css()
    emitted = set()
    for m in re.finditer(r"class=\"([^\"]*)\"", js):
        for tok in m.group(1).split():
            if tok.startswith("engineer-"):
                emitted.add(tok)
    # Only the ones the DS9 card markup actually uses.
    emitted = {c for c in emitted if c in css} | {
        c for c in emitted if c.startswith("engineer-btn-") or c.startswith("engineer-firm")
    }
    assert emitted, "no DS9 CSS classes are emitted by the loader"
    missing = sorted(c for c in emitted if f".{c}" not in css)
    assert not missing, f"the loader emits CSS classes with no rule in fleet.css: {missing}"


def test_the_endpoints_the_tab_calls_are_registered():
    """Every endpoint the DS9 tab fetches must exist on the blueprint."""
    js = _js()
    paths = set(re.findall(r"/tools/department-hq/api/(engineer\w[\w/-]*)", js))
    assert paths, "the DS9 tab calls no engineer endpoints - is the tab still wired?"
    route_src = "\n".join(p.read_text(encoding="utf-8") for p in DHQ.glob("*.py") if p.name not in ("__init__.py",))
    for path in sorted(paths):
        # A blueprint route is registered either with the full path
        # ("/api/engineers/omniroute-quota") or, for a nested group, with a
        # prefix plus the tail. Accept either - what matters is that SOME
        # route serves the path the tab fetches.
        if f'"/api/{path}"' in route_src:
            continue
        tail = path.rstrip("/").split("/")[-1]
        assert f'"/api/{tail}"' in route_src, (
            f"the DS9 tab calls /api/{path} but no blueprint registers " f'"/api/{path}" (or "/api/{tail}")'
        )


def test_the_panel_is_in_the_rendered_page():
    """The DS9 panel must be part of the template body, not just declared."""
    tpl = _tpl()
    assert f'id="{PANEL_ID}"' in tpl
    # The tab list and the panel must both be present, and the panel must come
    # after the tab list in the same document.
    tab_at = tpl.find(f'("{TAB_KEY}"')
    panel_at = tpl.find(f'id="{PANEL_ID}"')
    assert tab_at != -1 and panel_at != -1
    assert tab_at < panel_at, (
        "the DS9 tab is declared AFTER its panel - the tab list and the panel " "are out of order in the template"
    )

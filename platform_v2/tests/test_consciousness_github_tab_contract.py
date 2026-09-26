"""The Consciousness GitHub tab's markup and JS must stay in contract.

``loadGitHub()`` in ``static/js/consciousness.js`` writes a fixed set of
``gh*`` element ids with ``setHtml``. ``setHtml`` on a missing id is a **silent
no-op** — no error, no console warning, the number simply never appears. That is
exactly how the repo review-status filter died: the JS kept
``filterRepos()``/``_ghFilter``/the ``ghFilter*`` count writers, the markup went
away, and nothing failed visibly. 18 repos were left sitting in
``under_review`` behind a filter nobody could reach.

These tests assert the contract from both directions so the next removal is a
test failure rather than a silent blank.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parents[1]
JS = PLATFORM / "static" / "js" / "consciousness.js"
TEMPLATE = PLATFORM / "tools" / "consciousness" / "templates" / "consciousness_dashboard.html"

# The JS names the under_review count `ghFilterReview`, not ghFilterUnderReview.
# Encoded here rather than derived, because deriving it is how the test lied.
FILTER_IDS = {
    "all": "ghFilterAll",
    "approved": "ghFilterApproved",
    "under_review": "ghFilterReview",
    "pending": "ghFilterPending",
    "rejected": "ghFilterRejected",
}


@pytest.fixture(scope="module")
def js() -> str:
    return JS.read_text()


@pytest.fixture(scope="module")
def tpl() -> str:
    return TEMPLATE.read_text()


def _element_by_id(html: str, element_id: str) -> str:
    m = re.search(r"<[a-zA-Z][^>]*\bid=\"%s\"[^>]*>" % re.escape(element_id), html, re.S)
    return m.group(0) if m else ""


def _strip_js_comments(source: str) -> str:
    """Remove // and /* */ comments so prose about old code can't satisfy a grep."""
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    source = re.sub(r"(?m)//.*$", " ", source)
    # Keep string literals intact enough that a '//' inside one is not eaten;
    # none of the assertions below look inside strings, so this is sufficient.
    return source


def _function_body(source: str, name: str) -> str:
    """Crude but sufficient: the text of `function name(...) { ... }`."""
    m = re.search(r"function\s+%s\s*\([^)]*\)\s*\{" % re.escape(name), source)
    if not m:
        return ""
    i = m.end() - 1
    depth = 0
    for j in range(i, len(source)):
        if source[j] == "{":
            depth += 1
        elif source[j] == "}":
            depth -= 1
            if depth == 0:
                return source[i : j + 1]
    return source[i:]


def test_every_gh_id_the_js_writes_exists_in_the_template(js, tpl):
    """Scoped to gh* — consciousness.js also drives ids owned by other modules."""
    written = sorted(set(re.findall(r'setHtml\("(gh[A-Za-z0-9_]+)"', js)))
    assert len(written) >= 20, f"expected the gh* id set, found only {len(written)}"
    missing = [i for i in written if not _element_by_id(tpl, i)]
    assert not missing, (
        f"{len(missing)} gh* id(s) the JS writes to do not exist in the template: "
        f"{missing}. setHtml() on a missing id is a silent no-op, so this presents "
        f"as a blank field rather than an error."
    )


def test_repo_review_filter_is_reachable(js, tpl):
    assert "function filterRepos(" in js
    assert "_ghFilter" in js
    for status, eid in FILTER_IDS.items():
        assert _element_by_id(tpl, eid), f"missing filter count element {eid} ({status})"
        btn = _element_by_id(tpl, "ghFilterBar")
        assert btn, "filter bar container missing"
        assert f"data-gh-filter=\"{status}\"" in tpl, f"no button for status {status!r}"


def test_view_toggle_is_not_swept_by_the_filter_active_reset(js, tpl):
    """filterRepos() clears .active across every .gh-filter-btn."""
    body = _strip_js_comments(_function_body(js, "filterRepos"))
    assert body, "filterRepos() not found"
    assert ".gh-filter-btn" in body and "classList.remove('active')" in body
    toggle = _element_by_id(tpl, "ghViewToggle")
    assert toggle, "ghViewToggle not in template"
    assert "gh-filter-btn" not in toggle, (
        "ghViewToggle must not carry .gh-filter-btn — filterRepos() strips .active "
        "from every .gh-filter-btn, which would corrupt the toggle's own state"
    )
    assert "gh-view-toggle" in toggle


def test_filter_styles_exist(js, tpl):
    """All gh-* styling is inline in this template, so it must be added there too."""
    assert ".gh-filter-btn" in tpl, "no .gh-filter-btn styles in the template"
    assert ".gh-view-toggle" in tpl, "no .gh-view-toggle styles in the template"
    assert ".gh-filter-btn.active" in tpl, "no active-state style for the filter buttons"
    assert ".gh-filter-count" in tpl, "no style for the count badges"


def test_filter_buttons_pass_their_element_explicitly(js, tpl):
    """filterRepos() used the implicit global `event`, absent in Firefox/Safari."""
    body = _strip_js_comments(_function_body(js, "filterRepos"))
    assert "event.target" not in body, (
        "filterRepos() must not depend on the deprecated implicit global `event` "
        "— it is absent in Firefox and Safari, and the count <span> inside each "
        "button makes event.target the wrong node anyway"
    )
    assert re.search(r"function filterRepos\(status,\s*btn\)", js)
    calls = re.findall(r"filterRepos\('([a-z_]+)',\s*this\)", tpl)
    assert sorted(calls) == sorted(FILTER_IDS), (
        f"every filter button must call filterRepos('<status>', this); got {calls}"
    )


def test_every_github_panel_onclick_handler_is_defined(js, tpl):
    """An undefined handler fails only on click, in a browser, for that user."""
    start = tpl.find('id="panel-github"')
    assert start > 0, "panel-github not found in the template"
    seg = tpl[start : start + 40000]
    handlers = sorted(set(re.findall(r'onclick="([a-zA-Z_][a-zA-Z0-9_]*)\(', seg)))
    assert handlers, "no onclick handlers found in panel-github"
    undefined = [
        h
        for h in handlers
        if not re.search(r"function\s+%s\s*\(" % re.escape(h), js)
        and not re.search(r"window\.%s\s*=\s*function" % re.escape(h), js)
    ]
    assert not undefined, f"onclick handlers with no JS definition: {undefined}"

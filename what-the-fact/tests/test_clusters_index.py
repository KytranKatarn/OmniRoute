"""Guard: the /clusters index (#6149 Design phase 2).

Pure imports + file reads — no DB, no network, no app context, so this cannot
silently SKIP.

🔴 THE LOAD-BEARING TESTS ARE
   test_no_template_uses_a_filter_this_app_does_not_register  and
   test_the_sql_ordinal_matches_the_python_band_order.

The first generalises a bug that nearly shipped here: the first draft wrote
`{{ cl.last_pub | localtime }}`, copying the PLATFORM's Jinja filter. WTF is a
separate Flask app that registers NO custom filters at all — an unknown filter
raises TemplateAssertionError at render time, so that one character sequence
would have 500'd the page on every request while looking entirely idiomatic.

The second pins the two halves of the lean scale together. The median is
computed in SQL from a CASE, and the label is looked up in Python from
_BAND_ORDER. Nothing but this test makes those agree, and if they drift the
page confidently prints the wrong lean — the failure is invisible because both
halves still "work".
"""
from __future__ import annotations

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEMPLATES = ROOT / "consumer" / "templates"
CLUSTERS_HTML = TEMPLATES / "clusters.html"

from consumer.routes import (  # noqa: E402
    _BAND_ORDER,
    _BAND_ORD_SQL,
    _CLUSTER_WINDOWS,
    _age_text,
    _band_label,
    _spread_sentence,
)


# ───────────────────────────────────────── 🔴 class-level guard 1: filters

def test_no_template_uses_a_filter_this_app_does_not_register():
    """Every filter used in a consumer template must be a Jinja builtin.

    This app defines no @app.template_filter anywhere, so the builtin set IS
    the whole vocabulary. Using anything else is a 500, not a fallback.

    Scoped to the templates this change owns plus its macro library; widening
    it to all 47 templates is a separate cleanup, not this PR's business.
    """
    from jinja2.filters import FILTERS

    builtin = set(FILTERS)
    for tpl in (CLUSTERS_HTML, TEMPLATES / "_archetypes.html"):
        body = tpl.read_text()
        # `{{ x | foo }}` / `{{ x|foo(...) }}` — the name right after a pipe.
        used = set(re.findall(r"\|\s*([a-zA-Z_][a-zA-Z0-9_]*)", body))
        unknown = sorted(used - builtin)
        assert not unknown, (
            f"{tpl.name} uses filter(s) this app never registers: {unknown} — "
            "that is a TemplateAssertionError at render time, not a no-op"
        )


# ──────────────────────────────────── 🔴 class-level guard 2: scale agreement

def test_the_sql_ordinal_matches_the_python_band_order():
    """The SQL CASE and _BAND_ORDER must encode the SAME scale.

    If they drift, percentile_disc returns an index into one scale and
    _band_label reads it out of another — the page then reports a median lean
    that is real, plausible, and wrong.
    """
    pairs = re.findall(r"WHEN '([a-z-]+)' THEN (\d+)", _BAND_ORD_SQL)
    assert pairs, "could not parse the ordinal CASE — the guard would be vacuous"
    mapping = {band: int(n) for band, n in pairs}
    assert mapping == {b: i for i, b in enumerate(_BAND_ORDER)}, (
        f"SQL says {mapping}, Python says {dict(enumerate(_BAND_ORDER))}"
    )


def test_the_scale_is_ordered_left_to_right():
    """Not just consistent — correctly ORDERED. A median is meaningless on a
    scale whose middle value is not politically in the middle."""
    assert _BAND_ORDER.index("center") == 2
    assert _BAND_ORDER.index("left") < _BAND_ORDER.index("center-left") < _BAND_ORDER.index("center")
    assert _BAND_ORDER.index("center") < _BAND_ORDER.index("center-right") < _BAND_ORDER.index("right")


# ─────────────────────────────────────────────────────────── band labels

def test_band_label_reads_the_scale():
    assert _band_label(0) == "Left"
    assert _band_label(2) == "Center"
    assert _band_label(4) == "Right"
    assert _band_label(1) == "Center-Left"


@pytest.mark.parametrize("bad", [None, 99, -1, "center", object()])
def test_band_label_never_prints_garbage(bad):
    """Returns '' rather than raising or rendering 'None' into the page."""
    assert _band_label(bad) == "" or isinstance(_band_label(bad), str)
    assert "None" not in _band_label(bad)


# ──────────────────────────────────── the spread sentence (the card body)

def test_a_real_spread_names_both_ends():
    s = _spread_sentence(outlets=3, scored=3, lo=0, hi=4)
    assert "Left" in s and "Right" in s and "3 outlets" in s


def test_no_spread_SAYS_SO_rather_than_implying_variety():
    """🔴 Non-vacuity. 81% of clusters are single-band (measured: 440 of 546
    over 7 days). If this case rendered the same shape as a real spread, the
    page would imply framing diversity across four cards in five that do not
    have any."""
    s = _spread_sentence(outlets=6, scored=6, lo=2, hi=2)
    assert "No framing spread" in s
    assert "same band" in s
    assert "Center" in s


def test_an_unscored_cluster_admits_it():
    s = _spread_sentence(outlets=2, scored=0, lo=None, hi=None)
    assert "not" in s.lower() or "no outlet" in s.lower()
    assert "None" not in s


def test_singular_plural_is_not_embarrassing():
    assert "1 scored outlet " in _spread_sentence(1, 1, 2, 2)
    assert "2 scored outlets" in _spread_sentence(2, 2, 2, 2)


# ───────────────────────────────────────────────────────────── age text

def test_age_text_buckets():
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    now = _dt.now(_tz.utc).replace(tzinfo=None)
    assert _age_text(now - _td(minutes=31)) == "31m ago"
    assert _age_text(now - _td(hours=3)) == "3h ago"
    assert _age_text(now - _td(days=2)) == "2d ago"


def test_age_text_survives_null_and_clock_skew():
    """A published_at a few seconds in the future (ingest clock skew) must not
    render '-1m ago'."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    assert _age_text(None) == "—"
    future = _dt.now(_tz.utc).replace(tzinfo=None) + _td(minutes=5)
    assert _age_text(future) == "just now"


def test_age_text_accepts_an_aware_datetime_too():
    """The column is naive UTC, but a caller passing an aware value must not
    crash the page with a naive/aware TypeError."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    assert _age_text(_dt.now(_tz.utc) - _td(hours=2)) == "2h ago"


# ───────────────────────────────────────────────── page honesty + wiring

def _rendered_source() -> str:
    """clusters.html with its {# ... #} comments stripped.

    ⚠️ These tests check what a READER can see. The template documents the
    traps it avoids by NAMING them ("not clusters|length", "22 OUTLETS"), so a
    naive substring check fails on the very comment that proves the trap was
    avoided — a test that punishes documentation. Strip the comments and assert
    against what actually renders.
    """
    return re.sub(r"\{#.*?#\}", "", CLUSTERS_HTML.read_text(), flags=re.DOTALL)


def test_the_comment_stripper_actually_strips():
    """Non-vacuity: if this regex silently matched nothing, the two tests below
    would be checking the raw file again and would fail, not pass — but prove
    it anyway rather than trusting it."""
    assert "22 OUTLETS" in CLUSTERS_HTML.read_text(), "fixture assumption changed"
    assert "22 OUTLETS" not in _rendered_source()


def test_the_page_does_not_reuse_the_prototype_overstated_numbers():
    """The design prototype hardcodes '22 OUTLETS' and six differently-leaning
    cards. The widest real cluster measured 8. Nothing static may leak in."""
    body = _rendered_source()
    assert "22 OUTLETS" not in body
    for mock in ("Bank of Canada holds overnight rate", "Grocery price index"):
        assert mock not in body, "prototype mock copy leaked into the template"


def test_the_count_tile_uses_the_window_total_not_the_page_size():
    """The exact trap called out in blindspot.html: labelling the page size as
    the number of clusters in the window."""
    body = _rendered_source()
    assert "totals.qualifying" in body
    assert "clusters|length" not in body


def test_the_median_not_average_rule_is_stated_on_the_page():
    """The page reports a median; a reader is owed the reason it is not a mean."""
    body = CLUSTERS_HTML.read_text()
    assert "not an average" in body


def test_windows_are_a_closed_set():
    """?days= is validated against this tuple; an open int would let a crawler
    ask for arbitrarily expensive windows."""
    assert _CLUSTER_WINDOWS == (3, 7, 30)


def test_the_template_extends_the_site_shell():
    """test_site_shell_continuity's rule, asserted for this page directly."""
    body = CLUSTERS_HTML.read_text()
    assert body.lstrip().startswith('{% extends "base.html" %}')
    assert "<html" not in body.lower()
    assert "<style" not in body.lower(), "page CSS belongs in style.css or an archetype"


def test_the_page_is_REACHABLE_from_the_site_nav():
    """🔴 A page nobody can navigate to is a page nobody reads.

    The design prototype's nav lists Clusters under News, and it was easy to
    assume ours did too — it did NOT (`grep -i cluster base.html` was empty).
    Shipping without this link would have repeated the /blindspot failure this
    codebase already paid for: a real page, real data, no way in.
    """
    base = (TEMPLATES / "base.html").read_text()
    assert "'/clusters'" in base or '"/clusters"' in base, (
        "/clusters is not linked from base.html's nav — the page would be orphaned"
    )


def test_every_internal_link_on_the_page_is_a_real_route():
    """🔴 A link to a route that does not exist is a 404 shipped to a reader.

    The first draft linked '/methodology' — copied from a sibling page's
    vocabulary — but this app has no such route: Methodology lives OFF-SITE at
    what-the-fact.tech/transparency. Rendering proved it 404s.

    Parsed statically from routes.py rather than via the app, so this needs no
    DB and cannot silently SKIP.
    """
    routes = set(re.findall(r'@bp\.(?:get|route)\(\s*["\']([^"\']+)', (ROOT / "consumer" / "routes.py").read_text()))
    assert len(routes) > 50, "route parse looks wrong — the guard would be vacuous"
    # literal internal hrefs only; concatenated ones ('/cluster/' ~ id) are dynamic
    hrefs = re.findall(r"""['"](/[a-z0-9\-/]*)['"]""", _rendered_source())
    def _known(h: str) -> bool:
        if h in routes or h.rstrip("/") in routes:
            return True
        # a href ending in "/" is the literal PREFIX of a concatenated dynamic
        # link ("/cluster/" ~ id) — match it against parameterised routes.
        return h.endswith("/") and any(r.startswith(h) for r in routes)

    dead = sorted({h for h in hrefs if not _known(h)})
    assert not dead, f"link(s) to non-existent route(s): {dead}"

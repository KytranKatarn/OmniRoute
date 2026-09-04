"""Integration coverage for the 3 live Parliament routes: /mps, /mp/<slug>, /senator/<slug>.

First coverage for these routes — grep of tests/ before this file found none.

⚠️ These routes hit the REAL `parliament`/`wtf` schemas. mp_profile() / mps_listing() /
senator_profile() in consumer/routes.py hardcode `FROM parliament.mps` / `FROM
parliament.senators` — unlike consumer/entities.py, there is no WTF_PARLIAMENT_SCHEMA
override for these three routes, so there is no way to point them at an isolated
wtf_test-style schema without editing production code (out of scope for this fix). These
tests therefore run read-only SELECTs and GETs against the live production database — the
same one the site itself serves from — and skip gracefully (not fail) if it is unreachable
from wherever this suite happens to run.

Regression this file pins (verified fixed 2026-09-03): mp_profile() used to look up the
party badge colour with a raw, case-sensitive `_PARTY_COLOURS.get(mp["party"], "#6b7280")`.
`parliament.mps.party` stores Title-Case values from the OpenParliament sync ("Liberal",
"Conservative", ...) while `_PARTY_COLOURS`'s keys are all-lowercase, so the lookup missed
on every single MP and the badge silently fell back to grey on every individual MP profile
page. mps_listing() (the /mps roster) was never affected — it already called the
case-insensitive `_party_colour()` fuzzy-match helper. The fix makes mp_profile() call that
same helper. test_mp_profile_renders_the_correct_party_colour_not_grey is the pin: it fails
red against the old raw-dict-lookup line (proven manually — see the coder handoff) and green
against `_party_colour()`.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

pytest.importorskip("flask")
pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _read_env_var(name: str) -> str | None:
    """The value the running app would see for `name` — env first, else the repo's own
    .env. consumer/app.py does not auto-load dotenv (the container gets it from `env_file:`
    in compose), so a bare pytest run here has to look it up the same way by hand."""
    if os.environ.get(name):
        return os.environ[name]
    env_file = ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return None


def _live_engine():
    url = _read_env_var("WTF_DATABASE_URL")
    if not url:
        return None
    try:
        eng = create_engine(url, connect_args={"connect_timeout": 5})
        with eng.begin() as c:
            c.execute(text("SELECT 1"))
        return eng
    except Exception:
        return None


_ENGINE = _live_engine()

requires_live_db = pytest.mark.skipif(
    _ENGINE is None,
    reason=(
        "parliament.mps/parliament.senators are hardcoded to the live schema in "
        "consumer/routes.py (no WTF_PARLIAMENT_SCHEMA override for /mps, /mp/<slug> or "
        "/senator/<slug>) — WTF_DATABASE_URL was unset or unreachable from this box, so "
        "these integration tests are skipped rather than failed on an infra problem."
    ),
)

# Colours mp_profile()/mps_listing() must render for these parties, per the fuzzy
# `_party_colour()` map in consumer/routes.py (`_PARTY_COLOURS`). Hardcoded here rather
# than imported so this pins the routes' RENDERED OUTPUT, not just "whatever the dict
# currently says" — a change to the dict's values would also show up as a test failure.
_EXPECTED_PARTY_COLOUR = {
    "Conservative": "#3b82f6",
    "Liberal": "#d71920",
    "NDP": "#f37021",
    "Bloc": "#89cff0",
}
_GREY_FALLBACK = "#6b7280"


@pytest.fixture(scope="module")
def real_mp():
    """One real, currently-sitting MP whose party has a colour listed above. Picked live
    so the test never hardcodes a name/slug that goes stale when someone leaves office."""
    if _ENGINE is None:
        pytest.skip("no live DB")
    with _ENGINE.begin() as c:
        for party, colour in _EXPECTED_PARTY_COLOUR.items():
            row = c.execute(
                text(
                    "SELECT slug, party, riding_name, province_code FROM parliament.mps "
                    "WHERE is_current = true AND party = :party ORDER BY slug LIMIT 1"
                ),
                {"party": party},
            ).mappings().first()
            if row:
                return dict(row), colour
    pytest.skip("no current MP found for any party this test has an expected colour for")


@pytest.fixture(scope="module")
def real_senator_with_province():
    if _ENGINE is None:
        pytest.skip("no live DB")
    with _ENGINE.begin() as c:
        row = c.execute(
            text(
                "SELECT slug, name, province FROM parliament.senators "
                "WHERE is_current = true AND province IS NOT NULL AND province <> '' "
                "ORDER BY slug LIMIT 1"
            )
        ).mappings().first()
    if not row:
        pytest.skip("no current senator with a province on file right now")
    return dict(row)


@pytest.fixture(scope="module")
def real_senator_missing_province():
    """One of the small number of current senators (recently appointed) with no province
    on file yet — pins the graceful '—' fallback rather than a crash or a fabricated
    value. Not a bug: see .claude/rules/wtf.md 'Elections section' entry — this is a
    known, disclosed data gap, not something to fix here."""
    if _ENGINE is None:
        pytest.skip("no live DB")
    with _ENGINE.begin() as c:
        row = c.execute(
            text(
                "SELECT slug, name FROM parliament.senators "
                "WHERE is_current = true AND (province IS NULL OR province = '') "
                "ORDER BY slug LIMIT 1"
            )
        ).mappings().first()
    if not row:
        pytest.skip("every current senator has a province on file right now")
    return dict(row)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    url = _read_env_var("WTF_DATABASE_URL")
    if not url:
        pytest.skip("no live DB")
    monkeypatch.setenv("WTF_DATABASE_URL", url)
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-parliament-routes")
    monkeypatch.setenv("WTF_SCHEMA", "wtf")
    # consumer/db.py defaults WTF_BILLING_DB_PATH to /app/data/..., which does not exist
    # outside the production container — established pattern from test_nav_shell.py.
    monkeypatch.setenv("WTF_BILLING_DB_PATH", str(tmp_path / "billing.db"))

    # Reset the cached engine singletons so they (re)bind to WTF_DATABASE_URL as just set
    # here, rather than whatever a different test in the same session left behind.
    import consumer.routes as routes
    routes._engine = None
    import consumer.dr_mode as dr_mode
    dr_mode._primary = None

    from consumer.app import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


# ---------------------------------------------------------------------------
# /mps roster
# ---------------------------------------------------------------------------


@requires_live_db
def test_mps_listing_returns_200(client):
    r = client.get("/mps")
    assert r.status_code == 200


@requires_live_db
def test_mps_listing_shows_a_non_grey_party_colour(client, real_mp):
    """mps_listing() was never broken (it already called the fuzzy `_party_colour()`
    helper) — this is a baseline sanity check, not the regression pin."""
    mp, expected_colour = real_mp
    r = client.get("/mps")
    body = r.data.decode("utf-8")
    # mps.html embeds the full MP list as `{{ mps | tojson }}` for the JS-rendered
    # cards — the colour is literal text in the response for a real, current MP.
    assert f'"party_colour": "{expected_colour}"' in body or (
        f'"party_colour":"{expected_colour}"' in body
    ), "expected the fuzzy-matched colour somewhere in the embedded MP JSON"


@requires_live_db
def test_mps_listing_renders_riding_and_province_for_a_real_mp(client, real_mp):
    mp, _ = real_mp
    r = client.get("/mps")
    body = r.data.decode("utf-8")
    assert mp["riding_name"] in body
    assert (f'"province_code": "{mp["province_code"]}"' in body) or (
        f'"province_code":"{mp["province_code"]}"' in body
    )


# ---------------------------------------------------------------------------
# /mp/<slug> profile — the regression pin
# ---------------------------------------------------------------------------


@requires_live_db
def test_mp_profile_returns_200(client, real_mp):
    mp, _ = real_mp
    r = client.get(f"/mp/{mp['slug']}")
    assert r.status_code == 200


@requires_live_db
def test_mp_profile_renders_the_correct_party_colour_not_grey(client, real_mp):
    """THE regression pin.

    parliament.mps.party is Title-Case for every current MP (confirmed live: 'Liberal',
    'Conservative', 'NDP', 'Bloc', 'Green' — no lowercase rows exist), so this exercises
    the exact broken path: the old `_PARTY_COLOURS.get(mp['party'], '#6b7280')` raw lookup
    missed on 100% of MPs and rendered the party-pill grey. A wrong-but-non-grey colour
    must also fail this test, so it asserts the SPECIFIC expected hex, not merely
    "not grey".
    """
    mp, expected_colour = real_mp
    r = client.get(f"/mp/{mp['slug']}")
    body = r.data.decode("utf-8")

    # mp.html: <span class="wtf-mp-party-pill" style="background:{{ mp.party_colour }}22;
    #   color:{{ mp.party_colour }};border:1px solid {{ mp.party_colour }}44;">
    correct_pill = f"color:{expected_colour};border:1px solid {expected_colour}44;"
    broken_pill = f"color:{_GREY_FALLBACK};border:1px solid {_GREY_FALLBACK}44;"

    assert correct_pill in body, (
        f"party pill for a {mp['party']} MP did not render {expected_colour} — "
        f"looking for {correct_pill!r}"
    )
    assert broken_pill not in body, (
        "party pill rendered the grey #6b7280 fallback — this is the exact bug "
        "(_PARTY_COLOURS.get(mp['party'], '#6b7280') doing a case-sensitive lookup "
        "against Title-Case party names) reappearing"
    )


@requires_live_db
def test_mp_profile_renders_riding_and_province(client, real_mp):
    mp, _ = real_mp
    r = client.get(f"/mp/{mp['slug']}")
    body = r.data.decode("utf-8")
    assert mp["riding_name"] in body
    assert mp["province_code"] in body


# ---------------------------------------------------------------------------
# /senator/<slug> profile
# ---------------------------------------------------------------------------


@requires_live_db
def test_senator_profile_returns_200_and_renders_province(client, real_senator_with_province):
    r = client.get(f"/senator/{real_senator_with_province['slug']}")
    assert r.status_code == 200
    assert real_senator_with_province["province"] in r.data.decode("utf-8")


@requires_live_db
def test_senator_profile_with_no_province_renders_the_em_dash_fallback(
    client, real_senator_missing_province
):
    """Pins the graceful fallback for the handful of current senators with no province on
    file (a disclosed, known data gap — see .claude/rules/wtf.md) rather than a crash or a
    fabricated value."""
    r = client.get(f"/senator/{real_senator_missing_province['slug']}")
    assert r.status_code == 200
    body = r.data.decode("utf-8")
    assert re.search(r'<strong class="wtf-sen-strong">\s*—\s*</strong>', body), (
        "expected the em-dash fallback for a senator with no province on file"
    )

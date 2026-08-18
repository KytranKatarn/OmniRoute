"""Guards for the translation export bundle (#5750).

Measured 2026-08-18. The nightly `translation_coverage_scan` wrote a **2-byte `{}`**
to `/mnt/standalone/websites/what-the-fact.com/data/translations.json` and reported
SUCCESS, every night. Three things stacked up:

  * the export target was a static marketing site frozen 2026-04-14, from before WTF
    became a Flask app — nothing serves that directory;
  * the DB held no rows for the keys scanned there, so the bundle resolved empty;
  * the verify step fetched the LIVE url, which serves the file baked into the
    wtf-consumer image — a DIFFERENT artifact the export never wrote. It passed on
    content the export had nothing to do with.

Unmonitored while appearing monitored: the same shape as a retention tier with a
policy and no pruner, or a staleness column nothing reads.

Blast radius of the empty-bundle refusal was measured before shipping: of the seven
configured bundles, six held 137-2601 key-language pairs and exactly ONE was empty —
the broken one. This guard cannot newly fail a healthy domain.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LANG_ROUTES = ROOT / "tools" / "consciousness" / "language_routes.py"
DOMAIN_REGISTRY = ROOT / "tools" / "consciousness" / "translation_scanners" / "domain_registry.py"


def _sources_block() -> str:
    src = LANG_ROUTES.read_text()
    return src[src.index("EXTERNAL_SCAN_SOURCES = [") : src.index("def _get_db()")]


def _entries():
    """(label, site_dir, bundle_path_or_None) parsed from the real registry."""
    out = []
    for m in re.finditer(
        r'\(\s*"([a-z_]+)",\s*"([^"]+)",\s*(?:"([^"]+)"|None)\s*,?\s*\)',
        _sources_block(),
        re.S,
    ):
        out.append((m.group(1), m.group(2), m.group(3)))
    return out


def test_registry_parses():
    entries = _entries()
    assert len(entries) >= 8, f"expected the full source registry, parsed {len(entries)}"
    assert any(e[0] == "website_what_the_fact" for e in entries)


def test_no_bundle_targets_the_dead_static_site():
    """The 2026-04-14 marketing site is not served by anything. Exporting there wrote
    `{}` nightly and reported success.

    Asserted against the PARSED bundle paths, not the raw source text: the registry
    carries an explanatory comment naming that path, and a substring scan matches its
    own documentation and fails on a correct file. The scan DIRECTORY may still point
    there (harmless — it is only read); what must never happen is a bundle WRITE.
    """
    dead_root = "/mnt/standalone/websites/what-the-fact.com"
    offenders = [(label, bundle) for label, _site_dir, bundle in _entries() if bundle and bundle.startswith(dead_root)]
    assert not offenders, (
        f"these bundles write into the dead static site: {offenders} — "
        "nothing serves that path, so a nightly success there is a lie"
    )


def test_wtf_export_is_disabled_not_repointed_at_the_live_file():
    """Deliberately bundle=None, NOT repointed at consumer/static/data/translations.json.

    The DB set and the hand-maintained file are not supersets of one another —
    measured 2026-08-18: DB 8 keys x 8 languages, file 18 keys x 3 languages — so an
    export onto the live file would silently drop 10 keys in each language the site
    actually offers. Scanned for coverage, exported by nobody.
    """
    for label, _site_dir, bundle in _entries():
        if label == "website_what_the_fact":
            assert bundle is None, "WTF must not export a bundle at all"
            return
    pytest.fail("website_what_the_fact missing from EXTERNAL_SCAN_SOURCES")


def test_empty_bundle_is_refused_before_writing():
    """The generalizable half: any domain resolving zero translations must fail loudly.

    Asserted against the source because exercising the Flask route needs an app +
    live DB; what matters is that the refusal sits BEFORE the write, so an empty
    export can never clobber an existing bundle.
    """
    src = LANG_ROUTES.read_text()
    assert "Refusing to write an EMPTY bundle" in src
    guard_at = src.index("Refusing to write an EMPTY bundle")
    write_at = src.index('with open(bundle_path, "w"', guard_at - 4000)
    assert guard_at < write_at, "the empty-bundle check must precede the file write"


def test_registry_url_is_not_the_404_path():
    """what-the-fact.com/data/translations.json returns 404 — the app serves
    /static/data/. The audit scanner reported the domain unreachable because of it."""
    text = DOMAIN_REGISTRY.read_text()
    assert (
        '"https://what-the-fact.com/data/translations.json"' not in text
    ), "that URL 404s; the served path is /static/data/translations.json"
    assert "https://what-the-fact.com/static/data/translations.json" in text


@pytest.mark.parametrize(
    "label",
    [
        "website_kytranempowerment",
        "website_creed",
        "product_civic_watch",
        "product_gov_watch",
        "product_legal_watch",
        "product_market_watch",
    ],
)
def test_healthy_domains_keep_their_bundle(label):
    """Negative half. These six each held 137-2601 key-language pairs when measured;
    none may be disabled as collateral of the WTF fix."""
    for lbl, _site_dir, bundle in _entries():
        if lbl == label:
            assert bundle, f"{label} must keep exporting a bundle"
            return
    pytest.fail(f"{label} missing from EXTERNAL_SCAN_SOURCES")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

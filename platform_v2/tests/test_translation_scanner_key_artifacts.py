"""The scanner must reject JS/HTML syntax scraped as if it were a translation key.

`dashboard.js` assembles a data-i18n attribute at RENDER time:

    var nameKey = 'module.' + mod.id + '.name';            // dashboard.js:1442
    '<div ... data-i18n="' + nameKey + '">' + translatedName // dashboard.js:1451

There is no literal key in the file, so the attribute regex captures the
CONCATENATION FRAGMENTS instead. The coverage scan then approved them, and the
Languages tab's coverage matrix counted them — they are not strings, so they
can never be translated, and they inflate the number a human trusts when
deciding whether a language is done.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# platform_v2 for `tools.consciousness...`, and the repo root for `ai_bridge`
# — language_routes imports translation_service, which reaches across.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "platform_v2"))
sys.path.insert(0, str(_REPO_ROOT))

from tools.consciousness.language_routes import _is_scanner_artifact  # noqa: E402


# ── The exact rows this defect put in the translations table ─────────────────
# Measured live 2026-10-02: 8 rows keyed `' + nameKey + '`, 8 keyed
# `' + descKey + '`, both status=approved, generated_by=coverage_scan.
CAPTURED_FRAGMENTS = [
    "' + nameKey + '",
    "' + descKey + '",
    '" + mod.name + "',
    "' + translatedName + '",
]


class TestCapturedConcatenationFragments:
    @pytest.mark.parametrize("key", CAPTURED_FRAGMENTS)
    def test_dashboard_js_fragments_are_rejected(self, key):
        assert _is_scanner_artifact(key) is True

    def test_a_real_dotted_key_survives(self):
        # module.<id>.name is what the template INTENDS. It has dots and no
        # syntax, so the guard must not touch ordinary keys.
        assert _is_scanner_artifact("module.console.name") is False


class TestOtherSyntax:
    @pytest.mark.parametrize(
        "key",
        [
            "",
            "   ",
            "getInvolved()",  # a captured call expression
            "computeTotal()",
            "<div>",
            "{{ key }}",
            "{% raw %}",
            "total: %s",
            "value: %(name)s",
            "${t('home.title')}",  # JS template literal
        ],
    )
    def test_syntax_is_rejected(self, key):
        assert _is_scanner_artifact(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "nav.vision",
            "contact.dept_general",
            "membership.tier_explorer",
            "feat.fleet",
            "manifesto.hero.title",
            "comp_feat_translation",
            "login_divider_or",
            "tc-mon-ufw",
            "submit_story.intro",
            "platform-cap-i18n",
        ],
    )
    def test_real_keys_pass_through(self, key):
        assert _is_scanner_artifact(key) is False


class TestGuardIsNotOverbroad:
    """The guard must not become a silent key-loss mechanism."""

    def test_hyphens_and_underscores_are_legal(self):
        # The existing corpus is full of these; rejecting them would drop
        # thousands of real keys and understate coverage in the other direction.
        assert _is_scanner_artifact("tc-detail-soc2") is False
        assert _is_scanner_artifact("comp_building_hero-who") is False

    def test_plus_is_only_rejected_as_syntax(self):
        # A key that legitimately contains '+' is not in this codebase's
        # vocabulary; if one ever is, this is the assertion that forces a
        # decision rather than a silent drop.
        assert _is_scanner_artifact("a+b") is True

    def test_trailing_paren_without_call_is_not_treated_as_a_call(self):
        assert _is_scanner_artifact("label)") is False

    def test_leading_bracket_is_rejected(self):
        # A capture keeps its delimiter, so '[key]' or '{key}' is a fragment.
        assert _is_scanner_artifact("[key]") is True
        assert _is_scanner_artifact("{'a': 1}") is True


class TestRealScannerIntegration:
    """Exercise the regex the way production does, not the guard in isolation."""

    def test_dashboard_fragment_survives_regex_but_not_guard(self):
        import re

        # This is language_routes.py's actual pattern.
        pattern = re.compile(r'data-i18n(?:\-\w+)?="([^"]+)"')
        markup = '<div class="featured-card-name" data-i18n="\' + nameKey + \'">x</div>'
        captured = pattern.search(markup).group(1)
        # The regex alone is fooled...
        assert captured == "' + nameKey + '"
        # ...which is exactly why the guard exists.
        assert _is_scanner_artifact(captured) is True

    def test_a_well_formed_attribute_is_captured_and_kept(self):
        import re

        pattern = re.compile(r'data-i18n(?:\-\w+)?="([^"]+)"')
        markup = '<h1 data-i18n="nav.vision">Our vision</h1>'
        captured = pattern.search(markup).group(1)
        assert captured == "nav.vision"
        assert _is_scanner_artifact(captured) is False

"""Tests for P.R.O.B.E. Translation Audit System.

Run: docker exec archie_platform python -m pytest platform_v2/tests/test_translation_audit.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

SAMPLE_HTML = """
<html><body>
  <h1 data-i18n="hero.title">Welcome</h1>
  <p data-i18n="hero.subtitle">We build things</p>
  <input data-i18n-placeholder="search.placeholder" placeholder="Search">
</body></html>
"""

TRANSLATIONS_COMPLETE = {
    "en": {"hero.title": "Welcome", "hero.subtitle": "We build", "search.placeholder": "Search"},
    "fr": {"hero.title": "Bienvenue", "hero.subtitle": "Nous construisons", "search.placeholder": "Chercher"},
}

TRANSLATIONS_WITH_GAPS = {
    "en": {"hero.title": "Welcome", "hero.subtitle": "We build", "search.placeholder": "Search"},
    "fr": {
        # hero.title missing entirely
        "hero.subtitle": "We build",  # identical to EN = untranslated
        "search.placeholder": "Mock Search",  # Mock value
    },
}


class TestI18nKeyExtraction:
    def test_extracts_data_i18n_keys(self):
        from tools.consciousness.translation_scanners.domain_audit_scanner import _extract_i18n_keys

        keys = _extract_i18n_keys(SAMPLE_HTML)
        assert "hero.title" in keys
        assert "hero.subtitle" in keys
        assert "search.placeholder" in keys

    def test_empty_html_returns_empty_set(self):
        from tools.consciousness.translation_scanners.domain_audit_scanner import _extract_i18n_keys

        assert _extract_i18n_keys("<html><body>no keys</body></html>") == set()

    def test_data_i18n_placeholder_extracted(self):
        from tools.consciousness.translation_scanners.domain_audit_scanner import _extract_i18n_keys

        html = '<input data-i18n-placeholder="search.box" placeholder="Search">'
        keys = _extract_i18n_keys(html)
        assert "search.box" in keys


class TestDomainAuditScanner:
    def _run_scan(self, html, translations, langs=None):
        from tools.consciousness.translation_scanners.domain_audit_scanner import DomainAuditScanner

        domain = {
            "name": "test_domain",
            "translations_url": "https://test.example.com/data/translations.json",
            "pages": ["https://test.example.com/"],
            "active_languages": langs or ["en", "fr"],
            "active": True,
        }
        with (
            patch(
                "tools.consciousness.translation_scanners.domain_audit_scanner._fetch_text",
                return_value=html,
            ),
            patch(
                "tools.consciousness.translation_scanners.domain_audit_scanner._fetch_translations",
                return_value=translations,
            ),
        ):
            return list(DomainAuditScanner()._scan_domain(domain))

    def test_complete_translations_no_missing_gaps(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_COMPLETE)
        missing = [r for r in results if r.gap_type == "missing"]
        assert not missing, f"Unexpected missing gaps: {missing}"

    def test_missing_key_detected(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_WITH_GAPS)
        missing = [r for r in results if r.gap_type == "missing" and r.language == "fr"]
        assert any(r.key == "hero.title" for r in missing)

    def test_mock_value_flagged_quality_suspect(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_WITH_GAPS)
        quality = [r for r in results if r.gap_type == "quality_suspect"]
        assert any("Mock" in (r.snippet or "") for r in quality)

    def test_untranslated_copy_flagged(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_WITH_GAPS)
        quality = [r for r in results if r.gap_type == "quality_suspect" and r.key == "hero.subtitle"]
        assert quality, "Expected untranslated copy flag for hero.subtitle"

    def test_source_prefixed_with_domain_name(self):
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_WITH_GAPS)
        assert all(r.source == "domain:test_domain" for r in results)

    def test_inactive_domain_skipped(self):
        from tools.consciousness.translation_scanners.domain_audit_scanner import DomainAuditScanner

        inactive_registry = [
            {
                "name": "inactive",
                "active": False,
                "translations_url": "https://x.com/t.json",
                "pages": ["https://x.com/"],
                "active_languages": ["en"],
            }
        ]
        with patch(
            "tools.consciousness.translation_scanners.domain_audit_scanner.EXTERNAL_DOMAINS",
            inactive_registry,
        ):
            results = list(DomainAuditScanner().scan())
        assert results == []

    def test_unreachable_translations_json_yields_sentinel(self):
        from tools.consciousness.translation_scanners.domain_audit_scanner import DomainAuditScanner

        domain = {
            "name": "broken",
            "translations_url": "https://broken.com/t.json",
            "pages": ["https://broken.com/"],
            "active_languages": ["en"],
            "active": True,
        }
        with (
            patch(
                "tools.consciousness.translation_scanners.domain_audit_scanner._fetch_text",
                return_value=SAMPLE_HTML,
            ),
            patch(
                "tools.consciousness.translation_scanners.domain_audit_scanner._fetch_translations",
                return_value=None,
            ),
        ):
            results = list(DomainAuditScanner()._scan_domain(domain))
        assert any(r.key == "_translations_json_unreachable" for r in results)

    def test_empty_string_flagged_quality_suspect(self):
        translations = {
            "en": {"hero.title": "Welcome"},
            "fr": {"hero.title": ""},
        }
        html = '<h1 data-i18n="hero.title">Welcome</h1>'
        results = self._run_scan(html, translations)
        quality = [r for r in results if r.gap_type == "quality_suspect" and r.key == "hero.title"]
        assert quality

    def test_en_source_not_flagged_as_untranslated(self):
        """EN values identical to themselves should not produce quality_suspect."""
        results = self._run_scan(SAMPLE_HTML, TRANSLATIONS_COMPLETE, langs=["en"])
        quality = [r for r in results if r.gap_type == "quality_suspect"]
        assert not quality


class TestDomainRegistry:
    def test_all_domains_have_required_fields(self):
        from tools.consciousness.translation_scanners.domain_registry import EXTERNAL_DOMAINS

        required = {"name", "translations_url", "pages", "active_languages", "deploy_method"}
        for domain in EXTERNAL_DOMAINS:
            missing = required - set(domain.keys())
            assert not missing, f"Domain {domain.get('name')} missing: {missing}"

    def test_all_active_domains_have_en_language(self):
        from tools.consciousness.translation_scanners.domain_registry import EXTERNAL_DOMAINS

        for domain in EXTERNAL_DOMAINS:
            if domain.get("active"):
                assert "en" in domain["active_languages"], f"Domain {domain['name']} missing 'en'"

    def test_the_required_public_domains_are_active(self):
        """The two public sites must be scanned. The COUNT is not the invariant.

        This asserted `len(active) == 2` and now sees 8: the registry legitimately grew as
        the watch products came online (gov / civic / legal / market + what-the-fact .com
        and .tech). A pinned census fails every time the platform gains a site, and the
        only available fix is to bump the number — which teaches nothing and would equally
        hide a domain going dark.

        What actually matters is that these two never silently drop out of the scan.
        """
        from tools.consciousness.translation_scanners.domain_registry import EXTERNAL_DOMAINS

        active = {d["name"] for d in EXTERNAL_DOMAINS if d.get("active")}
        for required in ("kytranempowerment_com", "creed_ai_org"):
            assert required in active, f"{required} is not active — active set is {sorted(active)}"

    def test_no_duplicate_names(self):
        from tools.consciousness.translation_scanners.domain_registry import EXTERNAL_DOMAINS

        names = [d["name"] for d in EXTERNAL_DOMAINS]
        assert len(names) == len(set(names))


class TestGapBatcher:
    def _make_gaps(self, count, lang="fr"):
        return [
            {
                "id": i,
                "source": "domain:test",
                "language": lang,
                "key": f"key.{i}",
                "gap_type": "missing",
                "snippet": None,
            }
            for i in range(count)
        ]

    def test_no_gaps_returns_zeros(self):
        from tools.consciousness.translation_scanners.gap_batcher import route_domain_gaps_to_translate

        with patch(
            "tools.consciousness.translation_scanners.gap_batcher._load_unrouted_domain_gaps",
            return_value=[],
        ):
            result = route_domain_gaps_to_translate()
        assert result == {"batches_sent": 0, "gaps_routed": 0, "errors": 0}

    def test_45_gaps_creates_3_batches(self):
        from tools.consciousness.translation_scanners.gap_batcher import route_domain_gaps_to_translate

        mock_delegate = MagicMock(return_value={"success": True, "task_id": 1})
        with (
            patch(
                "tools.consciousness.translation_scanners.gap_batcher._load_unrouted_domain_gaps",
                return_value=self._make_gaps(45),
            ),
            patch(
                "tools.consciousness.translation_scanners.gap_batcher.delegate_task",
                mock_delegate,
            ),
            patch("tools.consciousness.translation_scanners.gap_batcher._mark_routed"),
        ):
            result = route_domain_gaps_to_translate()
        assert result["batches_sent"] == 3
        assert result["gaps_routed"] == 45

    def test_dry_run_does_not_call_delegate(self):
        from tools.consciousness.translation_scanners.gap_batcher import route_domain_gaps_to_translate

        mock_delegate = MagicMock()
        with (
            patch(
                "tools.consciousness.translation_scanners.gap_batcher._load_unrouted_domain_gaps",
                return_value=self._make_gaps(5),
            ),
            patch(
                "tools.consciousness.translation_scanners.gap_batcher.delegate_task",
                mock_delegate,
            ),
        ):
            route_domain_gaps_to_translate(dry_run=True)
        mock_delegate.assert_not_called()

    def test_failed_delegate_increments_errors(self):
        from tools.consciousness.translation_scanners.gap_batcher import route_domain_gaps_to_translate

        mock_delegate = MagicMock(return_value={"success": False, "error": "agent busy"})
        with (
            patch(
                "tools.consciousness.translation_scanners.gap_batcher._load_unrouted_domain_gaps",
                return_value=self._make_gaps(5),
            ),
            patch(
                "tools.consciousness.translation_scanners.gap_batcher.delegate_task",
                mock_delegate,
            ),
        ):
            result = route_domain_gaps_to_translate()
        assert result["errors"] == 1
        assert result["gaps_routed"] == 0

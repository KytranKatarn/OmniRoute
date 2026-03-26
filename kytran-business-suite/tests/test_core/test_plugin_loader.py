"""Tests for core/plugin_loader.py"""

import json
import pytest

from core.plugin_loader import discover_manifests, validate_manifest, sort_by_dependencies


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_manifest(tmp_path, dir_name, data):
    """Write a manifest.json into tmp_path / dir_name and return the path."""
    plugin_dir = tmp_path / dir_name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "manifest.json").write_text(json.dumps(data))
    return plugin_dir


FULL_MANIFEST = {
    "slug": "crm",
    "name": "CRM",
    "version": "1.0.0",
    "category": "business",
    "tier_required": "starter",
    "dependencies": [],
}


# ---------------------------------------------------------------------------
# discover_manifests
# ---------------------------------------------------------------------------

class TestDiscoverManifests:
    def test_finds_manifest_in_subdirectory(self, tmp_path):
        make_manifest(tmp_path, "crm", FULL_MANIFEST)
        results = discover_manifests(tmp_path)
        assert len(results) == 1
        assert results[0]["slug"] == "crm"

    def test_adds_dir_key(self, tmp_path):
        make_manifest(tmp_path, "crm", FULL_MANIFEST)
        results = discover_manifests(tmp_path)
        assert "_dir" in results[0]
        assert results[0]["_dir"].endswith("crm")

    def test_finds_multiple_plugins(self, tmp_path):
        make_manifest(tmp_path, "crm", {**FULL_MANIFEST, "slug": "crm"})
        make_manifest(tmp_path, "invoicing", {**FULL_MANIFEST, "slug": "invoicing"})
        results = discover_manifests(tmp_path)
        slugs = {r["slug"] for r in results}
        assert slugs == {"crm", "invoicing"}

    def test_ignores_directories_without_manifest(self, tmp_path):
        (tmp_path / "no_manifest").mkdir()
        results = discover_manifests(tmp_path)
        assert results == []

    def test_ignores_files_at_top_level(self, tmp_path):
        (tmp_path / "README.md").write_text("hello")
        make_manifest(tmp_path, "crm", FULL_MANIFEST)
        results = discover_manifests(tmp_path)
        assert len(results) == 1

    def test_nonexistent_directory_returns_empty(self, tmp_path):
        results = discover_manifests(tmp_path / "does_not_exist")
        assert results == []

    def test_skips_invalid_json(self, tmp_path):
        bad_dir = tmp_path / "bad_plugin"
        bad_dir.mkdir()
        (bad_dir / "manifest.json").write_text("NOT JSON {{{")
        results = discover_manifests(tmp_path)
        assert results == []


# ---------------------------------------------------------------------------
# validate_manifest
# ---------------------------------------------------------------------------

class TestValidateManifest:
    def test_passes_for_complete_manifest(self):
        # Should not raise
        validate_manifest(FULL_MANIFEST)

    def test_raises_for_missing_slug(self):
        m = {k: v for k, v in FULL_MANIFEST.items() if k != "slug"}
        with pytest.raises(ValueError, match="slug"):
            validate_manifest(m)

    def test_raises_for_missing_name(self):
        m = {k: v for k, v in FULL_MANIFEST.items() if k != "name"}
        with pytest.raises(ValueError, match="name"):
            validate_manifest(m)

    def test_raises_for_missing_version(self):
        m = {k: v for k, v in FULL_MANIFEST.items() if k != "version"}
        with pytest.raises(ValueError, match="version"):
            validate_manifest(m)

    def test_raises_for_missing_category(self):
        m = {k: v for k, v in FULL_MANIFEST.items() if k != "category"}
        with pytest.raises(ValueError, match="category"):
            validate_manifest(m)

    def test_raises_for_missing_tier_required(self):
        m = {k: v for k, v in FULL_MANIFEST.items() if k != "tier_required"}
        with pytest.raises(ValueError, match="tier_required"):
            validate_manifest(m)

    def test_raises_for_missing_dependencies(self):
        m = {k: v for k, v in FULL_MANIFEST.items() if k != "dependencies"}
        with pytest.raises(ValueError, match="dependencies"):
            validate_manifest(m)

    def test_raises_for_multiple_missing_fields(self):
        with pytest.raises(ValueError):
            validate_manifest({})

    def test_error_message_mentions_slug_when_available(self):
        m = {**FULL_MANIFEST}
        del m["version"]
        with pytest.raises(ValueError, match="crm"):
            validate_manifest(m)


# ---------------------------------------------------------------------------
# sort_by_dependencies
# ---------------------------------------------------------------------------

class TestSortByDependencies:
    def _manifest(self, slug, deps=None):
        return {**FULL_MANIFEST, "slug": slug, "dependencies": deps or []}

    def test_single_plugin_no_deps(self):
        manifests = [self._manifest("crm")]
        result = sort_by_dependencies(manifests)
        assert [m["slug"] for m in result] == ["crm"]

    def test_dependency_comes_before_dependent(self):
        """invoicing depends on crm → crm must appear before invoicing."""
        manifests = [
            self._manifest("invoicing", deps=["crm"]),
            self._manifest("crm"),
        ]
        result = sort_by_dependencies(manifests)
        slugs = [m["slug"] for m in result]
        assert slugs.index("crm") < slugs.index("invoicing")

    def test_chain_of_dependencies(self):
        """c depends on b, b depends on a → order must be a, b, c."""
        manifests = [
            self._manifest("c", deps=["b"]),
            self._manifest("b", deps=["a"]),
            self._manifest("a"),
        ]
        result = sort_by_dependencies(manifests)
        slugs = [m["slug"] for m in result]
        assert slugs.index("a") < slugs.index("b") < slugs.index("c")

    def test_independent_plugins_all_included(self):
        manifests = [self._manifest("x"), self._manifest("y"), self._manifest("z")]
        result = sort_by_dependencies(manifests)
        assert {m["slug"] for m in result} == {"x", "y", "z"}

    def test_raises_on_circular_dependency(self):
        manifests = [
            self._manifest("a", deps=["b"]),
            self._manifest("b", deps=["a"]),
        ]
        with pytest.raises(ValueError, match="[Cc]ircular"):
            sort_by_dependencies(manifests)

    def test_raises_on_self_dependency(self):
        manifests = [self._manifest("a", deps=["a"])]
        with pytest.raises(ValueError, match="[Cc]ircular"):
            sort_by_dependencies(manifests)

    def test_dependency_on_external_slug_is_skipped(self):
        """Deps on unknown slugs (not in current batch) are silently ignored."""
        manifests = [self._manifest("invoicing", deps=["unknown-plugin"])]
        result = sort_by_dependencies(manifests)
        assert result[0]["slug"] == "invoicing"

    def test_empty_list(self):
        assert sort_by_dependencies([]) == []

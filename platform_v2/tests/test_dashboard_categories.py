"""Dashboard categories: every enum member must be nameable, and C.R.E.E.D. is its own.

Owner change 2026-09-11: C.R.E.E.D. Command left AI Command and C.R.E.E.D. Institute
left the old "Media Outreach" category; both now sit in one C.R.E.E.D. category
directly under What The Fact. "Media Outreach" became "The Watch Series", which is
only accurate once the Institute is out of it — the four members left are exactly the
Watch products.

⚠️ The invariant worth having is the coverage one, and it is BROADER than this change.
A category has to be listed in FIVE places, and nothing joined any of them to the enum:

  1. `ModuleCategory`                             — the enum itself
  2. `dashboard_generator.get_categories_info()`  — name / icon / priority
  3. `public_api.category_labels`                 — the public API label
  4. `generate_registry_docs._CATEGORY_TITLES`    — the capability-index heading
  5. `static/js/dashboard.js` catAccents/catNames — search-result colour + label

Each of 2-5 falls back to the raw slug, silently. Three categories were already doing
it when this was written: `what_the_fact` was missing from 3, 4 AND 5; `placeholders_future`
was keyed in 4 as the never-used `coming_soon`; and `core_services` sat in 5 as a key
matching no category at all. A category with no entry renders under a heading with no
name, no icon and no priority, sorted wherever `.get()` happens to put it — which fails
silently, and is how it reaches the dashboard.

This file is the join, in both directions, for all four downstream maps.
"""

import pytest

from dashboard_generator import get_categories_info
from module_registry import MODULES, ModuleCategory


def _modules():
    return list(MODULES.values()) if hasattr(MODULES, "values") else list(MODULES)


def _ids_in(category: ModuleCategory):
    return {m.id for m in _modules() if m.category == category}


class TestCreedIsItsOwnCategory:
    def test_the_category_exists_and_is_named_for_creed(self):
        cats = get_categories_info()
        assert "creed" in cats, "the C.R.E.E.D. category is gone"
        assert cats["creed"]["name"] == "C.R.E.E.D."

    def test_it_holds_both_creed_modules_and_nothing_else(self):
        assert _ids_in(ModuleCategory.CREED) == {"creed_command", "creed_institute"}

    def test_creed_command_is_no_longer_under_ai_command(self):
        assert "creed_command" not in _ids_in(ModuleCategory.AI_COMMAND)

    def test_it_sits_directly_under_what_the_fact(self):
        """'under the What The Fact category' was the instruction — adjacency, not
        merely 'somewhere below'. A category inserted between them breaks that."""
        cats = get_categories_info()
        assert cats["creed"]["priority"] == cats["what_the_fact"]["priority"] + 1
        between = [
            k for k, v in cats.items() if cats["what_the_fact"]["priority"] < v["priority"] < cats["creed"]["priority"]
        ]
        assert not between, f"a category slipped between What The Fact and C.R.E.E.D.: {between}"


class TestTheWatchSeries:
    def test_the_category_is_renamed(self):
        cats = get_categories_info()
        assert cats["watch_series"]["name"] == "The Watch Series"
        assert "media_outreach" not in cats, "the old slug is still registered"

    def test_the_name_is_true_of_its_members(self):
        """A rename is only honest if the contents match it. The Institute leaving is
        what makes 'The Watch Series' accurate rather than aspirational."""
        assert _ids_in(ModuleCategory.WATCH_SERIES) == {
            "kytran_gov_watch",
            "kytran_market_watch",
            "kytran_legal_watch",
            "kytran_civic_watch",
        }

    def test_the_old_enum_member_is_gone(self):
        assert not hasattr(ModuleCategory, "MEDIA_OUTREACH")


class TestEveryCategoryCanBeRendered:
    """The invariant this file exists for."""

    def test_every_enum_member_has_dashboard_metadata(self):
        cats = get_categories_info()
        missing = sorted(c.value for c in ModuleCategory if c.value not in cats)
        assert not missing, (
            f"these categories have no name/icon/priority and would render as an " f"unnamed heading: {missing}"
        )

    def test_every_metadata_entry_names_a_real_enum_member(self):
        """The other direction: a stale entry is a heading that can never hold a module."""
        known = {c.value for c in ModuleCategory}
        orphans = sorted(k for k in get_categories_info() if k not in known)
        assert not orphans, f"metadata for categories that no longer exist: {orphans}"

    def test_priorities_are_unique(self):
        """Two categories sharing a priority sort non-deterministically."""
        prios = [v["priority"] for v in get_categories_info().values()]
        assert len(prios) == len(set(prios)), f"duplicate priorities: {sorted(prios)}"

    def test_every_module_sits_in_a_renderable_category(self):
        cats = get_categories_info()
        stranded = sorted({m.id for m in _modules() if m.category.value not in cats})
        assert not stranded, f"modules in an unrenderable category: {stranded}"


class TestTheGeneratedRegistryDocLabelsEveryCategory:
    """THIRD site with the same gap. `scripts/generate_registry_docs.py` renders the
    capability index's `## <heading>` from its own `_CATEGORY_TITLES`, falling back to
    the raw slug. Before 2026-09-11 `what_the_fact` rendered as `## what_the_fact`, and
    `placeholders_future` was keyed there as the never-used `coming_soon`.

    Three independent maps of the same thing, none joined to the enum. This test is the
    join."""

    def _titles(self):
        import pathlib
        import re

        # The repo root is parents[2] on the host, but inside archie_platform the
        # tests live at /app/tests and scripts/ is bind-mounted at its host path.
        # A skip here is a test that cannot fail, so try both before giving up.
        candidates = [
            pathlib.Path(__file__).resolve().parents[2] / "scripts" / "generate_registry_docs.py",
            pathlib.Path("/mnt/archie_brain/scripts/generate_registry_docs.py"),
        ]
        gen = next((c for c in candidates if c.exists()), None)
        if gen is None:
            pytest.skip(f"generate_registry_docs.py not reachable: tried {candidates}")
        m = re.search(r"_CATEGORY_TITLES = \{(.*?)\n\}", gen.read_text(), re.S)
        assert m, "_CATEGORY_TITLES not found"
        return dict(re.findall(r'"([a-z_]+)":\s*"([^"]+)"', m.group(1)))

    def test_no_category_renders_as_its_slug(self):
        titles = self._titles()
        missing = sorted(c.value for c in ModuleCategory if c.value not in titles)
        assert not missing, f"the capability index would render a raw slug heading for: {missing}"

    def test_no_stale_key(self):
        """`coming_soon` sat here for the enum member actually named
        `placeholders_future` — a key that could never match anything."""
        known = {c.value for c in ModuleCategory}
        orphans = sorted(k for k in self._titles() if k not in known)
        assert not orphans, f"titles keyed to categories that do not exist: {orphans}"

    def test_the_doc_order_matches_the_dashboard_order(self):
        """That map's insertion order IS the doc's section order. Keeping it in step
        with the dashboard priorities is why the two read the same way."""
        by_priority = [k for k, _ in sorted(get_categories_info().items(), key=lambda kv: kv[1]["priority"])]
        assert list(self._titles()) == by_priority


class TestThePublicApiLabelsEveryCategory:
    """public_api emits the LABEL, falling back to the raw slug — so a gap here ships
    `watch_series` to consumers instead of 'The Watch Series'. `what_the_fact` was
    missing from that map and had been doing exactly that."""

    def test_no_category_falls_back_to_its_slug(self):
        import pathlib
        import re

        src = (pathlib.Path(__file__).resolve().parents[1] / "public_api.py").read_text()
        m = re.search(r"category_labels = \{(.*?)\n    \}", src, re.S)
        assert m, "category_labels map not found"
        labelled = set(re.findall(r'"([a-z_]+)":', m.group(1)))
        missing = sorted(c.value for c in ModuleCategory if c.value not in labelled)
        assert not missing, f"public API would emit the raw slug for: {missing}"


class TestTheDashboardSearchMapsCoverEveryCategory:
    """FIFTH site. `static/js/dashboard.js` keys two maps off `data-category`, which the
    template renders as `{{ module.category }}` — the ENUM VALUE. A category missing from
    `catAccents` gets no accent on its search-result icon; missing from `catNames` it has
    no label.

    Two dead keys were sitting here, found only because the enum is now joined to every
    map: `placeholder_future` (SINGULAR — the member is `placeholders_future`, so it could
    never match) and `core_services` (not a category at all). Both predate this change."""

    def _maps(self):
        import pathlib
        import re

        js = (pathlib.Path(__file__).resolve().parents[1] / "static" / "js" / "dashboard.js").read_text()
        out = {}
        for var in ("catAccents", "catNames"):
            m = re.search(r"var %s = \{(.*?)\n\s*\};" % var, js, re.S)
            assert m, f"{var} not found"
            out[var] = set(re.findall(r"(\w+):\s*'", m.group(1)))
        return out

    @pytest.mark.parametrize("var", ["catAccents", "catNames"])
    def test_every_category_is_present(self, var):
        keys = self._maps()[var]
        missing = sorted(c.value for c in ModuleCategory if c.value not in keys)
        assert not missing, f"{var} has no entry for: {missing}"

    @pytest.mark.parametrize("var", ["catAccents", "catNames"])
    def test_no_dead_keys(self, var):
        known = {c.value for c in ModuleCategory}
        dead = sorted(k for k in self._maps()[var] if k not in known)
        assert not dead, f"{var} keys that can never match a rendered data-category: {dead}"

    def test_the_two_maps_agree(self):
        """A category with a colour but no name (or vice versa) renders half-styled."""
        m = self._maps()
        assert m["catAccents"] == m["catNames"], (
            f"only in catAccents: {sorted(m['catAccents'] - m['catNames'])}; "
            f"only in catNames: {sorted(m['catNames'] - m['catAccents'])}"
        )

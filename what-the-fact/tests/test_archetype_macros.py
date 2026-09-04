"""Archetype macros — the honesty rules the design encodes (#6149 phase 2b).

These are not cosmetic assertions. Each one pins a rule from the canvas
annotations that a plausible-looking refactor would silently break:

  * `measurement(None)` must render an em dash, never 0. The ECCC feed sends
    `<gust>00</gust>` to mean NO GUST on ~94% of forecast periods, so coercing
    absence to zero fabricates a measurement on almost every row.
  * `lean_pill` must always emit its text label. The redesign's whole reason for
    changing the lean ramp was that colour alone is unreadable under common
    colour-vision deficiencies — a bare swatch reintroduces exactly that.
  * external text must be escaped: WTF renders scraped news content and the XSS
    rule for this product is absolute (.claude/rules/wtf.md).

Rendered through a real Jinja Environment, so a macro that stops emitting the
markup fails here rather than at a reader.
"""

import pathlib

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"


@pytest.fixture(scope="module")
def env():
    return Environment(
        loader=FileSystemLoader(str(TPL)),
        autoescape=select_autoescape(["html"]),
    )


def render(env, call, **ctx):
    src = '{% from "_archetypes.html" import ' + call.split("(")[0] + " %}{{ " + call + " }}"
    return env.from_string(src).render(**ctx)


class TestMeasurementAbsenceIsNotZero:
    def test_none_renders_a_dash_not_zero(self, env):
        out = render(env, 'measurement(None)')
        assert "—" in out
        assert ">0<" not in out and "0—" not in out

    def test_empty_string_renders_a_dash(self, env):
        assert "—" in render(env, 'measurement("")')

    def test_a_real_zero_is_still_shown(self, env):
        """0 is a MEASUREMENT (calm wind, zero cases) and must not be hidden."""
        out = render(env, 'measurement(0, unit="km/h")')
        assert "0km/h" in out
        assert "—" not in out

    def test_normal_value_renders(self, env):
        assert "23" in render(env, 'measurement(23, unit="°C")')

    def test_custom_absent_marker(self, env):
        assert "n/a" in render(env, 'measurement(None, absent="n/a")')


class TestLeanPillAlwaysLabelled:
    @pytest.mark.parametrize("bucket", ["left", "center-left", "center", "center-right", "right"])
    def test_every_bucket_emits_a_text_label(self, env, bucket):
        out = render(env, f'lean_pill("{bucket}")')
        stripped = out.replace("<", " <").split("<")
        text = "".join(p for p in out.split(">") if p and not p.startswith("<"))
        assert any(ch.isalpha() for ch in text), "lean colour must never appear without a label"

    @pytest.mark.parametrize("bucket,token", [
        ("left", "--wtf-left"), ("center", "--wtf-center"), ("right", "--wtf-right"),
    ])
    def test_uses_the_token_not_a_hardcoded_hex(self, env, bucket, token):
        out = render(env, f'lean_pill("{bucket}")')
        assert f"var({token})" in out
        assert "#" not in out, "a hardcoded hex stops tracking the palette"

    def test_unknown_bucket_falls_back_to_neutral_centre(self, env):
        assert "var(--wtf-center)" in render(env, 'lean_pill("nonsense")')

    def test_custom_label_is_used(self, env):
        assert "Leans left" in render(env, 'lean_pill("left", label="Leans left")')


class TestEscaping:
    def test_person_card_escapes_external_names(self, env):
        out = render(env, 'person_card(name=evil)', evil='<script>alert(1)</script>')
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_data_table_escapes_cells(self, env):
        src = ('{% from "_archetypes.html" import data_table %}'
               '{{ data_table([("H","")], [[evil]]) }}')
        out = env.from_string(src).render(evil='<img src=x onerror=alert(1)>')
        assert "<img" not in out
        assert "&lt;img" in out

    def test_chip_escapes(self, env):
        assert "<b>" not in render(env, 'chip(evil)', evil="<b>x</b>")


class TestDataTable:
    def test_empty_rows_render_the_empty_message(self, env):
        src = ('{% from "_archetypes.html" import data_table %}'
               '{{ data_table([("A",""),("B","num")], []) }}')
        out = env.from_string(src).render()
        assert "No records match these filters." in out
        assert 'colspan="2"' in out

    def test_numeric_columns_get_the_num_class(self, env):
        src = ('{% from "_archetypes.html" import data_table %}'
               '{{ data_table([("Name",""),("Total","num")], [["Acme","42"]]) }}')
        out = env.from_string(src).render()
        assert out.count("wtf-a-num") >= 2  # header + cell


class TestRankedBars:
    def test_widths_are_relative_to_the_max(self, env):
        src = ('{% from "_archetypes.html" import ranked_bars %}'
               '{{ ranked_bars([{"label":"a","value":50},{"label":"b","value":100}]) }}')
        out = env.from_string(src).render()
        assert "width: 50.0%" in out and "width: 100.0%" in out

    def test_highlight_uses_the_accent_only_for_the_named_row(self, env):
        src = ('{% from "_archetypes.html" import ranked_bars %}'
               '{{ ranked_bars([{"label":"a","value":1},{"label":"b","value":2}], highlight="a") }}')
        out = env.from_string(src).render()
        assert out.count("is-highlight") == 1

    def test_empty_rows_do_not_divide_by_zero(self, env):
        src = '{% from "_archetypes.html" import ranked_bars %}{{ ranked_bars([]) }}'
        env.from_string(src).render()  # must not raise


class TestNoHardcodedColours:
    def test_macros_file_carries_no_literal_hex_colours(self):
        """Colours belong to the tokens. A hex here silently stops tracking the
        palette — the phase-1 bug class."""
        import re
        src = (TPL / "_archetypes.html").read_text()
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        assert not re.findall(r"#[0-9a-fA-F]{6}\b", code)


class TestSourcesBiasLegendMatchesCards:
    """#6149 phase 3 — /sources rendered its OWN lean scale, and its legend did
    not describe its own cards.

    Measured on the live page before the fix:
      * BAND_COLOURS hardcoded the RETIRED ramp (left #ef4444, center-left
        #f97316, center #22c55e, center-right #0ea5e9, right #2563eb) — the scale
        phase 1 replaced because red/orange are near-identical under common
        colour-vision deficiencies and GREEN AT THE MIDPOINT reads as a quality
        judgement.
      * 2 of 5 legend swatches differed from the cards they described
        (center-right card #0ea5e9 vs legend #3b82f6; right #2563eb vs #8b5cf6),
        so a reader got the wrong colour->band mapping for 40% of the scale.

    This is the bias legend for all 46 outlets — the most load-bearing use of
    colour on the site. Both failures are now structurally impossible: one BANDS
    list feeds the cards and the legend, both through the tokens.
    """

    RETIRED = ["#ef4444", "#f97316", "#22c55e", "#0ea5e9", "#2563eb", "#3b82f6", "#8b5cf6"]

    def _src(self):
        return (TPL / "sources.html").read_text()

    def test_no_retired_lean_hexes_remain(self):
        code = "\n".join(
            l for l in self._src().splitlines()
            if "#ef4444" not in l or "RETIRED" not in l
        )
        # strip the Jinja comment block, which quotes the old values deliberately
        import re
        code = re.sub(r"\{#.*?#\}", "", code, flags=re.S)
        found = [h for h in self.RETIRED if h in code]
        assert not found, f"retired lean colours still painted on /sources: {found}"

    def test_cards_and_legend_share_one_band_list(self):
        src = self._src()
        assert "{% set BANDS =" in src, "bands must come from a single list"
        assert src.count("lean_pill(") >= 2, "cards and legend should both render via lean_pill"

    def test_every_band_maps_to_a_token(self):
        src = self._src()
        for tok in ["--wtf-left", "--wtf-center-left", "--wtf-center",
                    "--wtf-center-right", "--wtf-right"]:
            assert tok in src, f"{tok} missing — band no longer tracks the palette"


class TestPaywallLockIsNeverEmoji:
    """The paywall() macro's own comment described a "lock + title / blurb /
    CTA / see plans" four-part block, but the code only ever rendered three —
    the lock was never actually coded, so all 14+ callers baked their own 🔒
    emoji into the title string instead. House rule: a stroked SVG padlock,
    never emoji (design-handoff/wtf-archive.html LOCK_SVG is the reference)."""

    TEMPLATES_WITH_A_GATE = [
        # map.html removed 2026-09-04: no paywall gate anymore (was over-gating
        # the entire base map with no premium enhancement behind it — see the
        # design-integration audit, KB vault_note #304357).
        "source.html", "journalist.html", "senator.html", "lobbying.html",
        "activity.html", "crtc.html", "entity.html", "article.html",
        "account.html",
    ]

    def test_paywall_macro_renders_an_svg_not_an_emoji(self, env):
        html = render(env, 'paywall("Gate — Starter+", "blurb", "/x")')
        assert "<svg" in html
        assert "🔒" not in html

    @pytest.mark.parametrize("fname", TEMPLATES_WITH_A_GATE)
    def test_no_rendered_template_still_uses_the_emoji(self, fname):
        """Source-grepped, not rendered: some of these gates are hand-rolled
        (never call paywall()), so this is the only check that covers every
        instance regardless of which markup pattern the page uses. Excludes
        Jinja comment blocks, which legitimately discuss the old emoji as
        history."""
        import re
        src = (TPL / fname).read_text(encoding="utf-8")
        code = re.sub(r"\{#.*?#\}", "", src, flags=re.S)
        assert "🔒" not in code, f"{fname} still renders the emoji lock"

"""Variant styles: AI agents get android wording, the KE frame toggle replaces the duplicate KE Corporate preset."""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.media_studio.services import portrait_service as ps  # noqa: E402

HTML = ROOT / "tools" / "media_studio" / "templates" / "tools" / "media_studio" / "media_studio.html"


def test_ai_agents_get_android_wording_for_every_style():
    for key in ("ai", "action", "professional", "casual", "lcars"):
        text = ps.compose_variant_prompt(preset=key, agent_kind="ai")
        assert "android" in text or "LCARS" in text, key
        assert "natural human skin" not in text, key


def test_humans_keep_the_original_wording():
    assert (
        ps.compose_variant_prompt(preset="professional", agent_kind="human")
        == ps.VARIANT_PRESET_PROMPTS["professional"]
    )
    assert "natural human skin" in ps.compose_variant_prompt(preset="ai", agent_kind="human")


def test_default_kind_is_human_for_backwards_compatibility():
    assert ps.compose_variant_prompt(preset="casual") == ps.VARIANT_PRESET_PROMPTS["casual"]


def test_ke_frame_toggle_adds_background_once_for_any_style():
    for preset in ("ai", "casual", "lcars"):
        text = ps.compose_variant_prompt(preset=preset, ke_background=True, agent_kind="ai")
        assert text.count(ps.KE_CORPORATE_BACKGROUND) == 1


def test_legacy_ke_corporate_preset_equals_the_toggle():
    """A stored/old client still posting preset=ke_corporate must not double-apply the background."""
    legacy = ps.compose_variant_prompt(preset="ke_corporate", ke_background=True)
    assert legacy.count(ps.KE_CORPORATE_BACKGROUND) == 1


def test_ui_no_longer_lists_ke_corporate_and_labels_the_toggle_as_a_frame():
    html = HTML.read_text()
    assert 'value="ke_corporate"' not in html
    assert "KE frame" in html and "ms-variant-preview" in html

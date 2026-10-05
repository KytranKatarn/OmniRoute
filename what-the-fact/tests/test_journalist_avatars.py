"""Journalist avatars: initials always, the photo laid over them when there is one.

No journalist has a photo yet (their metadata holds only `outlets`), so every card needs a real
fallback, and a future `metadata.image_url` must be safe to render: it comes from a database field,
so only https:// and /media/ sources are accepted, and a broken image must reveal the initials
instead of a broken-image icon. Rendered through a real Jinja Environment.
"""
import pathlib
import re

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = pathlib.Path(__file__).resolve().parents[1] / "consumer"
TPL = ROOT / "templates"


@pytest.fixture(scope="module")
def env():
    return Environment(loader=FileSystemLoader(str(TPL)), autoescape=select_autoescape(["html"]))


def avatar(env, name, url=None):
    return env.from_string('{% from "_archetypes.html" import avatar %}{{ avatar(name, url) }}').render(name=name, url=url)


def initials(html):
    return re.search(r'wtf-a-ph-init"[^>]*>([^<]*)<', html).group(1)


class TestInitials:
    @pytest.mark.parametrize("name,expect", [
        ("Jane Smith", "JS"), ("Jean-Luc Picard", "JP"), ("Cher", "CH"),
        ("élise tremblay", "ÉT"), ("Mary Ann O'Brien", "MO"),
    ])
    def test_initials(self, env, name, expect):
        assert initials(avatar(env, name)) == expect

    def test_empty_name_does_not_crash(self, env):
        assert initials(avatar(env, "")) == "?"
        assert initials(avatar(env, None)) == "?"

    def test_initials_are_hidden_from_screen_readers(self, env):
        assert 'aria-hidden="true"' in avatar(env, "Jane Smith")


class TestPhoto:
    def test_no_photo_means_no_img(self, env):
        assert "<img" not in avatar(env, "Jane Smith")

    def test_https_photo_is_rendered_over_the_initials(self, env):
        out = avatar(env, "Jane Smith", "https://example.org/jane.jpg")
        assert 'src="https://example.org/jane.jpg"' in out
        assert initials(out) == "JS"                      # still there underneath
        assert out.index("<img") < out.index("wtf-a-ph-init")

    def test_local_media_photo_is_rendered(self, env):
        assert 'src="/media/journalists/jane.jpg"' in avatar(env, "Jane Smith", "/media/journalists/jane.jpg")

    @pytest.mark.parametrize("bad", [
        "javascript:alert(1)", "http://example.org/x.jpg", "data:image/png;base64,AAAA",
        "//evil.example/x.jpg", "ftp://x/y.jpg", "JAVASCRIPT:alert(1)", "/etc/passwd",
    ])
    def test_unsafe_or_unsupported_sources_are_refused(self, env, bad):
        out = avatar(env, "Jane Smith", bad)
        assert "<img" not in out and bad not in out
        assert initials(out) == "JS"

    def test_a_broken_image_is_removed_to_reveal_the_initials(self, env):
        assert 'onerror="this.remove()"' in avatar(env, "Jane Smith", "https://example.org/a.jpg")

    def test_the_alt_is_empty_so_the_name_is_not_read_twice(self, env):
        assert 'alt=""' in avatar(env, "Jane Smith", "https://example.org/a.jpg")

    def test_a_hostile_name_is_escaped(self, env):
        out = avatar(env, "<script>alert(1)</script> Bob")
        assert "<script>" not in out


class TestWiring:
    def test_person_card_still_escapes_and_shows_initials(self, env):
        src = '{% from "_archetypes.html" import person_card %}{{ person_card(name=n, photo_url=u) }}'
        out = env.from_string(src).render(n="Jane Smith", u="https://example.org/j.jpg")
        assert 'class="wtf-a-pcard"' in out and 'src="https://example.org/j.jpg"' in out

    def test_the_directory_passes_each_journalists_image(self):
        t = (TPL / "journalists.html").read_text()
        assert "photo_url=j.image_url" in t

    def test_the_listing_query_carries_image_url(self):
        r = (ROOT / "routes.py").read_text()
        i = r.index("def journalists_listing")
        body = r[i:i + 4500]
        assert "metadata->>'image_url' AS image_url" in body and "c.image_url" in body

    def test_the_profile_renders_the_avatar(self):
        t = (TPL / "journalist.html").read_text()
        assert "avatar(j.canonical_name" in t and ", avatar %}" in t

    def test_css_defines_the_avatar_classes_with_tokens_only(self):
        css = (ROOT / "static" / "style.css").read_text()
        block = css[css.index(".wtf-a-ph-avatar"):css.index(".wtf-a-ph-img")+120]
        assert "wtf-a-ph-init" in block and "#" not in re.sub(r"/\*.*?\*/", "", block, flags=re.S)

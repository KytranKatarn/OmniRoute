"""/news must not request favicons that do not exist (task #6604, found by the design-port rig).

Nine of 46 sources have no icon file (their publishers refuse our self-identifying fetcher, scripts/fetch_source_favicons.py). The template used to
request every <slug>.png and let `onerror` show the badge, costing one guaranteed 404 per icon-less source per page view.
"""
import re
from pathlib import Path

from consumer.favicons import FAVICON_DIR, favicon_slugs, has_favicon

C = Path(__file__).resolve().parents[1] / "consumer"
NEWS = (C / "templates" / "news.html").read_text(encoding="utf-8")


def test_has_favicon_reflects_the_real_directory():
    on_disk = {p.stem for p in Path(FAVICON_DIR).glob("*.png")}
    assert on_disk, "the committed favicons are missing"
    for slug in list(on_disk)[:5]:
        assert has_favicon(slug)
    for slug in ("national_post", "cbc_english", "financial_post"):  # known icon-less sources
        assert slug not in on_disk and not has_favicon(slug)


def test_empty_or_missing_slug_is_never_a_favicon():
    for bad in ("", None, "../etc/passwd", "ctv_news/../x"):
        assert not has_favicon(bad)


def test_an_unreadable_directory_means_badges_not_an_error(tmp_path):
    missing = str(tmp_path / "nope")
    assert favicon_slugs(missing) == frozenset()
    assert not has_favicon("ctv_news", missing)


def test_only_png_files_count(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "b.txt").write_bytes(b"x")
    (tmp_path / "c.png.bak").write_bytes(b"x")
    assert favicon_slugs(str(tmp_path)) == frozenset({"a"})


def test_the_template_requests_the_icon_only_behind_has_favicon():
    markup = re.sub(r"\{#.*?#\}", "", NEWS, flags=re.S)
    img = markup.index('<img src="/static/favicons/{{ s.slug }}.png"')
    guard = markup.rfind("{% if has_favicon(s.slug) %}", 0, img)
    end = markup.index("{% endif %}", img)
    assert guard != -1 and guard < img < end, "the <img> must sit inside {% if has_favicon(s.slug) %}"


def test_an_icon_less_source_shows_its_badge_without_waiting_for_onerror():
    markup = re.sub(r"\{#.*?#\}", "", NEWS, flags=re.S)
    span = re.search(r'<span class="wtf-nw-src-fallback"[^>]*>', markup).group(0)
    assert "{% if not has_favicon(s.slug) %}" in span and "display:flex" in span


def test_the_route_registers_the_template_global():
    src = (C / "routes.py").read_text(encoding="utf-8")
    assert 'bp.add_app_template_global(_has_favicon, "has_favicon")' in src


def test_rendered_block_has_an_img_only_for_sources_with_an_icon():
    """Render the real icon block from news.html (not a regex over it): CTV has a file, National Post does not."""
    import jinja2

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(C / "templates")), autoescape=True)
    env.globals["has_favicon"] = has_favicon
    start = NEWS.index('<div class="wtf-news-favicon"')
    frag = env.from_string(NEWS[start : NEWS.index('<div class="wtf-nw-src-name">', start)])
    with_icon = frag.render(s={"slug": "ctv_news", "name": "CTV News"}, col="#0af")
    without = frag.render(s={"slug": "national_post", "name": "National Post"}, col="#0af")
    assert '<img src="/static/favicons/ctv_news.png"' in with_icon and "CT" in with_icon
    assert "<img" not in without and "favicons/national_post" not in without
    assert "display:flex" in without and "NA" in without

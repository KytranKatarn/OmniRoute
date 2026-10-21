"""Gallery: bare thumbnail paths must be browser-ready, and a late response must not overwrite a newer click.

Run with --noconftest.
"""

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.media_studio.services.gallery_service import _serialize_row, normalize_static_path  # noqa: E402

JS = ROOT / "tools" / "media_studio" / "static" / "js" / "ms-gallery.js"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("media/agents/2/2026-10-21/thumb_media_1.png", "/static/media/agents/2/2026-10-21/thumb_media_1.png"),
        ("static/media/images/x.png", "/static/media/images/x.png"),
        ("/static/media/images/x.png", "/static/media/images/x.png"),
        ("https://cdn.example/x.png", "https://cdn.example/x.png"),
        ("data:image/png;base64,AAAA", "data:image/png;base64,AAAA"),
        ("", ""),
        (None, None),
    ],
)
def test_normalize_static_path(raw, expected):
    assert normalize_static_path(raw) == expected


def test_serialize_row_fixes_the_bare_thumbnail_the_writer_produces():
    row = {
        "id": 7,
        "file_path": "/static/media/agents/2/2026-10-21/media_7.png",
        "thumbnail_path": "media/agents/2/2026-10-21/thumb_media_7.png",
        "metadata": {},
    }
    out = _serialize_row(row)
    assert out["thumbnail_path"] == "/static/media/agents/2/2026-10-21/thumb_media_7.png"
    assert out["url"] == out["file_path"] == "/static/media/agents/2/2026-10-21/media_7.png"


def test_serialize_row_keeps_null_thumbnail_null():
    assert (
        _serialize_row({"id": 1, "file_path": "/static/a.png", "thumbnail_path": None, "metadata": {}})[
            "thumbnail_path"
        ]
        is None
    )


def test_gallery_js_parses():
    subprocess.run(["node", "--check", str(JS)], check=True)


def test_gallery_js_drops_stale_responses_and_normalizes_image_paths():
    src = JS.read_text(encoding="utf-8")
    assert src.count("seq !== _loadSeq") == 3  # header callback, grid response, error path
    assert "var seq = ++_loadSeq;" in src
    assert "img.src = _src(item.thumbnail_path || item.url);" in src  # grid tiles
    assert "img.onerror" in src and "dataset.fallback" in src  # missing thumbnail falls back to the full image
    assert (
        "_withSubjects" in src and src.count("/api/agents/gallery-subjects") == 3
    )  # init, cache fill, poll (not per click)


def test_gallery_js_does_not_refetch_subjects_on_every_click():
    src = JS.read_text(encoding="utf-8")
    body = src[src.index("loadAssets: function") : src.index("_renderSubjectHeader: function")]
    assert "gallery-subjects" not in body  # the header uses the cached list


# ── Publish Portraits lives in the Portraits tab, not the Gallery ────────────────────────────────────
TPL = ROOT / "tools" / "media_studio" / "templates" / "tools" / "media_studio"


def test_publish_button_is_in_the_portraits_toolbar_not_the_gallery():
    gallery = (TPL / "_tab_gallery.html").read_text(encoding="utf-8")
    main = (TPL / "media_studio.html").read_text(encoding="utf-8")
    assert "msPublishSitesBtn" not in gallery and "msPublishSitesStatus" not in gallery
    assert main.count('id="msPublishSitesBtn"') == 1 and main.count('id="msPublishSitesStatus"') == 1
    start = main.index('id="ms-portrait-toolbar"')
    toolbar = main[start : main.index('id="ms-portrait-grid"', start)]
    assert (
        "msPublishSitesBtn" in toolbar and "msPublishSitesStatus" in toolbar
    )  # hides with the toolbar in the detail view


def test_portraits_tab_loads_the_publish_status_and_gallery_init_does_not():
    main = (TPL / "media_studio.html").read_text(encoding="utf-8")
    branch = main[main.index('else if (tabId === "portraits")') :][:220]
    assert "loadPortraits();" in branch and "msGallery.loadPublishStatus()" in branch
    init = JS.read_text(encoding="utf-8")
    body = init[init.index("init: function") : init.index("_withSubjects: function")]
    assert "loadPublishStatus" not in body


def test_publish_has_one_button_per_site_and_wtf_is_disabled_until_it_has_a_deploy_path():
    main = (TPL / "media_studio.html").read_text(encoding="utf-8")
    start = main.index('id="ms-portrait-toolbar"')
    toolbar = main[start : main.index('id="ms-portrait-grid"', start)]
    for domain in ("kytranempowerment.com", "creed-ai.org"):
        sid = domain.replace(".", "-")
        assert f"msGallery.publishPortraits('{domain}')" in toolbar
        assert f'id="msPublishStatus-{sid}"' in toolbar
    wtf = toolbar[toolbar.index('data-domain="what-the-fact.com"') :][:400]
    assert "disabled" in wtf and "publishPortraits" not in wtf  # a dead path must not be clickable
    assert "msGallery.publishPortraits()" in toolbar  # PUBLISH ALL keeps the old no-arg behaviour


def test_publish_sends_the_domain_only_when_one_is_given_and_status_is_filled_per_site():
    js = JS.read_text(encoding="utf-8")
    body = js[js.index("publishPortraits: function (domain)") : js.index("loadPublishStatus: function")]
    assert "JSON.stringify(domain ? { domain: domain } : {})" in body
    status = js[js.index("loadPublishStatus: function") :]
    assert "'msPublishStatus-' + String(s.domain)" in status

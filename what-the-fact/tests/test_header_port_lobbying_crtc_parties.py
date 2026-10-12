"""Shared centred page header on /lobbying, /crtc and /parties (PORT-STATUS rows 15, 30, 20).

Same pattern as test_explorer_headers_port.py. Template comments are stripped: assert markup only.
These pages used their own left-aligned headers (monospace 20px titles, emoji, a lede beside
nothing); the design's is a centred eyebrow + serif title + lede.
"""
import re
from pathlib import Path

C = Path(__file__).resolve().parents[1] / "consumer"


def markup(name):
    raw = (C / "templates" / name).read_text(encoding="utf-8")
    return re.sub(r"\{#.*?#\}", "", raw, flags=re.S)


def test_each_page_uses_the_shared_header_exactly_once():
    for name in ("lobbying.html", "crtc.html", "parties.html"):
        m = markup(name)
        assert m.count('<header class="wtf-pg-head">') == 1, name
        assert 'class="wtf-pg-eyebrow"' in m and 'class="wtf-pg-lede"' in m, name
        assert m.count('<h1') == (2 if name == "lobbying.html" else 1), name  # lobbying: detail + index
        assert 'class="wtf-pg-title"' in m, name


def test_titles_are_the_real_titles_and_carry_no_emoji():
    assert '<h1 class="wtf-pg-title">Lobbying tracker</h1>' in markup("lobbying.html")
    assert '<h1 class="wtf-pg-title">CRTC Decisions</h1>' in markup("crtc.html")
    assert '<h1 class="wtf-pg-title">Political parties</h1>' in markup("parties.html")
    for name in ("lobbying.html", "crtc.html", "parties.html"):
        for h1 in re.findall(r"<h1[^>]*>(.*?)</h1>", markup(name), re.S):
            assert not re.search("[\U0001F300-\U0001FAFF☀-➿]", h1), (name, h1)


def test_the_old_page_specific_headers_are_gone():
    lob, crtc, par = markup("lobbying.html"), markup("crtc.html"), markup("parties.html")
    # whole-token match: "wtf-crtc-sub" is a prefix of the still-valid "wtf-crtc-subject"
    for dead in ("wtf-lob-header", "wtf-lob-title", "wtf-lob-eyebrow"):
        assert not re.search(r"(?<![\w-])" + dead + r"(?![\w-])", lob), dead
    for dead in ("wtf-crtc-header", "wtf-crtc-title", "wtf-crtc-sub"):
        assert not re.search(r"(?<![\w-])" + dead + r"(?![\w-])", crtc), dead
    assert ".wtf-pt h1" not in par and "wtf-pt-lede" not in par


def test_lobbying_detail_keeps_its_back_link_and_real_counts():
    m = markup("lobbying.html")
    assert 'href="/lobbying">← All lobbying</a>' in m
    assert "{{ detail.org_label }}</h1>" in m and "registered communications with" in m


def test_parties_empty_state_still_has_its_message_in_the_header():
    m = markup("parties.html")
    assert "No election results have been ingested yet." in m
    # and the provenance paragraph ("Two elections, not a trend") is still there
    assert "Two elections, not a trend." in m

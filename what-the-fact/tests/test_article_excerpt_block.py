"""Article excerpt block: reader sees a SHORT cleaned excerpt or a link-out — never the
raw stored body. Renders only the marked block of article.html (the whole template
needs ~40 context vars). Plain Python: `python3 tests/test_article_excerpt_block.py`."""
import os, pathlib, re, sys
from jinja2 import DictLoader, Environment

HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
SRC = (HERE / "consumer" / "templates" / "article.html").read_text()
BLOCK = re.search(r"\{# excerpt-block-start #\}(.*?)\{# excerpt-block-end #\}", SRC, re.S).group(1)
ENV = Environment(autoescape=True, loader=DictLoader({"b": BLOCK}))
A = {"source_name": "CBC", "url": "https://example.com/a", "body": "RAW-STORED-BODY-SENTINEL " * 20}


def render(**kw):
    ctx = dict(a=A, is_limited_body=False, is_paywalled=False, excerpt="", excerpt_truncated=False)
    ctx.update(kw)
    return ENV.get_template("b").render(**ctx)


def test_raw_body_is_never_rendered():
    for kw in (dict(), dict(excerpt="Clean text."), dict(is_limited_body=True)):
        assert "RAW-STORED-BODY-SENTINEL" not in render(**kw)
    assert "a.body|" not in BLOCK and "truncate(2500" not in BLOCK


def test_excerpt_is_labelled_attributed_and_linked():
    h = render(excerpt="The mayor spoke.", excerpt_truncated=True)
    assert "Excerpt from CBC" in h and "does not republish it" in h
    assert 'href="https://example.com/a"' in h and "The mayor spoke.…" in h


def test_ellipsis_only_when_something_was_cut():
    assert "The mayor spoke.…" not in render(excerpt="The mayor spoke.", excerpt_truncated=False)


def test_contaminated_capture_gets_link_out_only():
    h = render(excerpt="")
    assert 'id="art-linkout"' in h and 'id="art-excerpt"' not in h
    assert "could not isolate" in h and "Read full article at CBC" in h


def test_limited_body_branch_unchanged():
    h = render(is_limited_body=True, is_paywalled=True)
    assert "behind a paywall at CBC" in h and "art-excerpt" not in h


def test_excerpt_is_escaped():
    assert "<script>" not in render(excerpt="<script>alert(1)</script>")


def test_route_wires_clean_body_with_short_cap():
    r = (HERE / "consumer" / "routes.py").read_text()
    assert "clean_body(a.get(\"body\"), max_chars=_ARTICLE_EXCERPT_CHARS)" in r
    assert re.search(r"_ARTICLE_EXCERPT_CHARS = 600\b", r)
    assert "excerpt=excerpt, excerpt_truncated=excerpt_truncated" in r


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)

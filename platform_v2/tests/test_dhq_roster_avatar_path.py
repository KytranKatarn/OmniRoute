"""Roster avatars: a bare ``media/...`` avatar_url must be served from /static (it used to 200 with an HTML page)."""

import json
import pathlib
import shutil
import subprocess

import pytest

JS = pathlib.Path(__file__).resolve().parents[1] / "tools/department_hq/static/js/department-hq.js"


def _run(expr: str):
    src = JS.read_text(encoding="utf-8")
    start = src.index("function staticUrl(")
    block = src[start : src.index("async function api(", start)]
    out = subprocess.run(
        ["node", "-e", block + f"\nconsole.log(JSON.stringify({expr}))"], capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def test_bare_media_path_gets_the_static_prefix():
    assert _run("bust('media/agents/8/x/thumb.png', null)") == "/static/media/agents/8/x/thumb.png"


def test_bust_keeps_the_cache_buster_after_normalising():
    assert _run("bust('media/agents/8/t.png', 5)") == "/static/media/agents/8/t.png?v=5"


@pytest.mark.parametrize(
    "path",
    ["/static/media/portraits/a.png", "https://cdn.example.com/a.png", "data:image/png;base64,AA", "/elsewhere/a.png"],
)
def test_absolute_and_static_paths_pass_through(path):
    assert _run(f"staticUrl({json.dumps(path)})") == path


def test_static_prefixed_without_slash_gets_only_the_slash():
    assert _run("staticUrl('static/media/a.png')") == "/static/media/a.png"


def test_empty_is_left_alone():
    assert _run("bust('', 5)") == ""

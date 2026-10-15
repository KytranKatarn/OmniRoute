"""wtf-raster.js (WX-S0, ADR #1134): runs the node behavioural tests for the lon/lat -> map-projection resampler."""

import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_raster_harness_passes():
    r = subprocess.run(["node", str(ROOT / "tests" / "test_wtf_raster.js")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_helper_is_pure_no_dom_no_network():
    src = (ROOT / "consumer" / "static" / "js" / "wtf-raster.js").read_text()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith(("*", "/*", "//")))
    for banned in ("document.", "fetch(", "XMLHttpRequest", "innerHTML", "d3."):
        assert banned not in code, banned

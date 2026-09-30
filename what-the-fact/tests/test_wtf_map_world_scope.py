"""Guards for the world scope of the shared map (design PORT-STATUS row 3).

Three things could regress without any page failing to load:

  1. THE DATA. The world file is keyed by ISO alpha-2 `properties.code`; a
     re-export that renames the key would draw every country as "no data"
     while the map still looked fine.
  2. THE DEFAULT. Canada must stay the default scope, so /map and /weather are
     byte-for-byte unchanged by this component change.
  3. THE PROJECTION. Natural Earth fitted to the sphere, run against the
     ACTUAL vendored d3-geo bundle (same reasoning as test_wtf_map.py).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "consumer/static/js/wtf-map.js"
VENDOR = ROOT / "consumer/static/vendor"
WORLD = ROOT / "consumer/static/world-countries.geojson"


@pytest.fixture(scope="module")
def world():
    return json.loads(WORLD.read_text(encoding="utf-8"))


def test_world_file_is_a_feature_collection(world):
    assert world["type"] == "FeatureCollection"
    assert len(world["features"]) >= 170


def test_every_feature_has_a_name_and_the_code_key(world):
    for f in world["features"]:
        assert set(f["properties"]) == {"code", "name"}
        assert f["properties"]["name"]


def test_coded_features_are_unique_alpha2(world):
    codes = [f["properties"]["code"] for f in world["features"] if f["properties"]["code"]]
    assert codes, "no coded features — every country would draw as no-data"
    assert all(re.fullmatch(r"[A-Z]{2}", c) for c in codes)
    assert len(codes) == len(set(codes)), "duplicate country code"


def test_known_countries_are_present_with_the_right_code(world):
    by = {f["properties"]["code"]: f["properties"]["name"]
          for f in world["features"] if f["properties"]["code"]}
    assert by["CA"] == "Canada"
    # France and Norway are the two Natural Earth famously ships with a
    # -99 ISO code; a naive export drops them silently.
    assert by["FR"] == "France"
    assert by["NO"] == "Norway"


def test_uncoded_features_are_few_and_not_guessed(world):
    uncoded = [f["properties"]["name"] for f in world["features"] if not f["properties"]["code"]]
    assert len(uncoded) <= 3, uncoded


def test_canada_is_still_the_default_scope():
    src = JS.read_text(encoding="utf-8")
    assert re.search(r'opts\.scope === "world" \? "world" : "canada"', src)


def test_public_api_exposes_scope_control():
    src = JS.read_text(encoding="utf-8")
    assert "setScope: setScope" in src
    assert "getScope:" in src


def test_world_geometry_is_local_not_third_party():
    src = JS.read_text(encoding="utf-8")
    assert '"/static/world-countries.geojson"' in src
    assert not re.search(r"https?://", re.sub(r"/\*.*?\*/", "", src, flags=re.S).replace("//", "\n//"))


def test_world_projection_is_fitted_to_the_sphere():
    src = JS.read_text(encoding="utf-8")
    assert "geoNaturalEarth1" in src and '{ type: "Sphere" }' in src


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_natural_earth_places_every_coded_country_inside_the_canvas(world):
    """Real arithmetic: fit the vendored bundle to the sphere and check the
    world's bounds land on the canvas, and Canada lands north of Brazil."""
    script = textwrap.dedent(
        """
        const fs = require('fs'), vm = require('vm');
        const ctx = { window: {}, self: {}, console };
        ctx.window = ctx; vm.createContext(ctx);
        for (const f of ['internmap','d3-array','d3-geo'])
          vm.runInContext(fs.readFileSync(process.argv[1] + '/' + f + '.min.js','utf8'), ctx);
        const d3 = ctx.d3;
        const world = JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
        const W = 800, H = 480, pad = 12;
        const proj = d3.geoNaturalEarth1().fitExtent([[pad,pad],[W-pad,H-pad]], {type:'Sphere'});
        const path = d3.geoPath(proj);
        let off = 0, drawn = 0, ca, br;
        for (const f of world.features) {
          const b = path.bounds(f);
          if (!isFinite(b[0][0]) || b[0][0] < -1 || b[1][0] > W+1 || b[0][1] < -1 || b[1][1] > H+1) off++;
          else drawn++;
          if (f.properties.code === 'CA') ca = path.centroid(f);
          if (f.properties.code === 'BR') br = path.centroid(f);
        }
        console.log(JSON.stringify({off, drawn, caNorthOfBr: ca[1] < br[1]}));
        """
    )
    out = subprocess.run(
        ["node", "-e", script, str(VENDOR), str(WORLD)],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, out.stderr
    res = json.loads(out.stdout.strip().splitlines()[-1])
    assert res["off"] == 0, res
    assert res["caNorthOfBr"] is True

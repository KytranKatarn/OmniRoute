/* Behavioural tests for consumer/static/js/wtf-raster.js (WX-S0). Run: node tests/test_wtf_raster.js */
"use strict";
const path = require("path");
const { reproject } = require(path.join(__dirname, "..", "consumer", "static", "js", "wtf-raster.js"));
let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log("  FAIL:", m); } };

// a 4x2 source: left half red, right half blue, opaque. bbox = lon -10..10, lat 0..10.
const SW = 4, SH = 2, BB = [-10, 0, 10, 10];
function mk(pixels) { const a = new Uint8ClampedArray(SW * SH * 4); pixels.forEach((p, i) => a.set(p, i * 4)); return a; }
const R = [255, 0, 0, 255], B = [0, 0, 255, 255], T = [0, 0, 0, 0];
const SRC = mk([R, R, B, B, R, R, B, B]);
// identity projection: dst 8x4 covers exactly the bbox
const ident = (W, H) => (x, y) => [BB[0] + x / W * 20, BB[3] - y / H * 10];
const px = (a, W, x, y) => Array.from(a.slice((y * W + x) * 4, (y * W + x) * 4 + 4));

console.log("wtf-raster");
// 1. identity mapping reproduces the picture (nearest): left red, right blue
let o = reproject(SRC, SW, SH, BB, 8, 4, ident(8, 4), { nearest: true });
ok(px(o, 8, 0, 0)[0] === 255 && px(o, 8, 7, 3)[2] === 255, "identity nearest keeps red left / blue right");
// 2. north is up: a source whose top row is red and bottom row blue stays that way
const SRC2 = mk([R, R, R, R, B, B, B, B]);
o = reproject(SRC2, SW, SH, BB, 8, 4, ident(8, 4), { nearest: true });
ok(px(o, 8, 3, 0)[0] === 255 && px(o, 8, 3, 3)[2] === 255, "row 0 is the north edge");
// 3. a point outside the bbox, or an invert that returns null/NaN, is transparent, never a clamped edge colour
o = reproject(SRC, SW, SH, BB, 8, 4, (x, y) => [100, 5], { nearest: true });
ok(px(o, 8, 0, 0)[3] === 0, "outside the bbox is transparent");
o = reproject(SRC, SW, SH, BB, 8, 4, () => null, { nearest: true });
ok(px(o, 8, 0, 0)[3] === 0, "null from invert is transparent");
o = reproject(SRC, SW, SH, BB, 8, 4, () => [NaN, 5], { nearest: true });
ok(px(o, 8, 0, 0)[3] === 0, "NaN from invert is transparent");
// 4. a shifted projection shifts the picture: dst x offset by +10 lon moves the red half out of view
o = reproject(SRC, SW, SH, BB, 8, 4, (x, y) => [BB[0] + 10 + x / 8 * 20, BB[3] - y / 4 * 10], { nearest: true });
ok(px(o, 8, 0, 0)[2] === 255 && px(o, 8, 7, 0)[3] === 0, "shifted lon moves the image and leaves a transparent margin");
// 5. bilinear: between a red and a blue pixel the colour blends; a transparent neighbour does not darken it
const SRC3 = mk([R, B, T, T, R, B, T, T]);
o = reproject(SRC3, SW, SH, BB, 8, 4, ident(8, 4));
const mid = px(o, 8, 2, 1);
ok(mid[0] > 0 && mid[2] > 0 && mid[3] === 255, "bilinear blends red and blue at a boundary");
const edge = px(o, 8, 4, 1);
ok(edge[3] > 0 && edge[3] < 255 && edge[0] === 0 && edge[2] === 255, "a transparent neighbour lowers alpha but never darkens the colour (premultiplied)");
// 6. fully transparent source stays transparent
o = reproject(mk([T, T, T, T, T, T, T, T]), SW, SH, BB, 8, 4, ident(8, 4));
ok(px(o, 8, 3, 2)[3] === 0, "transparent in, transparent out");
// 7. a degenerate bbox or short buffer returns an all-transparent result and does not throw
o = reproject(SRC, SW, SH, [0, 0, 0, 0], 4, 4, ident(4, 4));
ok(o.length === 64 && px(o, 4, 1, 1)[3] === 0, "degenerate bbox is transparent");
o = reproject(new Uint8ClampedArray(4), SW, SH, BB, 4, 4, ident(4, 4));
ok(o.length === 64 && px(o, 4, 1, 1)[3] === 0, "a short source buffer does not read out of bounds");
// 8. a non-linear (conic-like) projection still lands each pixel on the right source cell: check by round trip
const conic = (x, y) => { const lon = -10 + (x / 40) * 20 + Math.sin(y / 20) * 2, lat = 10 - (y / 20) * 10; return [lon, lat]; };
o = reproject(SRC, SW, SH, BB, 40, 20, conic, { nearest: true });
let bad = 0; for (let y = 0; y < 20; y++) for (let x = 0; x < 40; x++) {
  const ll = conic(x + 0.5, y + 0.5), inside = ll[0] >= -10 && ll[0] < 10;
  const p = px(o, 40, x, y);
  if (!inside) { if (p[3] !== 0) bad++; } else if ((ll[0] < 0) !== (p[0] === 255)) bad++;
}
ok(bad === 0, "non-linear projection samples the cell its lon/lat falls in (" + bad + " mismatches)");
console.log(`  ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);

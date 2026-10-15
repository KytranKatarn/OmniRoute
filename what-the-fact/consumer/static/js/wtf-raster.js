/* Raster reprojection for map overlays (WX-S0, task 7249, ADR #1134).
 *
 * WHY THIS EXISTS. The weather map is a d3 conic-conformal SVG on a SPHERE; the agencies' own Canada projection (EPSG:3978) is on the GRS80
 * ellipsoid, so placing an EPSG:3978 image with a few anchor points drifts by pixels. Instead the page asks the service for a plain lon/lat image
 * (CRS:84: linear in longitude and latitude) and this helper resamples it, one OUTPUT pixel at a time, through the map's own projection.invert, so
 * the overlay lands exactly where the map's coastlines do, whatever projection the map uses.
 *
 * Pure: typed arrays in, typed array out. No DOM, no d3, no network. The page owns fetching (through the server-side proxy) and canvas drawing.
 *
 *   WTFRaster.reproject(src, srcW, srcH, bbox, dstW, dstH, invert, opts) -> Uint8ClampedArray(dstW*dstH*4)
 *     src     RGBA bytes of the lon/lat image, row 0 = north edge
 *     bbox    [minLon, minLat, maxLon, maxLat] the image covers (the WMS BBOX)
 *     invert  (x, y) -> [lon, lat] | null   (e.g. projection.invert); null or non-finite -> transparent
 *     opts    { nearest: true } for categorical imagery (radar bands, fuel classes): no blending between classes.
 *             default is bilinear on premultiplied colour, so a transparent edge does not bleed a dark fringe.
 */
(function (global) {
  "use strict";

  function reproject(src, srcW, srcH, bbox, dstW, dstH, invert, opts) {
    var out = new Uint8ClampedArray(dstW * dstH * 4);
    var nearest = !!(opts && opts.nearest);
    var minLon = bbox[0], minLat = bbox[1], maxLon = bbox[2], maxLat = bbox[3];
    var lonSpan = maxLon - minLon, latSpan = maxLat - minLat;
    if (!(lonSpan > 0) || !(latSpan > 0) || src.length < srcW * srcH * 4) return out;

    for (var y = 0; y < dstH; y++) {
      for (var x = 0; x < dstW; x++) {
        var ll = invert(x + 0.5, y + 0.5);
        if (!ll || !isFinite(ll[0]) || !isFinite(ll[1])) continue;
        var u = (ll[0] - minLon) / lonSpan * srcW;     // source pixel coordinates, edge-based
        var v = (maxLat - ll[1]) / latSpan * srcH;
        if (u < 0 || v < 0 || u >= srcW || v >= srcH) continue;
        var o = (y * dstW + x) * 4;
        if (nearest) {
          var s = ((v | 0) * srcW + (u | 0)) * 4;
          out[o] = src[s]; out[o + 1] = src[s + 1]; out[o + 2] = src[s + 2]; out[o + 3] = src[s + 3];
          continue;
        }
        var fx = u - 0.5, fy = v - 0.5;                 // sample between pixel centres
        var x0 = Math.floor(fx), y0 = Math.floor(fy), tx = fx - x0, ty = fy - y0;
        var x1 = x0 + 1, y1 = y0 + 1;
        x0 = x0 < 0 ? 0 : x0; y0 = y0 < 0 ? 0 : y0;
        x1 = x1 > srcW - 1 ? srcW - 1 : x1; y1 = y1 > srcH - 1 ? srcH - 1 : y1;
        var w00 = (1 - tx) * (1 - ty), w10 = tx * (1 - ty), w01 = (1 - tx) * ty, w11 = tx * ty;
        var i00 = (y0 * srcW + x0) * 4, i10 = (y0 * srcW + x1) * 4, i01 = (y1 * srcW + x0) * 4, i11 = (y1 * srcW + x1) * 4;
        var a = src[i00 + 3] * w00 + src[i10 + 3] * w10 + src[i01 + 3] * w01 + src[i11 + 3] * w11;
        if (a <= 0) continue;
        for (var c = 0; c < 3; c++) {                   // premultiplied blend, then un-premultiply
          var p = src[i00 + c] * src[i00 + 3] * w00 + src[i10 + c] * src[i10 + 3] * w10 +
                  src[i01 + c] * src[i01 + 3] * w01 + src[i11 + c] * src[i11 + 3] * w11;
          out[o + c] = p / a;
        }
        out[o + 3] = a;
      }
    }
    return out;
  }

  var api = { reproject: reproject };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.WTFRaster = api;
})(typeof window !== "undefined" ? window : globalThis);

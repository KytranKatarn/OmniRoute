# PR 02 — Homepage map off Leaflet, onto the shared WTFMap component

Run from a checkout of **KytranKatarn/archie-platform** `main` (read at
`1c28354e7f56`). Branch: `design/pr-02-homepage-map`. Depends on nothing in PR 01.

**Why this is the map you're not seeing.** `/map` and `/weather` moved to the
shared d3-geo component (`static/js/wtf-map.js`) on 2026-09-02. The homepage was
never migrated — `weather.html` says so in its own comments — so `/` still runs
Leaflet 1.9.4 on CARTO raster tiles (the ones that watermarked on 2026-08-30),
with circle markers instead of province shapes.

**Touches:** `consumer/templates/index.html` only.
**No CSS change** — every class the component uses (`.wtf-map-d3`, `.wtf-map-svg`,
`.wtf-map-prov`, `.wtf-map-tip`, `.wtf-map-legend-row`, `.wtf-map-swatch`,
`.wtf-map-legend-note`) is already in `style.css` lines ~899–1655.
**No route change, no new data.** Same two endpoints the Leaflet map read.

---

## Prompt for Claude CLI

```
Work only under what-the-fact/. Branch design/pr-02-homepage-map.
Edit what-the-fact/consumer/templates/index.html only. Apply by content, not
line number. Do not reformat anything outside the spans named below.

1. DELETE these two lines near the top:
     <!-- Leaflet CSS -->
     <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" crossorigin=""/>

2. In #wtf-map-zone, inside <div class="wtf-h-map-controls">, directly BEFORE
   <div class="wtf-map-toggle">, insert:

     <div class="wtf-map-toggle" id="wtf-map-layer-toggle">
       <button id="btn-lean" class="wtf-map-btn active" onclick="setMapLayer('lean')">DOMINANT LEAN</button>
       <button id="btn-volume" class="wtf-map-btn" onclick="setMapLayer('volume')">VOLUME</button>
     </div>

3. Directly AFTER the closing </div> of <div id="wtf-map-row">, still inside
   #wtf-map-zone, insert:

     <div id="wtf-world-note" class="wtf-map-legend-note" hidden>
       World coverage is listed in the index. The map projection covers Canada;
       a world projection is coming in a follow-up.
     </div>
     <div id="wtf-home-map-legend" class="wtf-map-legend"></div>

4. REPLACE
     <!-- Leaflet JS -->
     <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" crossorigin=""></script>
   WITH
     <script src="/static/vendor/d3-array.min.js"></script>
     <script src="/static/vendor/d3-geo.min.js"></script>
     <script src="{{ url_for('static', filename='js/wtf-map.js') }}"></script>
   (same three tags map.html and weather.html use)

5. In the main <script>: replace everything from the line
     var map = L.map("wtf-canada-map", {
   down to, but NOT including, the line
     var BEAT_CONFIG = {
   with the contents of design-handoff/pr/pr-02-homepage-map/index-map.js — and in the marked
   spot, paste buildActivityItem, loadAgentActivity and timeAgo verbatim from
   the old span. PROVINCE_CENTROIDS, the Leaflet legend control, pinLayer,
   clusterLayer, provinceLayer and worldLayer are removed; nothing else reads
   them (grep to confirm).

6. setProvince / clearProvince (below BEAT_CONFIG) still reference Leaflet:
   - In setProvince(pc): add a second param `fromMap`. Replace the whole
       if (provinceLayer) { ... map.fitBounds ... }
     block with
       if (wtfmap) { if (!fromMap) wtfmap.select(pc); wtfmap.focusProvince(pc); }
     and at the very top add
       if (!pc) return clearProvince();
   - In clearProvince(): add param `fromMap`. Replace
       map.setView([60, -96], 3);
     with
       if (wtfmap) { if (!fromMap) wtfmap.select(null); wtfmap.resetView(); }
   - In toggleProvinceDropdown's item.onclick, move `setMapMode('canada')`
     BEFORE `setProvince(p.code)`.

7. grep index.html for "L\." "leaflet" "cartocdn" "map.setView" "map.fitBounds"
   "map.removeLayer" — all must return nothing.

8. pytest tests/ — green. Then open the PR with the body below.
```

## PR body

**Template:** `consumer/templates/index.html`
**Route:** `/` (unchanged). **Data:** `/api/proxy/map-data`, `/api/proxy/articles/geo` — unchanged, nothing derived.

Moves the homepage map onto `static/js/wtf-map.js`, the component `/map` and
`/weather` already use (ADR-018). Removes Leaflet, its CSS and the CARTO tile
requests from the most-visited page.

- Province **shapes**, Lambert conformal conic — no Mercator inflation of the North.
- **Dominant lean / Volume** toggle. Lean uses the existing `leanColour` ramp;
  provinces under 20 articles draw dimmed + dashed via the component's no-data
  rule, never as "balanced". Volume is neutral slate with `--wtf-accent` on the
  single highest province only (handoff correction #2).
- Legend is generated from each layer's ramp by the component.
- Clicking a shape, an index row or the dropdown all select the same province
  and filter the feed; the view refits to it.
- Tooltips via `textContent` (component rule 5).
- **World** keeps its ranked index and feed; the map area states that the
  projection covers Canada instead of clipping countries silently. A world
  projection is PR 03 (it changes the shared component, so it gets its own PR).

Dropped: individual article pins — they were opacity 0 below zoom 5 and the
homepage never zoomed past 3, so no reader saw them.

## Check after deploy (480 / 768 / 1024 px)

- [ ] `/` shows province shapes, no tiles, no CARTO attribution, no Leaflet
      requests in the network panel
- [ ] Dominant lean ↔ Volume switches fill and legend
- [ ] A province under 20 articles is dashed and dim in Lean, never grey-as-balanced
- [ ] Click shape / index row / dropdown → same province highlighted, map refits,
      banner shows, feed filters; Clear resets all three
- [ ] Beat pills refresh the map and the index
- [ ] World: index + feed work; note visible; no blank rectangle
- [ ] `/map` and `/weather` unchanged

# What The Fact — Brand & UI Overhaul Design

**Goal:** Transform what-the-fact.com into a fully branded Canadian AI newsroom — Georgian serif editorial aesthetic, real agent portraits on /team, and a 3-layer interactive Canada map with article pins.

**Architecture:** Three sequential PRs against the wtf-consumer and wtf-tech containers. PR A ships the brand CSS and nav. PR B ships the /team portrait redesign. PR C ships the map pin system (new wtf-tech endpoint + Leaflet JS layers).

**Tech Stack:** Flask + Jinja2 (wtf-consumer, wtf-tech), CSS custom properties (system dark/light theme), Leaflet.js 1.9.x (map layers), PostgreSQL wtf schema (geo pin query), platform.kytranempowerment.com (portrait image source).

---

## Design Decisions

### Brand Direction
- **Hybrid:** C (Editorial Clarity) + A (Breaking Signal urgency)
- **Theme:** Light day / Dark night — `prefers-color-scheme` media query, CSS custom properties
- **Headlines:** Georgia serif — authoritative, editorial weight
- **Data & UI labels:** IBM Plex Mono — bias scores, agent names, source tags, metadata
- **Live indicator:** Red dot (●) + "LIVE · N SOURCES" — always in nav, top right
- **Wordmark:** `WHAT·THE·FACT` (bold Georgia or system serif) + "CANADIAN AI NEWSROOM" mono subtext
- **Map zone:** Always dark (`#0d1117`) regardless of theme — cinematic separation

### Colour System

```css
:root {
  /* Light mode defaults */
  --wtf-bg:          #f9fafb;
  --wtf-bg-card:     #ffffff;
  --wtf-bg-panel:    #f3f4f6;
  --wtf-text:        #111111;
  --wtf-text-muted:  #6b7280;
  --wtf-border:      #e5e7eb;
  --wtf-accent:      #dc2626;   /* red — live, breaking, urgency */
  --wtf-map-bg:      #0d1117;   /* always dark */

  /* Bias spectrum — unchanged */
  --wtf-left:         #3b82f6;
  --wtf-center-left:  #93c5fd;
  --wtf-center:       #9ca3af;
  --wtf-center-right: #fca5a5;
  --wtf-right:        #ef4444;

  /* Agent accents */
  --wtf-fact:    #dc2626;
  --wtf-bias:    #f59e0b;
  --wtf-verify:  #10b981;
  --wtf-local:   #3b82f6;
  --wtf-aurora:  #7c3aed;
}

@media (prefers-color-scheme: dark) {
  :root {
    --wtf-bg:         #0d1117;
    --wtf-bg-card:    #0a0f1a;
    --wtf-bg-panel:   #060d14;
    --wtf-text:       #f9fafb;
    --wtf-text-muted: #6b7280;
    --wtf-border:     #1f2937;
  }
}
```

---

## PR A — Brand CSS + Nav Redesign

### Files
| File | Action |
|------|--------|
| `what-the-fact/consumer/static/style.css` | Rewrite with CSS custom properties + system theme |
| `what-the-fact/consumer/templates/base.html` | Redesign nav: wordmark + live dot + source count |
| `what-the-fact/consumer/templates/index.html` | Apply brand classes, Georgia headlines on article cards |
| `what-the-fact/consumer/templates/article.html` | Apply brand classes, Georgia article headline |
| `what-the-fact/consumer/templates/team.html` | Apply brand classes |

### Nav Design

```html
<nav class="wtf-nav">
  <div class="wtf-nav-brand">
    <span class="wtf-wordmark">WHAT·THE·FACT</span>
    <span class="wtf-subbrand">CANADIAN AI NEWSROOM</span>
  </div>
  <div class="wtf-nav-links">
    <a href="/">News</a>
    <a href="/team">Team</a>
    <a href="https://what-the-fact.tech/transparency">Methodology</a>
    <a href="https://what-the-fact.tech/score">Score Text</a>
  </div>
  <div class="wtf-nav-live">
    <span class="wtf-live-dot"></span>
    <span class="wtf-live-label">LIVE · {{ source_count }} SOURCES</span>
  </div>
</nav>
```

CSS: `wtf-live-dot` pulses with `@keyframes pulse` (opacity 1→0.4, 1.2s infinite).

### Article Card Typography

Headlines use `font-family: Georgia, 'Times New Roman', serif` at 14px/1.4 line-height. Metadata (source, province, bias band, badge) uses `font-family: 'IBM Plex Mono', 'Courier New', monospace` at 10px.

### Consumer routes.py change

The nav needs `source_count` — add to index route context:
```python
with engine.connect() as c:
    source_count = c.execute(text("SELECT COUNT(*) FROM wtf.sources")).scalar()
return render_template("index.html", articles=rows, wtf_tech_url=wtf_tech_url, source_count=source_count)
```

### Success criteria
- Light mode: white cards, black text, red LIVE dot
- Dark mode: `#0d1117` bg, `#f9fafb` text, same red dot
- Georgia headlines render correctly in both modes
- Map zone stays dark in both modes

---

## PR B — /team Portrait Redesign

### Files
| File | Action |
|------|--------|
| `what-the-fact/consumer/templates/team.html` | Rewrite with real portraits |
| `what-the-fact/consumer/routes.py` | TEAM_AGENTS with platform portrait URLs |

### Portrait Strategy

Portraits are served from `https://platform.kytranempowerment.com`. CORS is not an issue for CSS `background-image` (same-origin not required for background images in most browsers). If CORS becomes an issue, portraits are copied to `what-the-fact/consumer/static/portraits/` at deploy time.

Platform portrait URLs (as of 2026-04-29):

| Agent | URL |
|-------|-----|
| F.A.C.T. | `/static/media/images/2026-04-20/c78a58f0-ee5.png` |
| B.I.A.S. | `/static/media/images/2026-04-20/05821aee-a2e.png` |
| V.E.R.I.F.Y. | `/static/media/images/2026-04-20/5d0d0525-a4e.png` |
| L.O.C.A.L. | pending — emoji fallback (📍) until portrait generates |
| I.N.K. | `/static/media/images/2026-04-20/9e1efa5f-5a7.png` |
| D.R.A.F.T. | `/static/media/images/2026-04-20/70bc27b1-ede.png` |
| P.U.B.L.I.S.H. | `/static/media/images/2026-04-20/e7149ec2-f73.png` |

PLATFORM_BASE = `https://platform.kytranempowerment.com`

### /team Layout

```
HERO (dark, always)
  ● LIVE · AI NEWSROOM
  MEET THE TEAM
  Subtitle: "Seven AI agents. One mission — radical transparency."

4-COLUMN GRID (light/dark)
  [Portrait 72×90px] ← CSS background-image from platform URL
  NAME (monospace, agent accent colour)
  ROLE (monospace, muted)
  MODEL (monospace, pill)
  Short description (serif, muted)
  ACTIVE badge (green) | COMING SOON (grey) | PHASE 2 (purple)

Active agents: full colour portrait, solid agent-accent border, full opacity
Coming-soon agents: greyscale filter (filter: grayscale(70%)), dashed border, 0.7 opacity
A.U.R.O.R.A.: purple dashed border, galaxy emoji, "PHASE 2" badge

FOOTER
  "Portraits generated by Media Studio · Radical Transparency →"
```

### Success criteria
- All 4 active agents show their portrait (or emoji fallback)
- Coming-soon agents clearly visually distinct
- A.U.R.O.R.A. teaser card visible with purple styling
- Works in light and dark mode

---

## PR C — Map Pins (3-Layer System)

### Files
| File | Action |
|------|--------|
| `what-the-fact/tech/routes.py` | Add `GET /api/v1/articles/geo` |
| `what-the-fact/consumer/templates/index.html` | Add cluster + pin JS layers to Leaflet map |

### New wtf-tech endpoint: `GET /api/v1/articles/geo`

```python
@bp.get("/api/v1/articles/geo")
def articles_geo():
    """Articles with lat/lng for map pins (last 24h)."""
    from flask import jsonify
    S = _schema()
    with _db().connect() as c:
        rows = c.execute(text(f"""
            SELECT a.id, a.title, a.province_code,
                   a.lat, a.lng, a.geo_scope,
                   bs.band AS bias_band, bs.score AS bias_score,
                   s.name AS source_name, a.ai_analyzed
            FROM {S}.articles a
            LEFT JOIN {S}.bias_scores bs ON bs.article_id = a.id
            LEFT JOIN {S}.sources s ON s.id = a.source_id
            WHERE a.published_at >= NOW() - INTERVAL '24 hours'
              AND a.lat IS NOT NULL
              AND a.lng IS NOT NULL
            ORDER BY a.published_at DESC
            LIMIT 500
        """)).fetchall()

    return jsonify({"articles": [
        {
            "id": r.id,
            "title": r.title,
            "province_code": r.province_code,
            "lat": float(r.lat),
            "lng": float(r.lng),
            "bias_band": r.bias_band or "center",
            "source_name": r.source_name,
            "ai_analyzed": r.ai_analyzed,
        }
        for r in rows
    ]})
```

CORS: already scoped to `/api/v1/*` via flask-cors.

### Map JavaScript — 3 Layers

**Layer 1 — Province heat** (existing, from `/api/v1/map-data`):
- Province fill colour = bias band
- Province opacity = `min(0.15 + articles / 60, 0.85)`

**Layer 2 — Cluster badges** (new):
- Group articles by `province_code`
- For each province with articles, render a pulsing `L.circleMarker` at province centroid
- Radius = `Math.min(6 + count * 0.4, 20)` (capped)
- Colour = province accent (ON=cyan, QC=purple, AB=amber, BC=teal, etc.)
- Label: `L.divIcon` with article count inside
- Click → zoom to province (zoom level 6)

**Layer 3 — Individual bias pins** (new, visible at zoom ≥ 5):
- One `L.circleMarker` per article (radius 5)
- Fill = `BIAS_COLOURS[bias_band]`
- Click → article card slides in from right (existing panel pattern)
- Tooltip: `source_name + " — " + bias_band`

```javascript
const PROVINCE_CENTROIDS = {
  "ON": [51.25, -85.32], "QC": [53.00, -70.00], "BC": [53.73, -127.65],
  "AB": [53.93, -116.58], "SK": [52.94, -106.45], "MB": [56.42, -98.74],
  "NB": [46.57, -66.46], "NS": [44.68, -63.74], "NL": [53.14, -57.66],
  "PE": [46.51, -63.42], "YT": [64.28, -135.00], "NT": [64.28, -119.18],
  "NU": [70.30, -83.11]
};

const PROVINCE_COLOURS = {
  "ON":"#0af","QC":"#a78bfa","AB":"#f59e0b","BC":"#4ade80",
  "SK":"#34d399","MB":"#60a5fa","NS":"#f97316","NB":"#f97316",
  "NL":"#94a3b8","PE":"#94a3b8","YT":"#94a3b8","NT":"#94a3b8","NU":"#94a3b8"
};
```

### Map load sequence

```javascript
async function loadMap() {
  const [mapData, geoResp, pinsData] = await Promise.all([
    fetch(`${WTF_TECH}/api/v1/map-data`).then(r => r.json()),
    fetch("/static/canada-provinces.geojson").then(r => r.json()),
    fetch(`${WTF_TECH}/api/v1/articles/geo`).then(r => r.json()),
  ]);
  renderProvinceLayer(geoResp, mapData.provinces);   // Layer 1
  renderClusterLayer(mapData.provinces);              // Layer 2
  renderPinLayer(pinsData.articles);                 // Layer 3
  map.on("zoomend", () => {
    pinLayer.setStyle({ opacity: map.getZoom() >= 5 ? 0.9 : 0 });
  });
}
```

### Success criteria
- Province heat updates from `/api/v1/map-data`
- Cluster badges visible on load, sized by article count
- Individual bias pins hidden at zoom < 5, visible at zoom ≥ 5
- Click on pin → article card visible
- `/api/v1/articles/geo` returns articles with lat/lng/bias_band
- Works in both light and dark map themes (map always dark)

---

## Audience Impact

| Feature | General public benefit | Researcher benefit |
|---------|----------------------|-------------------|
| Georgia serif headlines | More readable, trustworthy | — |
| System dark/light theme | Comfort across devices | — |
| Real agent portraits | Newsroom identity, trust | Who built this? |
| Map cluster badges | Instant regional picture | Coverage distribution |
| Bias pin dots | Which stories lean which way | Spatial bias analysis |

---

## What This Does NOT Change

- Bias scoring methodology (unchanged — see /transparency)
- Ingest pipeline (unchanged)
- wtf-tech API (additive only — one new endpoint)
- Article page layout (brand CSS applies, no restructuring)
- Mobile layout (inherits from CSS custom properties)

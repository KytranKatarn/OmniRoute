# #3330 — WTF Municipal News Layer (`/municipal`)  [READY TO BUILD]

**Status:** pre-flight DONE, build NOT started (cont-82 hit context emergency). Owner said "go ahead." Execute next session — ~20 min clean.

## Key finding (overturns the earlier "too thin" read)
The data source is **`beat='municipal'` = 2,369 articles** (358 in last 30d), NOT `geo_scope='municipal'` (only 849). The beat is well-populated → the page is viable. Toronto-dominant but real multi-city coverage.

City distribution (where `beat='municipal' OR geo_scope IN('municipal','local')` AND city set):
Toronto 621 · Calgary 13 · Vancouver 11 · Los Angeles 10 · Washington D.C. 10 · New York 9 · Winnipeg 7 · Ottawa 6 · Barrie 6 · Edmonton 5 (+ long tail). ~792 municipal articles carry a city.

## Build (mirror `/weather` — `def weather()` in consumer/routes.py is the exact analog)
1. **Route** `consumer/routes.py` — add `@bp.get("/municipal")` `def municipal():`
   - `S = _schema()`; `with _db().begin() as c:`
   - articles: `SELECT id,title,url,source_slug,city,province_code,published_at,bias_label FROM {S}.articles WHERE beat='municipal'` + optional `AND city=:city` when `request.args.get('city')` set, `ORDER BY published_at DESC LIMIT 60`.
   - city facets: `SELECT city, count(*) n FROM {S}.articles WHERE beat='municipal' AND city IS NOT NULL AND city<>'' GROUP BY city ORDER BY n DESC LIMIT 15`.
   - total count for header. `render_template("municipal.html", articles=, cities=, active_city=, total=, source_count=source_count)`.
   - NO paywall — public (consistent with /weather, /economy). Use existing `_db()`,`_schema()`,`source_count` helpers.
2. **Template** `consumer/templates/municipal.html` — extend base.html; mirror weather.html layout. Header "🏙 Municipal" + coverage note ("Local & city-hall coverage across Canadian outlets — coverage is growing as geo-tagging expands"). City filter = chips/links `?city=<c>` (active highlighted) + an "All" reset. Article list reusing the card idiom from weather.html/news. **XSS: `textContent`/Jinja autoescape only — never innerHTML with article fields** (WTF hard rule).
3. **Nav** `consumer/templates/base.html` — add `<a href="/municipal">Municipal</a>` to DESKTOP `.wtf-nav-links` (after /mps or near /weather) **AND** the mobile `#wtfNavMobile` block (near `/weather`). (Mobile-nav gap that bit /journalists — don't repeat.)
4. **Deploy** Citadel: `rsync -avz --exclude='.env' .../what-the-fact/ root@100.64.0.10:/opt/archie-products/what-the-fact/` then `docker compose up -d --build wtf-consumer` (image-baked — restart won't pick up code). Then commit on a branch + PR (consumer routes.py + 2 templates).
5. **Verify** (Rule #1): fetch `https://what-the-fact.com/municipal` + `?city=Toronto` live (python3 urllib — Bash blocks curl) → 200, real article list, city filter narrows, mobile nav link present.

## Gotchas
- `_PAYWALLED_SOURCES` already filters per-source on consumer; municipal list inherits that automatically — fine.
- Don't reuse the 849 geo_scope column as primary; beat='municipal' is 3× richer.
- This is the LAST WTF "page" gap that's quick; #3331 Cross-Watch / #3333 Promise Tracker are big.

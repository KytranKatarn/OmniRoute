# Template inventory — the real site

Generated from all 49 templates in `uploads/wtf-design-bundle/templates`.
This bundle IS the live Flask source: `officers.html`'s paywall copy matches
what-the-fact.com verbatim. GitHub does not carry these templates.

## The migration is 8 of 48 pages done

`_archetypes.html` is a shared macro library. Only **8 pages import it**:

- `blindspot.html`
- `gic.html`
- `journalists.html`
- `map.html`
- `officers.html`
- `owners.html`
- `rates.html`
- `sources.html`

The other **39 pages** are pre-design-system: their own `<style>` blocks,
hardcoded hexes, and `font-family:'Orbitron'` — a font the site never loads,
so every one of those headings is silently rendering as generic sans.

### Orbitron is actually applied on 20 pages
`activity.html` · `chain.html` · `cluster.html` · `cost.html` · `cross_watch.html` · `crtc.html` · `dedup_review.html` · `divergence.html` · `economy.html` · `entity.html` · `ethics.html` · `journalist.html` · `lobbying.html` · `markets.html` · `mp.html` · `mps.html` · `municipal.html` · `search.html` · `senator.html` · `source.html`

(`gic`, `journalists`, `officers`, `rates` name Orbitron only in a comment
recording its removal — those are clean.)

### Worst hardcoded-colour offenders
| Template | Unique hexes |
|---|---|
| `article.html` | 100 |
| `index.html` | 63 |
| `activity.html` | 55 |
| `mps.html` | 45 |
| `weather.html` | 41 |
| `beat_landing.html` | 28 |
| `claims.html` | 28 |
| `mp.html` | 28 |
| `account.html` | 25 |
| `news.html` | 24 |
| `entity.html` | 23 |
| `cluster.html` | 22 |
| `score.html` | 22 |
| `source.html` | 21 |
| `alerts.html` | 20 |

`article.html` at 101 unique hex values is the single least systematic file in
the codebase, and it is the page readers land on most.

## _archetypes.html — the 22 macros to build against

Anything we rebuild should compose these rather than reinvent them.

| Macro | Signature |
|---|---|
| chip | `(label, title=None)` |
| segment | `(label, href="#", active=False)` |
| filter_chip | `(label, remove_href=None)` |
| photo | `(credit=None, css="")` |
| lean_pill | `(bucket, label=None)` |
| stat_tiles | `(tiles)` |
| entity_header | `(name, meta_chips=None, photo_credit=None)` |
| record_tabs | `(tabs, active=None)` |
| person_card | `(name, sub=None, href="#", spine_token=None, right=None)` |
| directory_grid | `()` |
| record_card | `(title, meta=None, chips=None, spine_token=None, stack=False)` |
| record_links | `(links)` |
| paywall | `(title, blurb, next_url, plans_href="/join")` |
| ranked_bars | `(rows, highlight=None)` |
| data_table | `(columns, rows, empty="No records match these filters.")` |
| layer_switch | `(layers, active=None)` |
| freshness | `(text, stale=False)` |
| measurement | `(value, unit="", absent="—")` |
| layer_row | `(label, value=None, unit="")` |
| doc_shell | `(toc)` |
| setting_row | `(label, description=None, checked=False, name=None)` |
| field | `(label, value="", readonly=True)` |

Two of these matter for honesty and we should use them everywhere:
**`measurement(value, unit, absent="—")`** renders a real absent state instead of
printing 0, and **`freshness(text, stale=False)`** marks stale data as stale.

Archetype class namespace: `wtf-a-*` — chip, fchip, ph, tiles, tile, idhdr,
idname, idmeta, tabs, pcard, spine, prow, pname, grid, rhead, rtitle, rchips,
rlinks, rlink, pay, pay-t, pay-b, pay-cta, pay-plans, ranked, ranked-row,
bar-track, ranked-v, tblwrap, tbl, num, nodata, layers, lrow, doc, toc, srow,
toggle, knob, field, flabel, fbox.

## Gated pages (Starter+)

| Template | Gate title | next_url |
|---|---|---|
| `_archetypes.html` | — | — |
| `activity.html` | — | — |
| `api_keys.html` | — | — |
| `article.html` | — | — |
| `blindspot.html` | Deeper analysis — Starter+ | `/blindspot` |
| `claims.html` | — | — |
| `cluster.html` | — | — |
| `crtc.html` | — | — |
| `divergence.html` | — | — |
| `entity.html` | — | — |
| `ethics.html` | — | — |
| `gic.html` | GIC Appointments — Starter+ | `/gic` |
| `index.html` | — | — |
| `journalist.html` | — | — |
| `lobbying.html` | — | — |
| `map.html` | — | — |
| `mp.html` | — | — |
| `news.html` | — | — |
| `officers.html` | Officers of Parliament — Starter+ | `/parliament/officers` |
| `owners.html` | Ownership Map — Starter+ | `/owners` |
| `rates.html` | — | — |
| `search.html` | — | — |
| `senator.html` | — | — |
| `source.html` | — | — |

## Data contracts — do not change these

- **`gic.html`** — unchanged: appointments[], depts[], dept, is_subscriber
- **`journalists.html`** — unchanged: journalists[], total, q
- **`officers.html`** — unchanged: officers[], is_subscriber
- **`owners.html`** — unchanged: owners[], source_count, unattributed, is_subscriber
- **`rates.html`** — is UNCHANGED: current, decisions[], is_subscriber. The paywall gate below is preserved exactly — this page is Starter+ gated

## Every page

### `_archetypes.html`
**H1:** {{ name }}  
**System:** not migrated · 1 hexes  
**Gated:** yes  
**Vars:** `title`, `label`, `href`, `remove_href`, `css`, `credit`, `_tok`, `t`, `name`, `spine_token`, `right`, `sub`  
**Links:** `/join`  
**Size:** 12665 bytes

### `account.html`
**Title:** My Account — What The Fact  
**H1:** Account Overview  
**System:** not migrated · 25 hexes  
**Vars:** `user_email`, `check`, `label`, `icon`  
**Links:** `/billing/portal`, `/billing/checkout/starter`, `/alerts`, `/literacy`, `/logout`  
**Size:** 10813 bytes

### `account_beats.html`
**Title:** My Beats — What The Fact  
**H1:** My Beats  
**System:** not migrated · 15 hexes  
**Vars:** `b`  
**Size:** 3028 bytes

### `activity.html`
**Title:** Agent Activity — What The Fact  
**H1:** AGENT ACTIVITY LOG  
**System:** not migrated · **Orbitron applied** · 55 hexes  
**Gated:** yes  
**Vars:** `trends`, `creed_scan`, `score`, `cat`, `cls`, `agent`, `tier_color`, `pct`, `label`, `note`, `astats`, `source_health`  
**Links:** `/governance`, `/join`  
**Size:** 44189 bytes

### `alerts.html`
**Title:** Custom Alerts — What The Fact  
**H1:** CUSTOM ALERTS  
**System:** not migrated · 20 hexes  
**Vars:** `user_email`, `s`, `alerts`, `a`, `parts`  
**Size:** 9379 bytes

### `api_docs.html`
**Title:** API Documentation — What The Fact  
**H1:** Public API  
**Meta:** Public API for Canadian news bias scores, outlet data and cross-product accountability signals.  
**System:** not migrated · 0 hexes  
**Vars:** `key_header`, `p`, `r`  
**Links:** `/cross-watch`, `/account/api-keys`  
**Size:** 5932 bytes

### `api_keys.html`
**Title:** API Keys — What The Fact  
**H1:** API keys  
**System:** not migrated · 1 hexes  
**Gated:** yes  
**Vars:** `keys`, `max_keys`, `k`  
**Links:** `/api/docs`  
**Size:** 6244 bytes

### `article.html`
**Title:** {{ a.title }} — What The Fact  
**H1:** {{ a.title }}  
**Meta:** {{ a.title | e }}  
**System:** not migrated · 100 hexes  
**Gated:** yes  
**Vars:** `a`, `_desc`, `reading_time_min`, `_cv_col`, `_cv_lbl`, `tk`, `ent`, `kf`, `band_class`, `display_band`, `pct`, `phrase`  
**Links:** `/billing/checkout/starter`, `/literacy`  
**Size:** 62828 bytes

### `base.html`
**Title:** What The Fact  
**Meta:** Canada's AI-powered newsroom. Every article scored for bias. Every claim fact-checked. No spin — just data.  
**System:** not migrated · 12 hexes  
**Vars:** `_p`, `section`, `href`, `label`, `nav_source_count`  
**Links:** `/static/favicon.svg`, `/search`, `/alerts`, `/account`, `/logout`, `/join`, `/login`, `/governance`  
**Size:** 15644 bytes

### `beat_landing.html`
**Title:** {{ beat.name }} — What The Fact  
**H1:** {{ beat.name }}  
**Meta:** {{ beat.description | e }}  
**System:** not migrated · 28 hexes  
**Vars:** `beat`, `a`, `preview_text`  
**Links:** `/login`  
**Size:** 6548 bytes

### `blindspot.html`
**Title:** Coverage Blind Spots · What The Fact  
**H1:** Coverage blind spots  
**Meta:** Stories carried by only one side of the Canadian media spectrum.  
**System:** migrated (imports archetypes) · 0 hexes  
**Gated:** yes → `/blindspot`  
**Vars:** `b`, `pct`, `days`  
**Size:** 4774 bytes

### `chain.html`
**Title:** Accountability Chain Explorer — What The Fact  
**H1:** Accountability Chain Explorer  
**Meta:** Follow the money through Canadian public life — donations, votes, contracts, and the news that covers them. The 8-link accountability chain, with honest data gaps.  
**System:** not migrated · **Orbitron applied** · 19 hexes  
**Vars:** `chain_slug`  
**Size:** 11914 bytes

### `claims.html`
**Title:** Election Claim Tracker — What The Fact  
**System:** not migrated · 28 hexes  
**Gated:** yes  
**Vars:** `politician_name`, `claims`, `claim`, `active_status`  
**Links:** `/claims`  
**Size:** 6153 bytes

### `cluster.html`
**Title:** {{ (cluster.representative_title or 'Story Cluster')|truncate(70) }} — Outlet Comparison · What The Fact  
**H1:** {{ cluster.representative_title or 'Story Cluster' }}  
**Meta:** {{ distinct_source_count }} outlets covered this story. Compare bias, framing, and fact-check verdicts side by side.  
**System:** not migrated · **Orbitron applied** · 22 hexes  
**Gated:** yes  
**Vars:** `distinct_source_count`, `cluster`, `_headline`, `_brief`, `bc`, `art`, `band_long`, `coverage_data`, `band_colour`, `pct`, `band`, `verdict_colour`  
**Links:** `/news`, `/join`  
**Size:** 17075 bytes

### `connect.html`
**Title:** Subscribe — What The Fact · Canadian AI Newsroom  
**H1:** THE NEWS, UNFILTERED.THE BIAS, EXPOSED.  
**System:** not migrated · 18 hexes  
**Vars:** `source_count`, `total_articles`, `icon`, `title`, `desc`, `url`, `col`, `name`  
**Links:** `/billing/checkout/starter`, `/login`  
**Size:** 11250 bytes

### `cost.html`
**Title:** What Parliament Costs Canadians · What The Fact  
**H1:** What Parliament Costs Canadians  
**Meta:** The approximate annual and 5-year cost to taxpayers of Canada's Parliament — MP and senator salaries plus office expenses. Sourced from public disclosures, every figure labelled approximate.  
**System:** not migrated · **Orbitron applied** · 5 hexes  
**Links:** `/mps`  
**Size:** 3272 bytes

### `cross_watch.html`
**Title:** Cross-Watch — Entities across the Watch Series · What The Fact  
**H1:** 🔗 Cross-Watch  
**Meta:** Cross-Watch — people and organizations resolved across Gov, Civic, Legal & Market Watch and the news, with their cross-product accountability footprint.  
**System:** not migrated · **Orbitron applied** · 15 hexes  
**Vars:** `q`, `e`, `m`  
**Links:** `/cross-watch`  
**Size:** 3804 bytes

### `crtc.html`
**Title:** CRTC Decisions — Broadcasting & Telecom Rulings · What The Fact  
**H1:** 📡 CRTC Decisions  
**Meta:** Canadian Radio-television and Telecommunications Commission decisions 2024–2026. Broadcasting licences, telecom rulings, and enforcement actions.  
**System:** not migrated · **Orbitron applied** · 15 hexes  
**Gated:** yes  
**Vars:** `decisions`, `concentration_badge`, `o`, `ti`, `bar_pct`, `tc`, `d`  
**Links:** `/owners`, `/crtc`, `/join`  
**Size:** 8071 bytes

### `dedup_review.html`
**Title:** Dedup Review — What The Fact (admin)  
**H1:** Dedup Review Queue  
**System:** not migrated · **Orbitron applied** · 14 hexes  
**Size:** 6134 bytes

### `divergence.html`
**Title:** Coverage Divergence · What The Fact  
**Meta:** Where Canadian outlets diverge most in how they cover the same story.  
**System:** not migrated · **Orbitron applied** · 16 hexes  
**Gated:** yes  
**Links:** `/join`, `/login`  
**Size:** 5917 bytes

### `economy.html`
**Title:** Economy &amp; Markets — M.A.R.K.E.T. · What The Fact  
**Meta:** Economy, business and foreign-policy coverage from What The Fact.  
**System:** not migrated · **Orbitron applied** · 15 hexes  
**Vars:** `economy_count`, `business_count`, `foreign_count`, `a`  
**Size:** 7741 bytes

### `edu.html`
**Title:** Education API — What The Fact  
**H1:** MEDIA LITERACY API  
**System:** not migrated · 10 hexes  
**Vars:** `rate_limit`, `rate_window`  
**Size:** 11258 bytes

### `entity.html`
**Title:** {{ e.canonical_name }} — Cross-Watch · What The Fact  
**H1:** {{ TYPE_ICON.get(e.entity_type,'🔎') }} {{ e.canonical_name }}  
**Meta:** {{ e.canonical_name }} — cross-product accountability footprint across Gov, Civic, Legal, Market Watch and the news, by What The Fact.  
**System:** not migrated · **Orbitron applied** · 23 hexes  
**Gated:** yes  
**Vars:** `e`, `products`, `total_mentions`, `recent`, `meta`, `p`, `a`, `cit`, `market`, `l`, `c`  
**Links:** `/cross-watch`, `/join`  
**Size:** 10589 bytes

### `ethics.html`
**Title:** Ethics Commissioner Rulings — Conflict of Interest Reports · What The Fact  
**H1:** ⚖️ Ethics Commissioner Reports  
**Meta:** All Ethics Commissioner investigation reports on Canadian MPs, ministers, and public officials. Conflict of interest findings 2015–2026.  
**System:** not migrated · **Orbitron applied** · 10 hexes  
**Gated:** yes  
**Vars:** `rulings`, `r`  
**Links:** `/join`, `/parliament/officers`  
**Size:** 4430 bytes

### `forecast_accuracy.html`
**Title:** Forecast Accuracy · What The Fact  
**H1:** We keep score on the weather forecast, the same way we keep score on the news  
**Meta:** How accurate Canada's weather forecasts actually turn out to be — measured against what the stations recorded.  
**System:** not migrated · 16 hexes  
**Vars:** `s`, `pt`, `c`, `pct`  
**Size:** 10630 bytes

### `gic.html`
**Title:** GIC Appointments — Governor in Council Patronage · What The Fact  
**H1:** Governor in Council appointments  
**Meta:** Every Governor in Council appointment in Canada — judges, Crown corp executives, regulatory boards, and federal tribunals. Patronage tracking via Orders-in-Council.  
**System:** migrated (imports archetypes) · 0 hexes  
**Gated:** yes → `/gic`  
**Vars:** `appointments`, `a`  
**Size:** 3669 bytes

### `governance.html`
**Title:** AI Newsroom Governance — What The Fact  
**H1:** AI Newsroom Governance  
**System:** not migrated · 12 hexes  
**Vars:** `scan`, `cat`, `pv`  
**Links:** `/activity`, `/team`  
**Size:** 4523 bytes

### `index.html`
**System:** not migrated · 63 hexes  
**Gated:** yes  
**Vars:** `a`, `is_subscriber`  
**Links:** `/activity`, `/news`, `/blindspot`, `/divergence`, `/join`, `/login`, `/weather`, `/economy`, `/owners`, `/sources`  
**Size:** 46995 bytes

### `journalist.html`
**Title:** {{ j.canonical_name }} — Journalist · What The Fact  
**H1:** 📝 {{ j.canonical_name }}  
**Meta:** {{ j.canonical_name }} — outlets, beats, and coverage analysis by What The Fact.  
**System:** not migrated · **Orbitron applied** · 19 hexes  
**Gated:** yes  
**Vars:** `j`, `declared`, `article_count`, `outlets`, `o`, `a`, `b`, `t`, `c`  
**Links:** `/journalists`, `/join`  
**Size:** 6589 bytes

### `journalists.html`
**Title:** Journalists — What The Fact  
**H1:** Journalists  
**Meta:** Track Canadian journalists across our news sources — beats, outlets, and coverage patterns by What The Fact.  
**System:** migrated (imports archetypes) · 0 hexes  
**Vars:** `total`, `q`  
**Size:** 2042 bytes

### `literacy.html`
**Title:** Media Literacy Score — What The Fact  
**H1:** MEDIA LITERACY SCORE  
**System:** not migrated · 18 hexes  
**Vars:** `user_email`, `score`, `band`, `color`, `pct`, `recent`, `r`  
**Size:** 6241 bytes

### `lobbying.html`
**Title:** {% if detail %}{{ detail.org_label }} — lobbying{% else %}Lobbying Tracker{% endif %} · What The Fact  
**H1:** 🏢 {{ detail.org_label }}  
**Meta:** {% if detail %}Who {{ detail.org_label }} lobbies in Parliament — {{ detail.contacts }} registered communications with {{ detail.mps }} MPs.{% else %}Who lobbies Canadian MPs — {{ '{:,}'.format(stats.contacts or 0) }} registered communications from the federal Lobbying Registry, by organization and by MP.{% endif %}  
**System:** not migrated · **Orbitron applied** · 14 hexes  
**Gated:** yes  
**Vars:** `detail`, `stats`, `m`, `r`, `o`  
**Links:** `/lobbying`  
**Size:** 9161 bytes

### `map.html`
**Title:** News Map — What The Fact  
**H1:** NEWS MAP  
**System:** migrated (imports archetypes) · 11 hexes  
**Gated:** yes  
**Size:** 7616 bytes

### `markets.html`
**Title:** Publicly traded federal contractors · What The Fact  
**H1:** 📈 Publicly traded federal contractors  
**Meta:** TSX-listed companies that are also federal contractors, ranked by cumulative federal-contract dollars — where public money meets the markets. Approximate & partial, via Gov Watch open procurement data.  
**System:** not migrated · **Orbitron applied** · 10 hexes  
**Vars:** `issuers`, `i`  
**Size:** 3319 bytes

### `mp.html`
**Title:** {{ mp.name }} — MP Profile · What The Fact  
**H1:** {{ mp.name }}  
**Meta:** {{ mp.name }} ({{ mp.party }}, {{ mp.riding_name }}) — vote record, media coverage analysis by What The Fact.  
**System:** not migrated · **Orbitron applied** · 28 hexes  
**Gated:** yes  
**Vars:** `mp`, `yes_count`, `no_count`, `stats`, `total_votes`, `articles`, `yes_pct`, `cm`, `ballot_class`, `v`, `ballot_icon`, `a`  
**Links:** `/mps`, `/join`  
**Size:** 21803 bytes

### `mps.html`
**Title:** Members of Parliament · What The Fact  
**H1:** 🏛 Members of Parliament  
**Meta:** {{ mps|length }} Members of Parliament tracked by What The Fact. See how they vote, who funds them, and how media covers them.  
**System:** not migrated · **Orbitron applied** · 45 hexes  
**Vars:** `mps`, `p`, `pc`, `col`, `party_name`, `party_mps_list`, `mp`, `leader_title`, `caucus_name`, `caucus_senators`, `s`, `senators`  
**Links:** `/mps`  
**Size:** 48436 bytes

### `municipal.html`
**Title:** Municipal Intelligence — L.O.C.A.L. · What The Fact  
**Meta:** Local government coverage across Canadian cities, from What The Fact.  
**System:** not migrated · **Orbitron applied** · 10 hexes  
**Vars:** `total`, `cities`, `c`, `active_city`, `a`  
**Links:** `/municipal`  
**Size:** 6516 bytes

### `news.html`
**Title:** Latest News — What The Fact  
**H1:** LATEST NEWS  
**System:** not migrated · 24 hexes  
**Gated:** yes  
**Vars:** `total`, `source_count`, `lean_cls`, `s`, `col`, `page`, `total_pages`, `val`, `province_filter`, `beat_filter`, `scope_filter`, `riding_filter`  
**Links:** `/billing/checkout/starter`  
**Size:** 11771 bytes

### `officers.html`
**Title:** Officers of Parliament — Canada's Accountability Watchdogs · What The Fact  
**H1:** Officers of Parliament  
**Meta:** Canada's 8 Officers of Parliament — independent accountability watchdogs including the Auditor General, Ethics Commissioner, and Commissioner of Lobbying.  
**System:** migrated (imports archetypes) · 0 hexes  
**Gated:** yes → `/parliament/officers`  
**Vars:** `officers`, `o`  
**Size:** 4249 bytes

### `owners.html`
**Title:** Media Owners — Who Controls Canadian News · What The Fact  
**H1:** Media ownership map  
**Meta:** Who owns Canadian news outlets? Ownership map, bias profiles, and outlet counts for every media owner tracked by What The Fact.  
**System:** migrated (imports archetypes) · 0 hexes  
**Gated:** yes → `/owners`  
**Vars:** `owners`, `source_count`, `unattributed`, `scored`, `bands`, `outlet`  
**Size:** 6837 bytes

### `rates.html`
**Title:** Bank of Canada Rate Decisions · What The Fact  
**H1:** Bank of Canada rate decisions  
**Meta:** Bank of Canada overnight rate decision history. Every cut, hike, and hold since 2000 — with basis-point changes.  
**System:** migrated (imports archetypes) · 1 hexes  
**Gated:** yes  
**Links:** `/join`, `/parliament/officers`  
**Size:** 4836 bytes

### `score.html`
**Title:** Score Any Article — What The Fact  
**H1:** Score Any Article  
**System:** not migrated · 22 hexes  
**Vars:** `error`, `colour`, `band`, `bias`, `phrase`, `vc`, `article_text`  
**Links:** `/billing/checkout/starter`  
**Size:** 6927 bytes

### `search.html`
**Title:** {% if q %}Search: {{ q }} — {% endif %}What The Fact  
**System:** not migrated · **Orbitron applied** · 17 hexes  
**Gated:** yes  
**Vars:** `q`, `results`, `colour`, `r`, `band`  
**Links:** `/join`  
**Size:** 3300 bytes

### `senator.html`
**Title:** {{ senator.name }} — Senator Profile · What The Fact  
**H1:** {{ senator.name }}  
**Meta:** {{ senator.name }} ({{ senator.caucus_label }}, {{ senator.province }}) — Senate of Canada profile on What The Fact.  
**System:** not migrated · **Orbitron applied** · 13 hexes  
**Gated:** yes  
**Vars:** `senator`, `c`, `ballot_colour`, `ballot_icon`, `v`  
**Links:** `/mps`  
**Size:** 10369 bytes

### `source.html`
**Title:** {{ src.name }} — Bias Profile · What The Fact  
**H1:** {{ src.name }}  
**Meta:** {{ src.name }} bias profile: {{ _band }} lean. {{ src.total_articles }} articles tracked by What The Fact's AI newsroom.  
**System:** not migrated · **Orbitron applied** · 21 hexes  
**Gated:** yes  
**Vars:** `src`, `_band`, `colour`, `band`, `bc`, `pct`, `bc_colour`, `art`, `art_colour`, `art_band`  
**Links:** `/news`, `/join`  
**Size:** 9322 bytes

### `sources.html`
**Title:** Canadian News Sources — Bias Profiles · What The Fact  
**H1:** Canadian news sources  
**Meta:** Bias profiles for 46 Canadian news outlets tracked by What The Fact. See rolling bias scores, article counts, and ownership for CBC, Globe and Mail, National Post, and more.  
**System:** migrated (imports archetypes) · 0 hexes  
**Vars:** `sources`, `s`  
**Size:** 4223 bytes

### `team.html`
**H1:** MEET THE TEAM  
**System:** not migrated · 0 hexes  
**Vars:** `agent`  
**Size:** 2605 bytes

### `unsubscribe.html`
**H1:** You're unsubscribed.  
**System:** not migrated · 3 hexes  
**Size:** 771 bytes

### `weather.html`
**Title:** Weather &amp; Climate Intelligence — A.U.R.O.R.A. · What The Fact  
**H1:** Weather &amp; climate intelligence  
**Meta:** Canadian wildfire, fire-weather and climate intelligence — active perimeters, satellite hotspots by province, and live station wind, with every layer's source and last pull shown.  
**System:** not migrated · 41 hexes  
**Vars:** `code`, `aurora_cities`, `a`, `climate_count`, `sci_count`, `source_count`, `fire_summary`, `f`, `w`, `aurora_map`, `city_stale_min`  
**Size:** 47562 bytes


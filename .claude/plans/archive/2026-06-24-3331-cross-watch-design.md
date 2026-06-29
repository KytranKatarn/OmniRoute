# #3331 — Cross-Watch Intelligence — Design Pass (2026-06-24)

**Task:** #3331 (project #259 WTF) — "connect WTF stories to Gov/Legal/Civic/Market Watch data."
**Owner decisions (verified via AskUserQuestion, 2026-06-24):**
- **Scope = FULL** — consumer surface + Legal & Market adapters + "this story just got real" alerts.
- **Surface = canonical entity profile + article teaser** (mirror the shipped `/mp` + `/journalist` profile pattern).

Status: **design pass complete, build NOT started.** This is a multi-session epic — phased so each phase ships standalone.

---

## 0. TL;DR — this is NOT greenfield

The hard part (the cross-product **graph backbone**, Project #373) is already live and large. Two parallel investigations (the WTF graph + the 5 product DBs) confirm:

- `wtf.shared` graph: **452k entities, 455k mentions, 788k relationships.** It already resolves the *same* person/org across products — **343 entities span ≥2 products, 13 span 3.**
- **Gov + Civic adapters LIVE** (290k procurement + 148k lobbying mentions). Parliament natively bridged (`mps.entity_id`; 533k donation edges, votes, appointments). WTF articles tagged in (14k).
- Dedup/resolution/alias engine + merge-review queue: built (#373).

**The three real gaps = exactly what FULL scope covers:**
1. **No consumer surface** — all that cross-linked data is invisible (the `cross_watch` module is API-only, no UI; only an alerts-badge `fetch` in base.html).
2. **Legal + Market not in the graph** — stub rows only (61 + ~31). Their DBs are SQLite on Citadel (free-text names; Market = bare tickers).
3. **No alerts for legal/market** — `cross_watch_signals` carries only wtf/gov/civic today.

Same shape as #3329: backend ~80% there, the gap is the **public UI** (+ 2 adapters + alert wiring).

---

## 1. Current State (verified 2026-06-24)

### 1.1 The graph — `wtf` DB, `shared` schema (Postgres on hub, `WTF_DATABASE_URL`)
| table | rows | role |
|---|---|---|
| `entities` | 452,411 | person 402,715 · organization 42,698 · journalist 1,554 · (legacy legislation 5,444) |
| `entity_mentions` | 455,065 | `product` column = the cross-product link |
| `entity_relationships` | 788,167 | chain edges (donated_to 533k, awarded_to 135k, cast_vote 57k, lobbied_by 50k, covered_by 8k) |
| `entity_blocks` | 445,366 | dedup blocking (norm_name) |
| `merge_review_queue` | 5,430 | human dedup review |
| `entity_external_ids` | **0** | provisioned, UNUSED (external-ID linking stubbed) |
| `chain_link_types` | 12 | the controlled link vocabulary |
| `adapter_registry` | 6 | per-product adapter registry |

**Mentions by product:** gov-watch procurement 290,782 · civic-watch lobby 148,641 · wtf article 14,662 · civic civic_event 919 · legal-watch ethics 61 · market via relationships ~31. → **Legal + Market are effectively absent.**

### 1.2 Two distinct `shared` schemas — DO NOT CONFLATE
- **`wtf` DB → `shared`** = the real graph (above).
- **`archie` DB → `shared`** = the lightweight **alert/follow layer** the hub `cross_watch` routes read (`get_db_cursor()` defaults to archie). `cross_watch_signals` 20,229 · `cross_watch_alerts` 24 · `user_follows`.

### 1.3 Adapter mechanisms — **TWO kinds (key architecture fact)**
- **In-repo reconcilers** (`what-the-fact/ingest/entity_graph_{wtf,parliament,ec_donations,securities}_reconcile.py`): operate on data **already in the wtf DB** → write **directly, set-based** via `WTF_DATABASE_URL`. No HTTP. (Skeleton: `entity_graph_securities_reconcile.py`.)
- **Cross-host adapters** (gov-watch, civic-watch product apps on Citadel): read **their own** product DB → build canonical-name payloads → **POST** to the wtf-consumer ingest endpoint over the mesh with `X-Internal-Key`. (KB #273399.)
- **→ Legal + Market must be CROSS-HOST adapters** (their data is in separate SQLite DBs), NOT in-repo reconcilers. The `securities_reconcile` skeleton only applies if data is first staged into the wtf DB (we don't want that).

### 1.4 The 5 product DBs (the link sources)
| Product | Engine / location | Best join surface (entity → name) |
|---|---|---|
| Gov | Postgres `gov_watch_db`, schema `gov_watch` (Citadel) | `proactive_disclosures.vendor_name` / `award_notices.winner_name` (org); `gic_appointments.appointment_of` (person) — **LIVE in graph** |
| Civic | SQLite `kytran_watch_api:/app/data/watch.db` | `lobby_communications.{registrant_name,client_name,dpoh_name}` (50k) — **LIVE in graph** |
| Legal | SQLite `kytran_legal_api:/app/data/legal.db` | `ethics_rulings.subject_name` (person, 61); `scc_decisions.{case_name,majority_author}` (0 rows); `regulations.department` (org) — **NOT in graph** |
| Market | SQLite `kytran_market_api:/app/data/market.db` | `rate_decisions.source` (macro); issuer = **bare `ticker`** only, entity tables empty — **NOT in graph; weakest surface** |
| WTF | `wtf` DB articles | article bylines + `article_mp_tags` → `entity_mentions` (product='wtf') |

**Central constraint:** 4 heterogeneous external stores (1 Postgres + 3 SQLite) + the 5th store being the wtf graph itself. **No DB-layer join exists or is feasible** — linkage happens in the graph via name resolution.

### 1.5 Existing surface / API
- **Hub `cross_watch` module** (`platform_v2/tools/cross_watch/routes.py`, blueprint `cross_watch_bp`, "API-only, no dashboard card") — reads **archie** DB. Endpoints in §3.4.
- **Consumer proxy** `what-the-fact/consumer/cross_watch.py` → thin pass-through to hub `CROSS_WATCH_HUB_URL` (mesh `http://100.64.0.4:3000`) with `Bearer $CROSS_WATCH_SERVICE_TOKEN` + `X-User-Email`. base.html:57 calls `/api/cross-watch/alerts`. **No cross-watch PAGE, no DHQ tab.**
- **Entity profiles:** `/journalist/<int:id>` (`routes.py:2380`, `journalist.html`) + `/mp/<slug>` (`routes.py:2195`, `mp.html`). `/api/entities/<id>/profile` (`consumer/entities.py`, **journalist-only**, `@require_product_access("wtf-premium")`). **`/entity/<id>` does NOT exist.**
- **Alert generator** `alert_generator.generate_cross_watch_alerts()` (APScheduler ~15min): signals(last 20min) → `user_follows` → one alert/follower.

---

## 2. Target Architecture

```
  Gov DB ─┐  (cross-host adapter, LIVE)
 Civic DB ┼─► POST /api/internal/entity-graph/ingest ─┐
 Legal DB ┤  (cross-host adapter, P2 NEW)             │
Market DB ┘  (cross-host adapter, P2 NEW)             ▼
 parliament/securities ──(in-repo reconcile)──►  wtf.shared GRAPH (452k entities)
                                                      │
        ┌─────────────────────────────────────────────┼───────────────────────────┐
        ▼                         ▼                     ▼                            ▼
  /entity/<id> profile     article teaser panel    /cross-watch explorer    alert layer (archie DB)
  (footprint by product)   (entities→footprint)    (search by footprint)    signals→follows→alerts
        └──────────────── all read wtf.shared (mentions.product + relationships) ──┘
```

Reuse the live graph; fill the 2 missing adapters; surface it 3 ways; layer alerts on top. Each phase is independently shippable.

---

## 3. Build-Ready Contracts (verified)

### 3.1 Ingest endpoint (the contract Legal/Market adapters POST to)
`POST /api/internal/entity-graph/ingest` — `what-the-fact/consumer/entity_graph_routes.py`. Auth `X-Internal-Key: $INTERNAL_API_KEY` (503 unset / 401 mismatch). Body `{product, entities[], mentions[], relationships[]}`, `product ∈ {wtf,gov-watch,civic-watch,legal-watch,market-watch}`, each list ≤ **5000**, one idempotent txn.
```jsonc
entity ref: {"canonical_name":"...", "entity_type":"person|organization|journalist",  // REQUIRED inline
             "role":{"type":"...","external_id":"..."}?, "raw_name":"..."?}            // OR pointer {"slug":"..."}
mention:    {"entity":<ref>, "content_type":"...", "content_id":"...",                  // all REQUIRED
             "mention_context":"..."?, "confidence":0.0-1.0?}
relationship:{"from":<ref>,"to":<ref>,"relationship_type":<edge>,                       // REQUIRED; edge ∈ VALID_EDGE_TYPES
             "source_id":"..."?, "valid_from":?, "valid_to":?, "metadata":{}?}
```
- **slug is server-derived** (`name_to_slug(normalize_name(name))` in `ingest/shared/entity_graph.py`: NFKD-deaccent→lower→strip honorifics→hyphenate). NEVER send slug for inline. Same name from any product → one node.
- Upserts: entities ON `slug`; mentions ON `(entity_id,product,content_type,content_id)`; relationships ON `(from,to,relationship_type,source_product,source_id)`.
- Returns `{ok, product, entities_created, entities_updated, mentions_upserted, relationships_upserted}`.

### 3.2 Adapter skeleton (cross-host; mirror gov/civic, KB #273399)
Lives in the **legal-watch / market-watch product app** on Citadel (NOT the wtf repo). Reads its own SQLite, builds canonical-name payloads, POSTs ingest.
```python
# legal-watch/adapters/entity_graph_legal_adapter.py  (and market analog)
INGEST = os.environ["ENTITY_INGEST_URL"]      # http://<wtf-consumer mesh>:8103/api/internal/entity-graph/ingest
KEY    = os.environ["INTERNAL_API_KEY"]
def build_payload(rows):
    entities, mentions, relationships = [], [], []
    for r in rows:
        name = clean(r["subject_name"])                       # legal: ethics_rulings.subject_name
        if not _sluggable(name): continue                     # NFKD-fold + require [a-z0-9]
        ent = {"canonical_name": name, "entity_type": "person"}
        mentions.append({"entity": ent, "content_type":"ethics_ruling",
                         "content_id": str(r["id"]), "mention_context": r["title"], "confidence": 0.9})
        # optional edge: relationships.append({"from": ent, "to": {...}, "relationship_type":"covered_by", ...})
    return {"product":"legal-watch", "entities":entities, "mentions":mentions, "relationships":relationships}
def run(dry=False):
    for batch in chunked(read_sqlite(), 5000):                # respect the 5000 cap
        payload = build_payload(batch)
        if dry: print(summary(payload)); continue
        post(INGEST, json=payload, headers={"X-Internal-Key": KEY}, timeout=30)
```
Run wiring: scheduled job in the product app (free weekday, off-peak), `--dry-run` first, idempotent (re-runnable). Pattern = exactly how gov/civic already feed the graph.

### 3.3 Entity profile (mirror, then generalize)
`/entity/<id>` is **net-new**. Mirror `journalist_profile()` (`routes.py:2380`) but resolve by id across `entity_type IN (person, organization)` and **group `entity_mentions` by `product`** = the footprint. Free tier = identity + which products mention it; premium (`is_subscriber()`) = counts, edges (contracts/donations/votes), co-mentions, trend. New API `GET /api/entities/<id>/footprint` (generalize the journalist-only `/profile`). **Gotcha:** `a.id::text = em.content_id` — never cast content_id→int.

### 3.4 cross_watch hub API (`platform_v2/tools/cross_watch/routes.py`, archie DB)
| Endpoint | Auth | Returns |
|---|---|---|
| `POST /signal` | bearer | `{signals_created, entities_matched[]}` (substring match headline↔entity name/alias) |
| `GET /alerts` | user (`X-User-Email`) | `{alerts[{id,entity_id,entity_name,entity_type,signal_id,signal_type,source_product,message,url,is_read,created_at}], unread}` |
| `POST /alerts/<id>/read` · `POST /follow` · `DELETE /follow/<id>` · `GET /following` | user | CRUD |
| `GET /entities` | token | `{entities[{id,name,entity_type,slug}]}` |
| `GET /procurement` · `/parliament-votes` · `/legal-rulings` · `/civic-events` | token | `{<items>[], count}` |
| `GET /search?q=&types=` | token | `{query, results{bucket:[...]}, total}` — `_VALID_TYPES={procurement,parliament_vote,legal_ruling,civic_event}` |

Consumer proxy `consumer/cross_watch.py` pass-through (mesh hub, bearer + X-User-Email, never leaks token, 5s timeout). Add a `/market` endpoint here in P3.

### 3.5 Alert layer (archie DB `shared`)
- `cross_watch_signals(id, entity_id, signal_type, source_product, source_item_id, headline, url, metadata, created_at)` UNIQUE `(entity_id,source_product,source_item_id)`.
- `cross_watch_alerts(id, user_id, entity_id, signal_id, message, url, is_read, created_at)` UNIQUE `(user_id,signal_id)`.
- `user_follows(id, user_id, entity_id, created_at)`.
- `generate_cross_watch_alerts()`: signals(last 20m) → followers → 1 alert each, ON CONFLICT DO NOTHING.
- Today: news 19,539 · gov new_tender 612 · parliament_vote 78. **Legal & Market = 0.** Add by having their adapters also `POST /api/cross-watch/signal` with `signal_type ∈ {legal_ruling, market_movement}` (both already in the CHECK), then add labels in `alert_generator._SIGNAL_TYPE_LABELS/_SOURCE_LABELS` + `routes._VALID_TYPES`.

### 3.6 Controlled vocab
- `entity_type` (ingest-accepted): **person, organization, journalist**.
- `signal_type` CHECK: new_tender, lobbying_activity, bill_passed, news_coverage, **market_movement**, **legal_ruling**, parliament_vote, civic_event.
- `chain_link_types` (12) — spine: donated_to(Money→MP), cast_vote(MP→Vote), enacted_as(Vote→Policy), awarded_to(Policy→Contract), contracts_with, market_reaction_to(Contract→Market), covered_by(→Coverage) + node markers; enrichment: lobbied_by, appointed_to, employs. `VALID_EDGE_TYPES` = the 7 spine + 3 enrichment = 10. UI renders footprint via `chain_link_types.label`.

---

## 4. Phasing

### Phase 1 — Consumer surface over the EXISTING graph  *(ships now, zero pipeline risk)*
**Value:** makes 290k+148k+533k already-linked rows visible. Legal/Market render "coverage expanding."
1. **`GET /api/entities/<id>/footprint`** (`consumer/entities.py`) — generalize the journalist `/profile`: entity by id; mentions grouped by `product` (+ counts); relationships by `relationship_type` (labeled via chain_link_types); co-mentioned entities. Premium-gated detail.
2. **`GET /entity/<int:id>`** (`routes.py`) + **`entity.html`** — mirror `journalist.html`; free = identity + products-that-mention; premium = footprint detail. XSS: textContent/autoescape only.
3. **Article teaser panel** — on the article page, list the article's tagged entities (`entity_mentions product='wtf' content_id=a.id::text`) → compact "Cross-Watch: also appears in {gov, civic, parliament…}" card → links to `/entity/<id>`.
4. **`GET /cross-watch` explorer** + `cross_watch.html` — search/browse entities by footprint (reuse `/api/cross-watch/search` + `/entities`).
5. **Nav** — "Cross-Watch" link in base.html desktop + mobile (the municipal lesson — both).
*PRs: (1a) footprint API + entity profile page, (1b) article teaser, (1c) explorer + nav. Deploy = Citadel wtf-consumer `--build`.*

### Phase 2 — Legal + Market cross-host adapters  *(fills the 2 missing datasets)*
6. **Legal adapter** (in legal-watch app): `ethics_rulings.subject_name` (person) + `scc_decisions` parties/`majority_author` + `regulations.department` (org) → mentions (content_type ethics_ruling/scc_decision) + `covered_by` edges. POST ingest, ≤5000 batches, dry-run, scheduled.
7. **Market adapter** (in market-watch app): ⚠️ weak surface — issuers are **bare tickers**. Needs a **ticker→issuer-name** resolution step (a reference dataset / SEDAR issuer list) before entities are meaningful. Emit `organization` issuers + `market_reaction_to` edges. **Decision point:** build ticker resolution now, or defer Market to "coming soon" and ship Legal only in P2.
8. Register both in `adapter_registry`; verify footprint now shows legal/market facets.
*PRs: (2a) legal adapter, (2b) market adapter (gated on ticker resolution decision).*

### Phase 3 — "This Story Just Got Real" alerts for all 5
9. Legal/Market adapters also `POST /api/cross-watch/signal` (signal_type legal_ruling / market_movement). Add labels in `alert_generator.py` + `_VALID_TYPES`/a `/market` endpoint in hub routes.
10. Ensure the article→entity `/signal` match covers the new products; surface alerts in the consumer (extend the existing badge → a follow button on `/entity/<id>` + an alerts page).
*PRs: (3a) legal/market signals + labels, (3b) consumer follow/alerts UI.*

---

## 5. Risks & Gotchas
- **Defamation / accuracy (HIGHEST):** asserting "the person in this article = this contract winner / ethics-ruling subject" is a reputational claim. Name collisions are common (402k persons). MUST: show provenance + confidence, hedge copy ("entities matching this name"), respect the dedup `confidence`/merge-review state, and set a confidence floor for *publicly* shown links. Do not auto-assert identity on common names.
- **Shared-gunicorn DoS** (KB, 2026-06-15: scheduled row-by-row entity backfills DoS'd what-the-fact.com): adapters MUST be **set-based + off-peak + batched ≤5000**; profile/footprint queries MUST be indexed (verify `entity_mentions(entity_id)`, `(product)`; add if missing) + cached.
- **Heterogeneous DBs:** no DB-layer join — adapters are per-product cross-host POST. Don't attempt cross-DB SQL.
- **Market is weak** (tickers only, entity tables empty) — likely defer depth; "coming soon" is honest.
- **Auth/paywall:** footprint detail premium-gated (like /mp, /journalist); `/api/internal/*` uses X-Internal-Key; consumer proxy never leaks the service token to the browser.
- **content_id is TEXT** — `a.id::text = em.content_id`, never cast to int.
- **Ingest cap 5000/list** — batch.
- **Two `shared` schemas** (wtf graph vs archie alert layer) — pick the right DB per query.

## 6. Open questions for the owner (before P2/P3 commit)
1. **Market depth:** build ticker→issuer resolution in P2, or ship Legal-only and defer Market to "coming soon"?
2. **Free/premium split** on the footprint (which facets are paywalled)?
3. **Public-link confidence threshold** — how conservative on asserting cross-product identity (defamation posture)?
4. **Unify or coexist:** should `/entity/<id>` eventually supersede `/mp` + `/journalist`, or stay a third profile type?

## 7. Effort summary
| Phase | Ships | Risk | Rough effort |
|---|---|---|---|
| P1 surface (over live graph) | immediate visible value | low | 1–2 sessions (3 PRs) |
| P2 Legal+Market adapters | all 5 datasets in footprint | med (market weak) | 1–2 sessions (1–2 PRs) |
| P3 alerts all-5 | follow + "got real" push | med | 1 session (2 PRs) |

**Recommended first build:** Phase 1a (`/api/entities/<id>/footprint` + `/entity/<id>` page) — highest value, lowest risk, unblocks the teaser + explorer.

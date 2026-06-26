# Competition-Enforcement → Company-Entity Linking — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Link Competition Bureau enforcement items to the 2,019 TMX listed-company nodes in the shared entity graph, conservatively and defamation-safely, so a company's cross-watch profile reflects competition exposure.

**Architecture:** A pure, unit-tested matcher (`company_match.py`) is the guardrail; a gated `competition` source in the existing legal adapter scans each enforcement headline against the live company set (fetched from a new WTF read endpoint) and emits a `competition_enforcement` **mention via a slug pointer** only on a single unambiguous match — never creating a node, never asserting a finding. The match-gate is shared so a future LLM extractor (Option 2) drops in behind it.

**Tech Stack:** Python 3.12, stdlib (`re`, `unicodedata`, `functools`) + `requests` (legal-watch); Flask + SQLAlchemy + psycopg2 (what-the-fact); SQLite (legal.db) → POST over mesh → hub `wtf` Postgres `shared` schema; pytest.

## Global Constraints

- **Two repos.** Matcher + adapter + tests → `kytran-legal-watch` repo (`/mnt/standalone/kytran-legal-watch`, branch `master`, remote `KytranKatarn/kytran-legal-watch`) = **PR B**. WTF read endpoint + these design/plan docs → `archie-platform` repo (`/mnt/archie_brain`, branch `feat/3059-competition-entity-linking`, `what-the-fact/` is a subdir) = **PR A**.
- **No DB migration** — `shared.entity_mentions` has no `content_type` CHECK; `competition_enforcement` is a free value.
- **Mesh only.** Live ingest host = `http://100.64.0.10:8106` (Citadel `wtf-ingest-api`). Companies URL = ingest URL with `/ingest`→`/companies`. Never public hostnames.
- **Mention framing is "named in a Competition Bureau {category} item"** — NEVER assert guilt/wrongdoing/finding. No relationships (frozen edge vocab, ADR-EG-001 §2).
- **Eligible categories only:** `merger`, `litigation`, `investigation`, `deceptive_marketing`. Exclude `advocacy`.
- **Pointer-only linking:** mention `entity = {"slug": <matched_slug>}` so it attaches to an existing node and can never create a duplicate.
- **Gated + manual run.** The `competition` source is NOT in the default backfill and NOT on a scheduled loop (KB #273576 — entity-graph backfills DoS'd what-the-fact.com). Run manually with `--source competition`, `--dry-run` first.
- **Deploy via rsync of specific changed files** (NOT full-tree) + `docker compose up -d --build <service>` on Citadel `root@100.64.0.10`. Never overwrite `.env`. Hub-git-≠-live-deploy is the recurring trap (KB #275549).
- **Inline HTTP in hub Bash is blocked** (`curl`/`requests.get(`/`fetch('http`). Verify the WTF endpoint via the adapter's own `--dry-run` (it fetches + logs the count) or `ctx_execute`, never inline hub HTTP.
- **F.O.R.G.E. review** via `tools.repair_bay.services.pr_diff_analyzer.review_pr(PR)` (synchronous, diff-grounded) — NOT the orphaning `commit-push-pr` Step-5 trigger (handoff cont-88 gotcha).

---

### Task 0: Branch hygiene + isolate pre-existing legal-watch changes

**Files:** none created — git inspection only.

- [ ] **Step 1: Inspect the 2 pre-existing uncommitted files in legal-watch**

Run:
```bash
git -C /mnt/standalone/kytran-legal-watch status --porcelain
git -C /mnt/standalone/kytran-legal-watch diff --stat
```
Expected: 2 changed paths. Record them. If either is `ingest/entity_graph_adapter.py` (the file Task 3 edits), read the diff in full and preserve those changes (Task 3 edits are additive). If they are unrelated WIP, do NOT include them in PR B — stash or leave them and commit only Task 1/Task 3 files explicitly by path.

- [ ] **Step 2: Create the PR B feature branch in legal-watch**

Run:
```bash
git -C /mnt/standalone/kytran-legal-watch checkout -b feat/3059-competition-entity-linking
git -C /mnt/standalone/kytran-legal-watch rev-parse --abbrev-ref HEAD
```
Expected: `feat/3059-competition-entity-linking`. (Pre-existing uncommitted changes carry over to the branch — that's fine; we commit only our files by explicit path.)

---

### Task 1: `company_match.py` — the pure matcher (the guardrail)

**Files:**
- Create: `/mnt/standalone/kytran-legal-watch/ingest/company_match.py`
- Test: `/mnt/standalone/kytran-legal-watch/tests/test_company_match.py`

**Interfaces:**
- Produces: `build_index(companies: Iterable[dict]) -> list[dict]` (each `{"slug","canonical_name","core":tuple,"eligible":bool}`); `resolve(text: str, index: list[dict]) -> dict | None` (returns `{"slug","canonical_name"}` iff exactly one eligible company core occurs as a contiguous token-run in `text`, else `None`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_company_match.py`:
```python
from ingest.company_match import build_index, resolve

INDEX = build_index([
    {"slug": "keyera-corp", "canonical_name": "Keyera Corp."},
    {"slug": "empire-company-limited", "canonical_name": "Empire Company Limited"},
    {"slug": "cae-inc", "canonical_name": "cae inc."},
    {"slug": "capital-power-corporation", "canonical_name": "Capital Power Corporation"},
    {"slug": "cineplex-inc", "canonical_name": "Cineplex Inc."},
])


def test_true_positive_keyera_possessive():
    r = resolve("Competition Bureau challenges Keyera's proposed acquisition", INDEX)
    assert r is not None and r["slug"] == "keyera-corp"


def test_safe_miss_brand_not_legal_name():
    # 'Sobeys' is a brand; the listed entity is Empire Company Limited -> no link.
    r = resolve("Competition Bureau advances investigation into Sobeys' use of property controls", INDEX)
    assert r is None


def test_distinctiveness_guard_short_single_token():
    # 'cae' core is len-3 single token -> ineligible -> safe skip even when present.
    r = resolve("the cae simulator was reviewed today", INDEX)
    assert r is None


def test_common_word_guard_needs_full_phrase():
    # 'capital' alone must NOT match Capital Power Corporation (multi-token core).
    r = resolve("a major capital investment was announced", INDEX)
    assert r is None


def test_multi_token_phrase_matches():
    r = resolve("Capital Power Corporation announced a deal", INDEX)
    assert r is not None and r["slug"] == "capital-power-corporation"


def test_ambiguous_two_matches_returns_none():
    r = resolve("Keyera and Cineplex were both named today", INDEX)
    assert r is None


def test_case_insensitive_suffix_stripped():
    r = resolve("CINEPLEX reported quarterly earnings", INDEX)
    assert r is not None and r["slug"] == "cineplex-inc"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /mnt/standalone/kytran-legal-watch && python3 -m pytest tests/test_company_match.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.company_match'`.

- [ ] **Step 3: Write the implementation**

Create `ingest/company_match.py`:
```python
"""company_match.py — resolve a free-text string to a single listed-company graph node.

Pure (no I/O, no DB, no network). The shared guardrail for Phase-2 competition->company
linking (#3059): both the v1 dictionary scan and any future LLM extractor feed candidate
text HERE, and only an unambiguous single match to a known TMX company yields a slug to
link. Brand!=legal-name (e.g. Sobeys vs Empire Company Limited) is a SAFE miss, not a
wrong link.
"""
import re
import unicodedata

# Trailing legal-form suffix tokens stripped to get a company's distinctive "core".
_SUFFIX = {"corp", "corporation", "inc", "incorporated", "ltd", "limited",
           "co", "company", "plc", "lp", "llp", "llc", "sa", "nv", "ag", "ulc"}

# Single-token cores too common to match safely on their own (tunable starter set).
_COMMON = {"capital", "power", "energy", "gold", "silver", "metals", "mining",
           "first", "north", "south", "west", "east", "royal", "canadian",
           "national", "pacific", "atlantic", "premium", "brands", "group",
           "holdings", "resources", "financial", "bank", "trust", "fund",
           "income", "growth", "global", "american", "international", "general"}

_MIN_SINGLE_TOKEN_LEN = 4


def _tokens(text):
    """NFKD-fold accents -> lowercase -> split on non-alphanumeric -> token list."""
    n = unicodedata.normalize("NFKD", text or "")
    n = "".join(c for c in n if not unicodedata.combining(c)).lower()
    return [t for t in re.split(r"[^a-z0-9]+", n) if t]


def _core(canonical_name):
    """Distinctive token core: normalized name minus TRAILING legal-form suffixes."""
    toks = _tokens(canonical_name)
    while toks and toks[-1] in _SUFFIX:
        toks.pop()
    return toks


def build_index(companies):
    """companies: iterable of {'slug','canonical_name'} -> list of match records.

    Each record: {'slug','canonical_name','core'(tuple),'eligible'(bool)}. A company with
    an empty or ineligible core is kept but never matches (safe).
    """
    index = []
    for c in companies:
        core = tuple(_core(c.get("canonical_name", "")))
        eligible = bool(core) and (
            len(core) >= 2
            or (len(core[0]) >= _MIN_SINGLE_TOKEN_LEN and core[0] not in _COMMON)
        )
        index.append({
            "slug": c.get("slug"),
            "canonical_name": c.get("canonical_name"),
            "core": core,
            "eligible": eligible,
        })
    return index


def _contains_subseq(haystack, needle):
    """True iff `needle` (token tuple) appears as a contiguous run in `haystack` (list)."""
    n = len(needle)
    if n == 0:
        return False
    for i in range(len(haystack) - n + 1):
        if tuple(haystack[i:i + n]) == needle:
            return True
    return False


def resolve(text, index):
    """Return the single {'slug','canonical_name'} whose eligible core occurs in `text`,
    or None if zero or >1 companies match (ambiguous -> never link)."""
    toks = _tokens(text)
    hits = [rec for rec in index if rec["eligible"] and _contains_subseq(toks, rec["core"])]
    if len(hits) == 1:
        return {"slug": hits[0]["slug"], "canonical_name": hits[0]["canonical_name"]}
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /mnt/standalone/kytran-legal-watch && python3 -m pytest tests/test_company_match.py -v`
Expected: PASS — 7 passed. (If pytest is unavailable, fallback: `python3 -c "import tests.test_company_match as t; [getattr(t,n)() for n in dir(t) if n.startswith('test_')]; print('ok')"`.)

- [ ] **Step 5: Commit (PR B branch)**

```bash
git -C /mnt/standalone/kytran-legal-watch add ingest/company_match.py tests/test_company_match.py
git -C /mnt/standalone/kytran-legal-watch commit -m "feat(entity-graph): pure company matcher for competition linking (#3059)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 2: WTF read endpoint — `GET /api/internal/entity-graph/companies`

**Files:**
- Modify: `/mnt/archie_brain/what-the-fact/consumer/entity_graph_routes.py` (add a route after `ingest_entity_graph`, ~line 372)

**Interfaces:**
- Produces: `GET /api/internal/entity-graph/companies` (auth `X-Internal-Key`) → `{"companies": [{"slug","canonical_name"}, ...]}` for `entity_type='organization' AND metadata->>'naics_source' IS NOT NULL`. Consumed by Task 3's `_fetch_company_index`.

> No local unit test — this is a thin Flask read over the remote hub `wtf` DB. Its real test is the live integration check in Task 4 (the adapter `--dry-run` fetches it and logs the count). Self-check the code against the existing `ingest_entity_graph` auth/engine pattern before committing.

- [ ] **Step 1: Add the endpoint**

Append to `consumer/entity_graph_routes.py` (after the `ingest_entity_graph` function, before EOF):
```python


@entity_graph_bp.route("/api/internal/entity-graph/companies", methods=["GET"])
def list_companies():
    """Read-only: the TMX-derived listed-company set (slug + canonical_name).

    Product adapters (e.g. legal-watch #3059) fetch this to match free-text targets to
    EXISTING company nodes, then emit mentions via slug pointers (never creating nodes).
    Auth: X-Internal-Key == INTERNAL_API_KEY (same as the ingest endpoint).
    """
    expected = os.environ.get("INTERNAL_API_KEY", "")
    if not expected:
        return jsonify({"error": "internal key not configured"}), 503
    if request.headers.get("X-Internal-Key", "") != expected:
        return jsonify({"error": "unauthorized"}), 401

    with _eng().connect() as conn:
        cur = conn.connection.cursor()
        cur.execute(
            "SELECT slug, canonical_name FROM shared.entities "
            "WHERE entity_type = 'organization' "
            "AND metadata->>'naics_source' IS NOT NULL "
            "ORDER BY slug"
        )
        rows = cur.fetchall()
        cur.close()
    return jsonify({"companies": [{"slug": s, "canonical_name": n} for s, n in rows]})
```

- [ ] **Step 2: Byte-compile check (catches syntax errors before deploy)**

Run: `python3 -m py_compile /mnt/archie_brain/what-the-fact/consumer/entity_graph_routes.py && echo OK`
Expected: `OK`.

- [ ] **Step 3: Commit (PR A — archie-platform feat branch)**

```bash
cd /mnt/archie_brain
git add what-the-fact/consumer/entity_graph_routes.py
git commit -m "feat(wtf): entity-graph companies read endpoint for #3059 linking

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3: `competition` source in the legal adapter (gated, matcher-wired)

**Files:**
- Modify: `/mnt/standalone/kytran-legal-watch/ingest/entity_graph_adapter.py`
- Test: `/mnt/standalone/kytran-legal-watch/tests/test_competition_source.py`

**Interfaces:**
- Consumes: `company_match.build_index`, `company_match.resolve` (Task 1); the WTF companies endpoint (Task 2).
- Produces: `build_competition_payload(rows, index) -> (entities, mentions, relationships)` with `entities==[]`, `relationships==[]`, and mentions using `entity={"slug":...}` pointers; a `--source {default,ethics,regulations,competition,all}` CLI flag (default preserves today's ethics+regulations behavior).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_competition_source.py`:
```python
from ingest import company_match
from ingest.entity_graph_adapter import build_competition_payload

INDEX = company_match.build_index([
    {"slug": "keyera-corp", "canonical_name": "Keyera Corp."},
    {"slug": "empire-company-limited", "canonical_name": "Empire Company Limited"},
])

_COLS = ("id", "title", "summary", "category", "news_url", "published_date")


def _rows(*items):
    return [dict(zip(_COLS, it)) for it in items]


def test_merger_single_match_emits_pointer_mention():
    rows = _rows((1, "Competition Bureau challenges Keyera's proposed acquisition",
                  "", "merger", "https://news/1", "2026-06-20"))
    ents, mentions, rels = build_competition_payload(rows, INDEX)
    assert ents == [] and rels == []
    assert len(mentions) == 1
    m = mentions[0]
    assert m["entity"] == {"slug": "keyera-corp"}
    assert m["content_type"] == "competition_enforcement"
    assert m["content_id"] == "https://news/1"
    assert "Keyera" in m["mention_context"]


def test_advocacy_category_excluded():
    rows = _rows((2, "Competitive markets are essential", "", "advocacy",
                  "https://news/2", "2026-06-20"))
    _, mentions, _ = build_competition_payload(rows, INDEX)
    assert mentions == []


def test_brand_not_listed_name_no_mention():
    rows = _rows((3, "investigation into Sobeys' use of property controls", "",
                  "investigation", "https://news/3", "2026-06-20"))
    _, mentions, _ = build_competition_payload(rows, INDEX)
    assert mentions == []


def test_missing_news_url_skipped():
    rows = _rows((4, "Keyera acquisition challenged", "", "merger", "", "2026-06-20"))
    _, mentions, _ = build_competition_payload(rows, INDEX)
    assert mentions == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /mnt/standalone/kytran-legal-watch && python3 -m pytest tests/test_competition_source.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_competition_payload'`.

- [ ] **Step 3: Add imports + competition constants/builder**

In `ingest/entity_graph_adapter.py`, add to the imports block (after `import unicodedata`):
```python
import functools
```
And after `import requests` add:
```python

from ingest import company_match
```

Add these constants near the other source constants (after `_REG_SELECT`, ~line 156):
```python
# ── competition_enforcement -> mentions on matched listed companies (#3059) ──────

_COMPETITION_ELIGIBLE_CATEGORIES = frozenset(
    {"merger", "litigation", "investigation", "deceptive_marketing"}
)

_COMPETITION_SELECT = """
    SELECT id, title, summary, category, news_url, published_date
    FROM competition_enforcement
    WHERE id > ?
    ORDER BY id
    LIMIT ?
"""


def build_competition_payload(rows, index):
    """competition_enforcement rows -> mentions on the SINGLE matched listed company.

    Pointer-by-slug => links to an existing TMX company node, never creates one. Advocacy
    rows, rows with no/ambiguous company match, and rows with no news_url emit nothing
    (single-match gate). Framing is 'named in a Competition Bureau item' — the verbatim
    title is the mention_context; we never assert a finding. No entities, no relationships.
    """
    mentions = []
    for raw in rows:
        r = dict(raw)
        category = (r.get("category") or "").strip()
        if category not in _COMPETITION_ELIGIBLE_CATEGORIES:
            continue
        text = f"{(r.get('title') or '')} {(r.get('summary') or '')}"
        match = company_match.resolve(text, index)
        if not match:
            continue
        news_url = (r.get("news_url") or "").strip()
        if not news_url:
            continue
        title = (r.get("title") or "").strip()
        mentions.append({
            "entity": {"slug": match["slug"]},
            "content_type": "competition_enforcement",
            "content_id": news_url,
            "mention_context": title[:280] or None,
        })
    return [], mentions, []


def _fetch_company_index(ingest_url, key):
    """GET the TMX company set from the WTF read endpoint (derived from ENTITY_INGEST_URL)
    and build the match index. Requires the internal key (the endpoint is authed)."""
    companies_url = ingest_url.replace("/ingest", "/companies")
    resp = requests.get(companies_url, headers={"X-Internal-Key": key}, timeout=60)
    resp.raise_for_status()
    companies = resp.json().get("companies") or []
    logger.info("fetched %d company records for matching", len(companies))
    return company_match.build_index(companies)
```

- [ ] **Step 4: Replace the `_SOURCES` constant + `run()` with source selection**

Replace the existing `_SOURCES = [...]` block (~lines 193-198) with:
```python
_BASE_SOURCES = {
    # SQL may be a plain string OR a callable(conn) -> str (computed per-connection).
    "ethics_rulings": ("ethics_rulings", _ethics_select_sql, build_ethics_payload),
    "regulations": ("regulations", _REG_SELECT, build_reg_payload),
}


def _select_sources(source, ingest_url, key):
    """Resolve --source to the ordered list of (name, select_sql, builder) to run.

    'default' = ethics + regulations (legacy behavior, unchanged). 'competition' needs the
    live company index (fetched once); 'all' runs everything.
    """
    if source in ("default", "ethics", "regulations"):
        if source == "ethics":
            return [_BASE_SOURCES["ethics_rulings"]]
        if source == "regulations":
            return [_BASE_SOURCES["regulations"]]
        return [_BASE_SOURCES["ethics_rulings"], _BASE_SOURCES["regulations"]]
    index = _fetch_company_index(ingest_url, key)
    comp = ("competition", _COMPETITION_SELECT,
            functools.partial(build_competition_payload, index=index))
    if source == "competition":
        return [comp]
    if source == "all":
        return [_BASE_SOURCES["ethics_rulings"], _BASE_SOURCES["regulations"], comp]
    raise ValueError(f"unknown --source {source!r}")
```

Change the `run()` signature and its source loop. Replace `def run(limit=None, dry_run=False):` ... `for source, select_sql, builder in _SOURCES:` with:
```python
def run(limit=None, dry_run=False, source="default"):
    url = os.environ.get("ENTITY_INGEST_URL")
    key = os.environ.get("INTERNAL_API_KEY", "")
    if not url:
        raise RuntimeError("ENTITY_INGEST_URL not set")
    # competition needs the key for the authed company-index GET even in dry-run.
    if (source in ("competition", "all") or not dry_run) and not key:
        raise RuntimeError("INTERNAL_API_KEY not set")

    sources = _select_sources(source, url, key)

    totals = {"rows": 0, "entities": 0, "mentions": 0, "relationships": 0,
              "batches": 0, "failed_batches": 0}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        for source_name, select_sql, builder in sources:
```
(Leave the body of the inner loop intact — it already references `source` only as the loop variable; it is now `source_name`. Update the two log lines and the `min(BATCH, remaining)` logic that reference the old `source` loop var to `source_name`.)

Within the loop's `if dry_run:` branch, add a per-mention preview so the matches can be eyeballed. Replace the existing dry-run log line with:
```python
                if dry_run:
                    logger.info(
                        "[dry-run] %s batch (id<=%s): %d rows -> %d entities, %d mentions, %d edges",
                        source_name, after_id, len(rows), len(ents), len(mentions), len(rels),
                    )
                    for m in mentions:
                        ent = m["entity"]
                        label = ent.get("slug") or ent.get("canonical_name")
                        logger.info("    match: %s  <-  %s", label, (m.get("mention_context") or "")[:90])
```

- [ ] **Step 5: Add the `--source` CLI flag**

In `main()`, after the `--dry-run` argument, add:
```python
    ap.add_argument("--source", default="default",
                    choices=["default", "ethics", "regulations", "competition", "all"],
                    help="which source(s) to run (default = ethics + regulations)")
```
And change `run(limit=args.limit, dry_run=args.dry_run)` to:
```python
    run(limit=args.limit, dry_run=args.dry_run, source=args.source)
```

- [ ] **Step 6: Run the tests + byte-compile**

Run:
```bash
cd /mnt/standalone/kytran-legal-watch && python3 -m pytest tests/test_competition_source.py tests/test_company_match.py -v && python3 -m py_compile ingest/entity_graph_adapter.py && echo COMPILE_OK
```
Expected: all tests PASS; `COMPILE_OK`.

- [ ] **Step 7: Commit (PR B branch)**

```bash
git -C /mnt/standalone/kytran-legal-watch add ingest/entity_graph_adapter.py tests/test_competition_source.py
git -C /mnt/standalone/kytran-legal-watch commit -m "feat(entity-graph): gated competition->company linking source (#3059)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 3.5: Surface competition mentions on the entity profile (visibility)

**Why:** The footprint shows non-WTF products as a bare COUNT only ("legal-watch: N"); the actual Competition Bureau headline isn't human-visible. This adds a free, defamation-safe section to the entity page. Served by **`wtf-consumer`** (port 8103), NOT wtf-ingest-api.

**Files:**
- Modify: `/mnt/archie_brain/what-the-fact/consumer/routes.py` (route `entity_profile_page`, ~line 2478)
- Modify: `/mnt/archie_brain/what-the-fact/consumer/templates/entity.html` (~after line 85)

> No local unit test — server-rendered Jinja2 over the remote DB; verified live in Task 4 by loading a matched company's `/entity/<id>`. Jinja2 `{{ }}` auto-escapes, so the external headline is XSS-safe; the `http(s)`-only guard defends the link href.

- [ ] **Step 1: Add the competition query to the route**

In `consumer/routes.py`, inside `entity_profile_page`, after the `recent = c.execute(...)` block (before the `links, co = [], []` premium block), add:
```python
        # Competition Bureau items naming this organization (free — Legal Watch link, #3059).
        # http(s)-only guard is defense-in-depth (news_url is a trusted GC canada.ca link).
        competition = []
        if ent["entity_type"] == "organization":
            competition = [
                dict(r) for r in c.execute(text(f"""
                    SELECT content_id AS news_url, mention_context AS headline
                      FROM {SH}.entity_mentions
                     WHERE entity_id=:e AND product='legal-watch'
                       AND content_type='competition_enforcement'
                     ORDER BY id DESC LIMIT 20
                """), {"e": entity_id}).mappings().all()
                if (r["news_url"] or "").startswith(("http://", "https://"))
            ]
```
And add `competition=competition,` to the `render_template("entity.html", ...)` kwargs.

- [ ] **Step 2: Add the free section to entity.html**

In `consumer/templates/entity.html`, immediately after the "Recent news coverage" section (after its closing `</div>` at line ~85, before `{% if is_subscriber %}`), add:
```html
{# ── Competition Bureau (free — Legal Watch link, #3059) ── #}
{% if competition %}
<div class="wtf-cw-section">
  <div class="wtf-cw-section-title">⚖️ Named in Competition Bureau items — via Legal Watch</div>
  {% for cit in competition %}
  <div style="display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #060d14;align-items:flex-start;">
    <div style="width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:5px;background:#a78bfa;"></div>
    <div style="flex:1;">
      <a href="{{ cit.news_url }}" target="_blank" rel="noopener noreferrer" style="font-size:12px;color:#ccc;text-decoration:none;line-height:1.4;">{{ cit.headline or 'Competition Bureau item' }}</a>
      <div style="font-size:10px;color:#4b5563;margin-top:2px;">Competition Bureau Canada · named in this item</div>
    </div>
  </div>
  {% endfor %}
  <div style="font-size:9px;color:#374151;margin-top:8px;">This {{ e.entity_type }} is named in the above Competition Bureau items surfaced by Legal Watch. Inclusion does not imply wrongdoing or any finding.</div>
</div>
{% endif %}
```

- [ ] **Step 3: Byte-compile the route + commit (PR A)**

```bash
python3 -m py_compile /mnt/archie_brain/what-the-fact/consumer/routes.py && echo OK
cd /mnt/archie_brain
git add what-the-fact/consumer/routes.py what-the-fact/consumer/templates/entity.html
git commit -m "feat(wtf): surface competition mentions on entity profile (#3059)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

### Task 4: Deploy to Citadel + live dry-run (OWNER GATE) + live ingest + verify

**Files:** none — deploy + verification only. SSH `root@100.64.0.10`, key `~/.ssh/id_ed25519`.

- [ ] **Step 1: Deploy the WTF endpoint + entity-page changes (must precede the legal dry-run)**

```bash
rsync -avz --exclude='.env' -e "ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no" \
  /mnt/archie_brain/what-the-fact/consumer/entity_graph_routes.py \
  /mnt/archie_brain/what-the-fact/consumer/routes.py \
  /mnt/archie_brain/what-the-fact/consumer/templates/entity.html \
  root@100.64.0.10:/opt/archie-products/what-the-fact/consumer/  # entity.html lands in consumer/ — fix path below
# NOTE: rsync the template to its real subdir explicitly:
rsync -avz -e "ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no" \
  /mnt/archie_brain/what-the-fact/consumer/templates/entity.html \
  root@100.64.0.10:/opt/archie-products/what-the-fact/consumer/templates/entity.html
ssh -i ~/.ssh/id_ed25519 root@100.64.0.10 \
  "cd /opt/archie-products/what-the-fact && docker compose up -d --build wtf-ingest-api wtf-consumer"
```
Expected: both `wtf-ingest-api` (serves the companies endpoint, Task 2) and `wtf-consumer` (serves the entity page, Task 3.5) rebuilt + healthy.

- [ ] **Step 2: Deploy the legal matcher + adapter**

```bash
rsync -avz --exclude='.env' -e "ssh -i ~/.ssh/id_ed25519 -o StrictHostKeyChecking=no" \
  /mnt/standalone/kytran-legal-watch/ingest/company_match.py \
  /mnt/standalone/kytran-legal-watch/ingest/entity_graph_adapter.py \
  root@100.64.0.10:/opt/archie-products/legal-watch/ingest/
ssh -i ~/.ssh/id_ed25519 root@100.64.0.10 \
  "cd /opt/archie-products/legal-watch && docker compose up -d --build"
```
Expected: legal-api rebuilt + healthy.

- [ ] **Step 3: Live DRY-RUN (verifies the WTF endpoint + previews every match) — OWNER GATE**

```bash
ssh -i ~/.ssh/id_ed25519 root@100.64.0.10 \
  "docker exec kytran_legal_api python -m ingest.entity_graph_adapter --source competition --dry-run"
```
Expected: a log line `fetched 2019 company records for matching` (confirms the WTF endpoint), then zero or more `match: <slug> <- <headline>` lines, then a totals summary. **STOP. Present the matched pairs to the owner for eyeball approval before any live POST.** If a match looks wrong (false positive), adjust `_COMMON` / `_MIN_SINGLE_TOKEN_LEN` in `company_match.py`, re-test (Task 1 Step 4), redeploy (Step 2), re-dry-run.

- [ ] **Step 4: Live ingest (only after owner approves the dry-run matches)**

```bash
ssh -i ~/.ssh/id_ed25519 root@100.64.0.10 \
  "docker exec kytran_legal_api python -m ingest.entity_graph_adapter --source competition"
```
Expected: `... ingested: {'ok': True, ... 'mentions_upserted': N ...}`, `failed_batches: 0`.

- [ ] **Step 5: Verify the mentions landed on real company nodes (hub wtf DB)**

```bash
docker exec archie_database psql -U archie -d wtf -c "
SELECT e.canonical_name, em.content_id, left(em.mention_context, 70) AS ctx
FROM shared.entity_mentions em
JOIN shared.entities e ON e.id = em.entity_id
WHERE em.product = 'legal-watch' AND em.content_type = 'competition_enforcement'
ORDER BY e.canonical_name;"
```
Expected: each row is a real TMX company (e.g. Keyera) with a verbatim Competition Bureau headline as context. Count matches the dry-run preview.

---

### Task 5: PRs (2 repos) + F.O.R.G.E. review + merge + Dev HQ close-out

**Files:** none — VCS + tracking.

- [ ] **Step 1: Push both branches**

```bash
git -C /mnt/standalone/kytran-legal-watch push --no-verify -u origin feat/3059-competition-entity-linking
cd /mnt/archie_brain && git push --no-verify -u origin feat/3059-competition-entity-linking
```

- [ ] **Step 2: Open both PRs**

```bash
cd /mnt/standalone/kytran-legal-watch && gh pr create --fill --base master \
  --title "feat(entity-graph): competition->company linking (#3059, Phase 2)"
cd /mnt/archie_brain && gh pr create --fill --base main \
  --title "feat(wtf+docs): entity-graph companies endpoint + #3059 design/plan"
```
Record both PR numbers.

- [ ] **Step 3: F.O.R.G.E. review (synchronous, diff-grounded — NOT the orphaning trigger)**

For each PR number, run (on the hub, in the archie_platform container context):
```bash
docker exec archie_platform python -c "
from tools.repair_bay.services.pr_diff_analyzer import review_pr
print(review_pr(<PR_NUMBER>))"
```
Expected: an APPROVE (or actionable findings). Address any REQUEST-CHANGES, re-review (no silent override). Note: the legal-watch PR is a different GitHub repo — confirm `review_pr` targets the right repo, or review that PR's diff manually if it is platform-repo-scoped.

- [ ] **Step 4: Merge after approval + verified live behavior**

```bash
cd /mnt/standalone/kytran-legal-watch && gh pr merge <PR_B> --squash --delete-branch
cd /mnt/archie_brain && gh pr merge <PR_A> --squash --delete-branch
```

- [ ] **Step 5: Dev HQ close-out**

```bash
# via MCP:
# complete_task(<#3059 task id>, notes="Phase 2 competition->company linking live: N mentions on TMX nodes; dry-run owner-gated.")
# log_decision(decision="Competition->company linking via conservative dictionary match + slug pointers; LLM extractor seam reserved for Option 2", context="ADR-EG-001 Phase 2")
# update_project_understanding(project #345)
# store_memory(mistake/learning if any)
```
Also delegate the KB doc-write to C.O.D.E.X. (`delegate_task(capability="documentation", reason="Document #3059 competition->company entity linking: matcher guardrails, slug-pointer linking, gated manual run")`).

---

## Self-Review

**Spec coverage:** §1 ground truth → Task 0 (data verified) + matcher tests. §2 decision (Option A now, Option B seam) → Task 1 `resolve()` reused; §8 seam documented in code docstrings. §3a matcher → Task 1. §3b adapter source → Task 3. §3c read endpoint → Task 2. §4 matcher rules → Task 1 impl + tests. §5 mention semantics/defamation → Task 3 `build_competition_payload` + Global Constraints. §6 dry-run/manual/no-schedule → Task 3 flag + Task 4 Step 3 + Constraints. §7 tests → Tasks 1 & 3. §9 files → all tasks. §10 open items → all resolved in Global Constraints (host `:8106`, derive `/companies`, no-migration, repo boundaries). No gaps.

**Placeholder scan:** No TBD/TODO; all code shown in full; all commands have expected output. Clean.

**Type consistency:** `build_index`→list[dict]; `resolve`→`{"slug","canonical_name"}|None`; `build_competition_payload`→`([], mentions, [])` consumed by the existing `run()` loop's `(ents, mentions, rels)` unpack; `_fetch_company_index`→`build_index` output → `resolve`. `--source` choices match `_select_sources` branches (default/ethics/regulations/competition/all). Consistent.

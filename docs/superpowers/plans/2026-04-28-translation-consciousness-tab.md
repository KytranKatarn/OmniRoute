# Consciousness Languages Tab — Translation Command Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the Consciousness Languages tab into a full translation command center — a live coverage matrix (9 languages × 8 domains), gap feed, R.O.S.E.T.T.A. work queue, and A.R.C.H.I.E. Dialects panel — making A.R.C.H.I.E.'s linguistic identity visible to Kytran in one place.

**Architecture:** New DB migration adds `translation_domain_registry` table. New endpoints in `language_routes.py` serve coverage matrix, gap feed, and R.O.S.E.T.T.A. queue. New `consciousness_languages.html` renders the tab. All dynamic HTML built with `escHtml()` to prevent XSS. CSS prefix `cs-lang-` throughout.

**Tech Stack:** Python/Flask, PostgreSQL, Jinja2, vanilla JS (30s poll for live queue), existing LCARS CSS system.

**Key files:**
- `platform_v2/tools/consciousness/language_routes.py`
- `platform_v2/tools/consciousness/templates/consciousness_languages.html`
- `platform_v2/static/css/consciousness.css`
- `platform_v2/database/migrations/171_translation_command_center.sql`

---

### Task 1: Database Migration

**Files:**
- Create: `platform_v2/database/migrations/171_translation_command_center.sql`

- [ ] **Step 1: Write the migration.**

```sql
-- 171_translation_command_center.sql
-- Adds translation_domain_registry table and performance indexes
-- Part of Translation Coverage System (2026-04-28)

CREATE TABLE IF NOT EXISTS translation_domain_registry (
    id               SERIAL PRIMARY KEY,
    name             VARCHAR(100) NOT NULL UNIQUE,
    display_name     VARCHAR(150) NOT NULL,
    url              VARCHAR(500) NOT NULL,
    translations_url VARCHAR(500) NOT NULL,
    deploy_method    VARCHAR(20) DEFAULT 'hostinger'
                     CHECK (deploy_method IN ('hostinger', 'vps')),
    active_languages TEXT[] DEFAULT ARRAY['en','fr','es'],
    is_active        BOOLEAN DEFAULT TRUE,
    last_audit_at    TIMESTAMP,
    created_at       TIMESTAMP DEFAULT NOW()
);

INSERT INTO translation_domain_registry
    (name, display_name, url, translations_url, deploy_method, active_languages, is_active)
VALUES
    ('kytranempowerment_com', 'kytranempowerment.com',
     'https://kytranempowerment.com',
     'https://kytranempowerment.com/data/translations.json',
     'hostinger', ARRAY['en','fr','es','pt','de','zh','ar','he','ai'], TRUE),
    ('creed_ai_org', 'creed-ai.org',
     'https://creed-ai.org',
     'https://creed-ai.org/data/translations.json',
     'hostinger', ARRAY['en','fr','es','pt','de','zh','ar','he','ai'], TRUE),
    ('kytran_gov_watch', 'Gov Watch',
     'https://gov.kytranempowerment.com',
     'https://gov.kytranempowerment.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('kytran_civic_watch', 'Civic Watch',
     'https://civic.kytranempowerment.com',
     'https://civic.kytranempowerment.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('kytran_legal_watch', 'Legal Watch',
     'https://legal.kytranempowerment.com',
     'https://legal.kytranempowerment.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('kytran_market_watch', 'Market Watch',
     'https://market.kytranempowerment.com',
     'https://market.kytranempowerment.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('what_the_fact_com', 'What The Fact (Consumer)',
     'https://what-the-fact.com',
     'https://what-the-fact.com/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE),
    ('what_the_fact_tech', 'What The Fact (Tech)',
     'https://what-the-fact.tech',
     'https://what-the-fact.tech/data/translations.json',
     'vps', ARRAY['en','fr','es','ai'], FALSE)
ON CONFLICT (name) DO NOTHING;

-- Indexes for fast domain gap queries
CREATE INDEX IF NOT EXISTS idx_translation_gaps_domain_source
    ON translation_gaps(source, status, language)
    WHERE source LIKE 'domain:%';

CREATE INDEX IF NOT EXISTS idx_translation_gaps_recent
    ON translation_gaps(created_at DESC, status);
```

- [ ] **Step 2: Run the migration.**

```bash
docker exec archie_database psql -U archie -d archie \
  -f /mnt/archie_brain/platform_v2/database/migrations/171_translation_command_center.sql
```

- [ ] **Step 3: Verify.**

```bash
docker exec archie_database psql -U archie -d archie -c \
  "SELECT name, is_active FROM translation_domain_registry ORDER BY name;"
```

Expected: 8 rows, 2 with `is_active=t`.

- [ ] **Step 4: Commit.**

```bash
git checkout -b feat/consciousness-languages-tab
git add platform_v2/database/migrations/171_translation_command_center.sql
git commit -m "feat(db): migration 171 — translation_domain_registry + gap indexes"
```

---

### Task 2: Coverage Matrix + Queue API Endpoints

**Files:**
- Modify: `platform_v2/tools/consciousness/language_routes.py`

- [ ] **Step 1: Write the failing test.**

Create `platform_v2/tests/test_consciousness_languages.py`:

```python
"""Tests for Consciousness Languages Tab.

Run: docker exec archie_platform python -m pytest \
     platform_v2/tests/test_consciousness_languages.py -v
"""
from __future__ import annotations


class TestBuildCoverageMatrix:
    def test_complete_coverage_returns_green(self):
        from tools.consciousness.language_routes import _build_coverage_matrix
        domains = [{"name": "d1", "display_name": "D1", "is_active": True,
                    "active_languages": ["en", "fr"]}]
        matrix = _build_coverage_matrix(domains, gap_counts={}, total_keys={"d1": 10})
        assert matrix["d1"]["fr"]["status"] == "green"
        assert matrix["d1"]["fr"]["coverage_pct"] == 100

    def test_5_gaps_of_20_is_yellow(self):
        from tools.consciousness.language_routes import _build_coverage_matrix
        domains = [{"name": "d1", "display_name": "D1", "is_active": True,
                    "active_languages": ["en", "fr"]}]
        matrix = _build_coverage_matrix(domains, {"d1:fr": 5}, {"d1": 20})
        assert matrix["d1"]["fr"]["coverage_pct"] == 75
        assert matrix["d1"]["fr"]["status"] == "yellow"

    def test_inactive_lang_shows_roadmap(self):
        from tools.consciousness.language_routes import _build_coverage_matrix
        domains = [{"name": "d1", "display_name": "D1", "is_active": True,
                    "active_languages": ["en", "fr"]}]
        matrix = _build_coverage_matrix(domains, {}, {"d1": 10})
        # 'de' not in active_languages
        assert matrix["d1"]["de"]["status"] == "roadmap"

    def test_en_always_source(self):
        from tools.consciousness.language_routes import _build_coverage_matrix
        domains = [{"name": "d1", "display_name": "D1", "is_active": True,
                    "active_languages": ["en", "fr"]}]
        matrix = _build_coverage_matrix(domains, {}, {"d1": 10})
        assert matrix["d1"]["en"]["status"] == "source"
        assert matrix["d1"]["en"]["coverage_pct"] == 100

    def test_zero_keys_does_not_divide_by_zero(self):
        from tools.consciousness.language_routes import _build_coverage_matrix
        domains = [{"name": "d1", "display_name": "D1", "is_active": True,
                    "active_languages": ["en", "fr"]}]
        matrix = _build_coverage_matrix(domains, {}, {"d1": 0})
        assert matrix["d1"]["fr"]["coverage_pct"] == 0
```

- [ ] **Step 2: Run — expect ImportError.**

```bash
docker exec archie_platform python -m pytest \
  platform_v2/tests/test_consciousness_languages.py -v 2>&1 | tail -5
```

Expected: `ImportError: cannot import name '_build_coverage_matrix'`

- [ ] **Step 3: Add helper and endpoints to `language_routes.py`.**

Add after existing imports:

```python
ALL_LANGS_ORDERED = ["en", "fr", "es", "pt", "de", "zh", "ar", "he", "ai"]


def _build_coverage_matrix(
    domains: list[dict],
    gap_counts: dict[str, int],
    total_keys: dict[str, int],
) -> dict:
    """Return {domain_name: {lang: {status, coverage_pct, gap_count}}}."""
    matrix: dict = {}
    for domain in domains:
        name = domain["name"]
        active_langs = domain.get("active_languages") or []
        total = total_keys.get(name, 0)
        matrix[name] = {}
        for lang in ALL_LANGS_ORDERED:
            if lang not in active_langs:
                matrix[name][lang] = {"status": "roadmap", "coverage_pct": None, "gap_count": None}
                continue
            if lang == "en":
                matrix[name][lang] = {"status": "source", "coverage_pct": 100, "gap_count": 0}
                continue
            gaps = gap_counts.get(f"{name}:{lang}", 0)
            pct = round(((total - gaps) / total) * 100) if total > 0 else 0
            status = "green" if pct >= 95 else ("yellow" if pct >= 70 else "red")
            matrix[name][lang] = {"status": status, "coverage_pct": pct, "gap_count": gaps}
    return matrix
```

Add three routes inside `register_language_routes(bp, admin_required)`:

```python
    @bp.route("/api/translations/coverage-matrix")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_coverage_matrix():
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    "SELECT name, display_name, is_active, active_languages, last_audit_at "
                    "FROM translation_domain_registry ORDER BY is_active DESC, name"
                )
                domains = [dict(r) for r in cur.fetchall()]
                cur.execute(
                    """SELECT REPLACE(source,'domain:','') AS domain_name, language,
                              COUNT(*) AS gap_count
                       FROM translation_gaps
                       WHERE status IN ('open','routed') AND source LIKE 'domain:%%'
                       GROUP BY domain_name, language"""
                )
                gap_counts = {
                    f"{r['domain_name']}:{r['language']}": r["gap_count"]
                    for r in cur.fetchall()
                }
                cur.execute(
                    """SELECT REPLACE(source,'domain:','') AS domain_name,
                              COUNT(DISTINCT key) AS total_keys
                       FROM translation_gaps WHERE source LIKE 'domain:%%'
                       GROUP BY domain_name"""
                )
                total_keys = {r["domain_name"]: r["total_keys"] for r in cur.fetchall()}

            matrix = _build_coverage_matrix(domains, gap_counts, total_keys)
            return jsonify({
                "success": True,
                "matrix": matrix,
                "domains": domains,
                "summary": {
                    "total_open_gaps": sum(gap_counts.values()),
                    "domains_active": sum(1 for d in domains if d["is_active"]),
                    "domains_total": len(domains),
                },
            })
        except Exception as e:
            logger.error(f"Coverage matrix error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/gap-feed")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def translation_gap_feed():
        domain = request.args.get("domain", "")
        language = request.args.get("language", "")
        gap_type = request.args.get("gap_type", "")
        page = max(1, int(request.args.get("page", 1)))
        per_page = min(100, max(1, int(request.args.get("per_page", 50))))
        offset = (page - 1) * per_page
        try:
            conditions = ["status IN ('open','routed')", "source LIKE 'domain:%%'"]
            params: list = []
            if domain:
                conditions.append("source = %s")
                params.append(f"domain:{domain}")
            if language:
                conditions.append("language = %s")
                params.append(language)
            if gap_type:
                conditions.append("gap_type = %s")
                params.append(gap_type)
            where = " AND ".join(conditions)
            with get_db_cursor() as (_conn, cur):
                cur.execute(f"SELECT COUNT(*) AS n FROM translation_gaps WHERE {where}", params)
                total = cur.fetchone()["n"]
                cur.execute(
                    f"SELECT id, source, gap_type, language, key, snippet, "
                    f"status, task_id, created_at "
                    f"FROM translation_gaps WHERE {where} "
                    f"ORDER BY created_at DESC LIMIT %s OFFSET %s",
                    params + [per_page, offset],
                )
                gaps = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "gaps": gaps, "total": total,
                            "page": page, "per_page": per_page})
        except Exception as e:
            logger.error(f"Gap feed error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/rosetta-queue")
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def rosetta_work_queue():
        try:
            with get_db_cursor() as (_conn, cur):
                cur.execute(
                    """SELECT id, title, status, priority, created_at, completed_at
                       FROM unified_tasks
                       WHERE capability IN ('translate','semantic_describe')
                         AND status IN ('pending','in_progress','completed')
                       ORDER BY
                         CASE status WHEN 'in_progress' THEN 0
                                     WHEN 'pending' THEN 1 ELSE 2 END,
                         created_at DESC
                       LIMIT 30"""
                )
                tasks = [dict(r) for r in cur.fetchall()]
            return jsonify({"success": True, "tasks": tasks})
        except Exception as e:
            logger.error(f"Rosetta queue error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @bp.route("/api/translations/dispatch-gap", methods=["POST"])
    @login_required
    @require_permission(Permission.ADMIN_ACCESS)
    def dispatch_translation_gap():
        from services.delegation_service import delegate_task
        body = request.get_json(silent=True) or {}
        gap_id = body.get("gap_id")
        domain = body.get("domain", "")
        language = body.get("language", "")
        key = body.get("key", "")
        if not all([gap_id, language, key]):
            return jsonify({"success": False, "error": "gap_id, language, key required"}), 400
        try:
            cap = "semantic_describe" if language == "ai" else "translate"
            result = delegate_task(
                capability=cap,
                reason=f"Manual dispatch: key='{key}' lang='{language}' domain:{domain}",
                args={"language": language, "keys": [key],
                      "sources": [f"domain:{domain}"], "gap_ids": [gap_id]},
                delegation_source="user_cli",
                requested_by="consciousness_languages_tab",
                priority=7,
            )
            if result.get("success"):
                with get_db_cursor(commit=True) as (_conn, cur):
                    cur.execute(
                        "UPDATE translation_gaps SET status='routed', task_id=%s WHERE id=%s",
                        (result.get("task_id"), gap_id),
                    )
            return jsonify(result)
        except Exception as e:
            logger.error(f"dispatch-gap error: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
```

- [ ] **Step 4: Run tests — all should pass.**

```bash
docker exec archie_platform python -m pytest \
  platform_v2/tests/test_consciousness_languages.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit.**

```bash
git add platform_v2/tools/consciousness/language_routes.py \
        platform_v2/tests/test_consciousness_languages.py
git commit -m "feat(consciousness): coverage-matrix, gap-feed, rosetta-queue, dispatch-gap endpoints"
```

---

### Task 3: Languages Tab HTML + CSS

**Files:**
- Create: `platform_v2/tools/consciousness/templates/consciousness_languages.html`
- Modify: `platform_v2/static/css/consciousness.css`

All dynamic HTML is built using `escHtml()` to prevent XSS — no raw API data ever written directly into innerHTML.

- [ ] **Step 1: Check consciousness.css size.**

```bash
wc -l /mnt/archie_brain/platform_v2/static/css/consciousness.css
```

If over 800 lines, create `consciousness-languages.css` separately and link it from the template.

- [ ] **Step 2: Create `consciousness_languages.html`.**

```html
{# consciousness_languages.html — Translation Command Center #}
<div class="cs-lang-container">

  {# Stats Bar #}
  <div class="cs-lang-stats-bar">
    <div class="cs-lang-stat">
      <span class="cs-lang-stat-value" id="clang-total-gaps">—</span>
      <span class="cs-lang-stat-label">Open Gaps</span>
    </div>
    <div class="cs-lang-stat">
      <span class="cs-lang-stat-value" id="clang-domains-active">—</span>
      <span class="cs-lang-stat-label">Domains Active</span>
    </div>
    <div class="cs-lang-stat">
      <span class="cs-lang-stat-value" id="clang-queue-count">—</span>
      <span class="cs-lang-stat-label">R.O.S.E.T.T.A. Tasks</span>
    </div>
  </div>

  {# Coverage Matrix #}
  <div class="cs-lang-section">
    <h2 class="cs-lang-section-title">Coverage Matrix</h2>
    <p class="cs-lang-section-sub">9 languages × 8 domains — click any cell to filter the gap feed</p>
    <div id="clang-matrix" class="cs-lang-loading">Loading…</div>
    <div class="cs-lang-legend">
      <span class="cs-lang-legend-green">■ 95%+</span>
      <span class="cs-lang-legend-yellow">■ 70–94%</span>
      <span class="cs-lang-legend-red">■ &lt;70%</span>
      <span class="cs-lang-legend-grey">■ Roadmap</span>
    </div>
  </div>

  {# Gap Feed #}
  <div class="cs-lang-section">
    <h2 class="cs-lang-section-title">Gap Feed</h2>
    <div class="cs-lang-filters">
      <select id="clang-fdomain" class="cs-lang-select">
        <option value="">All Domains</option>
      </select>
      <select id="clang-flang" class="cs-lang-select">
        <option value="">All Languages</option>
        <option value="fr">French</option>
        <option value="es">Spanish</option>
        <option value="pt">Portuguese</option>
        <option value="de">German</option>
        <option value="zh">Chinese</option>
        <option value="ar">Arabic</option>
        <option value="he">Hebrew</option>
        <option value="ai">AI Semantic</option>
      </select>
      <select id="clang-ftype" class="cs-lang-select">
        <option value="">All Types</option>
        <option value="missing">Missing</option>
        <option value="quality_suspect">Quality Suspect</option>
      </select>
      <button class="cs-lang-btn" id="clang-filter-btn">Filter</button>
    </div>
    <div id="clang-gaps" class="cs-lang-loading">Loading…</div>
  </div>

  {# R.O.S.E.T.T.A. Queue #}
  <div class="cs-lang-section">
    <h2 class="cs-lang-section-title">R.O.S.E.T.T.A. Work Queue</h2>
    <div id="clang-queue" class="cs-lang-loading">Loading…</div>
  </div>

  {# Dialects Panel #}
  <div class="cs-lang-section">
    <h2 class="cs-lang-section-title">A.R.C.H.I.E. Dialects</h2>
    <p class="cs-lang-section-sub">
      The languages A.R.C.H.I.E. speaks — 8 human dialects + 1 machine dialect.
    </p>
    <div class="cs-lang-dialects-grid" id="clang-dialects">
      <!-- Populated by JS below to keep template logic simple -->
    </div>
  </div>

</div>

<script>
(function () {
  'use strict';

  // ── Safe DOM helpers ───────────────────────────────────────────────────
  function escHtml(str) {
    const d = document.createElement('div');
    d.textContent = String(str == null ? '' : str);
    return d.innerHTML;
  }

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([k, v]) => {
      if (k === 'class') node.className = v;
      else if (k === 'title') node.title = v;
      else if (k.startsWith('data-')) node.dataset[k.slice(5)] = v;
      else node.setAttribute(k, v);
    });
    (children || []).forEach(c => {
      if (typeof c === 'string') node.appendChild(document.createTextNode(c));
      else if (c) node.appendChild(c);
    });
    return node;
  }

  function setText(id, text) {
    const node = document.getElementById(id);
    if (node) node.textContent = text;
  }

  // ── Constants ──────────────────────────────────────────────────────────
  const LANG_NAMES = {
    en:'English', fr:'Français', es:'Español', pt:'Português',
    de:'Deutsch', zh:'中文', ar:'العربية', he:'עברית', ai:'AI'
  };
  const ALL_LANGS = ['en','fr','es','pt','de','zh','ar','he','ai'];

  const DIALECTS = [
    ['en','English','Source language — all content originates in English','','active'],
    ['fr','Français','Québécois register — Canadian bilingual standard','','active'],
    ['es','Español','Latin American Spanish','','active'],
    ['pt','Português','Brazilian Portuguese','','roadmap'],
    ['de','Deutsch','Standard German','','roadmap'],
    ['zh','中文','Simplified Chinese (Mandarin)','','roadmap'],
    ['ar','العربية','Modern Standard Arabic','RTL','roadmap'],
    ['he','עברית','Hebrew','RTL','roadmap'],
    ['ai','AI Semantic',
     'Machine-readable intent layer — structured JSON descriptions for agent consumption.',
     '','active'],
  ];

  // ── Coverage Matrix ────────────────────────────────────────────────────
  async function loadMatrix() {
    const wrapper = document.getElementById('clang-matrix');
    wrapper.className = 'cs-lang-loading';
    wrapper.textContent = 'Loading…';
    try {
      const data = await fetch('/tools/consciousness/api/translations/coverage-matrix')
                         .then(r => r.json());
      if (!data.success) throw new Error(data.error);

      setText('clang-total-gaps', data.summary.total_open_gaps.toLocaleString());
      setText('clang-domains-active',
              data.summary.domains_active + '/' + data.summary.domains_total);

      // Populate domain filter
      const sel = document.getElementById('clang-fdomain');
      data.domains.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.name;
        opt.textContent = d.display_name;
        sel.appendChild(opt);
      });

      // Build matrix using DOM (safe — no innerHTML of user data)
      const table = el('table', {'class': 'cs-lang-matrix'});
      const thead = el('thead');
      const hrow = el('tr', {}, [el('th', {}, ['Domain'])]);
      ALL_LANGS.forEach(lang => {
        hrow.appendChild(el('th', {'class': 'cs-lang-matrix-lang'},
                             [LANG_NAMES[lang] || lang]));
      });
      thead.appendChild(hrow);
      table.appendChild(thead);

      const tbody = el('tbody');
      data.domains.forEach(domain => {
        const row = data.matrix[domain.name] || {};
        const tr = el('tr', {'class': domain.is_active ? '' : 'cs-lang-inactive'});
        const nameTd = el('td', {'class': 'cs-lang-domain-name'},
                          [domain.display_name]);
        if (!domain.is_active) {
          nameTd.appendChild(el('span', {'class': 'cs-lang-coming-soon'}, ['Coming Soon']));
        }
        tr.appendChild(nameTd);

        ALL_LANGS.forEach(lang => {
          const cell = row[lang] || {status: 'roadmap', coverage_pct: null, gap_count: null};
          const pctText = cell.coverage_pct !== null ? cell.coverage_pct + '%' : '—';
          const titleText = cell.gap_count !== null ? cell.gap_count + ' gaps' : cell.status;
          const td = el('td', {
            'class': 'cs-lang-cell cs-lang-cell-' + cell.status,
            'title': titleText,
          }, [pctText]);
          if (cell.status !== 'roadmap' && cell.status !== 'source' && domain.is_active) {
            td.style.cursor = 'pointer';
            td.addEventListener('click', () => drillDown(domain.name, lang));
          }
          tr.appendChild(td);
        });
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);

      wrapper.className = '';
      wrapper.innerHTML = '';
      wrapper.appendChild(table);
    } catch (e) {
      wrapper.className = 'cs-lang-error';
      wrapper.textContent = 'Failed to load matrix: ' + e.message;
    }
  }

  // ── Gap Feed ───────────────────────────────────────────────────────────
  async function loadGaps() {
    const domain = document.getElementById('clang-fdomain').value;
    const lang = document.getElementById('clang-flang').value;
    const type = document.getElementById('clang-ftype').value;
    const params = new URLSearchParams();
    if (domain) params.set('domain', domain);
    if (lang) params.set('language', lang);
    if (type) params.set('gap_type', type);

    const wrapper = document.getElementById('clang-gaps');
    wrapper.className = 'cs-lang-loading';
    wrapper.textContent = 'Loading…';

    try {
      const data = await fetch('/tools/consciousness/api/translations/gap-feed?' + params)
                         .then(r => r.json());
      if (!data.success) throw new Error(data.error);

      wrapper.className = '';
      wrapper.innerHTML = '';

      if (data.gaps.length === 0) {
        wrapper.className = 'cs-lang-empty';
        wrapper.textContent = '✅ No gaps found.';
        return;
      }

      const countEl = el('div', {'class': 'cs-lang-gap-count'},
                         [data.total + ' gaps total']);
      wrapper.appendChild(countEl);

      const table = el('table', {'class': 'cs-lang-gap-table'});
      const thead = el('thead', {}, [
        el('tr', {}, ['Domain','Key','Language','Type','Snippet','Action'].map(
          h => el('th', {}, [h])
        ))
      ]);
      table.appendChild(thead);
      const tbody = el('tbody');

      data.gaps.forEach(g => {
        const domainName = (g.source || '').replace('domain:', '');
        const tr = el('tr', {'class': 'cs-lang-gap-row cs-lang-gap-' + g.gap_type});
        tr.appendChild(el('td', {}, [domainName]));
        tr.appendChild(el('td', {'class': 'cs-lang-key'}, [g.key || '']));
        tr.appendChild(el('td', {}, [LANG_NAMES[g.language] || g.language || '']));
        tr.appendChild(el('td', {}, [
          el('span', {'class': 'cs-lang-gap-type-badge'}, [g.gap_type || ''])
        ]));
        const snippet = g.snippet ? g.snippet.substring(0, 60) : '—';
        tr.appendChild(el('td', {'class': 'cs-lang-snippet'}, [snippet]));

        const btn = el('button', {'class': 'cs-lang-btn cs-lang-btn-sm'}, ['Translate']);
        btn.addEventListener('click', () => dispatchGap(g.id, domainName, g.language, g.key));
        tr.appendChild(el('td', {}, [btn]));
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      wrapper.appendChild(table);
    } catch (e) {
      wrapper.className = 'cs-lang-error';
      wrapper.textContent = 'Error: ' + e.message;
    }
  }

  function drillDown(domain, lang) {
    document.getElementById('clang-fdomain').value = domain;
    document.getElementById('clang-flang').value = lang;
    loadGaps();
    document.getElementById('clang-gaps').scrollIntoView({behavior: 'smooth'});
  }

  // ── R.O.S.E.T.T.A. Queue ──────────────────────────────────────────────
  async function loadQueue() {
    const wrapper = document.getElementById('clang-queue');
    try {
      const data = await fetch('/tools/consciousness/api/translations/rosetta-queue')
                         .then(r => r.json());
      if (!data.success) throw new Error(data.error);

      const pending = data.tasks.filter(t =>
        t.status === 'in_progress' || t.status === 'pending').length;
      setText('clang-queue-count', pending);

      wrapper.className = '';
      wrapper.innerHTML = '';

      if (data.tasks.length === 0) {
        wrapper.className = 'cs-lang-empty';
        wrapper.textContent = 'Queue empty.';
        return;
      }

      const list = el('div', {'class': 'cs-lang-queue-list'});
      data.tasks.forEach(t => {
        const statusClass = t.status === 'in_progress' ? 'cs-lang-task-active' :
                            t.status === 'pending'     ? 'cs-lang-task-pending' :
                                                         'cs-lang-task-done';
        const item = el('div', {'class': 'cs-lang-queue-item ' + statusClass}, [
          el('span', {'class': 'cs-lang-task-status'}, [t.status]),
          el('span', {'class': 'cs-lang-task-title'}, [t.title || '']),
          el('span', {'class': 'cs-lang-task-date'},
             [new Date(t.created_at).toLocaleDateString()]),
        ]);
        list.appendChild(item);
      });
      wrapper.appendChild(list);
    } catch (e) {
      wrapper.className = 'cs-lang-error';
      wrapper.textContent = 'Queue error: ' + e.message;
    }
  }

  // ── Dispatch single gap ────────────────────────────────────────────────
  async function dispatchGap(gapId, domain, language, key) {
    if (!confirm('Dispatch translate task for key "' + key + '" (' + language + ')?')) return;
    try {
      const data = await fetch('/tools/consciousness/api/translations/dispatch-gap', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({gap_id: gapId, domain, language, key})
      }).then(r => r.json());
      if (data.success) {
        alert('Task dispatched → task_id=' + data.task_id);
        loadGaps();
        loadQueue();
      } else {
        alert('Error: ' + (data.error || 'unknown'));
      }
    } catch (e) {
      alert('Network error: ' + e.message);
    }
  }

  // ── Dialects Panel ─────────────────────────────────────────────────────
  function renderDialects() {
    const grid = document.getElementById('clang-dialects');
    if (!grid) return;
    DIALECTS.forEach(([code, name, note, badge, phase]) => {
      const card = el('div', {'class': 'cs-lang-dialect-card cs-lang-dialect-' + phase});
      card.appendChild(el('div', {'class': 'cs-lang-dialect-code'}, [code.toUpperCase()]));
      card.appendChild(el('div', {'class': 'cs-lang-dialect-name'}, [name]));
      card.appendChild(el('div', {'class': 'cs-lang-dialect-note'}, [note]));
      if (badge) card.appendChild(el('span', {'class': 'cs-lang-dialect-badge'}, [badge]));
      if (phase === 'roadmap') {
        card.appendChild(el('span', {'class': 'cs-lang-dialect-badge cs-lang-roadmap'}, ['Roadmap']));
      }
      grid.appendChild(card);
    });
  }

  // ── Init ───────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', function () {
    loadMatrix();
    loadGaps();
    loadQueue();
    renderDialects();
    document.getElementById('clang-filter-btn')
            .addEventListener('click', loadGaps);
    setInterval(loadQueue, 30000);
  });
}());
</script>
```

- [ ] **Step 3: Append CSS to consciousness.css.**

```css
/* ── Consciousness Languages Tab (cs-lang-) ────────────────────────── */
.cs-lang-container{padding:1.5rem;max-width:1400px;margin:0 auto}
.cs-lang-stats-bar{display:flex;gap:2rem;padding:1rem 1.5rem;background:var(--archie-surface,#0d1117);border:1px solid var(--archie-border,#30363d);border-radius:8px;margin-bottom:2rem;flex-wrap:wrap}
.cs-lang-stat{display:flex;flex-direction:column;align-items:center}
.cs-lang-stat-value{font-size:2rem;font-weight:700;color:#8b5cf6;font-family:'Orbitron',sans-serif}
.cs-lang-stat-label{font-size:.75rem;color:var(--archie-text-muted,#8b949e);text-transform:uppercase}
.cs-lang-section{margin-bottom:2.5rem}
.cs-lang-section-title{font-family:'Orbitron',sans-serif;color:#8b5cf6;font-size:1.1rem;margin-bottom:.25rem}
.cs-lang-section-sub{color:var(--archie-text-muted,#8b949e);font-size:.85rem;margin-bottom:1rem}
.cs-lang-loading{color:#8b949e;padding:1rem;font-size:.9rem}
.cs-lang-error{color:#f87171;padding:1rem;font-size:.9rem}
.cs-lang-empty{color:#4ade80;padding:1rem;font-size:.9rem}
/* Matrix */
.cs-lang-matrix{width:100%;border-collapse:collapse;font-size:.8rem}
.cs-lang-matrix th{background:#161b22;padding:.5rem;border:1px solid #30363d;text-align:center}
.cs-lang-matrix-lang{writing-mode:vertical-rl;transform:rotate(180deg);font-size:.7rem;min-width:40px}
.cs-lang-domain-name{font-weight:600;padding:.5rem;white-space:nowrap}
.cs-lang-cell{text-align:center;padding:.4rem .2rem;border:1px solid #30363d;font-size:.75rem;transition:opacity .15s}
.cs-lang-cell:hover{opacity:.8}
.cs-lang-cell-green{background:rgba(34,197,94,.2);color:#4ade80}
.cs-lang-cell-yellow{background:rgba(234,179,8,.2);color:#facc15}
.cs-lang-cell-red{background:rgba(239,68,68,.2);color:#f87171}
.cs-lang-cell-roadmap{background:#161b22;color:#484f58}
.cs-lang-cell-source{background:rgba(139,92,246,.15);color:#a78bfa}
.cs-lang-inactive{opacity:.5}
.cs-lang-coming-soon{font-size:.65rem;background:#30363d;padding:.1rem .3rem;border-radius:3px;margin-left:.4rem}
.cs-lang-legend{display:flex;gap:1rem;margin-top:.75rem;flex-wrap:wrap;font-size:.75rem}
.cs-lang-legend-green{color:#4ade80}.cs-lang-legend-yellow{color:#facc15}
.cs-lang-legend-red{color:#f87171}.cs-lang-legend-grey{color:#484f58}
/* Gap feed */
.cs-lang-filters{display:flex;gap:.75rem;margin-bottom:1rem;flex-wrap:wrap}
.cs-lang-select{background:#161b22;border:1px solid #30363d;color:#e6edf3;padding:.4rem .75rem;border-radius:4px;font-size:.85rem}
.cs-lang-btn{background:#8b5cf6;color:#fff;border:none;padding:.4rem 1rem;border-radius:4px;cursor:pointer;font-size:.85rem}
.cs-lang-btn:hover{background:#7c3aed}
.cs-lang-btn-sm{padding:.2rem .6rem;font-size:.75rem}
.cs-lang-gap-table{width:100%;border-collapse:collapse;font-size:.8rem}
.cs-lang-gap-table th,.cs-lang-gap-table td{padding:.4rem .6rem;border:1px solid #30363d;text-align:left}
.cs-lang-gap-table th{background:#161b22;color:#8b5cf6}
.cs-lang-key{font-family:'IBM Plex Mono',monospace;font-size:.75rem}
.cs-lang-snippet{font-family:'IBM Plex Mono',monospace;font-size:.7rem;color:#8b949e}
.cs-lang-gap-type-badge{padding:.1rem .4rem;border-radius:3px;font-size:.7rem}
.cs-lang-gap-missing .cs-lang-gap-type-badge{background:rgba(239,68,68,.2);color:#f87171}
.cs-lang-gap-quality_suspect .cs-lang-gap-type-badge{background:rgba(234,179,8,.2);color:#facc15}
.cs-lang-gap-count{font-size:.8rem;color:#8b949e;margin-bottom:.5rem}
/* Queue */
.cs-lang-queue-list{display:flex;flex-direction:column;gap:.5rem}
.cs-lang-queue-item{display:flex;align-items:center;gap:1rem;padding:.6rem 1rem;border-radius:4px;border:1px solid #30363d;font-size:.85rem}
.cs-lang-task-active{border-color:#8b5cf6;background:rgba(139,92,246,.1)}
.cs-lang-task-pending{border-color:#30363d}
.cs-lang-task-done{opacity:.5}
.cs-lang-task-status{font-size:.7rem;font-weight:700;text-transform:uppercase;width:80px}
.cs-lang-task-active .cs-lang-task-status{color:#8b5cf6}
.cs-lang-task-pending .cs-lang-task-status{color:#8b949e}
.cs-lang-task-done .cs-lang-task-status{color:#4ade80}
.cs-lang-task-title{flex:1}
.cs-lang-task-date{font-size:.75rem;color:#8b949e}
/* Dialects */
.cs-lang-dialects-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:1rem;margin-top:1rem}
.cs-lang-dialect-card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem;position:relative}
.cs-lang-dialect-active{border-color:#8b5cf6}
.cs-lang-dialect-roadmap{opacity:.6}
.cs-lang-dialect-code{font-family:'Orbitron',sans-serif;font-size:1.4rem;color:#8b5cf6;font-weight:700}
.cs-lang-dialect-name{font-weight:600;margin:.25rem 0;color:#e6edf3}
.cs-lang-dialect-note{font-size:.8rem;color:#8b949e;line-height:1.4}
.cs-lang-dialect-badge{position:absolute;top:.5rem;right:.5rem;font-size:.65rem;background:#30363d;padding:.1rem .4rem;border-radius:3px;color:#8b949e}
.cs-lang-roadmap{background:rgba(139,92,246,.2);color:#a78bfa}
```

- [ ] **Step 4: Commit.**

```bash
git add \
  platform_v2/tools/consciousness/templates/consciousness_languages.html \
  platform_v2/static/css/consciousness.css
git commit -m "feat(consciousness): Languages tab HTML + css — XSS-safe DOM building throughout"
```

---

### Task 4: Wire Tab into Consciousness Navigation

**Files:**
- Modify: `platform_v2/tools/consciousness/templates/consciousness_dashboard.html`

- [ ] **Step 1: Find where tabs are defined.**

```bash
grep -n "tab\|GitHub\|Knowledge\|Languages" \
  /mnt/archie_brain/platform_v2/tools/consciousness/templates/consciousness_dashboard.html \
  | head -20
```

- [ ] **Step 2: Add Languages tab button and content panel.**

Find the tab buttons block and add:

```html
<button class="cs-tab-btn" data-tab="languages"
        onclick="switchConsciousnessTab('languages')">
  Languages
</button>
```

Find the tab content panels block and add:

```html
<div id="tab-languages" class="cs-tab-content" style="display:none;">
  {% include "consciousness_languages.html" %}
</div>
```

- [ ] **Step 3: Restart and navigate to the tab.**

```bash
docker compose restart archie_platform
```

Open http://192.168.1.200:3000/tools/consciousness → click "Languages" tab.

Verify:
- Coverage matrix renders (8 domains × 9 languages, colour-coded)
- Gap feed shows filterable table
- R.O.S.E.T.T.A. queue shows tasks
- Dialects grid shows 9 cards
- Clicking a matrix cell filters the gap feed

- [ ] **Step 4: Commit, push, PR.**

```bash
git add platform_v2/tools/consciousness/templates/consciousness_dashboard.html
git commit -m "feat(consciousness): wire Languages tab into Consciousness nav"
git push origin feat/consciousness-languages-tab

gh pr create \
  --title "feat(consciousness): Languages Tab — Translation Command Center" \
  --body "## What ships
- Migration 171: translation_domain_registry (8 domains), gap performance indexes
- 4 new API endpoints: coverage-matrix, gap-feed, rosetta-queue, dispatch-gap
- consciousness_languages.html: XSS-safe DOM building (escHtml + DOM API, no raw innerHTML)
- Coverage heatmap (9×8 matrix), gap feed with filters, R.O.S.E.T.T.A. queue
- A.R.C.H.I.E. Dialects panel: 9 language cards (8 human + AI semantic)
- Inline Translate button dispatches gaps to R.O.S.E.T.T.A. via Department HQ

## Test
\`\`\`
docker exec archie_platform python -m pytest platform_v2/tests/test_consciousness_languages.py -v
\`\`\`
Navigate to http://192.168.1.200:3000/tools/consciousness#languages" \
  --base main
```

---

## Success Criteria

- Languages tab loads without errors
- Coverage matrix shows 8 domains × 9 languages with colour coding
- Clicking a red cell filters the gap feed to that domain + language
- R.O.S.E.T.T.A. queue live-polls every 30s
- Inline Translate button dispatches task through Department HQ + C.R.E.E.D.
- A.R.C.H.I.E. Dialects panel shows all 9 language cards
- `translation_domain_registry` has 8 rows (2 active, 6 coming soon)
- All 5 tests pass in `test_consciousness_languages.py`

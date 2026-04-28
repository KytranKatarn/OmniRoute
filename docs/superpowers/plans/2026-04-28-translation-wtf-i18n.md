# What The Fact i18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add EN/FR/ES + AI semantic translation to both What The Fact apps (consumer at what-the-fact.com and tech at what-the-fact.tech), translating UI chrome only (not article body text), then deploy to VPS and enable P.R.O.B.E. audit coverage.

**Architecture:** Same client-side `data-i18n` pattern as Watch products. Each app gets its own `static/data/translations.json` and `static/js/i18n.js`. Article body content stays in source language — only nav, headers, labels, filters, and UI controls are translated. R.O.S.E.T.T.A. fills FR/ES/ai via Department HQ dispatch.

**Tech Stack:** JavaScript (i18n.js), HTML `data-i18n` attrs, Python Flask Jinja2, Docker VPS deploy.

**Source paths:**
- Consumer app: `/mnt/archie_brain/what-the-fact/consumer/` (confirm exact path below)
- Tech app: `/mnt/archie_brain/what-the-fact/tech/` (confirm exact path below)

---

### Task 1: Confirm WTF App Paths and Template Structure

**Files:** Read-only audit

- [ ] **Step 1: Find exact WTF source paths.**

```bash
ls /mnt/archie_brain/what-the-fact/ 2>/dev/null || echo "not at this path"
find /mnt/archie_brain -maxdepth 3 -name "wtf*" -o -name "what-the-fact*" 2>/dev/null | head -20
```

- [ ] **Step 2: List templates in both apps.**

```bash
# Adjust paths based on Step 1 output
find /mnt/archie_brain/what-the-fact -name "*.html" 2>/dev/null
```

Expected: `base.html`, `index.html`, `article.html` for consumer; `base.html`, `index.html`, `dashboard.html`, `transparency.html` for tech.

- [ ] **Step 3: Count translatable strings per app.**

```bash
python3 -c "
import re
from pathlib import Path

wtf_path = Path('/mnt/archie_brain/what-the-fact')
for app in ['consumer', 'tech']:
    tpl_dir = wtf_path / app / 'templates'
    if not tpl_dir.exists():
        # try alternate structure
        tpl_dir = wtf_path / f'wtf-{app}' / 'templates'
    if not tpl_dir.exists():
        print(f'{app}: templates not found, check path')
        continue
    count = 0
    for f in tpl_dir.rglob('*.html'):
        matches = re.findall(r'>([A-Z][^<]{2,60})<', f.read_text())
        count += len([m for m in matches if not m.strip().startswith('{%')])
    print(f'{app}: ~{count} translatable strings')
"
```

---

### Task 2: Create i18n.js for Both WTF Apps

**Files:**
- Create: `consumer/static/js/i18n.js`
- Create: `tech/static/js/i18n.js`

Adjust paths based on Task 1 findings.

- [ ] **Step 1: Create consumer app i18n.js.**

Create at `<consumer_app_root>/static/js/i18n.js`:

```javascript
/**
 * What The Fact — Consumer i18n engine.
 * UI chrome only — article body text is NOT translated.
 */
const I18n = (() => {
    const STORAGE_KEY = 'wtf-lang';
    const DEFAULT_LANG = 'en';
    const RTL_LANGS = ['ar', 'he'];
    let translations = {};
    let currentLang = localStorage.getItem(STORAGE_KEY) || DEFAULT_LANG;

    function setDirection(lang) {
        document.documentElement.setAttribute('dir', RTL_LANGS.includes(lang) ? 'rtl' : 'ltr');
        document.documentElement.setAttribute('lang', lang);
    }

    function applyTranslations(lang) {
        if (lang === DEFAULT_LANG || lang === 'ai') {
            document.querySelectorAll('[data-i18n]').forEach(el => {
                const orig = el.getAttribute('data-i18n-original');
                if (orig) el.textContent = orig;
            });
            return;
        }
        const langData = translations[lang] || {};
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (!el.getAttribute('data-i18n-original')) {
                el.setAttribute('data-i18n-original', el.textContent);
            }
            if (langData[key]) el.textContent = langData[key];
        });
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            const key = el.getAttribute('data-i18n-placeholder');
            if (!el.getAttribute('data-i18n-placeholder-original')) {
                el.setAttribute('data-i18n-placeholder-original', el.getAttribute('placeholder') || '');
            }
            if (langData[key]) el.setAttribute('placeholder', langData[key]);
        });
    }

    function setLang(lang) {
        currentLang = lang;
        localStorage.setItem(STORAGE_KEY, lang);
        setDirection(lang);
        applyTranslations(lang);
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.lang === lang);
        });
    }

    function init(data) {
        translations = data || {};
        setDirection(currentLang);
        applyTranslations(currentLang);
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.addEventListener('click', () => setLang(btn.dataset.lang));
            btn.classList.toggle('active', btn.dataset.lang === currentLang);
        });
    }

    return { init, setLang, getCurrentLang: () => currentLang };
})();
```

- [ ] **Step 2: Create tech app i18n.js.**

Copy the same file, changing only `STORAGE_KEY`:

```bash
# Adjust paths to match actual structure found in Task 1
CONSUMER_STATIC="<consumer_app_root>/static/js"
TECH_STATIC="<tech_app_root>/static/js"
mkdir -p "$TECH_STATIC"
sed "s/'wtf-lang'/'wtf-tech-lang'/" "$CONSUMER_STATIC/i18n.js" > "$TECH_STATIC/i18n.js"
echo "Created tech i18n.js"
```

---

### Task 3: Create translations.json for Both Apps

**Files:**
- Create: `consumer/static/data/translations.json`
- Create: `tech/static/data/translations.json`

- [ ] **Step 1: Create consumer app translations.json.**

```json
{
  "en": {
    "nav.home": "Home",
    "nav.about": "About",
    "nav.contact": "Contact",
    "header.tagline": "Canadian News. No Spin.",
    "search.placeholder": "Search articles...",
    "filter.all_sources": "All Sources",
    "filter.bias_left": "Left-leaning",
    "filter.bias_center": "Centre",
    "filter.bias_right": "Right-leaning",
    "article.read_more": "Read More",
    "article.published": "Published",
    "article.fact_check": "Fact Check",
    "article.bias_score": "Bias Score",
    "article.source": "Source",
    "footer.copyright": "© Kytran Empowerment Inc.",
    "footer.privacy": "Privacy Policy",
    "footer.terms": "Terms of Service",
    "common.loading": "Loading...",
    "common.error": "Something went wrong. Please try again.",
    "common.no_results": "No results found."
  },
  "fr": {},
  "es": {},
  "pt": {},
  "de": {},
  "zh": {},
  "ar": {},
  "he": {},
  "ai": {
    "header.tagline": "{intent:brand_tagline, domain:news_media, values:[objectivity,no_spin], audience:canadian_readers}",
    "filter.bias_left": "{intent:filter, axis:political_bias, direction:left}",
    "filter.bias_right": "{intent:filter, axis:political_bias, direction:right}",
    "article.fact_check": "{intent:credibility_signal, type:fact_check, importance:high}"
  }
}
```

Save to `<consumer_app_root>/static/data/translations.json`.

- [ ] **Step 2: Create tech app translations.json.**

```json
{
  "en": {
    "nav.home": "Home",
    "nav.dashboard": "Dashboard",
    "nav.transparency": "Transparency",
    "nav.api_docs": "API Docs",
    "dashboard.title": "Editorial Bias Dashboard",
    "dashboard.subtitle": "Real-time analysis of Canadian news coverage",
    "dashboard.total_articles": "Total Articles",
    "dashboard.sources_tracked": "Sources Tracked",
    "dashboard.bias_overview": "Bias Overview",
    "transparency.title": "How We Work",
    "transparency.methodology": "Methodology",
    "transparency.bias_model": "Bias Scoring Model",
    "transparency.fact_check_model": "Fact-Check Model",
    "filter.date_range": "Date Range",
    "filter.source": "Source",
    "filter.bias": "Bias",
    "common.loading": "Loading...",
    "common.error": "Something went wrong.",
    "common.search": "Search",
    "footer.copyright": "© Kytran Empowerment Inc.",
    "footer.privacy": "Privacy Policy"
  },
  "fr": {},
  "es": {},
  "pt": {},
  "de": {},
  "zh": {},
  "ar": {},
  "he": {},
  "ai": {
    "dashboard.title": "{intent:data_dashboard, domain:news_bias_analysis, scope:canadian, realtime:true}",
    "transparency.bias_model": "{intent:methodology_disclosure, model_type:bias_scoring, transparency:high}"
  }
}
```

Save to `<tech_app_root>/static/data/translations.json`.

---

### Task 4: Tag Templates with data-i18n Attributes

**Files:**
- Modify: all `*.html` templates in both apps

**Critical rule:** Do NOT add `data-i18n` to article body content elements — only nav, header, footer, labels, buttons, and filter controls.

- [ ] **Step 1: Tag consumer app templates.**

For `base.html` (shared nav/footer across all consumer pages):

```html
<!-- Nav -->
<a href="/" data-i18n="nav.home">Home</a>
<a href="/about" data-i18n="nav.about">About</a>
<input data-i18n-placeholder="search.placeholder" placeholder="Search articles...">

<!-- Filter controls -->
<select>
  <option data-i18n="filter.all_sources">All Sources</option>
  <option data-i18n="filter.bias_left">Left-leaning</option>
  <option data-i18n="filter.bias_center">Centre</option>
  <option data-i18n="filter.bias_right">Right-leaning</option>
</select>

<!-- Footer -->
<span data-i18n="footer.copyright">© Kytran Empowerment Inc.</span>
<a href="/privacy" data-i18n="footer.privacy">Privacy Policy</a>

<!-- Language selector (add to nav) -->
<div class="lang-switcher">
  <button class="lang-btn" data-lang="en">EN</button>
  <button class="lang-btn" data-lang="fr">FR</button>
  <button class="lang-btn" data-lang="es">ES</button>
</div>
```

For `article.html` — only tag the article meta labels, NOT the article body:

```html
<!-- Tag these: -->
<span data-i18n="article.published">Published</span>
<span data-i18n="article.source">Source</span>
<span data-i18n="article.bias_score">Bias Score</span>
<a data-i18n="article.read_more">Read More</a>

<!-- Do NOT tag these (article body content stays in source language): -->
<h1 class="article-title">{{ article.title }}</h1>
<div class="article-body">{{ article.content }}</div>
```

Add i18n loader before `</body>`:

```html
<script src="/static/js/i18n.js"></script>
<script>
  fetch('/static/data/translations.json')
    .then(r => r.json())
    .then(data => I18n.init(data))
    .catch(() => I18n.init({}));
</script>
```

- [ ] **Step 2: Tag tech app templates.**

Same pattern for `base.html`, `dashboard.html`, `transparency.html`. Tag all UI labels and controls. Data visualization labels (chart axes, legend items) that come from JS/API responses do not get `data-i18n` — only static HTML text.

---

### Task 5: Dispatch R.O.S.E.T.T.A. + Deploy to VPS

**Files:** translations.json files updated by R.O.S.E.T.T.A.

- [ ] **Step 1: Route translation tasks to R.O.S.E.T.T.A.**

```bash
docker exec archie_platform python -c "
import json
from pathlib import Path
from services.delegation_service import delegate_task

apps = [
    ('wtf-consumer', '<consumer_app_root>/static/data/translations.json'),
    ('wtf-tech', '<tech_app_root>/static/data/translations.json'),
]

for app_name, path in apps:
    try:
        t = json.loads(Path(path).read_text())
    except FileNotFoundError:
        print(f'{app_name}: {path} not found')
        continue
    en_keys = list(t.get('en', {}).keys())
    for lang in ['fr', 'es', 'ai']:
        capability = 'semantic_describe' if lang == 'ai' else 'translate'
        result = delegate_task(
            capability=capability,
            reason=f'Fill {len(en_keys)} keys for {app_name} language={lang}',
            args={'language': lang, 'keys': en_keys, 'source_file': path, 'product': app_name},
            delegation_source='automation',
            requested_by='wtf_i18n_plan',
            priority=6,
        )
        print(f'{app_name} lang={lang} → task_id={result.get(\"task_id\")}')
"
```

- [ ] **Step 2: Wait for completion, then verify.**

```bash
python3 -c "
import json
from pathlib import Path

for label, path in [
    ('WTF Consumer', '<consumer_app_root>/static/data/translations.json'),
    ('WTF Tech', '<tech_app_root>/static/data/translations.json'),
]:
    try:
        t = json.loads(Path(path).read_text())
    except FileNotFoundError:
        print(f'{label}: file not found')
        continue
    for lang in ['fr', 'es']:
        data = t.get(lang, {})
        empty = [k for k,v in data.items() if not v]
        print(f'{label} {lang}: {len(data)} keys, {len(empty)} empty')
"
```

- [ ] **Step 3: Deploy to VPS.**

```bash
# Push changes to VPS git repo, then rebuild containers
# First find WTF repo path on VPS:
ssh root@76.13.107.109 "find /opt -name 'wtf*' -maxdepth 2 -type d 2>/dev/null"

# Then rebuild:
ssh root@76.13.107.109 "cd /opt/<wtf-path> && git pull && docker compose up -d --build"
```

- [ ] **Step 4: Verify both apps return HTTP 200.**

```bash
for url in "https://what-the-fact.com/" "https://what-the-fact.tech/"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  echo "$url → $code"
done
```

- [ ] **Step 5: Enable P.R.O.B.E. audit for WTF domains.**

In `domain_registry.py`, flip both WTF entries to `"active": True`.

- [ ] **Step 6: Commit and PR.**

```bash
cd /mnt/archie_brain
git checkout -b feat/wtf-i18n
git add platform_v2/tools/consciousness/translation_scanners/domain_registry.py
git commit -m "feat(i18n): WTF consumer + tech EN/FR/ES + AI semantic layer, P.R.O.B.E. enabled"
git push origin feat/wtf-i18n

gh pr create \
  --title "feat(i18n): What The Fact — EN/FR/ES + AI semantic layer on consumer + tech apps" \
  --body "## What ships
- wtf-consumer: translations.json (EN/FR/ES + ai), i18n.js, data-i18n tags on UI chrome
- wtf-tech: translations.json (EN/FR/ES + ai), i18n.js, data-i18n tags on dashboard/transparency
- Article body content NOT translated (stays in source language)
- Language selector (EN/FR/ES) in both app navs
- P.R.O.B.E. domain registry active=True for both WTF domains
- All translation work via R.O.S.E.T.T.A. through Department HQ + C.R.E.E.D." \
  --base main
```

---

## Success Criteria

- `what-the-fact.com` and `what-the-fact.tech` return HTTP 200
- Language selector switches UI chrome text (nav, labels, filters) without page reload
- Article body content remains in original language when language is switched
- 0 empty FR/ES values in both translations.json files
- P.R.O.B.E. DOM audit shows 0 missing gaps for both WTF domains

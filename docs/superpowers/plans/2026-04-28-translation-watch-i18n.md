# Watch Products i18n Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add full EN/FR/ES + AI semantic translation to all 4 Watch products (Gov, Civic, Legal, Market Watch), using the same client-side `data-i18n` pattern as kytranempowerment.com, then deploy to VPS and enable P.R.O.B.E. audit coverage.

**Architecture:** Each Watch product gets a standalone `static/data/translations.json` (9-language structure) and `static/js/i18n.js` (adapted from KE.com pattern). All HTML templates tagged with `data-i18n` attributes. R.O.S.E.T.T.A. fills FR/ES/ai values via Department HQ dispatch. Deployed to VPS via docker rebuild. P.R.O.B.E. domain registry `active` flag flipped after deploy.

**Tech Stack:** JavaScript (i18n.js), HTML `data-i18n` attributes, Python Flask (Jinja2 templates), Docker VPS deploy.

**Source paths:**
- Gov Watch: `/mnt/standalone/kytran-gov-watch/`
- Civic Watch: `/mnt/standalone/kytran-civic-watch/`
- Legal Watch: `/mnt/standalone/kytran-legal-watch/`
- Market Watch: `/mnt/standalone/kytran-market-watch/`

---

### Task 1: Audit Each Watch Product's Templates

**Files:**
- Read: each product's `templates/` directory

- [ ] **Step 1: List all templates and count visible text strings in each product.**

```bash
for product in kytran-gov-watch kytran-civic-watch kytran-legal-watch kytran-market-watch; do
  path="/mnt/standalone/$product"
  if [ -d "$path" ]; then
    echo "=== $product ==="
    find "$path/templates" -name "*.html" 2>/dev/null | head -20
    echo "---"
  else
    echo "$product: NOT FOUND at $path"
  fi
done
```

- [ ] **Step 2: For each product, extract all user-visible text strings from templates.**

```bash
python3 -c "
import os, re
from pathlib import Path

products = [
    ('gov-watch', '/mnt/standalone/kytran-gov-watch/templates'),
    ('civic-watch', '/mnt/standalone/kytran-civic-watch/templates'),
    ('legal-watch', '/mnt/standalone/kytran-legal-watch/templates'),
    ('market-watch', '/mnt/standalone/kytran-market-watch/templates'),
]
for name, tpl_path in products:
    if not os.path.isdir(tpl_path):
        print(f'{name}: templates dir not found at {tpl_path}')
        continue
    texts = []
    for f in Path(tpl_path).rglob('*.html'):
        content = f.read_text()
        # Find text content in tags (rough extraction)
        matches = re.findall(r'>([A-Z][^<]{2,60})<', content)
        texts.extend([m.strip() for m in matches if m.strip()])
    print(f'{name}: ~{len(texts)} text strings across {len(list(Path(tpl_path).rglob(\"*.html\")))} templates')
"
```

---

### Task 2: Create i18n.js for All Watch Products

**Files:**
- Create: `static/js/i18n.js` in each Watch product

The i18n.js is identical across all 4 products except the `STORAGE_KEY`. Copy the pattern from KE.com's i18n.js, adapting only the storage key and removing the API fallback (Watch products use bundle-only translations).

- [ ] **Step 1: Read KE.com's i18n.js to get the exact pattern.**

```bash
head -100 /mnt/archie_brain/website/kytranempowerment.com/js/i18n.js
```

- [ ] **Step 2: Create Gov Watch i18n.js.**

Create `/mnt/standalone/kytran-gov-watch/static/js/i18n.js`:

```javascript
/**
 * Gov Watch i18n — client-side translation engine.
 * Same pattern as kytranempowerment.com. Bundle-only (no API fallback).
 */
const I18n = (() => {
    const STORAGE_KEY = 'gw-lang';
    const DEFAULT_LANG = 'en';
    const RTL_LANGS = ['ar', 'he'];
    const SUPPORTED = ['en', 'fr', 'es', 'pt', 'de', 'zh', 'ar', 'he', 'ai'];

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
            document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
                const orig = el.getAttribute('data-i18n-placeholder-original');
                if (orig) el.setAttribute('placeholder', orig);
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
        if (!SUPPORTED.includes(lang)) return;
        currentLang = lang;
        localStorage.setItem(STORAGE_KEY, lang);
        setDirection(lang);
        applyTranslations(lang);
        document.querySelectorAll('.lang-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.lang === lang);
        });
    }

    function init(translationData) {
        translations = translationData || {};
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

- [ ] **Step 3: Create the same file for Civic, Legal, and Market Watch.**

Only the `STORAGE_KEY` changes per product:

```bash
# Copy Gov Watch i18n.js to the other 3 products, replacing the storage key
for product in kytran-civic-watch kytran-legal-watch kytran-market-watch; do
  key_prefix=$(echo "$product" | sed 's/kytran-//' | sed 's/-watch//' | cut -c1-2)w
  mkdir -p /mnt/standalone/$product/static/js/
  sed "s/'gw-lang'/'${key_prefix}-lang'/" \
    /mnt/standalone/kytran-gov-watch/static/js/i18n.js \
    > /mnt/standalone/$product/static/js/i18n.js
  echo "Created $product/static/js/i18n.js with key '${key_prefix}-lang'"
done
```

Expected output:
```
Created kytran-civic-watch/static/js/i18n.js with key 'ciw-lang'
Created kytran-legal-watch/static/js/i18n.js with key 'lew-lang'
Created kytran-market-watch/static/js/i18n.js with key 'maw-lang'
```

---

### Task 3: Create translations.json Skeleton for All Watch Products

**Files:**
- Create: `static/data/translations.json` in each Watch product

The skeleton has full EN values, empty FR/ES/pt/de/zh/ar/he objects, and minimal AI semantic values. R.O.S.E.T.T.A. fills the non-EN languages in Task 5.

- [ ] **Step 1: Audit Gov Watch templates for all translatable strings.**

```bash
python3 -c "
from pathlib import Path
import re

tpl_dir = Path('/mnt/standalone/kytran-gov-watch/templates')
keys_found = {}
for f in tpl_dir.rglob('*.html'):
    content = f.read_text()
    # Extract visible text in common tags
    for tag in ['h1','h2','h3','h4','p','button','a','label','span','td','th','li']:
        for m in re.finditer(rf'<{tag}[^>]*>([^<]{{3,100}})</{tag}>', content):
            text = m.group(1).strip()
            if text and not text.startswith('{%') and not text.startswith('{{'):
                # Suggest a key
                key = tag + '.' + re.sub(r'[^a-z0-9]', '_', text.lower())[:30].strip('_')
                keys_found[key] = text
print(f'Found ~{len(keys_found)} translatable strings')
for k, v in list(keys_found.items())[:20]:
    print(f'  {k!r}: {v!r}')
"
```

- [ ] **Step 2: Create Gov Watch translations.json with EN values.**

Create `/mnt/standalone/kytran-gov-watch/static/data/translations.json`:

```json
{
  "en": {
    "nav.home": "Home",
    "nav.about": "About",
    "nav.contact": "Contact",
    "nav.sign_in": "Sign In",
    "nav.sign_out": "Sign Out",
    "hero.title": "Government Procurement Intelligence",
    "hero.subtitle": "AI-powered federal tender matching for Canadian suppliers",
    "hero.cta": "Start Matching",
    "footer.copyright": "© Kytran Empowerment Inc.",
    "footer.privacy": "Privacy Policy",
    "footer.terms": "Terms of Service",
    "common.loading": "Loading...",
    "common.error": "Something went wrong. Please try again.",
    "common.search": "Search",
    "common.filter": "Filter",
    "common.submit": "Submit",
    "common.cancel": "Cancel",
    "common.save": "Save",
    "common.back": "Back"
  },
  "fr": {},
  "es": {},
  "pt": {},
  "de": {},
  "zh": {},
  "ar": {},
  "he": {},
  "ai": {
    "nav.home": "{intent:navigation, destination:home, type:primary_nav}",
    "hero.title": "{intent:brand_introduction, domain:government_procurement, audience:canadian_suppliers, tone:professional}",
    "hero.cta": "{intent:conversion, action:start_matching, type:primary_cta}"
  }
}
```

**Note:** The EN values above are placeholders. Run the audit in Step 1 to get the actual strings from the templates, then populate EN accordingly before moving on.

- [ ] **Step 3: Create translations.json for Civic, Legal, and Market Watch.**

Repeat the same structure for each product. Use the template audit output from each product's templates to populate EN values.

```bash
for product in kytran-civic-watch kytran-legal-watch kytran-market-watch; do
  mkdir -p /mnt/standalone/$product/static/data/
  # Create skeleton — EN values to be populated from template audit
  python3 -c "
import json
skeleton = {
    'en': {
        'nav.home': 'Home', 'nav.about': 'About', 'nav.contact': 'Contact',
        'nav.sign_in': 'Sign In', 'nav.sign_out': 'Sign Out',
        'footer.copyright': '© Kytran Empowerment Inc.',
        'footer.privacy': 'Privacy Policy', 'footer.terms': 'Terms of Service',
        'common.loading': 'Loading...', 'common.error': 'Something went wrong.',
        'common.search': 'Search', 'common.filter': 'Filter',
        'common.submit': 'Submit', 'common.cancel': 'Cancel',
    },
    'fr': {}, 'es': {}, 'pt': {}, 'de': {}, 'zh': {}, 'ar': {}, 'he': {},
    'ai': {
        'nav.home': '{intent:navigation, destination:home, type:primary_nav}',
        'footer.copyright': '{intent:legal, entity:Kytran_Empowerment_Inc, type:copyright}',
    }
}
print(json.dumps(skeleton, indent=2, ensure_ascii=False))
" > /mnt/standalone/$product/static/data/translations.json
  echo "Created $product/static/data/translations.json"
done
```

---

### Task 4: Tag All HTML Templates with data-i18n Attributes

**Files:**
- Modify: all `*.html` templates in each Watch product

This is the most manual task. For each template, wrap visible text with `data-i18n` attributes and add a `translations.json` key for each string.

- [ ] **Step 1: Tag Gov Watch templates.**

For each HTML template, replace hardcoded text with `data-i18n` attributes. Example pattern:

**Before:**
```html
<nav>
  <a href="/">Home</a>
  <a href="/about">About</a>
</nav>
<h1>Government Procurement Intelligence</h1>
<p>AI-powered federal tender matching for Canadian suppliers</p>
<button>Start Matching</button>
```

**After:**
```html
<nav>
  <a href="/" data-i18n="nav.home">Home</a>
  <a href="/about" data-i18n="nav.about">About</a>
</nav>
<h1 data-i18n="hero.title">Government Procurement Intelligence</h1>
<p data-i18n="hero.subtitle">AI-powered federal tender matching for Canadian suppliers</p>
<button data-i18n="hero.cta">Start Matching</button>
```

For input placeholders:
```html
<!-- Before -->
<input placeholder="Search tenders...">

<!-- After -->
<input data-i18n-placeholder="common.search" placeholder="Search tenders...">
```

Apply this pattern to all 3 Gov Watch templates: `landing.html`, `index.html`, `procure/chat.html`.

- [ ] **Step 2: Add language selector to each template's nav.**

Add to the nav bar in the base/layout template (or each template if no base):

```html
<!-- Language selector — add to nav -->
<div class="lang-switcher">
  <button class="lang-btn" data-lang="en">EN</button>
  <button class="lang-btn" data-lang="fr">FR</button>
  <button class="lang-btn" data-lang="es">ES</button>
</div>
```

- [ ] **Step 3: Load i18n.js and translations.json in each template.**

Add before `</body>` in each template (or in the base template if one exists):

```html
<script>
  // Load translations and init i18n
  fetch('/static/data/translations.json')
    .then(r => r.json())
    .then(data => I18n.init(data))
    .catch(() => I18n.init({}));
</script>
<script src="/static/js/i18n.js"></script>
```

**Note:** Script order matters — `i18n.js` must load before the inline init script. In practice, put the `<script src>` tag first, then the inline init.

Correct order:
```html
<script src="/static/js/i18n.js"></script>
<script>
  fetch('/static/data/translations.json')
    .then(r => r.json())
    .then(data => I18n.init(data))
    .catch(() => I18n.init({}));
</script>
```

- [ ] **Step 4: Repeat Steps 1–3 for Civic, Legal, and Market Watch.**

Same pattern — tag templates, add language selector, load i18n.js.

---

### Task 5: Dispatch R.O.S.E.T.T.A. to Fill FR/ES/ai Translations

**Files:**
- Modify: `static/data/translations.json` in each Watch product (R.O.S.E.T.T.A. fills the FR/ES/ai values)

- [ ] **Step 1: Extract all EN keys from each product's translations.json.**

```bash
python3 -c "
import json
from pathlib import Path

for product in ['kytran-gov-watch','kytran-civic-watch','kytran-legal-watch','kytran-market-watch']:
    path = f'/mnt/standalone/{product}/static/data/translations.json'
    try:
        t = json.loads(Path(path).read_text())
        en_keys = list(t.get('en', {}).keys())
        print(f'{product}: {len(en_keys)} EN keys')
    except FileNotFoundError:
        print(f'{product}: translations.json not found')
"
```

- [ ] **Step 2: Route translation tasks to R.O.S.E.T.T.A. for each product.**

```bash
docker exec archie_platform python -c "
import json
from pathlib import Path
from services.delegation_service import delegate_task

products = [
    ('kytran-gov-watch', '/mnt/standalone/kytran-gov-watch/static/data/translations.json'),
    ('kytran-civic-watch', '/mnt/standalone/kytran-civic-watch/static/data/translations.json'),
    ('kytran-legal-watch', '/mnt/standalone/kytran-legal-watch/static/data/translations.json'),
    ('kytran-market-watch', '/mnt/standalone/kytran-market-watch/static/data/translations.json'),
]
target_langs = ['fr', 'es', 'ai']

for product_name, path in products:
    try:
        t = json.loads(Path(path).read_text())
    except FileNotFoundError:
        print(f'{product_name}: file not found, skipping')
        continue

    en_keys = list(t.get('en', {}).keys())
    for lang in target_langs:
        capability = 'semantic_describe' if lang == 'ai' else 'translate'
        result = delegate_task(
            capability=capability,
            reason=(f'Fill {len(en_keys)} keys for {product_name} language={lang}. '
                    f'Write results to {path}'),
            args={'language': lang, 'keys': en_keys, 'source_file': path,
                  'product': product_name},
            delegation_source='automation',
            requested_by='watch_i18n_plan',
            priority=6,
        )
        print(f'{product_name} lang={lang} → task_id={result.get(\"task_id\")}')
"
```

- [ ] **Step 3: Monitor task completion in Dev HQ.**

Open http://192.168.1.200:3000/tools/consciousness/#devhq → Tasks. Wait for all translate tasks to reach `completed`.

---

### Task 6: Deploy All Watch Products to VPS + Enable P.R.O.B.E.

**Files:**
- Modify: `platform_v2/tools/consciousness/translation_scanners/domain_registry.py` (flip `active: True`)

- [ ] **Step 1: Verify each product's translations.json is complete.**

```bash
python3 -c "
import json
from pathlib import Path

for product in ['kytran-gov-watch','kytran-civic-watch','kytran-legal-watch','kytran-market-watch']:
    path = Path(f'/mnt/standalone/{product}/static/data/translations.json')
    t = json.loads(path.read_text())
    for lang in ['fr','es']:
        data = t.get(lang, {})
        empty = [k for k,v in data.items() if not v]
        print(f'{product} {lang}: {len(data)} keys, {len(empty)} empty')
"
```

- [ ] **Step 2: Deploy each Watch product to VPS.**

SSH to VPS and rebuild:

```bash
# For each product, trigger VPS docker rebuild
# Replace <product-dir> with the actual directory name on the VPS
ssh root@76.13.107.109 "cd /opt/kytran-gov-watch && git pull && docker compose up -d --build"
ssh root@76.13.107.109 "cd /opt/kytran-civic-watch && git pull && docker compose up -d --build"
ssh root@76.13.107.109 "cd /opt/kytran-legal-watch && git pull && docker compose up -d --build"
ssh root@76.13.107.109 "cd /opt/kytran-market-watch && git pull && docker compose up -d --build"
```

**Note:** Verify the exact directory paths on the VPS first:
```bash
ssh root@76.13.107.109 "ls /opt/"
```

- [ ] **Step 3: Verify each product returns HTTP 200.**

```bash
for url in \
  "https://gov.kytranempowerment.com/" \
  "https://civic.kytranempowerment.com/" \
  "https://legal.kytranempowerment.com/" \
  "https://market.kytranempowerment.com/"; do
  code=$(curl -s -o /dev/null -w "%{http_code}" "$url")
  echo "$url → $code"
done
```

Expected: all `200`.

- [ ] **Step 4: Enable P.R.O.B.E. audit for all Watch products.**

In `platform_v2/tools/consciousness/translation_scanners/domain_registry.py`, set `"active": True` for all 4 Watch product entries:

```python
# Change for each Watch product entry:
"active": True,  # was False
```

- [ ] **Step 5: Commit and push all changes.**

```bash
cd /mnt/archie_brain
git checkout -b feat/watch-products-i18n

# Stage all Watch product files (they live in /mnt/standalone)
# If standalone products are in a separate repo, commit there
# Otherwise stage from archie_brain if they're submodules or tracked paths

git add platform_v2/tools/consciousness/translation_scanners/domain_registry.py
git commit -m "feat(i18n): enable P.R.O.B.E. audit for all 4 Watch products"
git push origin feat/watch-products-i18n

gh pr create \
  --title "feat(i18n): Watch products EN/FR/ES + AI semantic layer" \
  --body "## What ships
- Gov/Civic/Legal/Market Watch: translations.json (EN/FR/ES + ai semantic, PT/DE/ZH/AR/HE slots)
- i18n.js adapted from KE.com pattern (storage keys: gw/ci/lew/maw-lang)
- All HTML templates tagged with data-i18n attributes
- Language selector (EN/FR/ES) added to each nav
- P.R.O.B.E. domain registry active=True for all 4 products
- All translation work routed through Department HQ + C.R.E.E.D." \
  --base main
```

---

## Success Criteria

- All 4 Watch products return HTTP 200
- Each product's `translations.json` has FR/ES values filled (0 empty strings)
- Language selector switches text on-page without reload
- P.R.O.B.E. DOM audit shows 0 missing gaps for all 4 Watch domains
- `domain_registry.py` shows `active: True` for all 4 Watch products

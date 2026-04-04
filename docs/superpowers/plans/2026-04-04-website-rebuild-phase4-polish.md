# Website Rebuild Phase 4: Polish & Final Deploy

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Final polish pass — migrate store product images, full breakpoint testing on all 28 pages, link audit, translation completeness check, SEO basics, and final production deploy.

**Depends on:** Phase 1 + 2 + 3 complete

---

## Task 1: Migrate Store Product Images

**Files:**
- Copy: 33+ product images from old site to new site `assets/` directory

- [ ] **Step 1: Copy all product images from old site**

```bash
# Copy all images from old site assets
cp /mnt/archie_brain/repos/website/kytranempowerment-site/assets/*.jpg /mnt/archie_brain/website/kytranempowerment.com/assets/
cp /mnt/archie_brain/repos/website/kytranempowerment-site/assets/*.png /mnt/archie_brain/website/kytranempowerment.com/assets/
```

- [ ] **Step 2: Rename Wix hash filenames to descriptive names**

The old site has files like `90845d_86213dfe998c49abb07cb6d103e9b3d4~mv2.jpg`. Create a Python script to rename them based on their usage in the old HTML files:

```python
#!/usr/bin/env python3
"""Rename Wix-exported images to descriptive filenames."""
import os, re, glob

OLD_SITE = "/mnt/archie_brain/repos/website/kytranempowerment-site"
NEW_ASSETS = "/mnt/archie_brain/website/kytranempowerment.com/assets"

# Find image references in old HTML
image_map = {}
for html_file in glob.glob(f"{OLD_SITE}/*.html"):
    content = open(html_file).read()
    # Find img src and background-image references
    for match in re.finditer(r'(?:src|url)\s*[=\(]\s*["\']?assets/([^"\')\s]+)', content):
        filename = match.group(1)
        page = os.path.basename(html_file).replace('.html', '')
        if filename not in image_map:
            image_map[filename] = page

# Rename files
counter = {}
for old_name, page in image_map.items():
    old_path = f"{NEW_ASSETS}/{old_name}"
    if not os.path.exists(old_path):
        continue
    ext = os.path.splitext(old_name)[1]
    base = page.replace('_', '-')
    counter[base] = counter.get(base, 0) + 1
    new_name = f"{base}-{counter[base]}{ext}"
    new_path = f"{NEW_ASSETS}/{new_name}"
    os.rename(old_path, new_path)
    print(f"Renamed: {old_name} -> {new_name}")
```

- [ ] **Step 3: Update store.html image references**

Update any `<img src="assets/...">` references in store.html and product-detail.html to use the new descriptive filenames.

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add assets/ store.html product-detail.html
git commit -m "feat(website): migrate + rename 33 store product images from old site"
```

---

## Task 2: Full Link Audit

**Files:** All 28 HTML files

- [ ] **Step 1: Run link audit script**

```python
#!/usr/bin/env python3
"""Audit all internal links across the 28-page site."""
import os, re, glob

SITE = "/mnt/archie_brain/website/kytranempowerment.com"
html_files = set(os.path.basename(f) for f in glob.glob(f"{SITE}/*.html") if not os.path.basename(f).startswith('_'))

broken = []
orphaned = set(html_files)

for html_file in sorted(glob.glob(f"{SITE}/*.html")):
    if os.path.basename(html_file).startswith('_'):
        continue
    content = open(html_file).read()
    page = os.path.basename(html_file)

    # Find all href links to local files
    for match in re.finditer(r'href=["\']([^"\'#]+\.html)', content):
        target = match.group(1)
        if target.startswith('http'):
            continue
        if target not in html_files:
            broken.append(f"{page} -> {target}")
        else:
            orphaned.discard(target)

    # This page is referenced (it exists)
    orphaned.discard(page)

print("=== BROKEN LINKS ===")
for link in broken:
    print(f"  {link}")

print(f"\n=== ORPHANED PAGES (not linked from anywhere) ===")
for page in sorted(orphaned):
    print(f"  {page}")
```

Expected: Zero broken links. Orphaned pages should only be `blocked.html` (intentionally not linked) and `order-success.html` (reached via checkout flow, not nav).

- [ ] **Step 2: Fix any broken links found**

Update href values in the relevant HTML files.

- [ ] **Step 3: Commit fixes**

```bash
git add *.html
git commit -m "fix(website): resolve broken internal links from link audit"
```

---

## Task 3: Translation Completeness Audit

**Files:**
- Modify: `data/translations.json`

- [ ] **Step 1: Audit data-i18n coverage**

```python
#!/usr/bin/env python3
"""Find all data-i18n keys used in HTML and check against translations.json."""
import os, re, json, glob

SITE = "/mnt/archie_brain/website/kytranempowerment.com"

# Collect all used keys
used_keys = set()
for html_file in glob.glob(f"{SITE}/*.html"):
    content = open(html_file).read()
    for match in re.finditer(r'data-i18n="([^"]+)"', content):
        used_keys.add(match.group(1))

# Load translations
translations = json.load(open(f"{SITE}/data/translations.json"))
languages = list(translations.keys())

print(f"Total i18n keys used in HTML: {len(used_keys)}")
print(f"Languages in bundle: {languages}")

for lang in languages:
    bundle_keys = set(translations[lang].keys())
    missing = used_keys - bundle_keys
    if missing:
        print(f"\n{lang} missing {len(missing)} keys:")
        for key in sorted(missing):
            print(f"  {key}")
    else:
        print(f"{lang}: complete ({len(bundle_keys)} keys)")
```

- [ ] **Step 2: Add any missing translation keys**

For each missing key, add translations in all 8 languages. Use the English text as the key content, translate appropriately for each language.

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add data/translations.json
git commit -m "feat(website): complete i18n coverage — all keys translated in 8 languages"
```

---

## Task 4: Full Breakpoint Testing (All 28 Pages)

**Files:** None (testing only, hotfixes as needed)

- [ ] **Step 1: Test at 1024px (Desktop)**

Use Playwright or Chrome DevTools MCP. For each of the 28 pages:
- Nav renders with dropdowns
- Content centered within max-width
- Card grids show 2-3 columns
- No horizontal scroll
- Logo visible

- [ ] **Step 2: Test at 768px (Tablet)**

For each page:
- Hamburger menu shows, dropdowns hidden
- Accordion menu opens bounded (not fullscreen)
- Content reflows to 1-2 columns
- Images scale correctly
- No overflow

- [ ] **Step 3: Test at 480px (Mobile)**

For each page:
- Single column layout
- Accordion menu bounded to 80vh
- Text readable without zooming
- Touch targets large enough (44px minimum)
- Forms usable
- Tables horizontally scrollable

- [ ] **Step 4: Test RTL (Arabic/Hebrew)**

Switch to Arabic and Hebrew:
- Text direction reverses
- Nav layout correct in RTL
- Accordion opens from correct side
- Card grids maintain layout
- No text overflow

- [ ] **Step 5: Fix any issues found and commit**

```bash
git add -A
git commit -m "fix(website): breakpoint testing fixes across all 28 pages"
```

---

## Task 5: SEO & Meta Tags

**Files:** All 28 HTML files

- [ ] **Step 1: Verify meta tags on all pages**

Each page must have:
- `<title>` — unique, descriptive, includes "Kytran Empowerment"
- `<meta name="description">` — unique, 150-160 chars
- `<meta name="viewport" content="width=device-width, initial-scale=1">`
- `<link rel="canonical">` — pointing to the page's canonical URL
- Open Graph tags: `og:title`, `og:description`, `og:image`, `og:url`

- [ ] **Step 2: Add JSON-LD structured data to key pages**

At minimum:
- `index.html` — Organization schema
- `services.html` — Service schema
- `membership.html` — Product schema with pricing
- `contact.html` — ContactPoint schema with phone number

- [ ] **Step 3: Create sitemap.xml**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <!-- One <url> entry per page with lastmod date -->
</urlset>
```

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add *.html sitemap.xml
git commit -m "feat(website): SEO meta tags + sitemap.xml for all 28 pages"
```

---

## Task 6: Final Production Deploy

- [ ] **Step 1: Update cache bust version**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
# Use current date for final deploy
sed -i 's/?v=20260404[a-z]*/?v=20260405/g' *.html
```

- [ ] **Step 2: Build and deploy**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
tar -czf /tmp/site-final.tar.gz .
```

Deploy via `mcp__hostinger-api__hosting_deployStaticWebsite`.

- [ ] **Step 3: Post-deploy verification**

Visit `https://kytranempowerment.com` and verify:
1. Homepage loads with logo, full nav, all content
2. Click through every nav dropdown item — all 28 pages load
3. Competitors page: calculator works, all sections render
4. Membership page: pricing cards show with market comparison
5. AI Directors: all 16 render
6. Watch pages: links to live apps work
7. Store: product images load
8. Mobile: hamburger menu bounded, accordion works
9. Translation: switch to French, Arabic — text changes, RTL works
10. Contact: phone number clickable

- [ ] **Step 4: Final commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add -A
git commit -m "feat(website): final production deploy — 28 pages, complete rebuild"
```

---

## Phase 4 Complete Checklist

- [ ] 33+ store product images migrated and renamed
- [ ] Zero broken internal links
- [ ] All i18n keys covered in all 8 languages
- [ ] All 28 pages tested at 1024px, 768px, 480px
- [ ] RTL tested (Arabic, Hebrew)
- [ ] SEO meta tags on all pages
- [ ] sitemap.xml created
- [ ] JSON-LD on key pages
- [ ] Cache busting updated
- [ ] Production deploy complete
- [ ] Post-deploy verification passed

---

## Overall Project Complete Checklist

- [ ] **28 pages** all live and accessible
- [ ] **Logo** visible on every page
- [ ] **Nav** — mega-dropdown desktop + bounded accordion mobile
- [ ] **Competitors** — 35+ companies, feature matrix, calculator, trends, transparency, KSM comparison
- [ ] **Pricing** — 5 tiers with market price comparison on membership page
- [ ] **Services** — every product and module listed
- [ ] **AI Directors** — 16 directors showcased with C.R.E.E.D. context
- [ ] **Watch products** — 4 dedicated landing pages with live app links
- [ ] **ARCHIE Code CLI** — product page ready for expansion
- [ ] **Translation** — 8 languages, hybrid static + API, RTL support
- [ ] **Responsive** — all breakpoints tested, hamburger fixed, content centered
- [ ] **Store** — product images restored, full e-commerce flow
- [ ] **Phone number** — 1-877-463-3352 in footer
- [ ] **"Get Started" CTA** — in nav, linking to membership
- [ ] **StockBot removed** — no references anywhere
- [ ] **SEO** — meta tags, sitemap, structured data

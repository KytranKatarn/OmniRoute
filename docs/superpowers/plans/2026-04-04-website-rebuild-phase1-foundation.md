# Website Rebuild Phase 1: Foundation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the foundation every page depends on — restore the logo, rebuild the nav with hybrid dropdown/accordion, fix responsive bugs, and implement the 8-language hybrid translation system.

**Architecture:** Modify the existing GSAP/Barba site in-place at `/mnt/archie_brain/website/kytranempowerment.com/`. Logo restored from old site. Nav rebuilt as mega-dropdown (desktop) + bounded accordion (mobile). Translation uses static JS bundle (8 languages, ~500 keys) with API overlay from `api.kytranempowerment.com`.

**Tech Stack:** Vanilla JS (no frameworks), CSS custom properties, GSAP/Barba/Lenis (existing), Hostinger deploy API

**Spec:** `docs/superpowers/specs/2026-04-04-website-complete-rebuild-design.md`

**Deploy command:** `cd /mnt/archie_brain/website/kytranempowerment.com && tar -czf /tmp/site.tar.gz . && mcp__hostinger-api__hosting_deployStaticWebsite`

**Test URL:** `https://kytranempowerment.com`

**Breakpoints:** 480px (small mobile), 768px (mobile/tablet), 1024px (desktop)

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `js/i18n.js` | Hybrid translation — static bundle + API overlay, language switcher logic |
| `data/translations.json` | Static translation bundle — 8 languages, ~500 keys |
| `css/pages/nav.css` | Nav-specific responsive styles extracted for clarity |

### Modified Files
| File | Changes |
|------|---------|
| `css/components.css` | Nav rewrite: mega-dropdown desktop, accordion mobile |
| `css/responsive.css` | Fix hamburger sizing, bounded accordion, alignment fixes |
| `js/nav.js` | Rewrite: dropdown logic, accordion toggle, bounded mobile menu |
| `js/translate.js` | Replace with import of new `i18n.js` (or remove if unused) |
| `js/app.js` | Initialize i18n system, add nav dropdown handlers |
| All 22 HTML files | Add logo, update nav structure, add `data-i18n` attributes, update CSS/JS refs |

### Migrated Assets
| Source | Destination |
|--------|------------|
| `/repos/website/kytranempowerment-site/logo.png` | `assets/logo.png` |
| `/repos/website/kytranempowerment-site/logo-sm.png` | `assets/logo-sm.png` |

---

## Task 1: Restore Logo

**Files:**
- Copy: `assets/logo.png`, `assets/logo-sm.png` (from old site)
- Modify: `css/components.css` (add `.nav__logo` styles)

- [ ] **Step 1: Copy logo files from old site**

```bash
cp /mnt/archie_brain/repos/website/kytranempowerment-site/logo.png /mnt/archie_brain/website/kytranempowerment.com/assets/logo.png
cp /mnt/archie_brain/repos/website/kytranempowerment-site/logo-sm.png /mnt/archie_brain/website/kytranempowerment.com/assets/logo-sm.png
```

- [ ] **Step 2: Verify logo files exist and are valid**

```bash
ls -la /mnt/archie_brain/website/kytranempowerment.com/assets/logo*.png
file /mnt/archie_brain/website/kytranempowerment.com/assets/logo*.png
```

Expected: Two PNG files, valid image data.

- [ ] **Step 3: Add logo CSS to components.css**

In `css/components.css`, find the `.nav` section and add after `.nav__inner`:

```css
.nav__logo {
  height: 40px;
  width: auto;
  object-fit: contain;
}

.nav__brand {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  text-decoration: none;
  color: var(--color-text);
}

.nav__brand-text {
  font-family: var(--font-nav);
  font-size: 1.2rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--color-primary);
}
```

- [ ] **Step 4: Commit**

```bash
git add assets/logo.png assets/logo-sm.png css/components.css
git commit -m "feat(website): restore Kytran Empowerment logo from original site"
```

---

## Task 2: Rebuild Nav HTML Structure

**Files:**
- Modify: All 22 existing HTML files (nav section only)

The nav must be updated in every HTML file. The new structure replaces the current `<nav>` block. Use find-and-replace or a script.

- [ ] **Step 1: Define the new nav HTML**

This is the canonical nav block that goes in every page. It replaces everything from `<nav` to `</nav>` plus removes the old mobile menu div if present:

```html
<nav class="nav" role="navigation" aria-label="Main navigation">
  <div class="nav__inner">
    <a href="/" class="nav__brand">
      <img src="assets/logo-sm.png" alt="Kytran Empowerment logo" class="nav__logo">
      <span class="nav__brand-text">Kytran Empowerment</span>
    </a>

    <div class="nav__links">
      <div class="nav__dropdown">
        <button class="nav__link nav__dropdown-trigger" aria-expanded="false" aria-haspopup="true">
          <span data-i18n="nav.products">Products</span>
          <svg class="nav__chevron" width="12" height="12" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
        </button>
        <div class="nav__dropdown-menu">
          <a href="platform.html" class="nav__dropdown-item" data-i18n="nav.platform">Platform (A.R.C.H.I.E.)</a>
          <a href="ai-directors.html" class="nav__dropdown-item" data-i18n="nav.ai_directors">AI Directors</a>
          <a href="archie-code.html" class="nav__dropdown-item" data-i18n="nav.archie_code">ARCHIE Code CLI</a>
          <div class="nav__dropdown-divider"></div>
          <a href="market-watch.html" class="nav__dropdown-item" data-i18n="nav.market_watch">Market Watch</a>
          <a href="civic-watch.html" class="nav__dropdown-item" data-i18n="nav.civic_watch">Civic Watch</a>
          <a href="legal-watch.html" class="nav__dropdown-item" data-i18n="nav.legal_watch">Legal Watch</a>
          <a href="gov-watch.html" class="nav__dropdown-item" data-i18n="nav.gov_watch">Gov Watch</a>
          <div class="nav__dropdown-divider"></div>
          <a href="https://business.kytranempowerment.com" class="nav__dropdown-item" data-i18n="nav.business_suite">Business Suite</a>
        </div>
      </div>

      <div class="nav__dropdown">
        <button class="nav__link nav__dropdown-trigger" aria-expanded="false" aria-haspopup="true">
          <span data-i18n="nav.services">Services</span>
          <svg class="nav__chevron" width="12" height="12" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
        </button>
        <div class="nav__dropdown-menu">
          <a href="services.html" class="nav__dropdown-item" data-i18n="nav.all_services">All Services</a>
          <a href="compliance-services.html" class="nav__dropdown-item" data-i18n="nav.compliance_scanning">Compliance Scanning</a>
          <a href="membership.html" class="nav__dropdown-item" data-i18n="nav.pricing">Membership & Pricing</a>
        </div>
      </div>

      <div class="nav__dropdown">
        <button class="nav__link nav__dropdown-trigger" aria-expanded="false" aria-haspopup="true">
          <span data-i18n="nav.trust">Trust</span>
          <svg class="nav__chevron" width="12" height="12" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
        </button>
        <div class="nav__dropdown-menu">
          <a href="compliance.html" class="nav__dropdown-item" data-i18n="nav.trust_center">Trust Center</a>
          <a href="competitors.html" class="nav__dropdown-item" data-i18n="nav.competitors">Why A.R.C.H.I.E.</a>
          <a href="creed.html" class="nav__dropdown-item" data-i18n="nav.creed">C.R.E.E.D.</a>
        </div>
      </div>

      <div class="nav__dropdown">
        <button class="nav__link nav__dropdown-trigger" aria-expanded="false" aria-haspopup="true">
          <span data-i18n="nav.company">Company</span>
          <svg class="nav__chevron" width="12" height="12" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
        </button>
        <div class="nav__dropdown-menu">
          <a href="about.html" class="nav__dropdown-item" data-i18n="nav.about">About</a>
          <a href="vision.html" class="nav__dropdown-item" data-i18n="nav.vision">Vision</a>
          <a href="directory.html" class="nav__dropdown-item" data-i18n="nav.directory">Directory</a>
          <a href="books.html" class="nav__dropdown-item" data-i18n="nav.books">Books</a>
          <a href="tips.html" class="nav__dropdown-item" data-i18n="nav.tips">Tips & Tricks</a>
        </div>
      </div>

      <a href="store.html" class="nav__link" data-i18n="nav.store">Store</a>
      <a href="contact.html" class="nav__link" data-i18n="nav.contact">Contact</a>
    </div>

    <div class="nav__actions">
      <button class="nav__lang-btn" aria-label="Change language" title="Change language">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><circle cx="10" cy="10" r="8" stroke="currentColor" stroke-width="1.5"/><path d="M2 10h16M10 2c-2.5 3-2.5 13 0 16M10 2c2.5 3 2.5 13 0 16" stroke="currentColor" stroke-width="1.5"/></svg>
      </button>
      <a href="membership.html" class="nav__link nav__link--cta" data-i18n="nav.get_started">Get Started</a>
      <button class="nav__menu-btn" aria-label="Toggle menu" aria-expanded="false">
        <span class="nav__menu-icon"></span>
      </button>
    </div>
  </div>

  <!-- Language overlay (shared across all pages) -->
  <div class="lang-overlay" hidden>
    <div class="lang-overlay__panel">
      <button class="lang-overlay__close" aria-label="Close language selector">&times;</button>
      <h3 class="lang-overlay__title" data-i18n="lang.choose">Choose Language</h3>
      <div class="lang-overlay__grid">
        <button class="lang-overlay__btn" data-lang="en">English</button>
        <button class="lang-overlay__btn" data-lang="fr">Français (QC)</button>
        <button class="lang-overlay__btn" data-lang="es">Español</button>
        <button class="lang-overlay__btn" data-lang="pt">Português</button>
        <button class="lang-overlay__btn" data-lang="de">Deutsch</button>
        <button class="lang-overlay__btn" data-lang="zh">中文</button>
        <button class="lang-overlay__btn" data-lang="ar" dir="rtl">العربية</button>
        <button class="lang-overlay__btn" data-lang="he" dir="rtl">עברית</button>
      </div>
    </div>
  </div>
</nav>

<!-- Mobile accordion menu (separate from nav for positioning) -->
<div class="nav-mobile" id="navMobile" aria-hidden="true">
  <div class="nav-mobile__inner">
    <div class="nav-mobile__group">
      <button class="nav-mobile__trigger" aria-expanded="false">
        <span data-i18n="nav.products">Products</span>
        <svg class="nav-mobile__chevron" width="16" height="16" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
      </button>
      <div class="nav-mobile__items">
        <a href="platform.html" data-i18n="nav.platform">Platform (A.R.C.H.I.E.)</a>
        <a href="ai-directors.html" data-i18n="nav.ai_directors">AI Directors</a>
        <a href="archie-code.html" data-i18n="nav.archie_code">ARCHIE Code CLI</a>
        <a href="market-watch.html" data-i18n="nav.market_watch">Market Watch</a>
        <a href="civic-watch.html" data-i18n="nav.civic_watch">Civic Watch</a>
        <a href="legal-watch.html" data-i18n="nav.legal_watch">Legal Watch</a>
        <a href="gov-watch.html" data-i18n="nav.gov_watch">Gov Watch</a>
        <a href="https://business.kytranempowerment.com" data-i18n="nav.business_suite">Business Suite</a>
      </div>
    </div>
    <div class="nav-mobile__group">
      <button class="nav-mobile__trigger" aria-expanded="false">
        <span data-i18n="nav.services">Services</span>
        <svg class="nav-mobile__chevron" width="16" height="16" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
      </button>
      <div class="nav-mobile__items">
        <a href="services.html" data-i18n="nav.all_services">All Services</a>
        <a href="compliance-services.html" data-i18n="nav.compliance_scanning">Compliance Scanning</a>
        <a href="membership.html" data-i18n="nav.pricing">Membership & Pricing</a>
      </div>
    </div>
    <div class="nav-mobile__group">
      <button class="nav-mobile__trigger" aria-expanded="false">
        <span data-i18n="nav.trust">Trust</span>
        <svg class="nav-mobile__chevron" width="16" height="16" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
      </button>
      <div class="nav-mobile__items">
        <a href="compliance.html" data-i18n="nav.trust_center">Trust Center</a>
        <a href="competitors.html" data-i18n="nav.competitors">Why A.R.C.H.I.E.</a>
        <a href="creed.html" data-i18n="nav.creed">C.R.E.E.D.</a>
      </div>
    </div>
    <div class="nav-mobile__group">
      <button class="nav-mobile__trigger" aria-expanded="false">
        <span data-i18n="nav.company">Company</span>
        <svg class="nav-mobile__chevron" width="16" height="16" viewBox="0 0 12 12"><path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" stroke-width="1.5" fill="none"/></svg>
      </button>
      <div class="nav-mobile__items">
        <a href="about.html" data-i18n="nav.about">About</a>
        <a href="vision.html" data-i18n="nav.vision">Vision</a>
        <a href="directory.html" data-i18n="nav.directory">Directory</a>
        <a href="books.html" data-i18n="nav.books">Books</a>
        <a href="tips.html" data-i18n="nav.tips">Tips & Tricks</a>
      </div>
    </div>
    <a href="store.html" class="nav-mobile__direct" data-i18n="nav.store">Store</a>
    <a href="contact.html" class="nav-mobile__direct" data-i18n="nav.contact">Contact</a>
    <a href="membership.html" class="nav-mobile__cta" data-i18n="nav.get_started">Get Started</a>
  </div>
</div>
```

- [ ] **Step 2: Write a shell script to replace nav in all HTML files**

Create a temporary script that replaces the nav in all 22 HTML files. The nav block starts with `<nav` and ends with the closing mobile menu div. Save the canonical nav as a partial file first:

```bash
# Save the nav HTML from Step 1 as a partial
# File: /mnt/archie_brain/website/kytranempowerment.com/_nav-partial.html
# (contains the full nav block from Step 1)
```

Then for each HTML file, use a Python script to:
1. Read the file
2. Find `<nav` through the closing `</nav>` and any following mobile-menu div
3. Replace with the contents of `_nav-partial.html`
4. Write back

```python
#!/usr/bin/env python3
"""Replace nav block in all HTML files with canonical nav partial."""
import os, re, glob

SITE_DIR = "/mnt/archie_brain/website/kytranempowerment.com"
partial = open(f"{SITE_DIR}/_nav-partial.html").read()

# Pattern matches: <nav ...>...</nav> and optional mobile menu div after it
nav_pattern = re.compile(
    r'<nav\b[^>]*>.*?</nav>\s*(?:<div[^>]*class="[^"]*mobile-menu[^"]*"[^>]*>.*?</div>)?',
    re.DOTALL
)

for html_file in sorted(glob.glob(f"{SITE_DIR}/*.html")):
    if os.path.basename(html_file).startswith("_"):
        continue
    content = open(html_file).read()
    if "<nav" not in content:
        print(f"SKIP (no nav): {os.path.basename(html_file)}")
        continue
    new_content = nav_pattern.sub(partial, content, count=1)
    if new_content != content:
        open(html_file, "w").write(new_content)
        print(f"UPDATED: {os.path.basename(html_file)}")
    else:
        print(f"NO MATCH: {os.path.basename(html_file)}")
```

Run: `python3 /tmp/replace_nav.py`

- [ ] **Step 3: Verify nav replaced in all files**

```bash
grep -l 'nav__dropdown-trigger' /mnt/archie_brain/website/kytranempowerment.com/*.html | wc -l
```

Expected: 22 (all HTML files have the new nav)

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add *.html _nav-partial.html
git commit -m "feat(website): rebuild nav with mega-dropdown + mobile accordion structure"
```

---

## Task 3: Nav CSS — Desktop Dropdown + Mobile Accordion

**Files:**
- Modify: `css/components.css` (nav section rewrite)
- Modify: `css/responsive.css` (mobile accordion styles)

- [ ] **Step 1: Rewrite nav CSS in components.css**

Replace the existing `.nav` section in `css/components.css` (find from `.nav {` through `.nav__menu-icon` rules) with:

```css
/* ============================================
   NAV — Mega Dropdown (Desktop) + Accordion (Mobile)
   ============================================ */
.nav {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 1000;
  background: rgba(10, 10, 26, 0.85);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border-bottom: 1px solid rgba(0, 229, 255, 0.1);
  transition: background var(--speed-medium) var(--ease-out);
}

.nav__inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: var(--max-width);
  margin: 0 auto;
  padding: 0 var(--space-lg);
  height: var(--nav-height);
}

/* Brand / Logo */
.nav__brand {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  text-decoration: none;
  color: var(--color-text);
  flex-shrink: 0;
}

.nav__logo {
  height: 40px;
  width: auto;
  object-fit: contain;
}

.nav__brand-text {
  font-family: var(--font-nav);
  font-size: 1.2rem;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--color-primary);
}

/* Desktop nav links */
.nav__links {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

.nav__link {
  font-family: var(--font-nav);
  font-size: 0.9rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--color-text-muted);
  text-decoration: none;
  padding: var(--space-sm) var(--space-md);
  border-radius: 4px;
  transition: color var(--speed-fast), background var(--speed-fast);
  background: none;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}

.nav__link:hover,
.nav__link[aria-expanded="true"] {
  color: var(--color-primary);
  background: rgba(0, 229, 255, 0.05);
}

.nav__link--cta {
  background: var(--color-primary);
  color: var(--color-base);
  font-weight: 700;
  padding: var(--space-sm) var(--space-lg);
  border-radius: 6px;
}

.nav__link--cta:hover {
  background: #33ecff;
  color: var(--color-base);
}

/* Chevron icon */
.nav__chevron {
  transition: transform var(--speed-fast);
}

.nav__dropdown-trigger[aria-expanded="true"] .nav__chevron {
  transform: rotate(180deg);
}

/* Dropdown menu */
.nav__dropdown {
  position: relative;
}

.nav__dropdown-menu {
  position: absolute;
  top: calc(100% + var(--space-xs));
  left: 50%;
  transform: translateX(-50%);
  min-width: 220px;
  background: rgba(15, 15, 35, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(0, 229, 255, 0.15);
  border-radius: 8px;
  padding: var(--space-sm) 0;
  opacity: 0;
  visibility: hidden;
  transform: translateX(-50%) translateY(-8px);
  transition: opacity var(--speed-fast), transform var(--speed-fast), visibility var(--speed-fast);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.nav__dropdown:hover .nav__dropdown-menu,
.nav__dropdown-trigger[aria-expanded="true"] + .nav__dropdown-menu {
  opacity: 1;
  visibility: visible;
  transform: translateX(-50%) translateY(0);
}

.nav__dropdown-item {
  display: block;
  padding: var(--space-sm) var(--space-lg);
  color: var(--color-text-muted);
  text-decoration: none;
  font-family: var(--font-body);
  font-size: 0.85rem;
  transition: color var(--speed-fast), background var(--speed-fast);
}

.nav__dropdown-item:hover {
  color: var(--color-primary);
  background: rgba(0, 229, 255, 0.05);
}

.nav__dropdown-divider {
  height: 1px;
  background: rgba(0, 229, 255, 0.1);
  margin: var(--space-xs) 0;
}

/* Nav actions (lang, CTA, hamburger) */
.nav__actions {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.nav__lang-btn {
  background: none;
  border: none;
  color: var(--color-text-muted);
  cursor: pointer;
  padding: var(--space-xs);
  border-radius: 4px;
  transition: color var(--speed-fast);
  display: flex;
  align-items: center;
}

.nav__lang-btn:hover {
  color: var(--color-primary);
}

/* Hamburger button — hidden on desktop */
.nav__menu-btn {
  display: none;
  background: none;
  border: none;
  cursor: pointer;
  padding: var(--space-sm);
  position: relative;
  width: 32px;
  height: 32px;
}

.nav__menu-icon,
.nav__menu-icon::before,
.nav__menu-icon::after {
  display: block;
  width: 24px;
  height: 2px;
  background: var(--color-text);
  position: absolute;
  left: 4px;
  transition: transform var(--speed-medium) var(--ease-out), opacity var(--speed-fast);
}

.nav__menu-icon { top: 15px; }
.nav__menu-icon::before { content: ""; top: -7px; }
.nav__menu-icon::after { content: ""; top: 7px; }

/* X animation when open */
.nav__menu-btn[aria-expanded="true"] .nav__menu-icon { background: transparent; }
.nav__menu-btn[aria-expanded="true"] .nav__menu-icon::before { top: 0; transform: rotate(45deg); }
.nav__menu-btn[aria-expanded="true"] .nav__menu-icon::after { top: 0; transform: rotate(-45deg); }

/* Language overlay */
.lang-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
}

.lang-overlay[hidden] { display: none; }

.lang-overlay__panel {
  background: rgba(15, 15, 35, 0.95);
  border: 1px solid rgba(0, 229, 255, 0.2);
  border-radius: 12px;
  padding: var(--space-xl);
  max-width: 400px;
  width: 90vw;
  position: relative;
}

.lang-overlay__close {
  position: absolute;
  top: var(--space-sm);
  right: var(--space-md);
  background: none;
  border: none;
  color: var(--color-text-muted);
  font-size: 1.5rem;
  cursor: pointer;
}

.lang-overlay__title {
  font-family: var(--font-heading);
  color: var(--color-primary);
  margin-bottom: var(--space-lg);
  font-size: 1.1rem;
}

.lang-overlay__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-sm);
}

.lang-overlay__btn {
  background: rgba(0, 229, 255, 0.05);
  border: 1px solid rgba(0, 229, 255, 0.15);
  color: var(--color-text);
  padding: var(--space-sm) var(--space-md);
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.9rem;
  transition: all var(--speed-fast);
}

.lang-overlay__btn:hover,
.lang-overlay__btn.active {
  background: rgba(0, 229, 255, 0.15);
  border-color: var(--color-primary);
  color: var(--color-primary);
}

/* ============================================
   MOBILE ACCORDION NAV
   ============================================ */
.nav-mobile {
  position: fixed;
  top: var(--nav-height);
  right: 0;
  width: 85vw;
  max-width: 360px;
  max-height: 80vh;
  overflow-y: auto;
  background: rgba(10, 10, 26, 0.95);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-left: 1px solid rgba(0, 229, 255, 0.1);
  border-bottom: 1px solid rgba(0, 229, 255, 0.1);
  border-radius: 0 0 0 12px;
  z-index: 999;
  transform: translateX(100%);
  transition: transform var(--speed-medium) var(--ease-out);
  padding: var(--space-md) 0;
  display: none;
}

.nav-mobile[aria-hidden="false"] {
  transform: translateX(0);
  display: block;
}

.nav-mobile__inner {
  display: flex;
  flex-direction: column;
}

.nav-mobile__group {
  border-bottom: 1px solid rgba(0, 229, 255, 0.05);
}

.nav-mobile__trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: var(--space-md) var(--space-lg);
  background: none;
  border: none;
  color: var(--color-text);
  font-family: var(--font-nav);
  font-size: 0.95rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  cursor: pointer;
  transition: color var(--speed-fast);
}

.nav-mobile__trigger:hover {
  color: var(--color-primary);
}

.nav-mobile__chevron {
  transition: transform var(--speed-fast);
}

.nav-mobile__trigger[aria-expanded="true"] .nav-mobile__chevron {
  transform: rotate(180deg);
}

.nav-mobile__items {
  display: none;
  flex-direction: column;
  padding: 0 0 var(--space-sm) 0;
}

.nav-mobile__trigger[aria-expanded="true"] + .nav-mobile__items {
  display: flex;
}

.nav-mobile__items a {
  padding: var(--space-sm) var(--space-lg) var(--space-sm) var(--space-2xl);
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: 0.85rem;
  transition: color var(--speed-fast);
}

.nav-mobile__items a:hover {
  color: var(--color-primary);
}

.nav-mobile__direct {
  display: block;
  padding: var(--space-md) var(--space-lg);
  color: var(--color-text);
  text-decoration: none;
  font-family: var(--font-nav);
  font-size: 0.95rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-bottom: 1px solid rgba(0, 229, 255, 0.05);
  transition: color var(--speed-fast);
}

.nav-mobile__direct:hover {
  color: var(--color-primary);
}

.nav-mobile__cta {
  display: block;
  margin: var(--space-md) var(--space-lg);
  padding: var(--space-md);
  background: var(--color-primary);
  color: var(--color-base);
  text-align: center;
  text-decoration: none;
  font-family: var(--font-nav);
  font-weight: 700;
  font-size: 0.95rem;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border-radius: 6px;
  transition: background var(--speed-fast);
}

.nav-mobile__cta:hover {
  background: #33ecff;
}
```

- [ ] **Step 2: Update responsive.css for nav breakpoints**

Replace the existing nav-related responsive rules in `css/responsive.css`:

```css
/* ---- 1024px: Tablet ---- */
@media (max-width: 1024px) {
  .nav__brand-text {
    font-size: 1rem;
  }

  .nav__link {
    font-size: 0.8rem;
    padding: var(--space-xs) var(--space-sm);
  }

  .nav-mobile {
    width: 60vw;
    max-width: 320px;
  }
}

/* ---- 768px: Mobile ---- */
@media (max-width: 768px) {
  .nav__links {
    display: none;
  }

  .nav__link--cta {
    display: none;
  }

  .nav__menu-btn {
    display: block;
  }

  .nav-mobile {
    width: 85vw;
    max-width: 360px;
  }
}

/* ---- 480px: Small mobile ---- */
@media (max-width: 480px) {
  .nav__brand-text {
    font-size: 0.9rem;
  }

  .nav__logo {
    height: 32px;
  }

  .nav-mobile {
    width: 100vw;
    max-width: none;
    max-height: 80vh;
    border-radius: 0;
    border-left: none;
  }
}
```

- [ ] **Step 3: Verify CSS syntax**

```bash
# Quick syntax check — no errors should appear
grep -c '{' /mnt/archie_brain/website/kytranempowerment.com/css/components.css
grep -c '}' /mnt/archie_brain/website/kytranempowerment.com/css/components.css
```

Expected: Counts should match (balanced braces).

- [ ] **Step 4: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add css/components.css css/responsive.css
git commit -m "feat(website): nav CSS — mega-dropdown desktop + bounded accordion mobile"
```

---

## Task 4: Nav JavaScript — Dropdown + Accordion + Language

**Files:**
- Rewrite: `js/nav.js`

- [ ] **Step 1: Rewrite nav.js with dropdown and accordion logic**

Replace the entire contents of `js/nav.js`:

```javascript
/**
 * Nav — Hybrid Dropdown (Desktop) + Accordion (Mobile)
 * Handles: dropdown hover/click, mobile accordion, hamburger toggle, language overlay
 */
const Nav = (() => {
  let menuBtn, mobileNav, langBtn, langOverlay;

  function init() {
    menuBtn = document.querySelector('.nav__menu-btn');
    mobileNav = document.getElementById('navMobile');
    langBtn = document.querySelector('.nav__lang-btn');
    langOverlay = document.querySelector('.lang-overlay');

    if (!menuBtn || !mobileNav) return;

    // Hamburger toggle
    menuBtn.addEventListener('click', toggleMobile);

    // Mobile accordion triggers
    mobileNav.querySelectorAll('.nav-mobile__trigger').forEach(trigger => {
      trigger.addEventListener('click', () => toggleAccordion(trigger));
    });

    // Close mobile nav when clicking a link
    mobileNav.querySelectorAll('a').forEach(link => {
      link.addEventListener('click', closeMobile);
    });

    // Desktop dropdown keyboard support
    document.querySelectorAll('.nav__dropdown-trigger').forEach(trigger => {
      trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        const expanded = trigger.getAttribute('aria-expanded') === 'true';
        closeAllDropdowns();
        if (!expanded) {
          trigger.setAttribute('aria-expanded', 'true');
        }
      });
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
      if (!e.target.closest('.nav__dropdown')) {
        closeAllDropdowns();
      }
    });

    // Language overlay
    if (langBtn && langOverlay) {
      langBtn.addEventListener('click', () => {
        langOverlay.hidden = !langOverlay.hidden;
      });

      langOverlay.querySelector('.lang-overlay__close')?.addEventListener('click', () => {
        langOverlay.hidden = true;
      });

      langOverlay.addEventListener('click', (e) => {
        if (e.target === langOverlay) langOverlay.hidden = true;
      });

      // Language buttons dispatch to i18n system
      langOverlay.querySelectorAll('.lang-overlay__btn').forEach(btn => {
        btn.addEventListener('click', () => {
          const lang = btn.dataset.lang;
          if (window.I18n) window.I18n.setLang(lang);
          langOverlay.hidden = true;
          updateActiveLangBtn(lang);
        });
      });
    }

    // Escape key closes everything
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeMobile();
        closeAllDropdowns();
        if (langOverlay) langOverlay.hidden = true;
      }
    });

    // Highlight active language button
    const currentLang = localStorage.getItem('ke-lang') || 'en';
    updateActiveLangBtn(currentLang);
  }

  function toggleMobile() {
    const isOpen = mobileNav.getAttribute('aria-hidden') === 'false';
    if (isOpen) {
      closeMobile();
    } else {
      mobileNav.setAttribute('aria-hidden', 'false');
      menuBtn.setAttribute('aria-expanded', 'true');
      document.body.style.overflow = 'hidden';
    }
  }

  function closeMobile() {
    mobileNav.setAttribute('aria-hidden', 'true');
    menuBtn.setAttribute('aria-expanded', 'false');
    document.body.style.overflow = '';
    // Collapse all accordion sections
    mobileNav.querySelectorAll('.nav-mobile__trigger').forEach(t => {
      t.setAttribute('aria-expanded', 'false');
    });
  }

  function toggleAccordion(trigger) {
    const expanded = trigger.getAttribute('aria-expanded') === 'true';
    trigger.setAttribute('aria-expanded', expanded ? 'false' : 'true');
  }

  function closeAllDropdowns() {
    document.querySelectorAll('.nav__dropdown-trigger').forEach(t => {
      t.setAttribute('aria-expanded', 'false');
    });
  }

  function updateActiveLangBtn(lang) {
    if (!langOverlay) return;
    langOverlay.querySelectorAll('.lang-overlay__btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.lang === lang);
    });
  }

  return { init, closeMobile };
})();
```

- [ ] **Step 2: Update app.js to initialize Nav**

In `js/app.js`, verify `Nav.init()` is called on DOMContentLoaded. If it's already there, no change needed. If not, add:

```javascript
document.addEventListener('DOMContentLoaded', () => {
  Nav.init();
  // ... existing init calls
});
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add js/nav.js js/app.js
git commit -m "feat(website): nav JS — dropdown, accordion, language overlay handlers"
```

---

## Task 5: Hybrid Translation System (Static + API)

**Files:**
- Create: `js/i18n.js` (hybrid translation engine)
- Create: `data/translations.json` (static bundle — 8 languages)
- Modify: `js/app.js` (initialize I18n)
- Remove or redirect: `js/translate.js` (replaced by i18n.js)

- [ ] **Step 1: Create the static translations bundle**

Create `data/translations.json`. Start with nav keys + common UI keys for all 8 languages. The old site had 43 keys — we expand to cover all 28 pages. Begin with the nav and shared keys (~80 keys):

```json
{
  "en": {
    "nav.products": "Products",
    "nav.services": "Services",
    "nav.trust": "Trust",
    "nav.company": "Company",
    "nav.store": "Store",
    "nav.contact": "Contact",
    "nav.get_started": "Get Started",
    "nav.platform": "Platform (A.R.C.H.I.E.)",
    "nav.ai_directors": "AI Directors",
    "nav.archie_code": "ARCHIE Code CLI",
    "nav.market_watch": "Market Watch",
    "nav.civic_watch": "Civic Watch",
    "nav.legal_watch": "Legal Watch",
    "nav.gov_watch": "Gov Watch",
    "nav.business_suite": "Business Suite",
    "nav.all_services": "All Services",
    "nav.compliance_scanning": "Compliance Scanning",
    "nav.pricing": "Membership & Pricing",
    "nav.trust_center": "Trust Center",
    "nav.competitors": "Why A.R.C.H.I.E.",
    "nav.creed": "C.R.E.E.D.",
    "nav.about": "About",
    "nav.vision": "Vision",
    "nav.directory": "Directory",
    "nav.books": "Books",
    "nav.tips": "Tips & Tricks",
    "lang.choose": "Choose Language",
    "common.learn_more": "Learn More",
    "common.get_started": "Get Started",
    "common.contact_us": "Contact Us",
    "common.read_more": "Read More",
    "common.phone": "1-877-463-3352",
    "footer.copyright": "© 2026 Kytran Empowerment Inc. All rights reserved.",
    "footer.privacy": "Privacy Policy",
    "footer.terms": "Terms of Service"
  },
  "fr": {
    "nav.products": "Produits",
    "nav.services": "Services",
    "nav.trust": "Confiance",
    "nav.company": "Entreprise",
    "nav.store": "Boutique",
    "nav.contact": "Contact",
    "nav.get_started": "Commencer",
    "nav.platform": "Plateforme (A.R.C.H.I.E.)",
    "nav.ai_directors": "Directeurs IA",
    "nav.archie_code": "ARCHIE Code CLI",
    "nav.market_watch": "Market Watch",
    "nav.civic_watch": "Civic Watch",
    "nav.legal_watch": "Legal Watch",
    "nav.gov_watch": "Gov Watch",
    "nav.business_suite": "Suite Affaires",
    "nav.all_services": "Tous les services",
    "nav.compliance_scanning": "Analyse de conformité",
    "nav.pricing": "Adhésion et tarifs",
    "nav.trust_center": "Centre de confiance",
    "nav.competitors": "Pourquoi A.R.C.H.I.E.",
    "nav.creed": "C.R.E.E.D.",
    "nav.about": "À propos",
    "nav.vision": "Notre vision",
    "nav.directory": "Répertoire",
    "nav.books": "Livres",
    "nav.tips": "Trucs et astuces",
    "lang.choose": "Choisir la langue",
    "common.learn_more": "En savoir plus",
    "common.get_started": "Commencer",
    "common.contact_us": "Nous contacter",
    "common.read_more": "Lire la suite",
    "common.phone": "1-877-463-3352",
    "footer.copyright": "© 2026 Kytran Empowerment Inc. Tous droits réservés.",
    "footer.privacy": "Politique de confidentialité",
    "footer.terms": "Conditions d'utilisation"
  },
  "es": {
    "nav.products": "Productos",
    "nav.services": "Servicios",
    "nav.trust": "Confianza",
    "nav.company": "Empresa",
    "nav.store": "Tienda",
    "nav.contact": "Contacto",
    "nav.get_started": "Comenzar",
    "nav.platform": "Plataforma (A.R.C.H.I.E.)",
    "nav.ai_directors": "Directores IA",
    "nav.archie_code": "ARCHIE Code CLI",
    "nav.market_watch": "Market Watch",
    "nav.civic_watch": "Civic Watch",
    "nav.legal_watch": "Legal Watch",
    "nav.gov_watch": "Gov Watch",
    "nav.business_suite": "Suite Empresarial",
    "nav.all_services": "Todos los servicios",
    "nav.compliance_scanning": "Escaneo de cumplimiento",
    "nav.pricing": "Membresía y precios",
    "nav.trust_center": "Centro de confianza",
    "nav.competitors": "¿Por qué A.R.C.H.I.E.?",
    "nav.creed": "C.R.E.E.D.",
    "nav.about": "Acerca de",
    "nav.vision": "Nuestra visión",
    "nav.directory": "Directorio",
    "nav.books": "Libros",
    "nav.tips": "Consejos y trucos",
    "lang.choose": "Elegir idioma",
    "common.learn_more": "Más información",
    "common.get_started": "Comenzar",
    "common.contact_us": "Contáctenos",
    "common.read_more": "Leer más",
    "common.phone": "1-877-463-3352",
    "footer.copyright": "© 2026 Kytran Empowerment Inc. Todos los derechos reservados.",
    "footer.privacy": "Política de privacidad",
    "footer.terms": "Términos de servicio"
  },
  "pt": {
    "nav.products": "Produtos",
    "nav.services": "Serviços",
    "nav.trust": "Confiança",
    "nav.company": "Empresa",
    "nav.store": "Loja",
    "nav.contact": "Contato",
    "nav.get_started": "Começar",
    "nav.platform": "Plataforma (A.R.C.H.I.E.)",
    "nav.ai_directors": "Diretores IA",
    "nav.archie_code": "ARCHIE Code CLI",
    "nav.market_watch": "Market Watch",
    "nav.civic_watch": "Civic Watch",
    "nav.legal_watch": "Legal Watch",
    "nav.gov_watch": "Gov Watch",
    "nav.business_suite": "Suíte Empresarial",
    "nav.all_services": "Todos os serviços",
    "nav.compliance_scanning": "Varredura de conformidade",
    "nav.pricing": "Assinatura e preços",
    "nav.trust_center": "Centro de confiança",
    "nav.competitors": "Por que A.R.C.H.I.E.?",
    "nav.creed": "C.R.E.E.D.",
    "nav.about": "Sobre",
    "nav.vision": "Nossa visão",
    "nav.directory": "Diretório",
    "nav.books": "Livros",
    "nav.tips": "Dicas e truques",
    "lang.choose": "Escolher idioma",
    "common.learn_more": "Saiba mais",
    "common.get_started": "Começar",
    "common.contact_us": "Fale conosco",
    "common.read_more": "Leia mais",
    "common.phone": "1-877-463-3352",
    "footer.copyright": "© 2026 Kytran Empowerment Inc. Todos os direitos reservados.",
    "footer.privacy": "Política de privacidade",
    "footer.terms": "Termos de serviço"
  },
  "de": {
    "nav.products": "Produkte",
    "nav.services": "Dienste",
    "nav.trust": "Vertrauen",
    "nav.company": "Unternehmen",
    "nav.store": "Shop",
    "nav.contact": "Kontakt",
    "nav.get_started": "Loslegen",
    "nav.platform": "Plattform (A.R.C.H.I.E.)",
    "nav.ai_directors": "KI-Direktoren",
    "nav.archie_code": "ARCHIE Code CLI",
    "nav.market_watch": "Market Watch",
    "nav.civic_watch": "Civic Watch",
    "nav.legal_watch": "Legal Watch",
    "nav.gov_watch": "Gov Watch",
    "nav.business_suite": "Business Suite",
    "nav.all_services": "Alle Dienste",
    "nav.compliance_scanning": "Compliance-Scanning",
    "nav.pricing": "Mitgliedschaft & Preise",
    "nav.trust_center": "Vertrauenszentrum",
    "nav.competitors": "Warum A.R.C.H.I.E.?",
    "nav.creed": "C.R.E.E.D.",
    "nav.about": "Über uns",
    "nav.vision": "Unsere Vision",
    "nav.directory": "Verzeichnis",
    "nav.books": "Bücher",
    "nav.tips": "Tipps & Tricks",
    "lang.choose": "Sprache wählen",
    "common.learn_more": "Mehr erfahren",
    "common.get_started": "Loslegen",
    "common.contact_us": "Kontaktieren Sie uns",
    "common.read_more": "Weiterlesen",
    "common.phone": "1-877-463-3352",
    "footer.copyright": "© 2026 Kytran Empowerment Inc. Alle Rechte vorbehalten.",
    "footer.privacy": "Datenschutzrichtlinie",
    "footer.terms": "Nutzungsbedingungen"
  },
  "zh": {
    "nav.products": "产品",
    "nav.services": "服务",
    "nav.trust": "信任",
    "nav.company": "公司",
    "nav.store": "商店",
    "nav.contact": "联系",
    "nav.get_started": "开始使用",
    "nav.platform": "平台 (A.R.C.H.I.E.)",
    "nav.ai_directors": "AI 总监",
    "nav.archie_code": "ARCHIE Code CLI",
    "nav.market_watch": "市场观察",
    "nav.civic_watch": "公民观察",
    "nav.legal_watch": "法律观察",
    "nav.gov_watch": "政府观察",
    "nav.business_suite": "商务套件",
    "nav.all_services": "所有服务",
    "nav.compliance_scanning": "合规扫描",
    "nav.pricing": "会员与定价",
    "nav.trust_center": "信任中心",
    "nav.competitors": "为什么选择 A.R.C.H.I.E.？",
    "nav.creed": "C.R.E.E.D.",
    "nav.about": "关于",
    "nav.vision": "我们的愿景",
    "nav.directory": "团队目录",
    "nav.books": "书籍",
    "nav.tips": "技巧与窍门",
    "lang.choose": "选择语言",
    "common.learn_more": "了解更多",
    "common.get_started": "开始使用",
    "common.contact_us": "联系我们",
    "common.read_more": "阅读更多",
    "common.phone": "1-877-463-3352",
    "footer.copyright": "© 2026 Kytran Empowerment Inc. 版权所有。",
    "footer.privacy": "隐私政策",
    "footer.terms": "服务条款"
  },
  "ar": {
    "nav.products": "المنتجات",
    "nav.services": "الخدمات",
    "nav.trust": "الثقة",
    "nav.company": "الشركة",
    "nav.store": "المتجر",
    "nav.contact": "اتصل بنا",
    "nav.get_started": "ابدأ الآن",
    "nav.platform": "المنصة (A.R.C.H.I.E.)",
    "nav.ai_directors": "مدراء الذكاء الاصطناعي",
    "nav.archie_code": "ARCHIE Code CLI",
    "nav.market_watch": "مراقبة السوق",
    "nav.civic_watch": "المراقبة المدنية",
    "nav.legal_watch": "المراقبة القانونية",
    "nav.gov_watch": "مراقبة الحكومة",
    "nav.business_suite": "حزمة الأعمال",
    "nav.all_services": "جميع الخدمات",
    "nav.compliance_scanning": "فحص الامتثال",
    "nav.pricing": "العضوية والأسعار",
    "nav.trust_center": "مركز الثقة",
    "nav.competitors": "لماذا A.R.C.H.I.E.؟",
    "nav.creed": "C.R.E.E.D.",
    "nav.about": "عن الشركة",
    "nav.vision": "رؤيتنا",
    "nav.directory": "الدليل",
    "nav.books": "الكتب",
    "nav.tips": "نصائح وحيل",
    "lang.choose": "اختر اللغة",
    "common.learn_more": "اعرف المزيد",
    "common.get_started": "ابدأ الآن",
    "common.contact_us": "اتصل بنا",
    "common.read_more": "اقرأ المزيد",
    "common.phone": "1-877-463-3352",
    "footer.copyright": "© 2026 Kytran Empowerment Inc. جميع الحقوق محفوظة.",
    "footer.privacy": "سياسة الخصوصية",
    "footer.terms": "شروط الخدمة"
  },
  "he": {
    "nav.products": "מוצרים",
    "nav.services": "שירותים",
    "nav.trust": "אמון",
    "nav.company": "חברה",
    "nav.store": "חנות",
    "nav.contact": "צור קשר",
    "nav.get_started": "התחל עכשיו",
    "nav.platform": "פלטפורמה (A.R.C.H.I.E.)",
    "nav.ai_directors": "מנהלי בינה מלאכותית",
    "nav.archie_code": "ARCHIE Code CLI",
    "nav.market_watch": "מעקב שוק",
    "nav.civic_watch": "מעקב אזרחי",
    "nav.legal_watch": "מעקב משפטי",
    "nav.gov_watch": "מעקב ממשלתי",
    "nav.business_suite": "חבילה עסקית",
    "nav.all_services": "כל השירותים",
    "nav.compliance_scanning": "סריקת תאימות",
    "nav.pricing": "חברות ומחירים",
    "nav.trust_center": "מרכז אמון",
    "nav.competitors": "למה A.R.C.H.I.E.?",
    "nav.creed": "C.R.E.E.D.",
    "nav.about": "אודות",
    "nav.vision": "החזון שלנו",
    "nav.directory": "מדריך",
    "nav.books": "ספרים",
    "nav.tips": "טיפים וטריקים",
    "lang.choose": "בחר שפה",
    "common.learn_more": "למידע נוסף",
    "common.get_started": "התחל עכשיו",
    "common.contact_us": "צור קשר",
    "common.read_more": "קרא עוד",
    "common.phone": "1-877-463-3352",
    "footer.copyright": "© 2026 Kytran Empowerment Inc. כל הזכויות שמורות.",
    "footer.privacy": "מדיניות פרטיות",
    "footer.terms": "תנאי שירות"
  }
}
```

NOTE: This is the initial bundle with ~35 keys per language. Page-specific keys will be added in Phase 2-3 as each page is rebuilt. The API overlay handles any keys not in the static bundle.

- [ ] **Step 2: Create the hybrid i18n engine**

Create `js/i18n.js`:

```javascript
/**
 * I18n — Hybrid Translation System
 * Static bundle (instant, offline) + API overlay (updates, new keys)
 *
 * Usage: Add data-i18n="key.name" to HTML elements.
 * Call I18n.init() on DOMContentLoaded.
 * Call I18n.setLang('fr') to switch language.
 */
const I18n = (() => {
  const API_URL = 'https://api.kytranempowerment.com/api/public/translate';
  const CACHE_TTL = 24 * 60 * 60 * 1000; // 24 hours
  const STORAGE_KEY = 'ke-lang';
  const RTL_LANGS = ['ar', 'he'];

  let staticBundle = {};
  let currentLang = 'en';
  let bundleLoaded = false;

  async function init() {
    currentLang = localStorage.getItem(STORAGE_KEY) || 'en';

    // Load static bundle (instant)
    try {
      const resp = await fetch('data/translations.json');
      staticBundle = await resp.json();
      bundleLoaded = true;
    } catch (e) {
      console.warn('[I18n] Static bundle failed to load:', e);
    }

    // Apply immediately from static bundle
    if (currentLang !== 'en') {
      applyTranslations(currentLang);
    }

    // Set document direction for RTL languages
    setDirection(currentLang);
  }

  function setLang(lang) {
    currentLang = lang;
    localStorage.setItem(STORAGE_KEY, lang);
    setDirection(lang);
    applyTranslations(lang);
  }

  function setDirection(lang) {
    const dir = RTL_LANGS.includes(lang) ? 'rtl' : 'ltr';
    document.documentElement.dir = dir;
    document.documentElement.lang = lang;
  }

  function applyTranslations(lang) {
    if (lang === 'en') {
      // Restore originals
      document.querySelectorAll('[data-i18n]').forEach(el => {
        const original = el.getAttribute('data-i18n-original');
        if (original) el.textContent = original;
      });
      return;
    }

    const langBundle = staticBundle[lang] || {};
    const missingKeys = [];

    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');

      // Save original text on first translation
      if (!el.hasAttribute('data-i18n-original')) {
        el.setAttribute('data-i18n-original', el.textContent.trim());
      }

      // Try static bundle first
      if (langBundle[key]) {
        el.textContent = langBundle[key];
      } else {
        // Check localStorage cache
        const cached = getCachedTranslation(key, lang);
        if (cached) {
          el.textContent = cached;
        } else {
          missingKeys.push({ el, key, original: el.getAttribute('data-i18n-original') });
        }
      }
    });

    // Fetch missing keys from API (non-blocking)
    if (missingKeys.length > 0) {
      fetchFromAPI(missingKeys, lang);
    }
  }

  async function fetchFromAPI(missingKeys, lang) {
    for (const { el, key, original } of missingKeys) {
      try {
        const resp = await fetch(API_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            text: original,
            target_lang: lang,
            source_lang: 'en'
          })
        });

        if (resp.ok) {
          const data = await resp.json();
          if (data.translated_text) {
            el.textContent = data.translated_text;
            cacheTranslation(key, lang, data.translated_text);
          }
        }
      } catch (e) {
        // API unavailable — static bundle or original text remains
        console.debug(`[I18n] API fallback for key: ${key}`);
      }
    }
  }

  function getCachedTranslation(key, lang) {
    try {
      const raw = localStorage.getItem(`ke-t-${lang}-${key}`);
      if (!raw) return null;
      const { text, ts } = JSON.parse(raw);
      if (Date.now() - ts > CACHE_TTL) {
        localStorage.removeItem(`ke-t-${lang}-${key}`);
        return null;
      }
      return text;
    } catch {
      return null;
    }
  }

  function cacheTranslation(key, lang, text) {
    try {
      localStorage.setItem(`ke-t-${lang}-${key}`, JSON.stringify({ text, ts: Date.now() }));
    } catch {
      // localStorage full — silently fail
    }
  }

  function getLang() {
    return currentLang;
  }

  return { init, setLang, getLang };
})();
```

- [ ] **Step 3: Update app.js to initialize I18n**

In `js/app.js`, add I18n initialization after Nav:

```javascript
document.addEventListener('DOMContentLoaded', () => {
  Nav.init();
  I18n.init();
  // ... existing Effects.init(), Transitions.init()
});
```

- [ ] **Step 4: Add script tags to all HTML files**

In every HTML file, add before the closing `</body>`:

```html
<script src="js/i18n.js"></script>
```

And add the data directory for translations.json:

```bash
mkdir -p /mnt/archie_brain/website/kytranempowerment.com/data
```

- [ ] **Step 5: Remove old translate.js references**

In all HTML files, remove any `<script src="js/translate.js">` tags. The new `i18n.js` replaces it entirely.

```bash
# Find files referencing translate.js
grep -rl 'translate.js' /mnt/archie_brain/website/kytranempowerment.com/*.html
```

Remove those script tags.

- [ ] **Step 6: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add js/i18n.js data/translations.json js/app.js *.html
git rm js/translate.js 2>/dev/null || true
git commit -m "feat(website): hybrid i18n — static 8-language bundle + API overlay"
```

---

## Task 6: Fix Responsive Alignment Issues

**Files:**
- Modify: `css/responsive.css`
- Modify: `css/base.css` (if needed for global centering)

- [ ] **Step 1: Add global centering and alignment fixes**

In `css/base.css`, verify these rules exist (add if missing):

```css
/* Global content centering */
.container, .section__inner, main > section {
  max-width: var(--max-width);
  margin-left: auto;
  margin-right: auto;
  padding-left: var(--space-lg);
  padding-right: var(--space-lg);
}

/* Prevent horizontal overflow */
html {
  overflow-x: hidden;
}

* {
  box-sizing: border-box;
}
```

- [ ] **Step 2: Fix card grid alignment at breakpoints**

In `css/responsive.css`, ensure card grids center properly:

```css
/* Fix card grids at all breakpoints */
@media (max-width: 768px) {
  .card-grid {
    grid-template-columns: 1fr;
    gap: var(--space-md);
    justify-items: center;
  }

  .card-grid .card {
    max-width: 100%;
    width: 100%;
  }

  /* Ensure hero content centers */
  .hero {
    text-align: center;
  }

  .hero__stats {
    justify-content: center;
  }
}

@media (max-width: 480px) {
  /* Force single column and full width */
  .card-grid,
  .grid,
  [class*="grid"] {
    grid-template-columns: 1fr;
  }

  /* Prevent content overflow */
  img, video, iframe {
    max-width: 100%;
    height: auto;
  }

  /* Fix padding consistency */
  section {
    padding-left: var(--space-md);
    padding-right: var(--space-md);
  }
}
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add css/base.css css/responsive.css
git commit -m "fix(website): responsive centering and alignment at all breakpoints"
```

---

## Task 7: Update All HTML Files with Cache Busting + Footer

**Files:**
- Modify: All 22 HTML files

- [ ] **Step 1: Update cache bust version in all CSS/JS references**

```bash
# Update all cache busters to new date
cd /mnt/archie_brain/website/kytranempowerment.com
sed -i 's/?v=20260404/?v=20260404b/g' *.html
```

NOTE: We use `20260404b` to differentiate from the previous deploy. After the full rebuild, use the deploy date.

- [ ] **Step 2: Add phone number and complete footer to all pages**

Verify the footer in each HTML file includes the phone number. The footer should contain:

```html
<footer class="footer">
  <div class="footer__inner">
    <div class="footer__links">
      <a href="about.html" data-i18n="nav.about">About</a>
      <a href="services.html" data-i18n="nav.all_services">Services</a>
      <a href="compliance.html" data-i18n="nav.trust_center">Trust Center</a>
      <a href="contact.html" data-i18n="nav.contact">Contact</a>
      <a href="membership.html" data-i18n="nav.pricing">Pricing</a>
    </div>
    <div class="footer__contact">
      <a href="tel:+18774633352" data-i18n="common.phone">1-877-463-3352</a>
    </div>
    <div class="footer__copyright" data-i18n="footer.copyright">
      &copy; 2026 Kytran Empowerment Inc. All rights reserved.
    </div>
  </div>
</footer>
```

- [ ] **Step 3: Commit**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
git add *.html
git commit -m "feat(website): update footer with phone number + nav links on all pages"
```

---

## Task 8: Deploy and Test Phase 1

**Files:** None (deploy + verification)

- [ ] **Step 1: Deploy to Hostinger**

```bash
cd /mnt/archie_brain/website/kytranempowerment.com
tar -czf /tmp/site-phase1.tar.gz .
```

Then deploy via `mcp__hostinger-api__hosting_deployStaticWebsite`.

- [ ] **Step 2: Test in browser at all breakpoints**

Use Playwright or Chrome DevTools MCP to verify:

1. **Desktop (1024px+):** Logo visible, dropdown menus work on hover, "Get Started" CTA visible, language switcher opens overlay
2. **Tablet (768px):** Hamburger shows, accordion opens bounded (not fullscreen), content centered
3. **Mobile (480px):** Accordion menu bounded to 80vh, content single-column, no horizontal scroll
4. **Translation:** Switch to French, verify nav translates instantly from static bundle
5. **All pages:** Visit each of the 22 pages, verify nav renders correctly, no broken layout

- [ ] **Step 3: Screenshot baselines for Phase 2**

Capture screenshots of:
- Homepage at 1024px, 768px, 480px
- Nav dropdown open (desktop)
- Accordion open (mobile)
- Language overlay open
- Any page in French

- [ ] **Step 4: Commit any hotfixes discovered during testing**

```bash
git add -A
git commit -m "fix(website): phase 1 hotfixes from browser testing"
```

---

## Phase 1 Complete Checklist

- [ ] Logo restored on all pages
- [ ] Nav has mega-dropdown (desktop) with all 28-page links
- [ ] Nav has bounded accordion (mobile/tablet) — not fullscreen
- [ ] Hamburger menu sized correctly at tablet and mobile
- [ ] "Get Started" CTA in nav
- [ ] Phone number in footer
- [ ] 8-language translation working (static bundle)
- [ ] Language switcher in nav with overlay
- [ ] RTL support for Arabic/Hebrew
- [ ] Content centered at all breakpoints
- [ ] No horizontal scroll on any page
- [ ] All existing 22 pages render correctly with new nav
- [ ] Cache busting updated
- [ ] Deployed and browser tested

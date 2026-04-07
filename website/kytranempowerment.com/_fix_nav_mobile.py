#!/usr/bin/env python3
"""Fix missing nav-mobile accordion wrapper in all HTML files."""
import os, re, glob

DIR = "/mnt/archie_brain/website/kytranempowerment.com"

MOBILE_NAV = """
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
        <a href="membership.html" data-i18n="nav.pricing">Membership &amp; Pricing</a>
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
        <a href="tips.html" data-i18n="nav.tips">Tips &amp; Tricks</a>
      </div>
    </div>
    <a href="store.html" class="nav-mobile__direct" data-i18n="nav.store">Store</a>
    <a href="contact.html" class="nav-mobile__direct" data-i18n="nav.contact">Contact</a>
    <a href="membership.html" class="nav-mobile__cta" data-i18n="nav.get_started">Get Started</a>
  </div>
</div>
"""

# Regex to match orphaned links (between </nav> and next element)
ORPHAN_PATTERN = re.compile(
    r'<a\s+href="(?:store|contact|membership)\.html"\s+class="nav-mobile__(?:direct|cta)"[^>]*>[^<]*</a>\s*',
    re.DOTALL
)

# Pattern to match an existing nav-mobile div (to avoid double-inserting)
EXISTING_NAV_MOBILE = re.compile(r'<div\s+class="nav-mobile"\s+id="navMobile"', re.DOTALL)

files = glob.glob(os.path.join(DIR, "*.html"))
fixed = 0
skipped = 0

for fpath in sorted(files):
    fname = os.path.basename(fpath)
    if fname.startswith("_") or fname == "blocked.html":
        print(f"SKIP: {fname}")
        skipped += 1
        continue

    with open(fpath, "r", encoding="utf-8") as f:
        content = f.read()

    # Skip if already has navMobile div
    if EXISTING_NAV_MOBILE.search(content):
        print(f"ALREADY OK: {fname}")
        skipped += 1
        continue

    # Check for </nav> tag
    if "</nav>" not in content:
        print(f"NO NAV: {fname}")
        skipped += 1
        continue

    # Remove orphaned links
    content = ORPHAN_PATTERN.sub("", content)

    # Insert mobile nav after </nav>
    # Find the LAST </nav> (in case there are multiple)
    nav_close_idx = content.rfind("</nav>")
    if nav_close_idx == -1:
        print(f"NO NAV CLOSE: {fname}")
        skipped += 1
        continue

    insert_pos = nav_close_idx + len("</nav>")
    content = content[:insert_pos] + MOBILE_NAV + content[insert_pos:]

    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)

    fixed += 1
    print(f"FIXED: {fname}")

print(f"\nDone: {fixed} fixed, {skipped} skipped")

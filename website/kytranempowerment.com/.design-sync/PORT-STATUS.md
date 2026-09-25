# Design port status — kytranempowerment.com

The single place that says which design pages are live on the real site.
**Claude CLI updates this file in the same PR that changes a template.**
Claude Design reads it before designing anything, so it never works against
stale code, and the owner has one place to check instead of scrollback.

Status: `todo` · `nav` (shell/nav ported, body content still old) ·
`pr` (open, add number) · `merged` (on `main`) · `live` (merged AND deployed
to production, verified in a real browser)

**A merge is not a deploy on this site.** It's a static Hostinger host with
no CI hook — `main` can sit ahead of production for hours. Don't mark a row
`live` off a merged PR alone; confirm it rendered correctly on
kytranempowerment.com first.

Design file source: Claude Design's `.dc.html` handoff (visual/structural
reference only — never copied verbatim, ported by hand into the real
template preserving `data-i18n`, SEO meta, and the GA4 consent bootstrap).
Rules: `.design-sync/conventions.md`, `.design-sync/NOTES.md`.

| # | Design file | Template | Status | PR | Notes |
|---|---|---|---|---|---|
| 1 | `Home.dc.html`, `HomeMobile.dc.html` | `index.html` | live | #3446,#3447,#3450-3457,#3461,#3469,#3471,#3472 | Hero, constellation, sections ported; #3461 fixed a CDN cache-staleness bug; #3469 fixed 3 hero-stats spacing tokens; #3471 fixed 3-way inconsistent agent-count copy (FAQ/testimonial/meta); #3472 restored the missing live-status ticker strip (agents-online wired to the live directory API), Design's text-scramble title decode (a prior session had swapped it for a different effect), and a Lenis+GSAP double-raf scroll-jank bug. **#3471's own last commit was silently excluded by a stale-review-SHA race during merge — re-landed as #3472; verify the reviewed SHA matches the true PR head before merging in future, don't trust an APPROVE from a review triggered immediately after a push.** Verified live 2026-09-24 via `getComputedStyle`/DOM checks (title/tagline/stats spacing exact match, status strip renders with live agent count, zero console errors) |
| 2 | `NotFound.dc.html` | `404.html` | live | #3448 | Confirmed live 2026-09-24 (full-site deploy) |
| 3 | `Books.dc.html` | `books.html` | live | #3458 | Confirmed live 2026-09-24, zero console errors |
| 4 | `Links.dc.html` | `links.html` | live | #3458 | Confirmed live 2026-09-24 (full-site deploy) |
| 5 | `SubmitStory.dc.html` | `submit-story.html` | live | #3458 | Confirmed live 2026-09-24 (full-site deploy) |
| 6 | `Tips.dc.html` | `tips.html` | live | #3458 | Confirmed live 2026-09-24, zero console errors. Content is Claude-Code/dev-tooling tips verbatim from Design's own file — flagged for owner: is that the right audience for this page? |
| 7 | `Compliance.dc.html` | `compliance.html` | live | #3459 | New page — SOC2 grid, live scores, monitoring, framework details. Verified live 2026-09-23, zero console errors |
| 8 | `Competitors.dc.html` | `competitors.html` | nav | #3459 | Only the Trust Center nav link was repointed (now points at `compliance.html`); body content not ported |
| 9 | `ComplianceServices.dc.html` | `compliance-services.html` | nav | #3459 | Same — nav-link only |
| 10 | `CreedPage.dc.html` | `creed.html` | nav | #3459 | Same — nav-link only |
| 11 | `About.dc.html` | `about.html` | live | #3450,#3451,#3471,#3485 | Body content (Vision/Values/Team) was already ported by an earlier untracked pass — this row was stale. #3471 fixed 2 wrong icon glyphs (Transparency, Self-Improvement) + inconsistent team-size copy. #3485 fixed the Team section's founder heading, which read "Kytran Tran — Founder & CEO" — **the owner's name is just "Kytran", not "Kytran Tran"**. This was ported faithfully from Design's own source (`About.dc.html` line 62 has the identical error, while every other Kytran reference in the same file — lines 39/63/64/68 — correctly uses just "Kytran"), so it's a deliberate DEVIATION from the literal Design source, not a porting mistake. Verified live 2026-09-24 (pre-#3485), re-verified after #3485. |
| 12 | `Contact.dc.html` | `contact.html` | live | #3450,#3451,#3475 | Body content (hero, form, company info, quick links) was already ported by an earlier untracked pass — this row was stale, same pattern as About/Services. Fixed 3 literal-value fidelity gaps against Design: flex-row `gap` (3rem→2.5rem/40px), info-panel `flex-basis` (320px→300px), success-message wording ("We will"→"We'll"). The form's `action` is a literal Formspree `PLACEHOLDER` — deliberately NOT wired to a fake endpoint (no platform-side `/api/contact` exists; this is a static Hostinger site with no backend); the existing JS already degrades honestly with a "not yet configured, email us directly" message rather than a silent failure. Owner needs to either provision a real Formspree form ID or choose a different mechanism. Verified via `getComputedStyle` against Design's literal values (`gap:40px`, `flex-basis:300px` exact match), zero console errors |
| 13 | `Directory.dc.html` | `directory.html` | live | #3450,#3451,#3473 | Rebuilt agent cards to Design's horizontal layout (52px avatar left, name/type/department right, flex row, 10px radius) replacing the old vertical cards; filters rebuilt as search + type pills + department chips + live result count replacing `<select>` dropdowns. Portraits were already wired live (`avatar_thumb_url`/`avatar_url`), not a missing-asset problem. #3473's review came back coverage-demoted (one file 47% read, not a real defect — verified by reading the full file directly) and its own commit reused the prior day's `?v=` cache-buster, so the CDN kept serving pre-port CSS/JS at the same URL; both fixed and confirmed live 2026-09-24 via `getComputedStyle` (`display:flex`, `border-radius:10px`, 52px avatar) + zero console errors |
| 14 | `Vision.dc.html` | `vision.html` | pr | #3450,#3451,#3483 | Body content (3 essay panels, Four Pillars, Roadmap, CTA) was already ported word-for-word by an earlier untracked pass — this row was stale, same pattern as About/Contact/Platform/Services/Directory. #3483 fixed literal-value fidelity gaps against `Vision.dc.html` (from the 2026-09-24 design-handoff zip): essay panel padding (3rem→2.5rem/40px), essay h2 (1.8rem→1.6rem), essay p (1.05rem→1.02rem, margin 1.5rem→1.25rem), Pillars/Roadmap container width (was the site default 1200px, Design specifies 1100px), pillar icon (2.5rem→2rem)/h3 (added explicit 1.05rem, margin 0.75rem→0.6rem)/p (0.95rem→0.88rem), roadmap card padding (2rem→1.75rem)/phase label (0.85rem→0.8rem, letter-spacing 0.1em→0.08em)/h3 margin (0.75rem→0.6rem, size 1.3rem→1.2rem)/p (0.95rem→0.9rem, line-height 1.7→1.65), CTA p sizes (1.2rem/1.05rem→1.15rem/1rem). Verified via `getComputedStyle` against Design's literal values (40px/25.6px/16.32px/1100px/32px/16.8px/14.08px/28px/12.8px/19.2px — all exact matches) on a local static server, zero console errors. **NOT YET DEPLOYED — production deploy was blocked by the auto-mode classifier this session; needs the owner (or an approved session) to run `scripts/publish_website.sh` + the Hostinger deploy and confirm live before this row can move to `live`.** |
| 15 | `Platform.dc.html` | `platform.html` | live | #3450,#3451,#3477 | Body content ("Meet A.R.C.H.I.E.", stats, 17 departments by floor, architecture, capabilities, CTA) was already ported by an earlier untracked pass — same stale-row pattern as About/Services/Contact. Fixed against Design's literal values: stats-grid minmax 150px→140px, dept-grid hardcoded 3-col→auto-fill minmax(280px,1fr), floor-header margin-bottom 1.5rem→1.25rem, cta-row margin-top 2rem→2.5rem. Fixed 3 stale "50+ agents" references to 150+. Confirmed live 2026-09-25 via getComputedStyle (dept-grid genuinely responsive now, cta margin 40px), zero console errors. Done directly in-session without a subagent fork — two prior forks this session hit the Anthropic API session rate limit mid-task. |
| 16 | `ArchieCode.dc.html` | `archie-code.html` | pr | #3450,#3451,#3483 | Body content (terminal demo, features grid, how-it-works, roadmap, CTA) was already ported by an earlier untracked pass — this row was stale, same pattern as About/Contact/Directory/Platform/Vision. Unlike those, no fidelity fixes were needed against `ArchieCode.dc.html` (2026-09-24 design-handoff zip) — the LIVE content is actually AHEAD of Design's mockup: an 8th feature card for real F.O.R.G.E. PR-review (AI code review with APPROVE/REQUEST CHANGES verdicts, Telegram alerts) that Design's static file doesn't know about, an enhanced Git-Aware description mentioning the real A.R.C.H.I.E. unified-alerting system, and a CTA button wired to a real Stripe/business checkout URL instead of Design's generic membership link. Deliberately left as-is rather than reverting to Design's more generic/dated copy. Verified render on a local static server: zero console errors, terminal/features/steps/roadmap/CTA all render correctly. **NOT YET DEPLOYED — production deploy was blocked by the auto-mode classifier this session; needs the owner (or an approved session) to run `scripts/publish_website.sh` + the Hostinger deploy and confirm live before this row can move to `live`.** |
| 17 | `AiDirectors.dc.html` | `ai-directors.html` | live | #3450,#3451,#3473 | Flattened the old 5 grouped floor sections (with headers) into Design's single flat grid, each card carrying its own floor badge + 4px colored left border — this was the layout mismatch flagged against the Claude Design source. Avatar changed 80px-centered → 72px-left-aligned. Real per-agent portraits (media_studio pipeline) were already wired via `avatar_thumb_url`/`avatar_url` — no image asset was missing or needed copying from Design's placeholder set. Confirmed live 2026-09-24: 17 `.dir-card` elements, 0 floor-section wrappers, `border-left:4px`, 72px circular avatar, zero console errors |
| 18 | `AiServices.dc.html` | `ai-services.html` | pr | #3450,#3451,#3485 | Body content (watch-hero + 6 features + demo panel + CTA, reusing the shared `.watch-*` layout) was already ported word-for-word by an earlier untracked pass — this row was stale, same pattern as About/Contact/Directory/Platform/Vision/ArchieCode. #3485 fixed one stale figure not sourced from Design: the demo heading read "75+ Agents. 17 Departments." — corrected to "150+ Agents." matching the figure Platform.html already standardized on (PR #3477). Verified render on a local static server: zero console errors. **NOT YET DEPLOYED pending merge.** |
| 19 | `Membership.dc.html` | `membership.html` | nav | #3450,#3451 | |
| 20 | `SecurityServices.dc.html` | `security-services.html` | pr | #3450,#3451,#3485 | Body content (watch-hero + 6 features + demo panel + CTA) was already ported by an earlier untracked pass — this row was stale, same pattern as row 18. No fixes needed: compared line-by-line against `SecurityServices.dc.html`, content matches exactly (one feature's sentence order differs from Design but says the same thing — not a defect). Verified render on a local static server: zero console errors. **NOT YET DEPLOYED pending merge.** |
| 21 | `Services.dc.html` | `services.html` | live | #3450,#3451,#3471 | Body content was already ported by an earlier untracked pass (Standalone Products, Platform Modules, Professional/One-Time Services — the latter grown to 9 real cards beyond Design's 2). #3471 fixed inconsistent team-size copy (5 occurrences). Verified live 2026-09-24 |
| 22 | `SystemOperations.dc.html` | `system-operations.html` | nav | #3450,#3451 | |
| 23 | `WebsiteServices.dc.html` | `website-services.html` | pr | #3450,#3451,#3485 | Body content (watch-hero + 6 features + demo panel + CTA) was already ported by an earlier untracked pass — this row was stale, same pattern as row 18. No fixes needed: compared line-by-line against `WebsiteServices.dc.html`, content matches exactly. Verified render on a local static server: zero console errors. **NOT YET DEPLOYED pending merge.** |
| 24 | `WatchPage.dc.html` (shared) | `business-suite.html` | nav | #3450,#3451 | One design file covers all 5 Watch pages |
| 25 | `WatchPage.dc.html` (shared) | `civic-watch.html` | nav | #3450,#3451 | |
| 26 | `WatchPage.dc.html` (shared) | `legal-watch.html` | nav | #3450,#3451 | |
| 27 | `WatchPage.dc.html` (shared) | `market-watch.html` | nav | #3450,#3451 | |
| 28 | `WatchPage.dc.html` (shared) | `gov-watch.html` | nav | #3450,#3451 | |
| 29 | `Store.dc.html` | `store.html` | nav | #3450,#3451 | Cart/checkout content is where the real-backend-vs-localStorage-cart question gets decided |
| 30 | `Cart.dc.html` | `cart.html` | nav | #3450,#3451 | |
| 31 | `Checkout.dc.html` | `checkout.html` | nav | #3450,#3451 | |
| 32 | `OrderSuccess.dc.html` | `order-success.html` | nav | #3450,#3451 | |
| 33 | `ProductDetail.dc.html` | `product-detail.html` | nav | #3450,#3451 | |
| 34 | `Blocked.dc.html` | `blocked.html` | n/a | | Design's own note says stay faithful to source — deliberately unchanged |

Templates are the likely target by name — confirm the real filename in
`website/kytranempowerment.com/` before starting a row, and correct this
table if it differs.

---

## 13 pages have NO design file — a scope gap in Design's audit, not newer content

These are live, committed pages (Apr–Jun 2026) that no `.dc.html` handoff
covers. They are not stale by omission — Design's audit simply never
reached them. File a request for handoffs on these before touching them;
don't silently re-skin without a reference and don't leave them permanently
un-tracked either.

`what-the-fact.html` · `industry-construction.html` · `industry-electrical.html`
· `industry-limo.html` · `industry-mechanical.html` · `industry-photography.html`
· `industry-plumbing.html` · `industry-salon.html` · `certification.html`
· `signal.html` · `content-studio.html` · `agent-as-a-service.html` ·
`community.html`

---

## How a deploy actually reaches production (read before marking anything `live`)

This is a static Hostinger site — **no CI, no webhook, no auto-deploy on
merge.** The only way code on `main` reaches kytranempowerment.com:

1. `./scripts/publish_website.sh` builds `/tmp/kytranempowerment_deploy.zip`
   from the current working tree.
2. `mcp__hostinger-api__hosting_deployStaticWebsite(domain, archivePath, removeArchive=true)`
   pushes it — this REPLACES `public_html` entirely, always a full-site zip.
3. `mark_deploy_pushed(...)` records the push in `system_config` — this is
   the ONLY writer of a real `deployed` status; nothing else can know bytes
   actually landed.
4. **Cache-bust every deploy.** Hostinger's CDN caches CSS/JS at
   `max-age=604800` (7 days) per exact URL+query. If the `?v=` query string
   on `<link>`/`<script>` tags doesn't change, edge nodes that already
   cached the old file keep serving it *regardless of how many times the
   origin is redeployed* — different visitors see different versions of the
   site simultaneously. This bit the 2026-09-23 rebrand for most of a day
   (PR #3461). Bump the version string sitewide on any deploy that changes
   shared CSS/JS.

A PR merging to `main` means the code is correct. It does **not** mean a
visitor can see it. Don't tell the owner something "shipped" until you've
run steps 1–4 and verified it live in a real browser.

---

## Sitewide background layers (aurora / dot-grid / starfield canvas / ram-mark watermark)

At Design's request: audited every page against `index.html`'s background
treatment. `.aurora` and `.dot-grid` were already sitewide. The starfield
canvas (`.scroll-ambient__particles`) + drifting ram-mark watermark
(`.scroll-logo`) existed **only on `index.html`** — the JS that drives them
(`initParticles`/`initScrollAmbient` in `hero-animations.js`) was gated
behind a `.hero` element check that only the homepage has, and
`hero-animations.js` itself was only loaded on `index.html`.

Fix: extracted the particle-canvas + scroll-logo logic into a new,
dependency-free `js/ambient-background.js` (no gsap/ScrollTrigger/Lenis
needed — pure canvas + vanilla JS), loaded on every page and initialized
unconditionally from `app.js`'s Core Initialization block (no `.hero`
gate). `hero-animations.js` keeps only the genuinely hero-specific pieces
(cinematic entrance, stats counter, scroll reveals), still gated on
`.hero` as before, since those don't apply to non-hero pages.

**All 46 pages now have the same background layers as index.html**, same
markup, same z-index/opacity values, same canvas particle algorithm —
verified locally (zero console errors on a sample: about.html,
gov-watch.html) before shipping. `blocked.html` deliberately excluded
(Design's own note: stay faithful to source, don't touch it).

Touched: `404.html`, `about.html`, `agent-as-a-service.html`,
`ai-directors.html`, `ai-services.html`, `archie-code.html`, `books.html`,
`business-suite.html`, `cart.html`, `certification.html`, `checkout.html`,
`civic-watch.html`, `community.html`, `competitors.html`, `compliance.html`,
`compliance-services.html`, `contact.html`, `content-studio.html`,
`creed.html`, `directory.html`, `gov-watch.html`, `index.html`,
`industry-construction.html`, `industry-electrical.html`,
`industry-limo.html`, `industry-mechanical.html`,
`industry-photography.html`, `industry-plumbing.html`,
`industry-salon.html`, `legal-watch.html`, `links.html`,
`market-watch.html`, `membership.html`, `order-success.html`,
`platform.html`, `product-detail.html`, `security-services.html`,
`services.html`, `signal.html`, `store.html`, `submit-story.html`,
`system-operations.html`, `tips.html`, `vision.html`,
`website-services.html`, `what-the-fact.html`.

Also bumped the sitewide `?v=` cache-buster to `20260924a` (touched
JS content — see the CDN cache-busting note above; skipping this would
have reproduced the exact bug PR #3461 fixed).

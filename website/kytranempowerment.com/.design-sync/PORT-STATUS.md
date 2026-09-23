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
| 1 | `Home.dc.html`, `HomeMobile.dc.html` | `index.html` | live | #3446,#3447,#3450-3457,#3461 | Hero, constellation, sections ported; #3461 fixes a CDN cache-staleness bug that hid this behind stale `base.css` |
| 2 | `NotFound.dc.html` | `404.html` | merged | #3448 | |
| 3 | `Books.dc.html` | `books.html` | merged | #3458 | |
| 4 | `Links.dc.html` | `links.html` | merged | #3458 | |
| 5 | `SubmitStory.dc.html` | `submit-story.html` | merged | #3458 | |
| 6 | `Tips.dc.html` | `tips.html` | merged | #3458 | Content is Claude-Code/dev-tooling tips verbatim from Design's own file — flagged for owner: is that the right audience for this page? |
| 7 | `Compliance.dc.html` | `compliance.html` | pr | #3459 | New page — SOC2 grid, live scores, monitoring, framework details |
| 8 | `Competitors.dc.html` | `competitors.html` | nav | #3459 | Only the Trust Center nav link was repointed; body content not ported |
| 9 | `ComplianceServices.dc.html` | `compliance-services.html` | nav | #3459 | Same — nav-link only |
| 10 | `CreedPage.dc.html` | `creed.html` | nav | #3459 | Same — nav-link only |
| 11 | `About.dc.html` | `about.html` | nav | #3450,#3451 | Shell/nav propagated site-wide; body not ported |
| 12 | `Contact.dc.html` | `contact.html` | nav | #3450,#3451 | |
| 13 | `Directory.dc.html` | `directory.html` | nav | #3450,#3451 | |
| 14 | `Vision.dc.html` | `vision.html` | nav | #3450,#3451 | |
| 15 | `Platform.dc.html` | `platform.html` | nav | #3450,#3451 | |
| 16 | `ArchieCode.dc.html` | `archie-code.html` | nav | #3450,#3451 | |
| 17 | `AiDirectors.dc.html` | `ai-directors.html` | nav | #3450,#3451 | |
| 18 | `AiServices.dc.html` | `ai-services.html` | nav | #3450,#3451 | |
| 19 | `Membership.dc.html` | `membership.html` | nav | #3450,#3451 | |
| 20 | `SecurityServices.dc.html` | `security-services.html` | nav | #3450,#3451 | |
| 21 | `Services.dc.html` | `services.html` | nav | #3450,#3451 | |
| 22 | `SystemOperations.dc.html` | `system-operations.html` | nav | #3450,#3451 | |
| 23 | `WebsiteServices.dc.html` | `website-services.html` | nav | #3450,#3451 | |
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

repo: KytranKatarn/what-the-fact-site
branch: main

> Note: this repo is the April 2026 "Coming Soon" landing page, NOT the live
> product at what-the-fact.com. The deployed newsroom (~30 routes, map, feed,
> Blindspot, subscriber tiers) is served from a different, unconnected codebase.

## Last sync
date: 2026-09-01T16:30:36Z

### Updated in this project
- Read the landing page and stylesheet; wrote `WTF Review.dc.html` (8 findings + hero and bias-spectrum rebuilds)
- Confirmed via sitemap/changelog that the repo serves one page only
- Reviewed the live site directly for `WTF Product Review.dc.html` — map, homepage feed, Blindspot, nav, paywall

## Screen map
| Project screen | Source |
| --- | --- |
| WTF Review.dc.html — findings | repo: index.html, css/style.css |
| WTF Review.dc.html — Rebuild 01 Hero | repo: index.html (`.hero`, `.nav`), css/style.css |
| WTF Review.dc.html — Rebuild 02 Bias spectrum | repo: index.html (`.spectrum-card`), css/style.css (`.spectrum-*`) |
| WTF Product Review.dc.html — findings | live: `/`, `/map`, `/blindspot`, global nav |
| WTF Product Review.dc.html — Rebuild 01 Blindspot card | live: `/blindspot` |
| WTF Product Review.dc.html — Rebuild 02 Coverage map | live: `/map`, design system `wtf-map.js` rules |

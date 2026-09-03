# WTF homepage — applying the Design handoff's actual visual design (#6149)

**Branch:** `feat/wtf-home-design-6149` (exists, off `main` @ `c071b3c88` — superseded, see below)
**Status:** ⚠️ CORRECTED 2026-09-03 — the line below said "spec only, no code
written" and that went stale the same day it was written. Verified via
`git merge-base --is-ancestor <sha> main` before trusting either claim, not
by re-reading this file.

**What actually shipped (do not redo):**
- Recommended-order step 3 (homepage layout/typography translation) —
  PRs #3066/#3067 (`d8ff303ab`/`b8e48a200`), merged same day.
- The `.gate` (paywall) treatment from step 2 — already applied in
  `index.html` as `.wtf-gate`.
- Step 1 (shell site-wide) — `base.html`'s nav already uses translated
  `wtf-navgrp`/`wtf-nav-ico` classes.
- The remaining step-2 gap (weather strip `#wx-home`, map-index sidebar
  `#map-index`/`#ix-list`) — PR #3103 (`cf7f9a804`), merged 2026-09-03.
  `_home_weather_strip()` in `consumer/routes.py`; `#wtf-weather-strip` /
  `#wtf-map-index` in `index.html` + `style.css`.

Everything this spec originally called for is now live. Before starting
"the next phase" of this project, check what's actually still open —
this file's own body below (section map, translation table, constraints)
remains accurate reference material, only the STATUS line above was stale.

---

## 🔴 Read this first: what is NOT true

Three claims were made earlier in this project and **all three are wrong**. They are
recorded because each one costs an hour if re-derived.

| claim made | reality |
|---|---|
| "Phase 1 shipped the shell / the new design is live" | **FALSE.** What shipped was a 75-line token + accessibility block appended to the existing `style.css`. The design was never applied. The site still has the old layout and map. |
| "The handoff CSS is incompatible with our markup" | **FALSE.** The two homepages are section-for-section the same. See the id map below. |
| "Applying it means restructuring every template" | **FALSE.** It is a rename map plus a few genuinely new sections. |

The owner spotted all three. Design **did** work against the real site.

---

## The measurement that reframes the whole job

`design-handoff/wtf-shell.css` vs our live `consumer/static/style.css`:

```
design tokens: 23   ours: 33
  IDENTICAL : 18
  DIFFERENT :  5
  MISSING   :  0
```

The five differences are cosmetic:

| token | design | ours | action |
|---|---|---|---|
| `--wtf-local` | `#4a72d8` | `#3b82f6` | adopt design |
| `--wtf-aurora` | `#a78bfa` | `#8b5cf6` | adopt design |
| `--wtf-font-serif` | `'Newsreader',Georgia,serif` | same + `'Times New Roman'` | **keep ours** (more fallbacks) |
| `--wtf-font-body` | `'IBM Plex Sans',system-ui,…` | same + `'Segoe UI'` | **keep ours** |
| `--wtf-font-mono` | `'IBM Plex Mono',monospace` | same + `Consolas` | **keep ours** |

**⚠️ THE PALETTE IS ALREADY CORRECT. Do not re-token, and do not expect a colour
change.** This is exactly why the earlier token-only pass produced no visible
difference — it shipped the part that was already true.

**The redesign is LAYOUT and TYPOGRAPHY.**

---

## The payload — it lives in two files, not one

| source | size | contains |
|---|---|---|
| `design-handoff/wtf-shell.css` | 132 lines / 10.4 KB | shared shell: `.nav` sticky bar, `.brand`, `.navgrp` menus, `.wrap` (`--gut` gutters), `.phead`/`.eyebrow`/`.lede` type scale, `.card`, `.row2` grid, `.statrow`/`.stat`, `table.wtf`, `.pill` + `.p-left…p-right` lean chips, `.cardgrid`/`.mcard`, `.gate`, `.footer`, 7 media queries |
| `design-handoff/wtf-home.html` `<style>` | **251 lines** | homepage-only: `.beat-strip`/`.beat`, `.banner`/`.banner-x`, `.featured`, `.card--left/--center-left/--center/--center-right/--right` (lean-TINTED cards), `.card-title`/`.card-meta`, `.badge`/`.b-ai`/`.b-cluster`, `.act`/`.act-ico`/`.act-time`/`.act-txt`, `.ix`/`#ix-head`, `#feed`, `#editorial` |

Missing the second file is the likeliest way to do this job and still not see the
new homepage.

---

## Section map — the two homepages are the same page

Verified by comparing structural ids. Design built on our structure.

| prototype | ours (`consumer/templates/index.html`) |
|---|---|
| `.beat-strip` / `#beats` | `#wtf-beat-strip` |
| `.banner` / `#beat-banner` | `#wtf-beat-banner` |
| `.banner` / `#prov-banner` | `#wtf-province-banner` |
| `.featured` | `#wtf-featured-strip` |
| `#map-zone` | `#wtf-map-zone` |
| `#prov-select` / `#prov-menu` | `#wtf-province-selector` / `#wtf-province-dropdown` |
| `#editorial` | `#wtf-editorial` |
| `#feed` | `#wtf-feed` / `#wtf-feed-articles` |
| `.slabel` | `.wtf-section-label` |
| `.map-btn` | `.wtf-map-btn` |
| `.badge` | `.wtf-card-badge` |
| `.card-title` / `.card-meta` | `.wtf-card-title` / `.wtf-card-meta` |
| `.navgrp` / `.navgrp-menu` | `.wtf-navgrp` / `.wtf-navgrp-menu` |
| `.wtf-nav-ico` | `.wtf-nav-ico` — **already identical** |

`.wtf-nav-ico` matching exactly is the proof: the earlier `#6149` nav rebuild already
adopted the handoff's nav.

### Genuinely NEW in the prototype (no counterpart today)

- `#wx-home` / `.wxstrip` / `.wxf-head` / `.wxf-grid` / `.wxf-k` / `.wxf-n` / `.wxf-v` — a weather strip on the homepage
- `#map-row` / `#map-index` / `#ix-head` / `#ix-list` / `.ix` — a map-side index list
- `.gate` / `.gate-k` / `.gate-b` — the paywall treatment (we currently render a hand-rolled amber upsell box in `index.html` under `{% if not is_subscriber %}`)

---

## Recommended approach (owner-chosen order: 3 → 1 → 2)

**3. Homepage first.** Translate the shell + the 251 homepage lines onto our `wtf-`
names, apply to `index.html` only. Ship it, look at it, then decide.

**1. Then translate the shell site-wide** once the homepage proves the mapping holds.

**2. Then add the new structural sections** (weather strip, map index, `.gate`).

### Translation, not restructure

Prefer **renaming the design's selectors to our existing class names** over changing
our markup. Reasons:

- our templates already carry the right structure and ids
- `/blindspot`, `/clusters` and `/archive` are built on `_archetypes.html`
  (`.wtf-a-*`); changing markup fights that system for no gain
- the nav is already correct — touching it risks the dropdown-clipping bug that
  `tests/test_shell_refresh.py::test_the_nav_is_never_given_overflow` exists to catch

---

## Constraints that must survive

- **⚠️ `.wtf-nav`, `.wtf-navgrp`, `.wtf-nav-links` must never get a non-visible
  `overflow`.** A scroll container cannot have visible overflow on the other axis, so
  one `overflow-x:auto` silently clips EVERY dropdown. Pinned by
  `tests/test_shell_refresh.py`.
- **No `<style>` blocks in templates.** `tests/test_clusters_index.py` and
  `test_archive_index.py` both assert this. Homepage styles go in `style.css`.
  (`index.html` currently has one — it predates those guards; moving it is in scope.)
- **The map JS is live.** `#wtf-canada-map` is driven by existing client JS plus
  `/api/proxy/map-data`. The prototype wraps it in `#map-row`/`#map-index`. Determine
  whether that is a wrapper or a replacement **before** touching it; do not break the
  map to restyle it.
- **`_home_top_stories` ordering must not regress.** Signed-in readers get recency
  byte-identical to before, signed-out get spread-ranked. `tests/test_home_top_stories.py`
  pins it, including that the signed-in path issues no query.
- **XSS rule:** all external news content uses `element.textContent`, never `innerHTML`.
- Every `var(--x)` must resolve — an undefined custom property with no fallback is an
  invalid declaration and the browser drops the whole line silently. Pinned by
  `test_no_css_variable_is_used_without_being_defined`.

---

## Verifying

Local render (no DB writes; read-only queries):

```bash
cd what-the-fact
PW=$(grep -m1 '^DB_PASSWORD=' /mnt/archie_brain/.env | cut -d= -f2-)
WTF_ALLOW_INSECURE_SECRET=1 \
WTF_BILLING_DB_PATH=/tmp/wtf_billing_local.db \
WTF_DATABASE_URL="postgresql://archie:${PW}@192.168.1.200:5432/wtf" \
python3 -c "
from consumer.app import create_app
c = create_app().test_client()
print([ (u, c.get(u).status_code) for u in ('/','/news','/clusters','/archive','/blindspot') ])"
```

Then live, after deploy — **capture the BEFORE first**, or the change is unproven.

### Deploy (image-baked — a merge deploys NOTHING)

```bash
rsync -az --exclude='.env' --exclude='__pycache__' \
  /mnt/archie_brain/what-the-fact/ root@100.64.0.10:/opt/archie-products/what-the-fact/
ssh root@100.64.0.10 "cd /opt/archie-products/what-the-fact && \
  GIT_SHA=<sha> BUILD_TIME=\$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  docker compose up -d --build wtf-consumer"
```

Pin a rollback image first:
`docker tag $(docker inspect -f '{{.Image}}' what-the-fact-wtf-consumer-1) wtf-consumer:rollback-pre-<x>-$(date +%Y%m%d-%H%M%S)`

### Side-by-side reference

| | |
|---|---|
| current (old look) | `https://wtf.kytranempowerment.com` — basic auth `kytran`, password held by the owner |
| live | `https://www.what-the-fact.com` (301s to the apex) |

The legacy mirror is container `wtf-consumer-legacy` on Citadel :8114, image
`wtf-consumer:rollback-pre-phase1-20260902-113529`, with every backlog/alert/digest
flag disabled so it cannot double-write the shared `wtf` DB. It is `noindex` +
`Disallow: /` + basic-auth **on purpose**: that hostname used to serve a
byte-identical copy of what-the-fact.com and split SEO ranking, which is why it was a
301. ⚠️ **Do not remove the auth without restoring the 301.**

---

## Environment gotchas that cost time today

- Citadel's ingress Caddy container is named **`beacon`**, NOT `archie_ingress_caddy`
  as `.claude/rules/` says. (It also collides with the *fleet node* named Beacon at a
  different IP.) Config: `/opt/archie-ingress/Caddyfile`, Caddy v2.11.3.
- Editing that Caddyfile: **brace-count to find a block's end.** `s.index("}")` matches
  the `}` inside `{uri}` and truncates the file. Always `caddy validate` before
  `caddy reload`, and back up first.
- This app registers **no custom Jinja filters** — `|localtime` does not exist here and
  raises `TemplateAssertionError` at render time.
- `gh pr edit` can fail silently on a Projects-classic GraphQL deprecation. Re-read the
  PR to confirm; a comment is the reliable fallback.

---

## Review sizing (learned the hard way today)

`_diff_cap_for_model`: `qwen2.5:7b` **9,000** chars · `gemma3:12b` **18,768**. Measure
before opening the PR:

```bash
git diff main...HEAD -- <file> | wc -c
```

A single PR carrying helpers + route + template + tests let F.O.R.G.E. read **~2% of
`routes.py`** while still returning APPROVE. Splitting so the risky file landed alone
(4.1 KB) produced a clean APPROVE with no coverage block at all.

**⚠️ `forge:review_max_chunks` is a CEILING, not a target.** 1 → 3 helps (it enables
chunking); 3 → 5 is a literal no-op because `chunk_plan()` already asked for 3. If
coverage is thin on the risky file, **shrink the PR** — do not raise the number, and do
not ack. A coverage ack is consent to unread *tests*, never unread production code.

---

## Related

- ADR-020 — build to the DATA, not the prototype's implied dataset
- KB #301844 (max_chunks ceiling) · KB #301846 (shrink-the-PR playbook)
- `.claude/rules/wtf.md` — WTF lives in the platform monorepo at `what-the-fact/`,
  **not** `KytranKatarn/what-the-fact-site` (archived; its README was actively misleading)
- Handoff README's corrections table: `design-handoff/README.md`. ⚠️ Two of its Phase 3
  items were measured as already-fixed or not-applicable — **verify each correction
  against the live site before implementing it.**

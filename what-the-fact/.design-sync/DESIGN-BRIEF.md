# What The Fact — brief for Claude Design

Hand this to a Claude Design session verbatim. It is written to be pasted.

---

## Connect to

**`KytranKatarn/archie-platform`**, path **`what-the-fact/`**

That is the deployed source. `what-the-fact.com` runs from it.

**Do NOT connect these** — all archived April-2026 dead ends whose READMEs once
claimed to be the live site:
`what-the-fact-site` · `kytran-news` · `kytran-news-site`

**`KytranKatarn/kytran-what-the-fact`** is a *history mirror*. It has the full
602-commit history but **nothing pushed there reaches production** until a gated
cutover happens. Check its HEAD date before using it: if it is behind
`archie-platform`'s `what-the-fact/`, you would be designing against stale code.

## What this is

A Canadian news-transparency site. Flask + Jinja2 + Postgres. Server-rendered HTML,
no SPA, no build step for the app itself.

**Scale, measured 2026-09-22** — `consumer/routes.py` is **10,100 lines** carrying
**99 route decorators / 98 distinct paths** (86 `@bp.get`, 10 `@bp.post`, 3 `@bp.route`),
a mix of pages and JSON endpoints. Expect a very large single file; do not assume you
can hold it all at once, and do not reformat it wholesale.

| What | Where |
|---|---|
| Routes / pages | `consumer/routes.py` — 10,100 lines, 98 paths |
| Templates | `consumer/templates/*.html` |
| Shared shell + CSS | `consumer/static/` |
| Reusable macros | `consumer/templates/_archetypes.html` |
| Ingest / clustering / scoring | `ingest/` |
| Migrations | `migrations/` |
| Prior design handoff (39 pages) | `design-handoff/` — **read its README first** |

## Five rules that matter more than aesthetics

**1. Every number comes from Postgres. Never derive, never infer, never fill in.**
A previous handoff derived MP ridings from a slug hash and produced confident false
claims about named MPs — placing Elizabeth May in Alberta. 338 of 343 ridings are
deliberately blank. Blank is correct; invented is a defect. If you need a value the
DB does not have, leave the space empty and say so.

**2. External text is `textContent`, never `innerHTML`.**
Headlines, summaries, outlet names and author names come from RSS feeds we do not
control. `innerHTML` with that content is a live XSS hole.

**3. Colour carries meaning, and the meanings are already defined.**
Two separate axes, one resolver each, in `_archetypes.html`:
- `lean_token(bucket)` — political lean. **Green is never the centre.** Centrist is
  not "correct", and an unscored outlet reads muted, never neutral-green.
- `verdict_class(verdict)` — fact-check outcome (established / developing / contested).

The page once carried five competing lean maps and four verdict maps that disagreed;
ADR-023 collapsed them. Use the resolvers. Do not introduce a sixth palette.

**4. Tier gating is often in the template, not the route.**
A bare `{% if is_subscriber %}` in the markup is common. Moving markup can silently
expose paid content or hide free content. Check before relocating a block.

**5. Read `design-handoff/README.md` before proposing changes.**
It carries a corrections table of real defects found in the last pass — a Senate count
that rendered 93 against a stated 96, "232 fact-checked" that actually counted outlet
rows rather than stories, verdict-green used for geography on the map, lean shown for
provinces with under 20 articles, and a LIVE pill that was a dead `<span>`. Those are
the failure patterns to avoid repeating, not a list to re-fix blindly.

## How to deliver

**Open a pull request against `archie-platform`. Do not deliver a zip.**

A zip was tried and did not apply cleanly, because it was produced against code that
had drifted. A PR rebases, conflicts visibly, and gets reviewed by F.O.R.G.E. before
it can merge. Small PRs per page beat one large one.

For each change, say which template and which route it touches, and what data backs
any number you introduce.

## Done means

Rendered from live Postgres in a real browser at 480 / 768 / 1024px — not a static
mockup, and not "the HTML looks right". A page that renders beautifully with
fabricated data is a regression, not a deliverable.

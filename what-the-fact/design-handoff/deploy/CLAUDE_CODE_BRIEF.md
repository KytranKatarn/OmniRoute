# Brief for Claude Code — Phase 1: the shell

You are working in `KytranKatarn/archie-platform`, directory `what-the-fact/`,
a Flask + Jinja2 app. Read `what-the-fact/.design-sync/conventions.md` first;
it binds. Then read `what-the-fact/design-handoff/README.md` — the sections
"House conventions", "Shell — every page" and "Migration manifest".

## Task

Rebuild the site navigation and footer in `consumer/templates/base.html` to
match `design-handoff/_nav.html` and the footer in any `design-handoff/wtf-*.html`,
and add the shell rules from `design-handoff/wtf-shell.css` to
`consumer/static/style.css`.

Seven groups in this order, each a dropdown: **News · Politics · Elections ·
Money · Media · Data · About**. The exact items and hrefs are in `_nav.html`;
map each `wtf-*.html` href to its live route using the manifest table
(`wtf-mps.html` → `/mps`, `wtf-elections.html#provincial` → `/elections#provincial`,
and so on). Routes that do not exist yet (`/elections`, `/parties`, `/races`,
`/platforms`, `/archive`, `/search`, `/score`, `/cross-watch`, `/chain`,
`/edu`, `/governance`) get a minimal placeholder view in this phase so no nav
link 404s — a template extending `base.html` with the page's title, kicker and
lede copied from the design file, and nothing else.

Reuse the existing shell vocabulary where it exists (`.wtf-nav`,
`.wtf-nav-brand`, `.wtf-nav-live`, `.wtf-nav-search`, `.wtf-nav-subscribe`,
`.wtf-footer`); introduce `.wtf-nav-group` / `.wtf-nav-menu` for the dropdown
structure the current shell lacks. Port `design-handoff/wtf-nav.js` (click
toggle for touch, outside-click close) into `static/js/`.

Also add `consumer/static/dev/smoke-test.html` from `design-handoff/deploy/`.

## Acceptance

- Every existing route still renders, with the new nav and footer.
- Dropdowns open on hover **and** on tap; none is clipped. `.wtf-nav` and the
  group elements have `overflow: visible` — a scroll container on the bar
  silently clips every menu.
- The LIVE pill links to `/activity`; its label carries a class the ≤1180px
  rule can hide (see `wtf-shell.css` responsive block).
- `http://localhost:8103/static/dev/smoke-test.html` reports zero failures on
  every route, including the placeholders.
- `pytest tests/` passes. Add a test that renders `base.html` and asserts the
  seven group labels appear in order.
- The commit touching `static/style.css` contains no page-level styles.

## Do not

- Do not copy any `wtf-*.html` wholesale into `templates/` — they are design
  references with sample data and their own inline shells.
- Do not add `overflow-x: auto` to the nav to handle narrow widths; use the
  responsive collapse rules from `wtf-shell.css` (they wrap the bar at ≤820px).
- Do not read or write `sessionStorage['wtf-gate-preview']` anywhere.

## For later phases

Same shape: name the templates and routes from the manifest row, name the
database fields that replace each sample constant, state the acceptance checks
(smoke test green, tests green, numbers match a direct query), and repeat the
Phase 5 requirement verbatim — riding, province and party come from the
database, and an absent value renders an em dash, never a derivation.

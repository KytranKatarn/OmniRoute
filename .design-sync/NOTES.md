# design-sync notes — A.R.C.H.I.E.

## Shape: `styles-only` (no converter)
This repo has **no first-party JS component library** — no package.json with a build
script outside the vendored `repos/`, zero first-party `.tsx/.jsx`, no Storybook, no
component `dist/`. `archie-code` has no package.json. The UI is Flask/Jinja2 + CSS +
vanilla JS, so `package-build.mjs` cannot run and there is no `_ds_bundle.js` to ship.
Authoring React wrappers was considered and rejected (owner decision, 2026-09-01): the
skill forbids reimplementation, and wrappers would become a second source of truth that
drifts from the Jinja2 templates.

## Corrections found while syncing — the rules files are WRONG about these
- **Fonts**: the design TOKENS are **JetBrains Mono** (`--archie-font-mono`, and
  `--archie-font-body` aliases it) + **Orbitron** (`--archie-font-display`/`-heading`), and
  those are the only two `base.html` loads. No local font files exist anywhere.
  ⚠️ **A first pass at this note claimed "Antonio and IBM Plex Mono are loaded nowhere" —
  that was WRONG** and briefly went into frontend.md before the verification harness caught
  it. Both are real: individual templates load their own links (Antonio ×3, IBM Plex Mono ×4).
  The actual defect is narrower — `base.html` *references* both (`:122` Antonio, `:77` IBM
  Plex Mono) without loading either, so they fall back silently. Lesson: grepping only
  base.html's stylesheet `href`s answered "what does base.html load", not "what is used".
- **Load order**: `base.css` is **LAST** in base.html, not second; `lcars-header.css` and
  `category-nav.css` are **not loaded at all**. `.claude/rules/standalone-extraction.md`
  documents a 16-file order that does not match the template — and that file's own warning
  says a wrong order leaves a standalone "visually broken", so this matters for extraction.
- **`sc-live` / `sc-static`** (frontend.md, starbase.md) are **not** in the globally loaded
  CSS — they live in `station-ops.css`, which base.html does not load. Deliberately left
  out of the conventions header.
- **Themes**: 7 files in `css/themes/`, not 8. The 8th is `lcars-classic`, which has no
  file — it IS `theme.css`, and base.html only loads a theme override when the active theme
  is NOT lcars-classic. Importing a theme file by default would override the default look.

## Gotchas for the next sync
- `components.css` has **no bare base classes** for several families: there is no `.table`,
  `.nav`, `.stat`, `.tabs`, `.empty`. Only prefixed forms (`.table-container`, `.nav-link`,
  `.stat-card`, `.tabs-vertical`, `.empty-state`). Deriving family names by splitting on the
  first `-` invents classes that do not exist — the validation pass caught 5 of these.
- Bootstrap 5.3.2 + bootstrap-icons load from CDN before our CSS. Deliberately NOT in the
  bundle: `.row`/`.col-*` are Bootstrap's, not ours (our CSS defines `.btn` and `.card` but
  not `.row`). The header tells the agent to use `.grid`/`.flex` instead.
- Re-validate the header after any CSS change: the validator greps every documented token
  and class against `ds-bundle/**/*.css`, including the example snippet's classes.

## Sibling site syncs (2026-09-01)
Three more styles-only design systems live in per-site `.design-sync/` dirs INSIDE this
repo (each pins its own Claude Design project — repo-root config is the LCARS platform):
- `website/kytranempowerment.com/` → "Kytran Empowerment Website" (cyan/pink glass)
- `website/creed-ai.org/` → "creed-ai.org" (gold variant) — ⚠️ SYMLINK to /mnt/standalone/websites/creed-ai.org, its OWN git repo; config committed there
- `what-the-fact/` → "What The Fact" (wtf-* tokens; consumer style.css only, tech excluded)
Each has its own conventions.md + NOTES.md; validate with the same grep harness
(tokens + backtick classes + snippet classes vs ds-bundle/**/*.css).

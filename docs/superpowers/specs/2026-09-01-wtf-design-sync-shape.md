# WTF design-sync shape — spec

**Date:** 2026-09-01 · **Status:** proposal · **Supersedes:** my own suggestion earlier this
session to "widen `what-the-fact/.design-sync/config.json` past `styles-only` so `/design-sync`
ships templates + ROUTES.md."

## TL;DR — do NOT widen the shape. That proposal was wrong.

I proposed it before reading the `DesignSync` tool contract. Having read it, shipping Jinja2
templates and a routes document into a design-system project is the wrong use of that project
and would produce a pile of broken non-components.

Two different needs got conflated. They need two different mechanisms.

---

## What I got wrong, and how it was caught

`/design-sync` is **not** a repo skill — `grep` over `.claude/` finds no such skill, and
`.claude/skills/` contains only `enterprise-ui-design` and `ui-designer`. **`DesignSync` is a
first-party Claude Code tool.** The `shape` key in `.design-sync/config.json` is consumed by the
bundled `/design-sync` skill, not by anything in this repo. So "widen the shape" was never a
change we could make by editing our config in the first place.

Reading the tool contract then settled what a design-system project is FOR:

> "keep a local **component library** in sync with a Claude Design project — incrementally,
> **one component at a time**, never as a wholesale replace."

> "The Design System pane builds its card index from each **preview HTML's** first-line
> `<!-- @dsCard group="…" -->` comment (compiled into `_ds_manifest.json` by the app's
> self-check)."

Assets are **preview/spec files rendered as cards** with a `viewport` (width/height) and a
`group` label. That is the unit of content.

### Why templates + ROUTES.md fail that contract

| Artifact | Why it does not belong |
|---|---|
| 49 Jinja2 templates | Not renderable previews. `{% extends "base.html" %}`, `{{ articles }}`, `{% if is_subscriber %}` — a browser renders these as broken markup or blank. No `@dsCard` marker ⇒ no card. 49 files that render nothing. |
| `ROUTES.md` | Code context, not a design component. Markdown produces no card and no preview. |

Uploading them would leave the project structurally valid and semantically empty — the exact
failure shape this codebase keeps hitting: **a thing that looks synced while conveying nothing**
(cf. the phantom `backups` table, the declared-but-unapplied gdrive retention tier, the profile
name in `_BACKLOG_DEFAULT_PROFILE` that resolved to nothing).

## Measured current state

`DesignSync list_files` on the WTF project (`71f3c387-35fc-4956-beb5-5dff218ad1b9`), 2026-09-01:

```
css/
css/style.css
styles.css
README.md
_ds_needs_recompile
```

**Zero components. Zero cards.** Two stylesheets and a readme.

- 🔴 **CORRECTION (same day).** An earlier draft of this spec called `styles.css` and
  `css/style.css` "likely a duplicate… one of them is probably dead," and recommended removing
  one. **That was wrong, and acting on it would have broken the design system.** They are not
  duplicates — `styles.css` is the ENTRY POINT and its own header says so:

  ```css
  /*
   * styles.css — What The Fact design-system entry point.
   * ⚠️ Rendered designs receive ONLY this file's transitive @import closure.
   */
  @import url("https://fonts.googleapis.com/css2?family=Newsreader…IBM+Plex+Sans…Mono");
  @import url("./css/style.css");
  ```

  Delete `styles.css` ⇒ rendered designs receive NOTHING (that file is the closure root).
  Delete `css/style.css` ⇒ the import resolves to nothing; fonts survive, the design system does not.
  `css/style.css` is byte-identical to `consumer/static/style.css` (md5 `35ea7a3b68f8…`).

  The two-file layout is the intended `styles-only` shape and is identical in ALL THREE synced
  projects: LCARS `styles.css` 2,783 B + 10 under `css/`; kytranempowerment.com 800 B + 10;
  WTF 390 B + 1.

  **How the error happened:** I inferred "duplicate" from filename similarity in a `list_files`
  listing without opening either file. Same family as KB #300549 — deriving a claim from a name
  pattern instead of reading the artifact. A `list_files` listing shows paths, not purpose.
- ⚠️ `_ds_needs_recompile` is present, so the app self-check has not compiled `_ds_manifest.json`
  since the last write. With no `@dsCard` markers anywhere, a recompile yields an empty index
  regardless.
- Source is `sourceCssDir: consumer/static`, which holds exactly **one** CSS file — which is why
  the sync reported 3 files.

## The two needs, separated

### A. Context for a Claude Design *conversation* — SOLVED, no spec needed

Claude Design needs to see the markup it is restyling and the data each page receives. That is
conversation context, not project content.

**Mechanism:** attach `/home/kytran/wtf-design-bundle.zip` (199 K) to the Design chat.
Built 2026-09-01: 49 templates + the CSS + `README.md` + generated `ROUTES.md` (42 page routes →
template → context vars → tiered?, distilled from a 5,743-line `routes.py`).

Regenerate `ROUTES.md` when routes move — the extractor is a ~25-line regex pass over
`consumer/routes.py` pairing `@bp.(get|post|route)` with the following `render_template(...)`.
It found 42 route/template pairs from 42 route decorators, so nothing was silently dropped.

### B. A real WTF component library — the thing the project is actually for

This is the valuable work and it is **not** a config change. It is: extract the recurring UI
patterns out of the 49 templates into standalone, self-contained preview HTML with `@dsCard`
markers, so the Design System pane has real cards.

**Not proposed for now** — it is a genuine build, not a tweak. Scoping notes if it is ever taken:

- Candidate components, from the namespaced classes already in use: article card, bias/verdict
  chip (`✓ Established` / `⚡ Developing` / `⚠ Contested`), source badge, beat filter pill,
  province map legend, paywall/upgrade CTA, the nav "LIVE · N SOURCES" counter.
- Each preview must be **standalone HTML** — inline the tokens it needs, no `{% extends %}`, no
  server context. It has to render opened directly in a browser.
- First line must be `<!-- @dsCard group="…" -->` or it produces no card.
- Build incrementally. The tool is explicit: one component at a time, never wholesale.
- ⚠️ Any component showing news text must demonstrate `textContent`, never `innerHTML` — every
  string on these pages comes from an RSS feed.

**Sequencing:** do NOT start B by uploading the 49 templates as a "first pass." That is exactly
the wrong-shaped push this spec exists to prevent.

## Decision requested

1. **Confirm no shape change.** Leave all four `.design-sync/config.json` files at `styles-only`.
   They were standardised on 2026-09-01 (#3044/#3045) and are correct as they stand.
2. ~~Resolve the `styles.css` vs `css/style.css` duplicate.~~ **WITHDRAWN — there is no
   duplicate.** See the correction above. Both files are load-bearing; removing either breaks
   the design system. No action.
3. **Defer B** until there is an actual appetite for a WTF component library. File it if wanted;
   do not half-start it.

## Postscript — two wrong calls in one short spec

Worth recording, because they have the same root:

1. "Widen the shape" — proposed before reading the `DesignSync` contract.
2. "Remove the duplicate stylesheet" — proposed before opening either file.

Both were confident inferences from surface signals (a config key name; two similar filenames in
a `list_files` listing). Both dissolved the moment the actual artifact was read, and the second
would have caused real damage if executed. **A path listing tells you names, not purposes** —
which is the same lesson as KB #300549 and "an empty result is not a pass."

## Rules touched

None. No code change, no config change proposed.

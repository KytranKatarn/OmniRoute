# Standing brief for Claude CLI — porting the design

Paste this once. After that, "next page" is the whole instruction.

---

You are porting the What The Fact design into the live templates.

**Repo:** `KytranKatarn/archie-platform`, path `what-the-fact/`. Work only there.
**Spec:** `what-the-fact/design-handoff/` — HTML prototypes, one per page.
**Rules:** `what-the-fact/.design-sync/DESIGN-BRIEF.md` and
`design-handoff/README.md`. They outrank the prototypes wherever they disagree.
**Status:** `what-the-fact/design-handoff/PORT-STATUS.md`. Create it from the
copy provided if it doesn't exist.

## Setup (once)

1. Copy `PORT-STATUS.md` into `what-the-fact/design-handoff/`. Open one PR for it
   on its own.
2. Apply the two prepared PRs, `pr-01-shell-branding/` and
   `pr-02-homepage-map/`, as separate PRs, following their READMEs. Mark rows 1
   and 2 `pr` with their numbers.

## Each time I say "next page"

1. Take the lowest row marked `todo`. Tell me which one before you start.
2. Read the design file and the current template. List for me what differs,
   in plain words, before editing anything.
3. Port it:
   - Compose from the `_archetypes.html` macros; use the repo's class names over
     the prototype's.
   - Every number comes from Postgres through the route. If the DB doesn't have
     a value, leave the space blank (em dash) and say so in the PR. Never
     derive, infer or copy a sample constant from the prototype.
   - External text goes in with `textContent`. Never add `|safe` to a
     caller-supplied value.
   - Colour only through `lean_token()` / `verdict_class()`. Brand cyan is for
     identity only (logo, wordmark, live pill), never data.
   - Check every `{% if is_subscriber %}` before moving markup.
   - Page styles go in the template's own `<style>` block (except the homepage,
     whose CSS lives in `style.css` by that file's own rule). Never put a
     `style.css` change and page styles in the same commit.
4. `pytest tests/`, green.
5. Open one PR for this page only. The body lists: template, route, which DB
   fields back each number, what the design wanted that the DB can't yet give.
6. In the same PR, set the row to `pr` and add the number.
7. After merge and `./deploy.sh consumer`: check the page live at 480 / 768 /
   1024 px against the design file. Set the row to `live`, or back to `todo`
   with a note on what didn't match.

## When the design itself should change

Stop and say so. Don't redesign in the template. I'll take it back to Claude
Design, which will update the file in `design-handoff/`, and you port it again.

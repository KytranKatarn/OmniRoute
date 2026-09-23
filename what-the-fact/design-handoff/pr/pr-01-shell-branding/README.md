# PR 01 — Shell branding (logo + brand cyan)

Paste the prompt below into Claude CLI, running in a checkout of
**KytranKatarn/archie-platform** at `main` (verified against `1c28354e7f56`).

> I can't open pull requests myself — this folder is the PR, ready for Claude CLI
> to apply, commit and open.

---

```
Work only under what-the-fact/. Branch: design/pr-01-shell-branding.

1. Copy design-handoff/pr/pr-01-shell-branding/what-the-fact/consumer/static/wtf-logo.png to
   what-the-fact/consumer/static/wtf-logo.png. It is the design-handoff logo
   resized to 72x72 (2x for a 36px mark). Do NOT use design-handoff/assets/
   wtf-logo.png directly — it is 1.3 MB and would load on every page.

2. Apply the edits in design-handoff/pr/pr-01-shell-branding/changes.diff. Line numbers are
   against 1c28354e7f56; if they have drifted, apply by content — each hunk is
   a small, unique block. Do not reformat surrounding code.

3. Append this block to what-the-fact/consumer/static/style.css directly after
   the .wtf-subbrand rule (shell styles only — no page styles in this commit):

   .wtf-nav-logo {
     width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0;
     border: 1px solid #1d2b3a;
     box-shadow: 0 0 0 1px rgba(255,255,255,.07), 0 2px 10px -4px rgba(0,0,0,.9);
   }
   .wtf-nav-brand-txt { display: flex; flex-direction: column; gap: 0; }
   .wtf-wordmark b { color: var(--wtf-brand); font-weight: 700; }
   @media (max-width: 760px) { .wtf-nav-brand-txt { display: none; } }

4. pytest tests/  — must be green. tests/test_archetype_macros.py guards
   hardcoded hexes in templates; this PR adds none to templates.

5. Open the PR titled "Shell: logo + brand cyan in nav" with the body below.
```

## PR body

**Template:** `consumer/templates/base.html` (nav brand block only)
**Stylesheet:** `consumer/static/style.css` (shell rules only)
**Asset:** `consumer/static/wtf-logo.png` (72×72, new)
**Route:** none. **Data:** none — no numbers introduced.

- Round logo beside the wordmark, 36px, `alt=""` because the wordmark next to it
  already names the site.
- "THE" in `--wtf-brand` (#14bef0, already defined in style.css line ~945 and
  previously unused).
- Subbrand, LIVE label and LIVE dot move from grey/red to `--wtf-brand`. Brand
  cyan is identity only — none of these elements carry data.
- Wordmark text hides ≤760px, logo stays.

Not touched: gating, routes.py, any page template, any colour resolver.

## Check after deploy (480 / 768 / 1024 px)

- [ ] Logo shows in the nav on every page
- [ ] "THE" is cyan; subbrand is cyan
- [ ] LIVE dot and label are cyan and still link to /activity
- [ ] ≤760px: logo only, no wordmark; nav does not wrap awkwardly
- [ ] Dropdowns still open on hover and tap (no `overflow` added to nav)

## Deliberately not in this PR

- **Five more languages.** `translations.json` has empty `pt`, `de`, `zh`, `ar`,
  `he` objects. Adding their buttons now would flip `ar`/`he` pages to
  right-to-left while every string stays English. Add the buttons in the same PR
  that fills those strings from the platform's translation service.
- **Footer tagline band** and **homepage d3 map** — separate PRs, per the
  one-small-PR rule.
- Nav background is hardcoded `#050d1a` rather than `--wtf-bg-card`; flagged
  for a later shell pass, not changed here.

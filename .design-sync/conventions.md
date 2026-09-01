# A.R.C.H.I.E. — LCARS Design System

A dark, Star-Trek-LCARS-influenced system for the A.R.C.H.I.E. platform. The default look
is **`lcars-classic`**: near-black surfaces, a green terminal foreground, monospace body
text, and heavy accent-colored frame chrome.

**This system ships styles, not components.** The platform's UI is Flask/Jinja2 templates,
so there is no component bundle to import — you write your own markup and dress it in the
classes and tokens below. Everything here is verified present in the uploaded CSS.

## Setup

No provider or wrapper is required — every token is declared on `:root` in
`tokens/theme.css`, so anything inside `<body>` resolves them.

Two switches, both plain classes on `<body>`:

- `<body class="light-mode">` — `css/light-mode.css` re-declares the `--archie-*` tokens at
  body scope. Do not hand-pick light colors; toggle this class and the tokens follow.
- Alternate themes and layout families are **opt-in and not loaded by default**. See
  `css/themes/*.css` (7) and `css/layouts/*.css` (3); activate by adding one `@import`
  after `tokens/theme.css` in `styles.css`.

⚠️ Do **not** use Bootstrap grid classes (`.row`, `.col-*`). The platform loads Bootstrap
from a CDN for legacy pages, but it is not part of this system and is not uploaded here —
`.row` resolves to nothing. Use `.grid` / `.flex` with the gap utilities instead. (`.btn`
and `.card` *are* ours and are safe.)

## The styling idiom

Two layers, both in `css/components.css`, used together.

**Semantic components** — real class families, each with variants:

| Family | Notable classes |
|---|---|
| `alert` | `alert-info` `alert-success` `alert-warning` `alert-danger` `alert-title` `alert-icon` `alert-close` |
| `badge` | `badge` `badge-danger` (+ status variants) |
| `avatar` | `avatar` `avatar-sm` `avatar-lg` `avatar-xl` `avatar-group` |
| `btn` / `card` | base + variants |
| nav | `nav-brand` `nav-header` `nav-link` `nav-btn` |
| table | `table-container` `table-sortable` `table-empty` `table-empty-icon` |
| tabs | `tabs-vertical` |
| stats | `stat-card` `stat-card-mini` `stat-value` `stat-change` `stat-icon` |
| empty state | `empty-state` `empty-state-icon` `empty-state-title` `empty-state-message` |
| feedback | `progress` `spinner` `skeleton` `loading` `toast` `tooltip` `modal` |
| chrome | `breadcrumb` `sidebar` `divider` `kbd` |

⚠️ These families have **no bare base class** — there is no `.table`, `.nav`, `.stat`,
`.tabs` or `.empty`. Use the prefixed names above verbatim; a bare stem renders unstyled.

**Utilities** — a Tailwind-shaped set, same file: `flex` `grid` `gap-*` `items-*` `justify-*`
`p-*` `px-*` `py-*` `m-*` `mt-*` `mb-*` `mx-*` `my-*` `w-*` `h-*` `max-*` `min-*` `text-*`
`bg-*` `border-*` `rounded-*` `font-*` `leading-*` `tracking-*` `opacity-*` `overflow-*`
`truncate` `uppercase` `capitalize` `hidden` `relative` `absolute` `fixed` `sticky` `z-*`.

**Tokens** (268 `--archie-*`, in `tokens/theme.css`) for anything the utilities don't cover:

- Surfaces `--archie-bg-deep` `--archie-bg-card` `--archie-bg-elevated`
- Text `--archie-text-primary` (`#00ff41`) `--archie-text-secondary` `--archie-text-muted`
- Accent `--archie-accent` + `--archie-accent-alpha-5/10/20/30`, `--archie-accent-amber|blue|gold`
- Borders `--archie-border-default` `--archie-border-emphasis` `--archie-border-glow`
- Spacing `--archie-space-1` (.25rem) … `--archie-space-4` (1rem) … and up
- Radius `--archie-radius-sm|md|lg|xl` (3/6/8/12px) · Type `--archie-text-2xl..6xl`
- Fonts `--archie-font-body` (JetBrains Mono) `--archie-font-heading` (Orbitron)
  `--archie-font-mono` — body text is monospace by design; don't override it to a UI sans.

## LCARS frame chrome

The signature look. Page shell in `css/lcars-frames.css`: `lcars-body` `lcars-bar`
(`lcars-bar-title` `lcars-bar-status` `lcars-bar-spacer`) `lcars-content`
`lcars-elbow-top` `lcars-elbow-bottom` `lcars-footer-bar` (`lcars-footer-dots`
`lcars-footer-dot` `lcars-footer-stardate`).

Modals in `css/lcars-modals.css` nest in a fixed order:

```
bm-overlay > bm-shell > bm-frame (+ bm-frame-elbow-top/-bottom, bm-frame-fill,
                                   bm-frame-light)
                      + bm-content > bm-header + bm-body + bm-footer
                                     (bm-actions, bm-close, bm-footer-strip,
                                      bm-footer-dot)
```

Theme one by setting `--bm-accent` (and `--bm-accent-rgb` for alpha blends) on the overlay.

## Read the real files

Summaries go stale; the uploaded CSS does not. Before styling anything non-trivial, read
`styles.css` (the load order is commented and load-bearing — `base.css` is intentionally
LAST), then `tokens/theme.css` for exact token values, `css/components.css` for the class
list, and `css/lcars-frames.css` / `css/lcars-modals.css` for the chrome.

## Example

```html
<div class="lcars-body">
  <div class="lcars-bar">
    <span class="lcars-bar-title">DEPARTMENT HQ</span>
    <span class="lcars-bar-spacer"></span>
    <span class="lcars-bar-status">ONLINE</span>
  </div>

  <div class="lcars-content">
    <div class="grid gap-4">
      <div class="card p-4"
           style="background: var(--archie-bg-card);
                  border: 1px solid var(--archie-border-default);
                  border-radius: var(--archie-radius-md);">
        <div class="flex items-center justify-between">
          <span style="font-family: var(--archie-font-heading);">K.I.N. Welfare</span>
          <span class="badge">ACTIVE</span>
        </div>
        <p class="text-sm" style="color: var(--archie-text-secondary);">
          12 agents on duty · 2 resting
        </p>
      </div>

      <div class="alert alert-warning">
        <span class="alert-icon">!</span>
        <div>
          <div class="alert-title">Backlog above threshold</div>
          <div class="alert-message">Queue depth 412 of 500.</div>
        </div>
      </div>
    </div>
  </div>
</div>
```

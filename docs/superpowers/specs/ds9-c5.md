# DS9 Criterion 5 — Branding layer: token specification against existing assets

**Status:** specification only. No stylesheet, token, or theme is changed by this document.
**Criterion 5 asks** that *"the DS9/LCARS design names the specific `lcars.json` / `lcars.css` tokens it reuses rather than introducing new ones."*
**This document is that specification.** Every claim below was verified against the live tree and
the rendered page on 2026-10-06.

---

## 1. Correction to the premise, first

The spec names three assets and warns *"do not start a parallel theme system."* Measuring before
writing turned up two things that change the shape of the work:

**The spec's first path is wrong.** It cites `kytran-server-manager/themes/lcars.json`; the file is
at `repos/kytran-server-manager/kytran_server_manager/themes/lcars.json`.

**A parallel system has already started.** There are **three** distinct LCARS implementations, and
two of them are byte-identical copies shipped into a second product:

| Asset | Bytes | Rules | Custom props | Duplicated into |
|---|---|---|---|---|
| `kytran-business-suite/shared/theme/lcars.css` | 9,165 | 49 | 26 | — |
| `archie-comms/static/css/lcars-header.css` | 22,452 | 151 | 2 | `standalone/media_hub/.../lcars-header.css` (**byte-identical**) |
| `ds-bundle/css/lcars-frames.css` | 24,774 | 121 | 10 | `standalone/media_hub/.../lcars-frames.css` (**byte-identical**) |
| `ds-bundle/css/lcars-modals.css` | 11,036 | 84 | 0 | — |

**They share zero custom properties.** Not "one system with drift" — three implementations that
happen to share a name. So the DS9 layer cannot simply "reuse the LCARS tokens": there is no single
LCARS token set to reuse.

---

## 2. The authoritative token source, named

The platform's real token layer is **`platform_v2/static/css/`**, loaded by `base.html`:

| File | Role | Loaded by `base.html`? |
|---|---|---|
| `theme.css` | base theme | yes (line 22) |
| `light-mode.css` | **58 `--archie-*` tokens** | yes (line 30) |
| `lcars-frames.css`, `lcars-modals.css` | frame/modal chrome | yes (26, 27) |
| **`lcars-tokens.css`** | **278 custom props** | **NO — by zero templates** |

`lcars-tokens.css` is the largest token surface in the repo and **no template loads it.** It is
either dead or injected dynamically; either way it cannot be the authoritative source while it is
unreferenced.

**Recommendation:** the DS9 layer reuses **`--archie-*` from `light-mode.css`**, because that is the
token set actually resolved on the page. `lcars-tokens.css` should be either adopted (loaded, and
made the source) or deleted — but not left as a third option nobody uses.

---

## 3. Three competing namespaces, one design system

| Namespace | Count | Owner |
|---|---|---|
| `--archie-*` | 58 | platform (`light-mode.css`) — **resolved on the Contractors tab** |
| `--kbs-*` | 26 | business suite (`shared/theme/lcars.css`) |
| `--frame-*` | 10 | DS bundle / media hub frame chrome |

`--kbs-*` and `--archie-*` are near-identical in *role* (`--kbs-cyan` ≡ `--archie-cyan`,
`--kbs-bg` ≡ `--archie-bg-primary`, `--kbs-error` ≡ `--archie-danger`) and differ only in values
and naming. The DS9 layer should not adopt both. **Use `--archie-*`.**

---

## 4. Two defects found while doing this

### 4a. The Contractors tab is a dark surface with light tokens

`light-mode.css` is the **only** variant loaded anywhere — no `dark-mode.css` exists, and no
template references one. So on the Contractors tab:

```
--archie-text-primary: #111827     <- near-black
--archie-bg-primary:  #ffffff
--archie-text-muted:  #6b7280
```

resolve against a card background that renders dark (`#0a0e1a` body, per the rendered check in
PR #3679). Near-black text on a near-black card is the muted, low-contrast appearance that row
has. **This is not a token-availability bug — the tokens load fine. It is a missing dark variant.**

### 4b. `fleet.css` hardcodes 436 literal hex colours

Against an available 58-token palette. The most repeated:

| Count | Value | Note |
|---|---|---|
| 46 | `#00ffff` | |
| 35 | `#10b981` | |
| 28 | `#f59e0b` | |
| 25 | `#32CD32` | **mixed case** |
| 24 | `#00e5ff` | |
| 23 | `#FFD700` | **mixed case** |

Two spellings of the same green in one file (`#32CD32` vs a tokenised green) and mixed-case hex are
the signature of a palette that was never centralised. This is the concrete work C5 should schedule.

**Including work I added this session:** the probe button (#3669), the switch-history button (#3670)
and the narrow-width fix (#3679) each introduced literal hex (`#22d3ee`, `#fbbf24`, `#a855f7`,
`#22c55e`, `#94a3b8`). I had `--archie-*` available and did not use it. That is the exact behaviour
criterion 5 forbids, and it is recorded here rather than quietly fixed.

---

## 5. What the DS9 layer should use — the mapping

For the Contractors tab specifically. `--contractor-color` / `--contractor-rgb` already exist as
per-provider accent tokens in `fleet.css`'s vocabulary, which is the right primitive: **a provider's
identity is a token, not a hex literal.**

| Need | Token | Verified value |
|---|---|---|
| Provider accent | `--contractor-color`, `--contractor-rgb` | defined; per-provider |
| Routing ON (safe to spend) | `--archie-green` | `#00aa33` |
| Routing OFF / muted | `--archie-text-muted` | `#6b7280` |
| Configured / inactive | `--archie-text-secondary` | `#374151` |
| Warning, budget, history | `--archie-orange` | `#cc7700` |
| Danger, probe failure | `--archie-red` | `#cc2244` |
| Primary action, probe | `--archie-cyan` | `#00a0a0` |
| Edit / selection | `--archie-purple` | `#7c3aed` |

Note the ⚠ on the last four: those are **light-palette values and they will look wrong on the dark
card** until §4a is resolved. They are still the correct tokens to *name* — the palette needs a dark
variant, not a second set of literals.

---

## 6. Recommended sequence

1. **Adopt `lcars-tokens.css` or delete it.** 278 unreferenced custom properties is the largest
   source of "which token is real?". Decide before anything is built on it.
2. **Add a dark variant** of `--archie-*` and load it on dark surfaces. Without this, every token
   named in §5 is nominal.
3. **Tokenise `fleet.css`**, most-repeated first (`#00ffff` ×46, `#10b981` ×35, …). Mechanical,
   reviewable per batch, and it is where the 436 literals actually live.
4. **De-duplicate** the byte-identical `lcars-frames.css` / `lcars-header.css` copies. One source,
   referenced by both products.
5. **Fix the literals I added this session** (#3669, #3670, #3679) to use §5. Small, and it stops
   the debt growing while 3 is pending.

Steps 3–5 are separable PRs. Step 1 is a decision, not a task.

---

## 7. Decisions required

1. **Is `lcars-tokens.css` authoritative — loaded and adopted, or deleted?**
2. **Is `--archie-*` the DS9 namespace?** (§3 recommends yes.)
3. **Who owns a dark variant**, and is that in scope for DS9 or a separate piece of work?
4. **Which of the three LCARS implementations is canonical** once the byte-identical copies are
   collapsed?

---

## Provenance

Asset inventory, token counts, duplication comparison, template load order and hex-frequency counts
were all measured from the live tree on 2026-10-06. The rendered-column and clipping measurements
come from the browser check in PR #3679. **One claim I made mid-investigation was wrong and was
corrected before use:** I initially concluded `fleet.css`'s 33 undefined custom properties were a
load-order bug. `base.html` does load `theme.css` and `light-mode.css`, so the tokens resolve — the
real defect is the missing dark variant (§4a), not a missing stylesheet.

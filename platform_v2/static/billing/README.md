# Kytran Paywall — Drop-in Upgrade Overlay

A reusable tier-gated paywall component for Watch products and any
Kytran-branded surface that needs to redirect paid-tier features to
the KBS billing plugin.

Routes the **Upgrade** button to
`https://business.kytranempowerment.com/plugins/billing/checkout`
(see `plugins/kbs_billing/routes.py` in the KBS repo).

## Files

| File | Purpose |
|---|---|
| `paywall.css` | Overlay + card styles, mobile-responsive, no external deps |
| `paywall.js`  | Exposes `window.KytranPaywall.show(opts)` / `.hide()` |

## Integration

### Option 1 — CDN (simplest, recommended for Watch products)

```html
<link rel="stylesheet" href="https://platform.kytranempowerment.com/static/billing/paywall.css">
<script src="https://platform.kytranempowerment.com/static/billing/paywall.js"></script>
```

### Option 2 — vendor locally

Copy both files into your app's static directory and reference them
with your own `<link>` / `<script>` paths. Pin the version by copying
the git SHA from the commit that shipped this component.

## Usage

```js
KytranPaywall.show({
  productName: "Legal Watch",             // shown as title
  productSlug: "legal-watch",             // optional — passed as ?product= to checkout
  requiredTierSlug: "starter",            // REQUIRED — passed as ?tier= to checkout
  requiredTierLabel: "Starter",           // shown in copy + upgrade button
  currentTierLabel: "Explorer (Free)",    // shown in copy
  blurb: "Custom alerts and full jurisdictional coverage are included on Starter and above.",
  tiers: [
    { key: "free",         label: "Free" },
    { key: "starter",      label: "Starter" },
    { key: "professional", label: "Pro"   }
  ],
  features: [
    { label: "Daily news digest",   free: true,  starter: true,  professional: true  },
    { label: "All jurisdictions",   free: false, starter: true,  professional: true  },
    { label: "Custom alerts",       free: false, starter: true,  professional: true  },
    { label: "API access",          free: false, starter: false, professional: true  },
    { label: "Team workspaces",     free: false, starter: false, professional: true  }
  ]
});
```

Dismiss programmatically: `KytranPaywall.hide()`. Users can also click
outside the card or press `Esc`.

## Return URL

The component automatically sets `return_url=<current page URL>` on the
checkout link so users return to the feature they wanted after payment.

## Feature-gating tables (reference)

Use the tables from `docs/superpowers/specs/2026-04-15-unified-subscription-billing-design.md`
§3.2 for per-product defaults.

## Per-product checklist (post-freeze)

For each Watch product (Legal, Civic, Market, Gov Watch + The News):
- [ ] Vendor `paywall.css` + `paywall.js` (or reference via CDN)
- [ ] Wrap gated feature entry points with an auth + tier check
- [ ] On gate-miss, call `KytranPaywall.show({...})` with the product's
      feature-gating table from spec §3.2
- [ ] Test with a free-tier user account — redirect to KBS, complete
      test checkout in Stripe test mode, return lands on the feature

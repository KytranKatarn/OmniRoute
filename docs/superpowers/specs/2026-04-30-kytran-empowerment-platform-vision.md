# Kytran Empowerment — Full Platform Vision Spec
**Date:** 2026-04-30
**Status:** Approved for implementation
**Projects:** #264 (billing), #295 (catalogue), #296–#301 (new products), Master Project (TBD)

---

## 1. Vision

Build Kytran Empowerment's complete product platform — designed for our own AI company first, then offered to others. Every product is individually purchasable. The dashboard shows only what you've activated. Communications (email + phone + SMS) are first-class citizens alongside billing and commerce.

**Three pillars:**
1. **Commerce** — Subscriptions (KBS billing), physical/digital store (Printful + Stripe)
2. **Communications** — Email HQ (all mailboxes unified), Call Center (RingCentral/Telus + SMS)
3. **Products** — ARCHIE, Watch series, WTF, KSO, KBS, social AI, content AI, community

---

## 2. Pricing Model

### Hybrid: À la carte + Auto Bundle Discounts

Products are purchased individually. Discounts apply automatically based on active subscription count — no promo codes needed.

| Active subscriptions | Discount |
|---------------------|---------|
| 1–2 | None |
| 3–4 | 15% off total monthly |
| 5+ | 25% off total monthly |

Bundle logic is handled by KBS billing via Stripe coupon applied to the subscription. Recalculated monthly.

Store purchases (Printful, digital products) are always one-time and never discounted by bundle.

---

## 3. Full Product Catalogue

### Core Platform (Kytran Empowerment stack — built first)

| Product | Price | Status |
|---------|-------|--------|
| ARCHIE Platform (base) | $149/mo | Built |
| KBS Core (CRM, invoicing, contracts) | $79/mo | Built |
| S.I.G.N.A.L. LinkedIn AI | $99/mo | Built |
| WTF — Free tier (article feed, bias, verdicts) | Free | Built |
| WTF — Premium (audit trails, history, API) | $39/mo | Needs paywall |
| KSO Compliance (STIG/HIPAA/CIS) | $129/mo | Needs gate |

### Watch Intelligence Products

| Product | Price | Status |
|---------|-------|--------|
| Civic Watch | $99/mo | Needs gate |
| Legal Watch | $99/mo | Needs gate |
| Market Watch | $99/mo | Needs gate |
| Gov Watch (full P.R.O.C.U.R.E.) | $199/mo | Needs gate |
| Gov Watch Starter Alerts (email digest) | $49/mo | To build |

### Store — shop.kytranempowerment.com

| Product | Price | Status |
|---------|-------|--------|
| Kytran/ARCHIE branded merch (Printful) | One-time | Needs products added |
| AI art prints (P.I.X.E.L. / M.U.S.E.) | One-time | Needs products added |
| Digital products (templates, guides, prompts) | $19–$99 | Needs products added |

### Marketplace Add-ons (install/remove)

| Product | Price | Status |
|---------|-------|--------|
| KBS Industry Vertical (per vertical) | $49/mo | Needs billing gate |
| AI Content Studio (D.R.A.F.T. + I.N.K.) | $79/mo | To build |
| Agent-as-a-Service (setup + hosting) | $199 + $49/mo | To build |
| Community + AI Certification | $29/mo | To build |
| Compliance-as-a-Service | Custom quote | To build |
| KBS White-Label | Custom quote | To build |

---

## 4. Architecture

### 4.1 Access Control Model

Three-layer: **Identity (Account Center)** → **Billing (KBS)** → **Access (each product)**

```
User pays via KBS checkout
  → Stripe webhook fires to KBS
  → KBS calls Account Center API: POST /api/access/grant
  → Account Center writes to access_grants table:
      { user_id, product_slug, tier, valid_until }
  → Product checks access on login via GET /api/access/check?product=wtf-premium
  → Locked products show "Upgrade" CTA linking to KBS checkout
```

**New table: `access_grants`**
```sql
CREATE TABLE access_grants (
  id SERIAL PRIMARY KEY,
  user_id INTEGER REFERENCES users(id),
  product_slug VARCHAR(100) NOT NULL,  -- 'wtf-premium', 'civic-watch', 'kso', etc.
  source VARCHAR(50) DEFAULT 'stripe', -- 'stripe' | 'manual' | 'trial'
  valid_from TIMESTAMP DEFAULT NOW(),
  valid_until TIMESTAMP,               -- NULL = active until cancelled
  created_at TIMESTAMP DEFAULT NOW()
);
```

On Stripe `customer.subscription.deleted` or `invoice.payment_failed` → Account Center revokes access (sets valid_until = NOW()).

### 4.2 KBS Billing Dashboard (/billing)

Dedicated page in KBS nav. Custom LCARS UI — no Stripe hosted portal.

**Sections:**
1. **Current plan card** — product name, price, renewal date, Change Plan + Cancel buttons
2. **Plan picker** (shown on Change Plan click) — tier cards with proration preview before confirm
3. **Active access panel** — which products are unlocked, which are locked with Upgrade CTA
4. **Invoice history** — date, amount, status, PDF download link (Stripe invoice URL)

**Cancel flow:** Cancel at period end (not immediate). Status → `canceling`. Access retained until period expires.

**Upgrade/downgrade flow:** Stripe `subscription.update` with `proration_behavior: 'create_prorations'`. Preview proration amount before confirming.

### 4.3 Account Center Profile Redesign

Full profile replacing the current read-only subscription view.

**Sections:**
- Avatar, name, email, tier badge
- Usage stats: agents used, API calls (30d), member since
- Active products with Launch buttons (links to each product URL)
- Locked products with Upgrade CTAs (links to KBS /billing)
- Subscription summary: plan name, price, renewal date → "Manage" links to KBS /billing

### 4.4 Dashboard Cleanliness

Each product registers itself in a `marketplace_registry` table with:
- `product_slug`, `name`, `url`, `icon`, `category`, `required_plan`

The KBS and Account Center dashboards render nav and product tiles **only for active access_grants**. Installing a vertical (e.g. kbs_photography) adds it to the tenant's nav. Removing it hides it.

---

## 5. Communications Pillar

### 5.1 Email HQ

**What it is:** Unified email operations center built on top of the existing Email Manager module (`/tools/email-manager`). All 48 mailboxes (38 AI agents + 10 business) visible in one feed with sender/recipient/subject/status.

**Agent oversight:** Assign R.E.S.O.L.V.E. (Customer Success) as Email HQ manager. R.E.S.O.L.V.E. monitors:
- Unanswered emails > 24h → flags for attention
- New subscription inquiries → routes to billing flow
- Support tickets → creates KBS help desk tickets automatically
- Agent mailboxes receiving external mail → notifies relevant department director

**New Email HQ tab in Email Manager:**
- Unified inbox across all mailboxes (filter by mailbox, direction, status)
- "Assign to agent" action — routes email to specific agent for handling
- Thread view with full conversation history
- Integration with KBS help_desk — one click to create ticket from email
- Stats panel: emails/day, response rate, avg response time by mailbox

**Backend additions:**
- `email_assignments` table: email_id, assigned_agent_id, status, notes
- APScheduler job: `email_oversight` (every 30 min) — R.E.S.O.L.V.E. reviews flagged emails
- `email_rules` table: condition (from_domain, subject_contains) → action (assign_agent, create_ticket, auto_reply)

### 5.2 Call Center (RingCentral/Telus Integration)

**What exists:** `kbs_call_center` plugin (built). Hari started RingCentral configuration.

**What needs connecting:**
- RingCentral API OAuth → store credentials in `tenant_integrations` (same pattern as Stripe/Printful)
- Telus Business Line: inbound call routing, call queue management
- SMS/text number: inbound texts → appear in Call Center + trigger agent notification via Telegram
- Voicemail → transcription via Whisper/STT → stored in `call_logs` + searchable
- Click-to-call from KBS CRM contact records

**Call Center additions:**
- `call_logs` table: caller_id, direction, duration, transcription, assigned_agent, outcome
- `sms_logs` table: from_number, to_number, body, direction, created_at
- RingCentral webhook receiver: `POST /api/callcenter/webhook/ringcentral`
- SMS handler: routes inbound texts to R.E.S.O.L.V.E. for triage or auto-reply
- Call Center dashboard tab: live queue, recent calls, SMS inbox, voicemail

**Agent assignment:** R.E.S.O.L.V.E. handles triage. Human agents (Kytran + team) handle escalated calls. After-hours → voicemail + Telegram notification.

---

## 6. Printful Store

**URL:** shop.kytranempowerment.com
**Status:** `kbs_store` + Printful fully built. Needs products loaded and public URL configured.

**Product categories to add:**
1. **Merch** — Kytran/ARCHIE branded: t-shirts, hoodies, mugs, stickers. P.I.X.E.L. generates mockups.
2. **AI Art Prints** — M.U.S.E. and P.I.X.E.L. generate limited edition prints. Printed/shipped via Printful.
3. **Digital Products** — Template packs, prompt libraries, certification study guides. Delivered via download link post-purchase.

**What to build:**
- Load Printful product catalogue via `/api/printful/sync`
- Design 5–10 launch products with P.I.X.E.L. + M.U.S.E.
- Configure NPM proxy: shop.kytranempowerment.com → kbs_store public routes
- Add store link to kytranempowerment.com nav

---

## 7. Website CTA Alignment

All kytranempowerment.com pages updated to link CTAs to KBS checkout with correct `product_slug` parameter.

**Pages in scope:**
- `membership.html` — tier comparison → KBS checkout
- `civic-watch.html`, `legal-watch.html`, `market-watch.html`, `gov-watch.html` — Watch product CTAs
- `ai-services.html`, `business-suite.html`, `compliance-services.html`, `security-services.html`, `website-services.html` — service pages
- `platform.html` — ARCHIE platform CTA
- `what-the-fact.com` — WTF Premium upgrade CTA

**KBS checkout URL pattern:**
```
https://business.kytranempowerment.com/billing/checkout?product=civic-watch&return_url=https://civic.kytranempowerment.com
```

---

## 8. Marketplace Architecture

Each add-on product:
1. Has a `product_slug` registered in `marketplace_registry`
2. Can be activated/deactivated per tenant
3. Only shows in dashboard/nav when `access_grants` has an active record
4. Has its own landing page on kytranempowerment.com
5. Has a KBS marketplace card with description, price, features, activate button

**KBS Marketplace page** (`/marketplace`):
- Browse all available add-ons by category
- "Active" badge on installed products
- "Try free 14 days" button (existing trial system in `core/marketplace.py`)
- One-click activate → Stripe subscription item added → access granted

---

## 9. Implementation Phases

### Phase 0 — Foundation (1 week)
- `access_grants` table migration
- `marketplace_registry` table + seed all products
- Account Center access check API (`GET /api/access/check`, `POST /api/access/grant`)
- KBS billing webhook updated to call AC grant/revoke
- Bundle discount logic in KBS (calculate and apply Stripe coupon)

### Phase 1 — KBS Billing Dashboard (1 week)
- `/billing` route in KBS nav
- Plan card, plan picker with proration preview
- Cancel at period end flow
- Invoice history with PDF links

### Phase 2 — Account Center Profile Redesign (1 week)
- New profile page layout (avatar, tier badge, usage stats)
- Active products with Launch buttons
- Locked products with Upgrade CTAs
- Subscription summary → links to KBS /billing

### Phase 3 — Email HQ (1 week)
- Unified inbox tab in Email Manager
- `email_assignments` + `email_rules` tables
- R.E.S.O.L.V.E. oversight job (every 30 min)
- KBS help_desk ticket creation from email
- Email stats panel

### Phase 4 — Call Center (1–2 weeks)
- RingCentral OAuth flow + credential storage
- Inbound webhook receiver
- `call_logs` + `sms_logs` tables
- SMS inbox in Call Center dashboard
- Voicemail transcription pipeline
- Telegram notifications for missed calls/texts

### Phase 5 — Store Launch (1 week)
- Printful product sync + 5–10 launch products designed
- shop.kytranempowerment.com NPM proxy
- Store nav link on kytranempowerment.com
- Digital product delivery (download link post-purchase)

### Phase 6 — Product Billing Gates (1 week)
- WTF freemium paywall (consumer + tech containers)
- KSO subscription gate (Professional+ required)
- Watch products gate (Civic, Legal, Market, Gov)
- Market Watch billing gate

### Phase 7 — Website CTA Alignment (3 days)
- All 15+ pages updated with KBS checkout URLs
- Product pages updated with accurate pricing
- Store link added to nav

### Phase 8 — Marketplace Add-ons (2 weeks)
- KBS Marketplace page (`/marketplace`)
- Industry vertical billing gates (7 verticals × $49/mo)
- Industry landing pages on kytranempowerment.com
- Gov Watch Starter Alerts (weekly digest email)

### Phase 9 — New Products (ongoing)
- AI Content Studio (kbs_content_ai plugin)
- S.I.G.N.A.L.-as-a-Service (kbs_signal plugin for KBS customers)
- Agent-as-a-Service (commissioning page + delivery pipeline)
- Community portal + AI Certification program

---

## 10. Key Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Pricing model | Hybrid à la carte + auto bundle discounts | Serves niche buyers and power users |
| Upgrade/downgrade UI | Custom KBS plan picker | Full LCARS branding, no Stripe portal |
| Access control | AC grants/revokes via KBS webhook | Single source of truth, all products check AC |
| Email oversight agent | R.E.S.O.L.V.E. (Customer Success) | Natural fit — customer comms management |
| Call center platform | RingCentral (Telus business line) | Already configured by Hari, existing setup |
| Store | kbs_store + Printful (already built) | Production ready, just needs products |
| Dashboard cleanliness | Only active access_grants show in nav | Marketplace installs, dashboard reacts |

---

## 11. Out of Scope (this spec)

- Node .246/.245 GPU compute resale (future — when nodes online)
- B2B white-label KBS (future — after core is stable)
- EU AI Act compliance pack (tracked in #234)
- ARCHIE CLI public release (separate project)

# Kytran Gov Watch — Master Project Document

**Date:** 2026-05-14
**Status:** Pre-Launch
**URL:** gov.kytranempowerment.com
**Port:** 8102 (VPS — 76.13.107.109)
**Version:** 1.0

---

## Executive Summary

Kytran Gov Watch is an AI-powered Canadian federal procurement intelligence platform built for small and mid-sized businesses competing for federal contracts. It aggregates every open tender from CanadaBuys (Public Services and Procurement Canada), layers a 17-year contract history dataset on top, and deploys P.R.O.C.U.R.E. — a conversational AI agent trained on procurement methodology — to help suppliers qualify opportunities, draft bids, parse RFPs, and track award history. The product is live at gov.kytranempowerment.com and functionally complete for a v1 launch.

The platform is differentiated by its AI-first approach to a market where incumbents (Merx, BidNet Direct, GovWin IQ) offer search and alerts but no drafting, no RFP parsing, and no conversational procurement guidance. No direct Canadian AI procurement assistant competitor has been identified. This is a genuine market gap.

The product is not yet revenue-ready. Three blocking issues prevent promotion: billing limits are not enforced (any authenticated user can call AI endpoints unlimited times), the weekly digest email does not reach paying users due to a tier string mismatch, and the website pricing ($199/mo) is misaligned with the in-app pricing tiers (Free / Solo $499 / Team $1,499 / Agency $4,999). These are well-scoped bugs — none require architecture changes. Once resolved, the platform is ready for public promotion and paid acquisition.

---

## What We Have Today

### Fully Working Features

| Feature | Description |
|---|---|
| **Tender Browse** | Full CanadaBuys feed with 8 filters: department, NAICS code, province, value range, status, deadline, keyword search, and sort. Paginated. |
| **Tender Detail** | Complete tender view with partner-with list sourced directly from CanadaBuys CKAN. |
| **Tender Stats** | Aggregate dashboard: total open tenders, breakdown by department and province, average contract value, closing-this-week count. |
| **Supplier Profile Wizard** | 6-step onboarding: Company Info → NAICS Codes → Certifications → Diversity Flags → Capacity → Summary. Hard-redirect enforced until complete. |
| **AI Tender Analysis** | Async dispatch to A.R.C.H.I.E. Bridge — opportunity fit assessment scored against the supplier's profile, NAICS codes, and certifications. |
| **AI Bid Draft** | Full proposal draft generated asynchronously with a 7-retry backoff loop over 10 minutes to handle cold-model startup. |
| **PDF Export** | Branded, copy-protected PDFs via WeasyPrint + pikepdf for bid drafts and contract reports. |
| **P.R.O.C.U.R.E. Chat** | Conversational procurement AI (agent #349, Analytics & Intelligence, qwen2.5:7b) with persistent memory, full supplier context injection, NAICS descriptions, and bid team awareness. |
| **RFP Parser** | Paste or upload a PDF RFP → extract mandatory criteria, rated criteria, deliverables, and submission deadlines. |
| **Contract History Intelligence** | 17-year federal proactive disclosure dataset. Vendor profiles, department/category spend breakdowns, year-over-year charts, contract concentration analysis, expiring contracts, and first-time winner identification. |
| **Award History** | Award notices from CanadaBuys with trend analysis by winner, department, and category. Authenticated users get a "my focus" filter aligned to their NAICS/province profile. |
| **Bid Teams** | Per-bid delivery team composition tracking for Indigenous, women-led, and veteran-led set-aside eligibility. |
| **Vendor Pins** | Bookmark vendors, departments, or categories with live associated spend statistics. |
| **Deadline Alerts** | Real-time profile-matched tender alerts via email and Telegram. |
| **Weekly Digest** | Monday morning email of matched tenders, award news, and contract intelligence. *(Broken for paying users — see bugs.)* |
| **KBS CRM Integration** | One-click push of a tender as a CRM opportunity to the Kytran Business Suite. |
| **Bilingual (EN/FR)** | Full English and French support across UI and all AI-generated content. |
| **Kytran SSO** | OAuth 2.0 PKCE with refresh tokens and subscription tier sync on every login. |
| **NAICS Tree** | Seeded NAICS catalog with eligible/sibling/uncovered analysis for supplier profile building. |
| **Sample Bids** | Public sample bid drafts (IT services, construction, consulting) — no login required, for lead generation. |

---

### Known Bugs & Gaps

**Severity: CRITICAL — Blocking promotion**

1. **Billing not enforced.** Tier limits (e.g., 5 AI bid drafts/month for Solo) are display-only labels. Any authenticated user can call `/api/analyze`, `/api/draft`, and `/api/rfp-parse` unlimited times regardless of their subscription tier. This represents an unbounded compute liability and must be fixed before any paid marketing begins.

2. **Weekly digest broken for all paying users.** The digest gate checks `WHERE tier IN ('professional', 'enterprise', 'vip')` but the live tier values are `solo`, `team`, and `agency`. No paying user has ever received the Monday morning email. The digest job runs successfully — it just finds zero eligible recipients every time.

3. **Pricing misalignment between website and in-app.** The public marketing page (kytranempowerment.com/gov-watch.html) advertises $199/mo. The in-app pricing modal shows Free / Solo $499 / Team $1,499 / Agency $4,999. A prospect who clicks "Get Started" from the website will see pricing nearly 2.5× higher than expected with no explanation.

**Severity: HIGH — Impacts reliability**

4. **`get_db()` NameError in dashboard (silent fail).** The dashboard calls `get_db()`, which is not in scope — the correct function is `get_conn()`. The call is wrapped in a broad `except Exception: pass`, so it fails silently and always returns a wizard completion percentage of 0%. The dashboard stat is permanently wrong.

**Severity: MEDIUM — Known data gap**

5. **Contract overruns panel has no data.** The `amendment_value` and `original_value` columns are NULL across the CanadaBuys proactive disclosure dataset. The overruns analysis feature exists in the UI with a note explaining the data gap. No fix is possible until the upstream dataset improves.

6. **Geographic vendor split coverage ~30%.** The `vendor_country` column is sparsely populated in the contracts dataset. The geographic breakdown feature works but represents only about 30% of contracts. This is a data quality issue, not a code bug.

**Severity: LOW — Technical debt**

7. **`auth.py` tier system is vestigial dead code.** `TIER_LEVELS = {"free": 0, "viewer": 1, "pro": 2}` and the `tier_required` decorator exist in `auth.py` but are never referenced anywhere. This is a leftover from a previous tier model and creates confusion. Safe to remove.

---

## Pricing Strategy

### Current State

| Where | Tiers | Price |
|---|---|---|
| Marketing website | Unnamed "standard" plan | $199/mo CAD |
| In-app modal | Free / Solo / Team / Agency | $0 / $499 / $1,499 / $4,999/mo |
| KBS (reference) | Explorer / Starter / Professional / Enterprise | $0 / $299 / $799 / $1,499/mo |

The gap is significant and creates immediate credibility damage for any prospect who researches before buying.

### Competitive Context

| Competitor | Market | Price |
|---|---|---|
| Merx | Canada — dominant tender aggregator | ~$200–400 CAD/mo for full access |
| BidNet Direct | North America | ~$495 USD/mo |
| GovWin IQ | Enterprise (US-dominant) | $1,000+ USD/mo |
| **Kytran Gov Watch** | Canada — AI-native, no direct AI competitor identified | TBD |

The key positioning insight: incumbents offer search and alerts. Kytran Gov Watch offers search, alerts, AI qualification scoring, bid drafting, RFP parsing, contract intelligence, and a conversational procurement advisor. The AI layer justifies a meaningful premium over Merx, but the current Solo price ($499) is aggressive enough to require strong proof of value before conversion.

### Recommended Pricing (Requires Kytran Approval)

| Tier | Price | Included |
|---|---|---|
| **Free** | $0 | Browse tenders, 3 AI summaries/month, no profile |
| **Starter** | $99/mo CAD | Full browse + filters, profile, 10 AI analyses/month, deadline alerts |
| **Professional** | $199/mo CAD | Everything in Starter + unlimited AI drafts, RFP parser, contract intelligence, award history, KBS CRM push, weekly digest, bilingual AI |
| **Agency** | $499/mo CAD | Everything in Professional + bid teams, REST API access (Q4), white-label (Q4), priority P.R.O.C.U.R.E. routing |

This aligns the website's $199/mo with the Professional tier entry point, which is the most defensible position given the competitive landscape. It also creates a viable free→paid funnel via the 3-summary limit.

---

## Product Roadmap

### Q2 2026 — Pre-Launch Critical

These are blocking items. No paid promotion should launch until all are resolved.

- [ ] **Fix billing enforcement** — Gate `/api/analyze`, `/api/draft`, `/api/rfp-parse` on tier limits. Decrement counters. Return 402 with upgrade CTA on limit breach.
- [ ] **Fix weekly digest tier gate** — Change `WHERE tier IN ('professional', 'enterprise', 'vip')` to match actual tier strings (`solo`, `team`, `agency`) or map to the recommended new pricing.
- [ ] **Fix `get_db()` → `get_conn()` in dashboard** — Two-line fix. Restore accurate wizard completion stat.
- [ ] **Align pricing between website and in-app** — Adopt the recommended tier/price structure or an alternative approved by Kytran. Update both surfaces simultaneously.
- [ ] **Deploy SSO refresh tokens** — Done (PR T24).
- [ ] **Complete supplier wizard enforcement** — Done (PR T17).
- [ ] **Update kytranempowerment.com/gov-watch.html** — Align marketing copy and pricing with live product.
- [ ] **Review sample bids for quality** — Ensure public samples reflect the AI's current output quality.
- [ ] **Load test** — Concurrent tender browse + AI dispatch under realistic load (10–20 concurrent users).

### Q3 2026 — Growth

Features that increase retention and conversion after initial paid subscriber base is established.

- [ ] **Mobile-responsive UI** — Dashboard, tender browse, and P.R.O.C.U.R.E. chat optimized for field use on tablets and phones.
- [ ] **Bid Submission Tracker** — Log submitted bids, track status (submitted / shortlisted / awarded / lost), record award amounts for win-rate analytics.
- [ ] **Notification Hub** — Consolidated alerts dashboard: tender matches, approaching deadlines, new award publications. Currently only email/Telegram delivery; add in-app inbox.
- [ ] **AI Director Escalation** — Route complex bid requirements to C.O.D.E.X. (technical documentation) or G.A.V.E.L. (legal/regulatory) via A.R.C.H.I.E. Bridge for specialist handling.
- [ ] **Set-Aside Eligibility Scoring** — Auto-score each tender's Indigenous, women-owned, and veteran-led set-aside potential against the supplier's diversity profile flags.
- [ ] **Remove vestigial auth.py tier code** — Low-risk cleanup.

### Q4 2026 — Scale

Features for larger accounts and platform defensibility.

- [ ] **Partner Matching** — Joint venture partner finder for set-aside tenders. Match suppliers by overlapping NAICS codes and complementary diversity certifications.
- [ ] **Bid Template Library** — Agency tier: reusable proposal sections with version control. Build institutional knowledge across bids.
- [ ] **REST API** — Agency tier: authenticated bearer-token API for tender data, alert webhooks, and bid status. Required for integrator/reseller use cases.
- [ ] **Overruns Panel** — Populate `original_value` / `amendment_value` when CanadaBuys proactive disclosure data improves. Watch for data quality improvements in PSPC feeds.
- [ ] **Competitor Intel** — Surface who else is winning contracts in a supplier's NAICS codes and target provinces. Derived from award history dataset.
- [ ] **Government Spending Trends** — Budget forecast by department for upcoming contract waves, derived from historical spend + departmental budget announcements.
- [ ] **White-Label Option** — Agency tier: custom domain + branding for bid consultancies reselling Gov Watch analysis to their clients.

---

## Pre-Launch Checklist

### Bugs (Must Fix)
- [ ] Billing enforcement: gate AI endpoints by tier + usage counter
- [ ] Weekly digest: fix tier string mismatch
- [ ] Dashboard: fix `get_db()` → `get_conn()` NameError

### Pricing & Messaging
- [ ] Decide final tier names and price points (Kytran approval required)
- [ ] Update in-app pricing modal
- [ ] Update kytranempowerment.com/gov-watch.html price + feature list
- [ ] Update FAQ with accurate current feature list
- [ ] Align KBS pricing reference (Gov Watch as an add-on vs. standalone)

### Quality Assurance
- [ ] Review all 3 sample bids (IT services, construction, consulting) — check quality and accuracy
- [ ] End-to-end SSO login → profile wizard → tender browse → AI analysis flow
- [ ] End-to-end bid draft PDF export test
- [ ] P.R.O.C.U.R.E. chat cold-model retry behavior (10-minute backoff)
- [ ] Alert email delivery test (matching + deadline)
- [ ] Weekly digest test send to internal account

### Infrastructure
- [ ] Load test: 10–20 concurrent users browsing + AI dispatch
- [ ] Verify VPS container memory limits under load
- [ ] Confirm CanadaBuys CKAN feed ingestion is running on schedule
- [ ] Verify contract history dataset is current

### Design
- [ ] UIMAX design applied to wizard and landing page (in progress)
- [ ] Back navigation in wizard (done)
- [ ] Mobile breakpoints tested at 480px and 768px on key views

---

## Technical Architecture Notes

### Stack
- **Backend:** Python / Flask, running in Docker container `kytran_gov_watch` on VPS (76.13.107.109)
- **Database:** PostgreSQL, `gov_watch` schema on hub Postgres (192.168.1.200). Shared DB — not a standalone database.
- **AI Inference:** All LLM calls routed via A.R.C.H.I.E. Bridge (Department HQ Dispatcher). Agent: P.R.O.C.U.R.E. (#349, `qwen2.5:7b`, Analytics & Intelligence). Hub-side dispatch surface: `POST /api/procure/dispatch` with JWT bearer authentication.
- **Source files:** `/mnt/standalone/kytran-gov-watch/` (canonical — not `/mnt/archie_brain/kytran-gov-watch/` which is empty).
- **PDF generation:** WeasyPrint + pikepdf (copy protection).

### Data Sources
- **Live tenders:** CanadaBuys CKAN API (`CanadaBuysFeed` in `feeds.py`) — ingested on a scheduled basis.
- **Contract history:** PSPC proactive disclosure dataset — 17-year federal spend history, loaded into `gov_watch` schema tables.
- **Award history:** CanadaBuys award notices via CKAN.
- **NAICS:** Standard NAICS catalog seeded into DB, with eligible/sibling/uncovered analysis layer.

### Integrations
- **Kytran SSO:** OAuth 2.0 PKCE with refresh token support. Subscription tier synced from platform DB on every token exchange. All five standalone Watch products share the same SSO path.
- **KBS CRM:** HTTP push from gov-watch to Kytran Business Suite CRM opportunity endpoint.
- **Telegram:** Alert delivery for deadline notifications.
- **Email:** Alert + digest delivery via Stalwart Mail (`mail.kytranempowerment.com`).

### P.R.O.C.U.R.E. Agent Profile
- **Agent ID:** #349 | **Department:** Analytics & Intelligence | **Model:** `qwen2.5:7b`
- **Skills:** tender_match (Lv5), tender_summarize (Lv5), bid_draft (Lv4), naics_mapping (Lv4), deadline_alert (Lv3), award_history_analysis (Lv3), sosa_navigation (Lv3), supplier_profile (Lv3)
- **Competitive positioning:** Beats the federal government's own Procura chatbot by personalizing to the supplier profile, extracting RFP criteria as checklists, and refusing to deflect users to phone lines. (KB #258941)
- **Dispatch path:** Hub bridge dispatch surface at `POST /api/procure/dispatch`. System prompt auto-loaded from `agents.system_prompt` — persona opens with "Procure here."

---

## Feature Ideas for Future Sessions

*Not committed — parking lot for ideas worth exploring when capacity allows.*

- **Competitor spend intelligence:** Show which companies are currently winning in a supplier's target NAICS/province/department combination, with win rate and average contract size. Derived from existing award history dataset.
- **Budget season alerts:** Notify suppliers when their target departments publish procurement plans or budget supplementary estimates — high-signal events that precede RFP waves.
- **Bid win/loss analysis:** After enough bid submissions are tracked, run pattern analysis on what separates winning from losing bids in a given category. Requires Bid Submission Tracker (Q3 roadmap) as a prerequisite.
- **Mentor network:** Match first-time bidders with experienced suppliers in the same NAICS who are open to JV or subcontracting. Extension of the Partner Matching feature.
- **Compliance calendar:** Track supplier certification renewal dates (ISO, COR, Indigenous certification, etc.) and alert before expiry — active certifications affect bid eligibility.
- **Departmental buyer profiles:** Aggregate behavioral patterns of federal contracting officers by department — which departments prefer low-cost bids, which prefer past-performance narrative, which run open competitions vs. advance contract award notices.
- **Public API for brokers:** Bid consultancies and procurement brokers could resell Gov Watch analysis under their own brand. Requires white-label + REST API from Q4 roadmap.
- **French-market expansion:** While the product is bilingual today, active marketing in Quebec and Francophone communities (OSBL, coopératives) is an untapped segment. Federal set-aside programs for Indigenous communities in Quebec are underserved by existing tools.
- **Provincial tender feeds:** CanadaBuys covers federal contracts. Adding MERX provincial feeds (Ontario, BC, Alberta) would expand TAM significantly. Requires separate feed parser and data model extension.
- **Telegram bot interface:** Allow suppliers to query P.R.O.C.U.R.E. via Telegram for quick tender lookups and deadline reminders without opening the web UI. A.R.C.H.I.E. Comms already provides the infrastructure.

---

*Document owner: Kytran Katarn / A.R.C.H.I.E. Platform*
*Next review: After pre-launch checklist completion*
*KB reference: Search `search_knowledge` with tags ["gov_watch", "procurement", "procure"]`*

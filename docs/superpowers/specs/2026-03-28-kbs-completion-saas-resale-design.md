# Kytran Business Suite — Completion, Integration & SaaS Resale Design

**Date:** 2026-03-28
**Project:** #196 — Unified Business Suite
**Status:** Approved
**Scope:** 4-wave progressive launch + P.R.O.C.U.R.E. standalone product

---

## Product Vision

A modular SaaS business operating system that Kytran Empowerment uses internally AND resells to clients. AI-first website builder, omnichannel communications, self-serve billing, and industry-specific tooling.

## Architecture

- **Codebase:** `/mnt/archie_brain/kytran-business-suite/`
- **Stack:** Flask + PostgreSQL (schema-per-tenant) + Redis + Docker
- **Plugins:** 22 total (14 core + 8 industry), manifest-based discovery
- **AI:** ARCHIE Bridge dispatch for all inference
- **Hosting:** Hostinger for client websites + domain management + Reach email marketing
- **Billing:** Stripe (checkout, subscriptions, add-ons, metering)
- **Phone/SMS:** RingCentral via Telus Biz Connect
- **Port:** 8091 (mapped from internal 8090)
- **Docker:** kbs_app, kbs_worker, kbs_redis
- **DB:** ARCHIE's PostgreSQL, schema `tenant_1` for Kytran, `tenant_N` for clients

---

## Wave 1 — Core + Website Builder (The Hook)

### Goal
A working business platform where Kytran Empowerment and first clients can manage contacts, send invoices, book appointments, handle support tickets, and build AI-generated websites.

### Plugin Completion

| Plugin | Current State | Work Needed |
|--------|--------------|-------------|
| `kbs_crm` | Has routes | Verify full CRUD, add search, segment filtering |
| `kbs_invoicing` | Schema only | Complete routes: create/send/pay/track, PDF generation, email delivery via SMTP |
| `kbs_appointments` | Schema only | Service types, availability slots, booking flow. Standalone booking page + embeddable widget |
| `kbs_help_desk` | Has routes | Verify ticket CRUD, add email intake (inbound email → ticket), SLA tracking |
| `kbs_website_builder` | CRUD routes, no deploy | Wire Hostinger deploy, template system, text-to-design AI flow |
| `kbs_store` | Schema only | Basic product catalog + order tracking (invoicing integration) |

### Text-to-Design Website Builder

**Flow:**
1. Client opens Website Builder → picks "Start from scratch" or "Start from template"
2. **From scratch:** Client describes business in text box (e.g., "I run a hair salon in Ottawa called Luxe Cuts, modern and minimal, online booking")
3. KBS sends prompt to ARCHIE Bridge → AI generates complete HTML/CSS site (multi-page: home, about, services, contact, booking)
4. Client previews in live iframe → types refinements ("make the header darker", "add a testimonial section")
5. Each refinement re-generates via Bridge with conversation context
6. Client clicks "Deploy" → KBS calls Hostinger MCP `hosting_deployStaticWebsite` → site goes live
7. **From template:** Client picks industry template → template pre-fills AI context → same refinement flow

**Templates:**
- Reuse CRM template pattern — stored in DB
- Fields: `name`, `category` (industry), `thumbnail`, `base_prompt` (AI context), `base_html` (starter markup)
- Templates are AI starting points, not rigid layouts — client text still drives customization

### Email (SMTP)
- Wire existing `mail_client.py` to send via configured SMTP
- Transactional emails: invoice sent, appointment confirmed, ticket updated, booking received
- Configure with Kytran Empowerment's mail server credentials

### Auth & Onboarding
- Existing auth works (email + Google OAuth)
- Add onboarding wizard: business name → industry → timezone → logo upload → first plugin activation
- Free tier auto-activates: CRM, Invoicing, Store, Automations

### Booking
- Standalone page: `book.kytranempowerment.com/{clientslug}`
- Embeddable widget: `<script src="kbs.../booking-widget.js" data-client="slug"></script>`
- KBS-built websites: booking section auto-integrated

### Not in Wave 1
- No phone/SMS, no RingCentral
- No Stripe billing (manual client management)
- No marketplace
- No industry plugins
- No knowledge base

---

## Wave 2 — Communications Stack

### Goal
Full omnichannel communications — phone, SMS, email marketing, live chat — all logged to CRM.

### RingCentral Integration (via Telus Biz Connect)

**Phase 1 — Call Logging + CRM Sync:**
- Inbound/outbound call logging via RingCentral webhook → KBS endpoint → `call_record` linked to CRM contact (phone number match)
- Call history timeline on contact profile
- Missed call alerts (dashboard notification + optional email)

**API Discovery:** Verify Telus Biz Connect API access level before building. Determines full RingCentral API vs restricted reseller subset.

### SMS
- RingCentral SMS API (if available through Telus plan)
- Twilio fallback if RingCentral SMS restricted
- SMS tied to CRM contacts — conversation thread view
- Use cases: appointment reminders, booking confirmations, client follow-ups

### Email Marketing (Hostinger Reach)
- Wire Hostinger Reach MCP tools for bulk campaigns
- `kbs_marketing` plugin: contact list sync → segment targeting → template editor → send → track opens/clicks
- Transactional stays on SMTP, marketing goes through Reach

### Live Chat Widget
- Embeddable WebSocket-based chat widget
- Auto-injected on KBS-built sites
- Client receives chats in help desk as ticket channel
- Offline mode: form becomes ticket submission
- No AI chatbot in Wave 2

### Unified Inbox
- All channels in one view per client: email tickets, phone calls, SMS threads, chat conversations
- Each interaction linked to CRM contact, tagged by channel
- Filter by channel, status, assigned team member

### Booking Completion
- Booking confirmations via SMS + email
- Google Calendar API sync (client connects their calendar)

### Not in Wave 2
- No Stripe billing
- No marketplace
- No click-to-call (Wave 4)
- No AI chatbot

---

## Wave 3 — SaaS Resale Infrastructure

### Goal
Self-serve client onboarding, billing, and marketplace. Clients sign up, pick a plan, pay, and start using KBS without manual intervention.

### Stripe Billing

Code exists in `stripe_billing.py`. Wire to live Stripe account:

| Feature | Detail |
|---------|--------|
| Checkout flow | Pick tier → Stripe Checkout → redirect → `sync_tier_modules()` activates plugins |
| Subscription management | Upgrade/downgrade/cancel/pause via Stripe Customer Portal |
| Add-on purchases | Individual plugins outside tier (`addon_purchase` in `tenant_modules`) |
| Usage metering | Track website deploys, email sends, SMS count — enforce tier limits |
| Invoice sync | Stripe invoices mirrored in KBS |
| Trial flow | 14-day Business trial → auto-downgrade to Free |

### Pricing Structure

| Tier | Monthly | Includes |
|------|---------|----------|
| Free | $0 | CRM, Invoicing, Store, Automations, 1 website (subdomain only) |
| Business | $49/mo | Free + Appointments, Content Studio, Social Media, Website Builder, Marketing, Help Desk, Accounting, 5 websites, custom domain, booking page |
| Enterprise | $149/mo | Business + Call Center, Automations UI, Contracts, unlimited websites, priority support, API access |
| Industry Add-on | $29/mo each | Any industry vertical — requires Business+ |
| Plugin a la carte | $9-19/mo each | Individual plugins outside tier |

*Starting prices — adjust based on market research.*

### Marketplace UI
- Visual grid of all 22 plugins with icons, descriptions, screenshots
- Filter by category (CRM, Finance, Marketing, Industry)
- Tier badge (Free / Business / Enterprise / Add-on)
- Activate → checks tier → activates, prompts upgrade, or starts Stripe add-on purchase
- "Try Free for 14 Days" on paid plugins
- Plugin detail page: features, pricing, dependencies

### Client Onboarding Flow
1. Sign up (email or Google OAuth) → tenant schema created
2. Wizard: business name → industry → timezone → logo upload
3. Industry auto-recommends bundle ("You're a salon? Try the Salon Suite")
4. Pick tier → Stripe Checkout → plugins activate
5. Dashboard guided checklist: "Import contacts", "Create first invoice", "Set up booking", "Build your website"

### Subdomain Provisioning
- On signup: `{clientslug}.kytranempowerment.com` auto-provisioned via Hostinger DNS API (`DNS_updateDNSRecordsV1`)
- Health monitor: agent loop job checks all subdomains every 30 min
- Paid clients: connect custom domain via Hostinger API + SSL

### Client Dashboard
- Active plugins + usage stats
- Plan + billing (Stripe portal link)
- Team members + roles
- Quick actions: Build Website, Add Contact, Create Invoice, View Tickets
- Notifications: upcoming appointments, overdue invoices, open tickets

### Admin Dashboard (Kytran Empowerment)
- Total clients, MRR, churn rate
- Plugin activation heatmap
- Support ticket volume across all clients
- Revenue per tier, per add-on
- Client health scores

### Not in Wave 3
- No industry plugin routes completed
- No AI agents
- No knowledge base
- No government opportunity agent

---

## Wave 4 — Industry Verticals, AI Agents & Polish

### Goal
The differentiators — industry-specific tooling, AI agents, self-service knowledge bases, and platform polish.

### Industry Plugin Completion

| Plugin | Key Features |
|--------|-------------|
| `kbs_industry_salon` | Service menu, stylist profiles, booking integration, product inventory, client preferences |
| `kbs_industry_construction` | Project tracker, subcontractor management, RFIs, change orders, inspections, permits |
| `kbs_industry_electrical` | Panel schedules, circuit mapping, load calculations, material lists, code compliance |
| `kbs_industry_plumbing` | Service call dispatch, fixture inventory, backflow testing, parts ordering |
| `kbs_industry_mechanical` | HVAC tracking, maintenance schedules, energy audits, commissioning reports |
| `kbs_industry_photography` | Shoot scheduler, packages, gallery delivery, editing queue, proofing portal |
| `kbs_industry_limo` | Fleet management, driver dispatch, booking calendar, route optimization, maintenance logs |
| `kbs_industry` (framework) | Permit applications, compliance checklists, government integration hooks |

### AI Agents Per Vertical
- Each industry vertical gets a branded acronym AI agent (names TBD — task #1431)
- Powered by ARCHIE Bridge dispatch
- Industry-specific advice, document generation, data analysis
- Example: Salon agent suggests rebooking, analyzes popular services, drafts slow-day campaigns
- Example: Construction agent flags permit deadlines, generates RFI responses, estimates costs
- Premium feature: Enterprise tier or industry add-on required
- Trained on industry knowledge via ARCHIE knowledge base

### Knowledge Base (Help Desk Extension)
- Each client builds a self-service portal for their customers
- Article editor with categories + search
- Auto-suggested articles on ticket submission
- Analytics: most viewed, search gaps
- Public URL: `{clientslug}.kytranempowerment.com/help`
- AI article generation: describe topic → agent drafts article

### Click-to-Call (RingCentral Phase 2)
- Click phone in CRM → RingCentral API initiates call
- Softphone or desk phone ring (client chooses)
- Call recording playback in CRM (if plan supports)
- Requires verified API access from Telus

### AI Chatbot for Client Websites
- Upgrade Wave 2 chat widget with AI responses
- Trained on client's knowledge base articles
- Handles common questions, books appointments, escalates to human
- Powered by ARCHIE Bridge
- Enterprise tier feature

### Platform Polish

| Item | Detail |
|------|--------|
| LCARS theme | Full frame styling, elbows, sidebar, responsive 480/768/1024px |
| PWA | Push notifications for appointments, tickets, calls |
| Reporting | Cross-plugin dashboard: revenue, bookings, resolution, traffic |
| API access | REST API for Enterprise clients |
| Webhooks | Outbound webhooks on events (new booking, invoice paid, etc.) |
| White-label | Enterprise clients remove Kytran branding (future revenue) |

---

## P.R.O.C.U.R.E. — Standalone Product

**Procurement Research, Opportunity Coordination & Unified Resource Engine**

### Overview
Standalone government contracting intelligence dashboard, same architecture pattern as Kytran News and Market Watch.

### Details
- **URL:** `procure.kytranempowerment.com`
- **Architecture:** Standalone app, own Docker container, follows extraction playbook
- **Data sources:** PSPC, CRA, DND, provincial procurement portals
- **Browse by:** Department, trade category, province, value range, deadline
- **UI pattern:** Category-based browsing like News/Market Watch (not buried in a plugin)
- **AI agent:** P.R.O.C.U.R.E. — analyzes tenders, summarizes requirements, flags deadlines, drafts bid responses
- **Free tier:** Browse opportunities
- **Premium (KBS subscription):** Alerts, AI analysis, bid drafting, CRM integration
- **KBS integration:** Opportunity alerts flow into client CRM, bid tracking through CRM pipeline
- **Extraction:** Follows Tier 1/2/3 standalone extraction playbook

### Agent Profile
- **Name:** P.R.O.C.U.R.E.
- **Full:** Procurement Research, Opportunity Coordination & Unified Resource Engine
- **Role:** Government contracting intelligence analyst
- **Department:** Analytics & Intelligence (under S.P.E.C.T.R.A.)
- **Capabilities:** Tender monitoring, opportunity matching, bid analysis, deadline tracking, compliance checking

---

## New Acronym Agents Summary

| Agent | Full Name | Product/Context |
|-------|-----------|----------------|
| **P.R.O.C.U.R.E.** | Procurement Research, Opportunity Coordination & Unified Resource Engine | Standalone at procure.kytranempowerment.com |
| *Industry agents TBD* | To be designed in task #1431 | One per industry vertical in KBS |

---

## Delivery Order

1. **Wave 1** — Core + Website Builder (the sellable product)
2. **Wave 2** — Communications (phone, SMS, email marketing, chat)
3. **Wave 3** — SaaS Resale (Stripe, marketplace, onboarding, subdomains)
4. **Wave 4** — Industry Verticals, AI Agents, P.R.O.C.U.R.E., Polish

Each wave ships independently and delivers immediate value.

# KBS Plugin Index (kytran-business-suite)

**CRITICAL**: Search this file BEFORE building any new LinkedIn, social, billing, CRM, or automation feature.
KBS already has 25 plugins. Building duplicates wastes sessions.

**Source**: `/mnt/archie_brain/kytran-business-suite/plugins/`
**URL**: business.kytranempowerment.com (port 8091)

---

## ⚠️ High-Value Plugins (Most Likely to Be Duplicated by Mistake)

| Plugin | What it already does |
|--------|---------------------|
| **kbs_social_media** | LinkedIn + OAuth token posting, social account management — **DO NOT rebuild LinkedIn posting, it's here** |
| **kbs_invoicing** | Stripe-integrated invoicing, payment tracking |
| **kbs_store** | Stripe e-commerce storefront |
| **kbs_crm** | Full customer relationship management |
| **kbs_automations** | Event-driven workflow automation engine |
| **kbs_automations_ui** | Visual workflow builder for automations |
| **kbs_marketing** | Campaign and marketing automation |
| **kbs_content_studio** | Content creation and management |

---

## Full Plugin List (25 plugins)

### Core Business
| Directory | Description |
|-----------|-------------|
| `kbs_accounting` | Financial tracking and ledger management |
| `kbs_appointments` | Public booking system (no login required) |
| `kbs_call_center` | Call handling and queue management |
| `kbs_communications` | Internal/external messaging |
| `kbs_contracts` | Contract lifecycle management |
| `kbs_core_objects` | Base data models and shared entities |
| `kbs_crm` | Customer relationship management |
| `kbs_help_desk` | Ticket and support management |
| `kbs_invoicing` | Invoicing + **Stripe** |
| `kbs_knowledge_base` | Internal documentation and KB |
| `kbs_marketing` | Campaign and marketing automation |
| `kbs_social_media` | Social posting + **LinkedIn OAuth** |
| `kbs_store` | E-commerce + **Stripe** |
| `kbs_website_builder` | Drag-and-drop site builder |
| `kbs_content_studio` | Content creation tools |
| `kbs_automations` | Automation engine |
| `kbs_automations_ui` | Visual automation builder |

### Industry Verticals (extend `kbs_industry` base)
| Directory | Description |
|-----------|-------------|
| `kbs_industry` | Base industry plugin framework |
| `kbs_industry_construction` | Construction-specific workflows |
| `kbs_industry_electrical` | Electrical trade tools |
| `kbs_industry_limo` | Limousine service management |
| `kbs_industry_mechanical` | Mechanical trade workflows |
| `kbs_industry_photography` | Photography business management |
| `kbs_industry_plumbing` | Plumbing trade workflows |
| `kbs_industry_salon` | Salon/spa appointment and service management |

---

## kbs_social_media — Detail (Most Relevant to A.R.C.H.I.E. Work)

- **LinkedIn OAuth**: tokens stored in `social_accounts` table (id=4 for Kytran's account)
- **Posting**: POST to LinkedIn feed via OAuth token — already works
- **Path**: `/mnt/archie_brain/kytran-business-suite/plugins/kbs_social_media/`
- **Use for**: All LinkedIn API posting — KBS OAuth path, NOT Playwright
- **Use Playwright (archie_browser)**: ONLY for browser-only actions LinkedIn API can't do (company page admin, profile editing, connection requests, DMs)

## kbs_automations — Detail

- Event-driven workflow engine with visual builder
- Before building any automation/trigger/webhook in A.R.C.H.I.E. — check if KBS automations covers it
- Path: `kbs_automations/` + `kbs_automations_ui/`

---

*Last updated: 2026-04-29 | Source: task #2458*

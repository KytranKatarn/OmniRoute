---
globs: ["platform_v2/tools/crm/**", "platform_v2/tools/website_studio/**", "platform_v2/tools/store_builder/**", "platform_v2/tools/call_center/**", "platform_v2/tools/stockbot/**", "platform_v2/tools/invoicing/**", "platform_v2/tools/social_media/**", "platform_v2/tools/content_studio/**", "platform_v2/tools/google_work_suite/**", "platform_v2/tools/saas_manager/**"]
---

# SaaS Services Rules

## Modules (10 total)
- **CRM** — `/tools/crm`, `crm_bp` (40+ routes, most mature)
- **Website Designer** — `/tools/website-studio`, `website_studio_bp` (20+ routes)
- **Store Builder** — `/tools/store-builder`, `store_builder_bp` (Printful integration)
- **Call Center** — `/tools/call-center`, `call_center_bp`
- **StockBot** — `/tools/stockbot`, `stockbot_bp` (15+ routes, AI-powered)
- **Invoicing** — `/tools/invoicing`, `invoicing_bp`
- **Social Media** — `/tools/social-media`, `social_media_bp` (30+ routes, OAuth)
- **Content Studio** — `/tools/content-studio`, `content_studio_bp`
- **Google Work Suite** — `/tools/google-work-suite`, `google_work_suite_bp`
- **SaaS Manager** — `/tools/saas-manager`, `saas_manager_bp` (multi-tenant: orgs, domains, modules; `show_on_dashboard=False` — folded into Account Center ORGS tab)

## Critical Rule: Per-User Data Isolation
ALL SaaS module data MUST be scoped by `user_id`. Every table, every query, every feature filtered by `current_user.id`. No shared/global tables for user content.

## Key DB Tables
- CRM: `crm_customers`, `crm_segments`, `crm_interactions`
- StockBot: `stock_watchlists`, `stock_portfolio`, `stock_alerts`, `stock_concepts`
- Social: `social_accounts`, `social_posts`
- Store: `store_orders`, `store_products`, `store_integrations`
- Invoicing: `invoices`, `invoice_items`, `invoice_settings`

## Bridge Dispatch Usage
- **StockBot**: Uses `get_dispatcher()` for AI stock analysis, `get_model_for_capability()`
- **Content Studio**: Uses Bridge for AI writing assistance
- **Others**: Direct external API calls (no Bridge needed)

## External Integrations
- StockBot: Alpha Vantage API for market data
- Social Media: OAuth token refresh for platform APIs
- Store Builder: Printful API for print-on-demand
- Google Work Suite: Google APIs (email, calendar, drive)
- Website Designer: Hostinger integration

## Template Pattern
- Templates at `templates/tools/{module_name}.html`
- Blueprint `template_folder="../../templates/tools"`
- All extend `base.html`, include `business_tools_nav.html`

## Gotchas
- OAuth token refresh logic in social media (tokens expire)
- StockBot has 5 specialized agents (quant/value/pulse/shield/oracle) — need Modelfiles
- Rate limiting on external API endpoints
- CRM has import/export features — watch for large data handling

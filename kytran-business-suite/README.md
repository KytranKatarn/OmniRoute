# Kytran Business Suite (KBS)

Modular SaaS platform for small businesses. Multi-tenant architecture with 26 plugins.

## Quick Start

```bash
cp .env.example .env    # Configure database, Stripe, Printful keys
docker compose up -d    # Starts on port 8091
```

## Architecture

- **Framework**: Flask + Gunicorn
- **Database**: PostgreSQL (multi-tenant via schema isolation)
- **Plugins**: 26 modular plugins in `plugins/` (CRM, Store, Invoicing, Website Builder, etc.)
- **Core**: Auth, tenant management, event bus, Stripe billing, Printful client, PDF generation

## Plugins

Each plugin follows the same structure: `manifest.json`, `routes.py`, `__init__.py`, `migrations/`, `templates/`, `static/`, `tests/`.

| Category | Plugins |
|----------|---------|
| Core Business | CRM, Invoicing, Accounting, Contracts |
| E-Commerce | Store, Website Builder |
| Communications | Help Desk, Call Center, Communications |
| Marketing | Marketing, Social Media, Content Studio |
| Operations | Appointments, Automations, Knowledge Base |
| Industry | Construction, Electrical, Limo, Mechanical, Photography, Plumbing, Salon |

## Configuration

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string |
| `KBS_STRIPE_SECRET_KEY` | Platform Stripe API key |
| `KBS_STRIPE_WEBHOOK_SECRET` | Stripe webhook verification |
| `KBS_PRINTFUL_API_KEY` | Printful API key |
| `KBS_BRIDGE_URL` | A.R.C.H.I.E. AI Bridge URL |
| `KBS_BASE_URL` | Public URL for redirects |

## Port

- **8091** (external) -> 8090 (internal)

## License

Proprietary - Kytran Empowerment Inc.

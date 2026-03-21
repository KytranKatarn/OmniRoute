# Applications Rules

## Modules
- **Fitness** — `/tools/fitness`, `fitness_bp`
- **Therapy** — `/tools/therapy`, `therapy_bp`
- **DOC** — `/tools/doc`, `doc_bp`

## Status
- Minimal/placeholder modules — early-stage development
- Templates exist at `templates/tools/{module_name}.html`

## Structure
- Each: `routes.py` + `__init__.py` in `tools/{module_name}/`
- Small route count — basic CRUD and display

## Patterns
- Per-user data isolation applies (SaaS pattern)
- No Bridge dispatch currently
- These are consumer-facing apps (fitness tracking, therapy sessions, document management)

## Gotchas
- StockBot is registered under APPLICATIONS category in module_registry but has more in common with SAAS_SERVICES — see `saas-services.md`

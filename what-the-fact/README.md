# What The Fact

3-service stack for AI-powered transparent news.

## Services
- **wtf-consumer** (port 8103) — public reader at what-the-fact.com
- **wtf-tech** (port 8104) — transparency + developer portal at what-the-fact.tech
- **wtf-ingest** (internal) — RSS → canonical article → bias scoring → DB

## Development
1. `cp .env.example .env` and fill secrets
2. `docker compose up -d`
3. Visit http://localhost:8103

## Tests
`pip install -r requirements-dev.txt && pytest tests/`

## Deployment
Deployed to US Outpost (`76.13.107.109`) behind Caddy. See `docs/superpowers/specs/2026-04-18-wtf-thenews-consolidation-design.md`.

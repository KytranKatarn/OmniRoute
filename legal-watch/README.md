# Kytran Legal Watch

Legal intelligence dashboard tracking court filings, regulatory changes, and compliance updates.

## Quick Start

```bash
cp .env.example .env    # Configure API keys
docker compose up -d    # Starts on port 8100
```

## Architecture

- **Framework**: Flask
- **Database**: SQLite (self-contained)
- **Entry**: `app.py`

## Port

- **8100** (external) -> 8080 (internal)

## License

Proprietary - Kytran Empowerment Inc.

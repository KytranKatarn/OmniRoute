# Kytran Civic Watch

Real-time civic intelligence dashboard tracking government activity, public meetings, and municipal decisions.

## Quick Start

```bash
cp .env.example .env    # Configure API keys
docker compose up -d    # Starts on port 8099
```

## Architecture

- **Framework**: Flask
- **Database**: SQLite (self-contained)
- **Entry**: `app.py`

## Port

- **8099** (external) -> 8080 (internal)

## License

Proprietary - Kytran Empowerment Inc.

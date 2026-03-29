# Kytran Market Watch

Market intelligence dashboard with autonomous trading analysis, 8 analytical tabs, and M.A.R.K.E.T. AI agent.

## Quick Start

```bash
cp .env.example .env    # Configure API keys
docker compose up -d    # Starts on port 8101
```

## Architecture

- **Framework**: Flask
- **Database**: SQLite (self-contained)
- **Entry**: `app.py`
- **AI Agent**: M.A.R.K.E.T. (Market Analysis, Research, Knowledge, Evaluation & Trading)

## Port

- **8101** (external) -> 8080 (internal)

## License

Proprietary - Kytran Empowerment Inc.

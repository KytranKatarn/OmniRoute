# A.R.C.H.I.E. V2.0

**AI Research Command Hub & Intelligent Engine**

Complete modular platform for AI-powered development and automation.

## Structure

- `platform_v2/` - Main application (modular)
- `database/` - Database schemas and migrations
- `scripts/` - Management scripts
- `backups/` - System backups
- `docs/` - Complete documentation

## Quick Start

```bash
# Production
docker-compose up -d

# Test environment
docker-compose -f docker-compose.test.yml up -d
```

## Documentation

See `docs/` directory for complete documentation.

## Backup

```bash
./scripts/backup.sh
```

## Restore

```bash
./scripts/restore.sh [backup_directory]
```

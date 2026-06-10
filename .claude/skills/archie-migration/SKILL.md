---
name: archie-migration
description: Database migration workflow for A.R.C.H.I.E. platform
---

# Database Migration Workflow

## Create Migration
File: `database/migrations/NNN_description.sql`
- Always idempotent: `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- Header: `-- Migration NNN: Description` + `-- Idempotent: safe to run multiple times`
- Use `ON CONFLICT DO NOTHING` for seed data

## Run Migration
```bash
docker cp database/migrations/NNN_file.sql archie_database:/tmp/
docker exec archie_database psql -U archie -d archie -f /tmp/NNN_file.sql
```

## Verify
```bash
docker exec archie_database psql -U archie -d archie -c "\d table_name"
```

## Current Migration: 171 (next: 172)

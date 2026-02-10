#!/bin/bash
# Post-Session Ingestion Hook
# Runs after session_end_hook.sh to ingest new conversation logs

echo "Ingesting new conversation logs..."

docker exec archie_platform python3 -c "
from tools.consciousness.log_ingestor import batch_ingest_logs
result = batch_ingest_logs(limit=50)
if result.get('success'):
    created = result.get('created', 0)
    skipped = result.get('skipped', 0)
    if created > 0:
        print(f'Ingested {created} new logs ({skipped} already existed)')
    else:
        print(f'No new logs to ingest ({skipped} already existed)')
else:
    print(f'Ingestion error: {result.get(\"error\", \"unknown\")}')
" 2>&1

echo "Done."

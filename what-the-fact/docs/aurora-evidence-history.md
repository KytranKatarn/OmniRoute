# A.U.R.O.R.A. source evidence history

This change adds append-only retrieval history for three feeds:

- ECCC CAP alerts retain each source XML version, including distinct alert,
  update and cancellation messages.
- CWFIS station records retain the original GeoJSON feature alongside its
  normalized fire-weather values.
- CWFIS rolling hotspot points are captured hourly with their original
  properties and geometry. The daily FWI station and provincial summary jobs
  remain daily because they are daily/current-layer products.
- NASA FIRMS current detections can be captured hourly when
  `NASA_FIRMS_MAP_KEY` is configured. Rows retain source-native CSV fields and
  are classified as thermal anomalies, not confirmed fires.

`source_observed_at`, `source_published_at`, `first_retrieved_at`, and
`ingested_at` have separate meanings. `operational_received_at` remains NULL
unless a later evidence source proves when an operational recipient received
the information. Public-source timestamps do not prove operational receipt.

FIRMS setup is optional. Request a free MAP_KEY from [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/download/),
then provision it through the existing approved runtime secret mechanism as
`NASA_FIRMS_MAP_KEY`. Do not add it to repository files, command arguments,
logs, database URLs, or source URLs. `AURORA_FIRMS_AREA` may set a
`west,south,east,north` bounding box; it defaults to a Canada-wide box.
FIRMS's [Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) limits each
request to one through five days. This scheduled collector requests current
NRT records; it does not backfill historical dates. Historical downloads
require the [FIRMS archive](https://firms.modaps.eosdis.nasa.gov/download/)
and Earthdata authentication. NASA notes that RT/URT records can be replaced
by NRT processing or removed after six hours, so near-real-time versions must
be retained when observed. The API's detection timestamp is acquisition time,
not publication or agency receipt time.

## Validation

From `what-the-fact/`:

```bash
python3 -m py_compile ingest/weather/evidence.py ingest/weather/firms.py \
  ingest/weather/alerts.py ingest/weather/cwfis.py ingest/run.py \
  ingest/parliament/drift_guard.py
python3 -m pytest -q tests/test_aurora_evidence_history.py
python3 -m pytest -q tests/test_aurora_provenance.py
python3 scripts/migrations_apply.py plan
python3 scripts/migrations_apply.py rehearse
```

The migration plan and rehearsal must target Citadel's WTF database through the
guarded runner described in `migrations/README.md`. They are read-only plan and
transactional rollback checks respectively; do not substitute the hub's
`archie_database`. The tests use fixtures and do not contact NASA, CWFIS, ECCC,
or production PostgreSQL.

## Rollback

This work does not run the migration, backfill records, restart services, or
deploy. Before a future approved deployment, take the normal Citadel WTF backup
and run the guarded migration rehearsal. If rollback is required before any
consumer depends on the data, remove the new capture tables and migration-ledger
row using a reviewed down-migration, remove the collector scheduler gates, and
rebuild the WTF ingest image. Keep the existing `aurora_alerts`, fire-weather,
hotspot aggregate and perimeter tables intact. Do not truncate the evidence
tables as an operational shortcut.

The hourly point history is additive and will grow over time; production owners
should review database growth and retention requirements before enabling the
new collectors. The initial implementation does not prune source evidence.

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

## Archive search, CAP history, and coverage

The evidence reader keeps source-time and first-retrieval filters separate. It
uses a stable keyset cursor for subsequent pages; older offset requests remain
bounded for compatibility. The cursor is an opaque paging boundary, not an
authorization token. Full CAP history is loaded on demand by the exact CAP
identifier and follows the active source-time and `available_before` filters.
Each version remains the original immutable source row; the lifecycle is only a
projection. A page-scoped search result is not described as the complete alert
history until the full-history request finishes.

`/api/weather/evidence/coverage` summarizes retained source dates, first and
latest retrievals, recent run outcomes, empty successful captures, and the
median attempt interval measured from the last 30 days of this archive's own
capture runs. It does not state a target cadence or service-level guarantee.
Failed attempts are stored as `status='failed'` capture-run rows without
exception details or credential-bearing URLs. NASA FIRMS remains optional; no
attempt history by itself does not prove whether its credential is configured.

JSON and CSV exports contain only the evidence rows currently loaded in the
browser, along with source IDs, timestamps, source URL and payload checksum.
Exports intentionally omit `raw_payload`; they carry the active filters and a
scope note so a partial browser result is not presented as a complete archive.
On-demand CAP lifecycle versions preserve the archive and source-time cutoffs,
but do not need to match the original text or bounding-box search; the manifest
marks this distinction. The reader caps loaded records and disables larger
client-side exports.

Keyset pagination avoids discarding deep offset pages, but the current WTF
database's query plan and table size were not available in this session. Do not
add indexes based only on this code review. Before a schema optimization, run a
read-only `EXPLAIN (ANALYZE, BUFFERS)` against representative archive queries on
the verified Citadel WTF database and size the candidate indexes against the
backup/restore budget.

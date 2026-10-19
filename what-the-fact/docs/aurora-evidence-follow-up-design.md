# A.U.R.O.R.A. evidence history — follow-up design

**Status:** design proposal; implementation and production operations are not included.
**Foundation dependency:** PR #3935 (`feat(aurora): preserve source evidence history`).
**Scope:** the five follow-ups identified after the source-history work: safe release, a
geographic evidence map, stronger archive search, evidence retention, and visible feed
coverage.

## Purpose

Help a reader answer two different questions without conflating them:

1. What does the source record say happened, and when?
2. What evidence had this platform captured by a selected time?

Neither public publication nor platform capture establishes when an operational
decision-maker received the information. `operational_received_at` stays unknown unless
an independent record establishes it. Satellite thermal anomalies remain anomalies, not
confirmed fires. Fire-weather indices remain at the source's published calculation
cadence; a daily index must not be drawn as an hourly series.

## Dependency and delivery order

1. Review and merge #3935. Its append-only source-version schema, bounded read API, and
   capture jobs are the data foundation. Do not run its migration or enable new schedules
   from this design PR.
2. Complete the release-readiness checklist below on the integrated main revision.
3. Implement the map and search as a small consumer/API PR, then coverage as a separate
   API/UI PR. Both can use the source versions and capture runs from #3935.
4. Measure database growth and backup/restore cost before selecting an archive tier or
   any retention duration. Implement archival only after that measurement and an owner
   decision.

Keep the follow-up PRs focused: each should change no more than 5–10 files where
practical, identify its dependency, and avoid mixing deployment operations with product
code. F.O.R.G.E. reviews; a human merges. A merge is not deployment for the image-baked
What-The-Fact services.

## 1. Release-readiness gate for #3935

This is a deployment checklist, not authorization to deploy.

### Before an approved release

- Confirm #3935 is merged and the deployment candidate is a clean integrated `main`.
- Confirm the backup is from the dedicated What-The-Fact database on its verified host.
  Never substitute the hub's similarly named database.
- Run the product migration planner and transactional rehearsal against that target using
  the guarded procedure in `migrations/README.md`; record both outputs in the release
  evidence. Do not run a raw `psql` migration copied from another product.
- Review the new tables' grants with the actual runtime role. Confirm source evidence is
  append-only to the application role and that API payloads exclude `raw_payload`.
- Build a disposable candidate from the merged commit. Verify health, `/version`, evidence
  API behavior, and collector dry-run behavior before any production scheduler change.
- Enable collectors separately and in a bounded order: CAP, daily fire-weather station
  versions, hourly hotspot-point capture, then optional FIRMS only after its credential is
  provisioned through the approved secret mechanism. A missing optional credential means
  disabled, not a failed deployment.
- Verify from the running service that scheduled runs and source versions are being
  captured. File presence and a successful image build do not prove the runtime loaded it.

### Rollback

- Stop or disable only the newly introduced collector schedules first; preserve existing
  weather jobs and public layers.
- Roll back the image to the last known-good main build if the consumer or ingest service
  is unhealthy.
- Do not delete captured source versions as an application rollback. If schema rollback is
  required before dependants exist, use a reviewed down-migration after the backup has
  been verified. Keep the current alerts, station, hotspot-summary, and perimeter tables.
- Reconcile the deployed image SHA and running process after rollback.

## 2. Geographic historical evidence map

### Interaction and visual structure

- Reuse the existing `WTFMap` Canada geometry, conic projection, and keyboard/pointer
  conventions. Add a dedicated historical-evidence layer rather than making a second
  unrelated map or using a latitude/longitude scatter chart as a geographic map.
- Plot only source coordinates returned in the selected result set. Marker color and
  legend encode evidence class (for example, alert location versus satellite thermal
  anomaly); they do not encode fire certainty.
- Selecting a point opens a compact detail panel with source-native ID, coordinates,
  observed/acquisition time, publication time where present, first retrieval time, and
  source link. Empty or invalid geometry is counted as unlocated and never placed at
  (0, 0).
- Keep the source's spatial resolution and confidence fields visible when present. Do
  not draw a point as a perimeter or imply a detection footprint more precise than the
  source product supports.
- The Wainwright investigation can set a location and time window, but that view must not
  silently identify nearby points as the same incident.

### API and verification

- Extend the bounded evidence endpoint with validated geographic filters only where the
  source record has coordinates. Bind all values as SQL parameters; reject invalid
  longitude/latitude and inverted bounds.
- Return enough provenance to explain every marker and retain a hard page limit.
- Tests: known GeoJSON point maps to its expected position; swapped/invalid coordinates
  are rejected or excluded; missing geometry stays unlocated; UI says “thermal anomaly”;
  query filters cannot widen beyond configured limits.

## 3. Archive search and alert lifecycle

### Search model

Expose separate controls for:

- dataset/evidence class;
- source observation or alert-effective interval;
- archive availability cutoff (`first_retrieved_at <= cutoff`);
- geographic bounding box when the selected dataset supports coordinates;
- text/source-native identifier for a known station, alert, or detection.

Keep `source_observed_at`, `source_published_at`, `first_retrieved_at`,
`operational_received_at`, and `ingested_at` distinct in the response and display. A
missing value remains “not recorded.” Search windows and result counts stay bounded; use
keyset pagination on a stable `(COALESCE(source_observed_at, source_published_at,
first_retrieved_at), dataset_key, source_record_key, id)` order if offset scans become
expensive. Preserve deterministic ordering across pages.

### CAP lifecycle

Group CAP source versions by the CAP identifier while retaining each original version and
message type (Alert, Update, Cancel). Display the original issue and every later update or
cancellation as a chronological chain. Do not overwrite an earlier alert with the latest
state. The lifecycle view is a projection over immutable versions, not a new canonical
copy.

### Verification

- Tests prove `available_before` filters on first retrieval, not source publication or
  observation time.
- Tests prove timezone offsets normalize to UTC without changing the source timestamp in
  the evidence record.
- Tests cover CAP update/cancel ordering, duplicate versions, missing timestamps, bound
  validation, pagination stability, and output escaping.

## 4. Evidence retention and archival policy

### Policy before implementation

Source versions are an evidence ledger. Do not add TTL deletion or an automatic purge for
this data. First measure monthly bytes by dataset, index overhead, backup growth, and
restore time over a representative capture period. Then choose an owner-approved hot
database window and a durable archive tier based on those measurements and applicable
records obligations.

### Archive design if growth requires it

- Export immutable batches containing the original payload, provenance timestamps,
  source URL/identifier, and SHA-256 digest. Keep the database row or a stable archive
  pointer and digest so the public reader can still find the evidence.
- Verify a batch by reading it back and re-computing every digest before marking it
  archived. A failed or incomplete batch remains in the hot database and is reported as
  an error; never delete first and archive later.
- Preserve capture-run links and source-version identity across archive/restore. Restoring
  the same batch must be idempotent and must not create duplicate evidence versions.
- Retention expiration, legal hold, and deletion are separate owner-governed operations.
  An archive migration must include a restore test and a rollback that leaves the source
  ledger readable.

### Acceptance checks

- A test corrupting one archived byte causes checksum verification to fail.
- A simulated interrupted export leaves all source rows available in the database.
- Re-import is idempotent and preserves the original digest and timestamps.
- No automated deletion path exists in the collector or reader.

## 5. Feed coverage and capture cadence

Add a coverage summary to the A.U.R.O.R.A. page and API, sourced from capture-run and
source-version records rather than hard-coded promises. Per dataset, show:

- earliest and latest source-observation timestamps available;
- earliest and latest first-retrieval timestamps in this archive;
- last successful capture run, last attempted run, captured row count, and run status;
- configured target cadence from the collector configuration, separate from measured
  capture intervals;
- explicit gaps and whether a feed is optional, disabled, stale, or not yet configured.

The wording must distinguish a source's historical coverage from this platform's own
retention history. For example, “source record is dated Oct 17; first archived here Oct
18” is valid; “we had it on Oct 17” is not. Daily fire-weather records must be labeled
daily and must not imply hourly FWI observations.

### Verification

- Empty capture runs remain visible and do not make coverage appear healthy.
- Failed runs do not update the last-success timestamp.
- First-seen coverage comes from the earliest retained `first_retrieved_at`, not the
  record's event date.
- Cadence is labeled configured/target, while measured intervals derive from actual run
  timestamps.
- A feed with no rows has a clear “no archive coverage” state, not a zero or green badge.

## Proposed implementation PR slices

| Slice | Scope | Expected files | Depends on |
|---|---|---:|---|
| A | Real geographic evidence layer and selected-record detail | 3–5 | #3935 |
| B | Bounded date/ID/bounds search and CAP lifecycle projection | 4–7 | #3935 |
| C | Per-feed capture coverage API and reader summary | 3–6 | #3935 |
| D | Measured retention policy and verified archive prototype | 4–8, likely separate storage review | A–C measurements |
| E | Release-readiness evidence and deployment verification | docs/checklist first; operations separately authorized | #3935 merged |

Keep D in design/measurement until storage and backup costs are known. No source history
is purged to implement this proposal.

## Explicit non-goals

- No production migration, backfill, collector enablement, deployment, service restart, or
  production-data write in this proposal.
- No inference that a source record was visible to a commander, emergency service, or
  other operational recipient.
- No conversion of hotspots into confirmed fire events, or of daily FWI into hourly risk.
- No automatic deletion of public-source evidence.

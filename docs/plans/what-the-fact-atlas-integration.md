# What The Fact integration and Atlas release plan

Prepared 2026-10-13. This is a staged application release plan, not deployment
permission or proof of historical verification. Current work implements Phase 1
(the Atlas research preview), not the entire ecosystem handoff.

## Grounding and reuse

Authoritative source: archie-platform/what-the-fact, not the history mirror or
archived landing-site repositories. Application base: 41e8ff522. Read-only Citadel
inspection on 2026-10-13 found /opt/archie-products/what-the-fact, Compose service
wtf-consumer, container what-the-fact-wtf-consumer-1. Its running /version reported
41e8ff522c8bcc325f4910939d964f850fcab3cb, built 2026-10-13T13:19:02Z. The inventory
also included local what-the-fact-wtf-postgres-1. Older rules claiming the primary
WTF database is on the hub are stale; do not use them to target migrations.
No databases were queried or changed for this Atlas release.

The existing Flask app, Jinja shell, navigation, editorial fonts/tokens, static
asset pipeline and image provenance are reused. Routes live in a dedicated
history Blueprint rather than expanding the large consumer/routes.py. Public
history has no tenant/private data, inference, cross-product calls or work queue.
The app's existing authentication and entitlements are unchanged. The entire
research surface is gated by WTF_HISTORY_ATLAS_ENABLED=1, default off.

Input packages:

- What-The-Fact-Codex-Integration-Package.zip: 33 entries; SHA-256
  dacb5bc570571a3fa1c71e8608f66f0a37faf49a140fe82d19260a01a535417f.
  v0.3 source review dated October 11 plus October 12 coordination materials.
  Its findings are historical observations, not current vulnerability findings.
- Canadian-History-Atlas-159-Events.zip: 27 entries, CRC verification passed.
  The data manifest records the archive hash, original member hashes, packaged
  hashes and the sole normalization: repository-required final newlines.

## Phase 1 — read-only Atlas research preview (these PRs)

Two dependent PRs keep each review within the 25-file lane limit:

1. Data/assets (#3832): 159 stable-ID draft events, 128 sources, 13 selected movements,
   23 supplied passive NRCan-derived SVG snapshots and provenance manifest.
2. Application: opt-in /history and /history/atlas; bounded GET-only
   /api/history/events; source details at /history/events/CH-xxxx; movement list
   at /history/movements; shared Data navigation; responsive map comparison and
   explicit, keyboard-operable playback. No automatic playback.

The UI separates broad region, explicit present-day province/territory context,
actual recorded date ranges, undated events, and map snapshot selection. A map is
not exact event geometry. Undated records do not acquire dates; pre-1867 events do
not acquire political maps; missing translations/routes/counts remain unknown.
All content remains research-only, labelled draft and noindex/nofollow. It does
not feed news fact-check counters or publish seed allegations as established.

Native Land territory geometry and the mixed topology containing it are excluded.
No migration, ingestion/backfill, database write, paid service, new scheduler,
notification or inference is part of Phase 1. Versioned bundled records provide a
replay-safe initial catalogue without creating another mutable evidence store.

Acceptance: every event detail renders its sources/limitations; malformed filters
are bounded; hashes and source references validate; tampering returns unavailable,
not an empty success; dynamic text is escaped; feature-off routes return 404;
map years switch/comparison/playback work with keyboard and on mobile. All record
links and 23 maps remain usable without JavaScript.

## Phase 2 — foundation/evidence reliability

Reproduce relevant R01–R17 findings against current owning checkouts and deployed
revisions. Prioritize fail-closed service authentication, account isolation,
production secret policy, evidence-backed verdict semantics, numeric/French/time
clustering and coherent summaries. Separate articles, curated political claims
and keyword promise candidates. Do not certify a historical issue from a ZIP
snapshot. Standalone Market/Civic/Legal and protected infra need their owners.
No public historical/political conclusion becomes verified solely from AI output
or a C.R.E.E.D. score. Retain exact source document versions, hashes and locators.

## Phase 3 — Promises & Results

Extend canonical accountability entities and existing expenditure/contract mirrors.
Add one source-backed Investments, Housing and Savings record, with separately
reviewed statement evidence and delivery state. Model announcement, financing
capacity, authorization/appropriation, legal commitment, award/amendment, payment
and measured outcome separately. Preserve fiscal/calendar periods, currency,
price basis, denominators and parent/child overlap groups. Unknown is not zero.
A budget headline is not a disbursement and housing starts are not completions.
Use additive reviewed migrations with disposable restore/rollback tests; no cross-
product database writes. No bulk publication of keyword research seeds.

## Phase 4 — Legislation & Money

Reuse the S-7 dossier and 31-Act register as research intake. Bind exact parliament,
session, bill/clause version, commencement and primary source evidence. Indexing
Acts is not completed subsection analysis or evidence of misconduct. Repair Civic
bill/vote replay and Legal fetch/error semantics in their owning repositories.
Typed awards, grants, loans, regulatory benefits, lobbying and dated ownership
remain distinct, with reviewed entity resolution and counter-evidence.

Canonical WTF graph and hub follow/signal graph have separate databases/IDs. Use
explicit mappings and authenticated versioned read-only adapters. Keep private
bids, portfolios and legal workspace data out of public dossiers. No research-to-
trading path. Reuse Department HQ for bounded future inference and existing
single-writer graph ingress, source-health machinery, durable jobs and C.R.E.E.D.
telemetry; do not create duplicate fleets or task stores.

## Phase 5 — reviewed research and durable corrections

Expand nation-authored histories, translations, local histories and licensed
geometry through source review. Version evidence, retain originals and propagate
withdrawals/corrections to dependent summaries. Use acknowledged outboxes,
idempotency, leases, retry/dead-letter reasons and measured coverage. Source outage
must stay distinct from a valid empty feed. Advance records to public conclusions
only after editorial approval and provenance review, never by changing every
publication_ready flag during import.

## Release and rollback gates

See what-the-fact/docs/history-atlas-release.md for exact validation, consumer-only
release, feature enablement, runtime checks and rollback. Both PRs require current-
head review and human merge in dependency order. No production deployment,
container restart, migration or feature enablement was performed in development.

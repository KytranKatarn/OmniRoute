# Canadian History Atlas — operator release checklist

This checklist is reviewable release preparation, not an executed deployment.
Merge the data PR before the application PR; verify their reviewed heads and the
integrated release SHA. After its data dependency merges, rebase only the application commits onto
merged main, retarget the application PR to main, and review the new exact head. Do not deploy a branch or bypass F.O.R.G.E./human review.

## Validation before release

From the integrated isolated checkout:

```sh
PYTHONPATH=what-the-fact python3 -m pytest --noconftest -p no:cacheprovider -p tests.history_no_external_io -q \
  what-the-fact/tests/test_history_atlas.py \
  what-the-fact/tests/test_nav_shell.py \
  what-the-fact/tests/test_news_favicon_requests.py
node --check what-the-fact/consumer/static/history/atlas.js
git diff --check
```

Most tests use a local Flask instance and bundled files. One integration check
boots create_app() with billing initialization and the navigation counter stubbed.
The explicit pytest guard forbids PostgreSQL connections and requests HTTP calls,
and redirects any existing billing fixture to a disposable SQLite file.
The broader DB-backed test fixtures must NOT run against production: their
clean_schema fixture drops/recreates test schemas. If a broader suite is required,
provision an explicitly disposable database and WTF_TEST_DATABASE_URL first.

Check the manifest event/map hashes, stable IDs, source references and original
archive identity. The only source normalization is one final newline for repository
hooks; original and packaged hashes are both retained. SVGs have only passive
geometry/text: no scripts, external resources or event handlers. The mixed topology
with unlicensed Native Land geometry is deliberately not shipped.

Local browser acceptance: 1440px desktop and 390px phone; keyboard range Home/End;
1867/2003 snapshot switch; preceding-snapshot comparison; explicit play/pause;
province search; undated event sources; no horizontal overflow or page errors.
Also check with JavaScript disabled: records, filters, sources and all dated map
links remain usable. The page has no automatic playback and pauses when hidden.

## Source rights/editorial review

The official NRCan dataset identifies the Open Government Licence — Canada:
https://open.canada.ca/data/dataset/e88ce995-b69a-4595-a752-bb06b061b5a3

Retain attribution and the source/licence links. Natural Earth's terms identify
its raster/vector data as public domain:
https://www.naturalearthdata.com/about/terms-of-use/

Native Land licensing is unresolved in the input archive and its geometry is
excluded, not merely hidden. The Library of Congress 1763 catalogue reference is
not an embedded licensed image. No rights clearance of source prose or claim of
full primary-document review is implied by this release. Review the visible
research preview and source reuse before enabling it for public visitors.

## Preflight on Citadel (read only)

Verified on 2026-10-13: mesh host 100.64.0.10, product directory
/opt/archie-products/what-the-fact, service wtf-consumer, running container
what-the-fact-wtf-consumer-1. Verify again before release; names may change.

```sh
ssh root@100.64.0.10 'docker ps --format "{{.Names}} {{.Image}}"'
ssh root@100.64.0.10 'curl --max-time 10 -fsS http://127.0.0.1:8103/version'
ssh root@100.64.0.10 'docker inspect --format "{{.Image}}" what-the-fact-wtf-consumer-1'
```

Record the old image ID/digest, running SHA, release SHA and feature flag state in
the operator release receipt. Preserve the old image with a rollback tag before
building, because the existing helper reuses the 0.1.0 image tag. Preserve the
current deployment source and protected configuration through the existing backup
manager, without printing credentials. There is no Atlas schema change or backfill;
do not touch the local PostgreSQL volume, hub database, or existing journal data.
Confirm restore availability for normal operations; image rollback is not data
restoration. Keep all unrelated workers/services on their current revisions.

## Approved consumer-only deployment

Use the existing product deployment workflow from the exact reviewed, integrated
release checkout. The existing helper stamps GIT_SHA/BUILD_TIME and syncs source
while excluding .env. Its default is ALL services, so explicitly select consumer:

```sh
./what-the-fact/deploy.sh consumer
```

This rebuilds image-baked consumer code. Restart alone cannot deploy it. Do not
invoke the helper with `all`, rebuild databases, run migrations, or touch ingestion
for this Atlas UI release. The ingest API shares the consumer image tag but its
running container need not be restarted for this read-only preview; record its
separate provenance rather than claiming every service was updated.

The new feature defaults OFF. An authorized operator separately adds
WTF_HISTORY_ATLAS_ENABLED=1 to the consumer's existing env_file configuration
without exposing or rewriting other secrets. Recreate only the consumer with the
existing reviewed Compose workflow. Codex does not edit .env or Compose files.
Do not mistake shell-exporting a variable for passing it into the container: this
flag is read from the application's environment at process startup.

With the flag OFF, verify /history/atlas and /api/history/events return 404 and the
shared Data menu has no Atlas entry. After reviewed enablement, verify /version
matches the release SHA through the running process, then verify direct and public
/history/atlas, /history/events/CH-0001, /history/movements, and bounded
/api/history/events. Test one actual image URL and 1867/2003 comparison in a real
browser. Confirm draft labels, noindex headers, source links, mobile/keyboard
behavior, 159 events and absence of Native Land geometry. Capture errors and exact
image identity; a successful build or current source file is not runtime proof.

## Rollback

First disable the Atlas feature through the same authorized configuration workflow
and recreate ONLY the consumer; verify routes return 404 and navigation disappears.
For code rollback, restore/tag the recorded previous image and run the approved
consumer-only `up --no-deps --force-recreate` workflow without rebuilding the new
source. Verify the old /version SHA and normal news/auth routes. Preserve both
release receipts and old images until acceptance; never prune the rollback image
mid-release. No Atlas database changes require reversing and no source evidence
should be deleted to roll back the UI. Revert application code through a reviewed
PR if necessary; retained draft assets are inert when the feature is disabled.

# Restricted-role application acceptance plan

Status: **planned, not executed on PostgreSQL for this revision**.
Production is untouched. The previously reported Claude CLI rehearsal passed the
earlier ACL boundary after adding owner schema USAGE and waiting for the database.
This revision changes application code and adds ingest DELETE on
`parliament.ec_contributions`; that result must not be reused as proof of this revision.

## Candidate and preparation

Candidate source snapshot is based on `309a55a8d33d62f64054fd9d5a56aa3dce5b3d7f`.
It includes Claude's owner-USAGE and real-database readiness fixes. The readiness
probe now also uses container-local TCP so it cannot pass on initdb's temporary
Unix-socket server. Network access, host mounts, production secrets and external
collectors must remain unavailable during these tests.

1. Review/apply the explicit patch to a clean feature worktree. Reconcile migration
   number 107 with current main before committing. Never stage an incomplete
   worktree's apparent mass deletions or unrelated shared-tree files.
2. Restore the reviewed `docs/audits/2026-10-20-wtf-schema-only.sql` into a NEW
   disposable PostgreSQL 16 instance. No production data or application secrets.
3. Apply migration 107 twice as the scratch operator. Verify eight bootstrap
   tables and four indexes exist, GIC action_type is present, and exactly one
   migration-107 ledger row exists. Compare schema before/after; no unexpected
   table, constraint or function changes. Also exercise bootstrap on an empty
   scratch schema with a WTF-shaped migrations ledger to prove missing objects
   can be provisioned. This is not a fresh install of all historical migrations.
4. Apply the regenerated role SQL twice AFTER the bootstrap migration. Re-run all
   four actual-login ACL checks, evidence positive/negative tests and the
   deliberately forbidden-grant control. Save exact revision/image digest,
   PostgreSQL version, commands and results without credentials.

From the role-split directory, the updated boundary rehearsal command is:

```sh
python3 rehearse.py /absolute/path/to/reviewed-wtf-schema.sql \
  --bootstrap-migration ../../migrations/107_ingest_schema_bootstrap.sql
```

That command removes its container and does not run the application workloads
below. Use a separately disposable application-test instance seeded with synthetic
fixtures to run those. Keep the app candidate network-isolated with its scratch
database; mock external feed, billing, mail, dispatch and inference calls.

## Application workload matrix

Each service must connect as its actual restricted login (including each cached
engine/pool), not an operator using SET ROLE. Confirm current/session_user,
non-superuser flags, effective rights and correct non-login owners before testing.
For each mutation, verify the persisted row through an independent scratch read.
Capture expected failures as well as success; a clean HTTP response alone is not
proof, because some application helpers swallow persistence errors.

| Login / path | Synthetic fixture and operation | Required result |
|---|---|---|
| Ingest — GIC `_upsert` | Insert appointment, repeat with changed action_type | One pc_number row updated; no runtime DDL; defaults and sequence work |
| Ingest — securities `run` | Stub a healthy 50-issuer fetch; repeat with changed name | Correct UPSERTs, no schema creation; thin-fetch guard still prevents writes |
| Ingest — BoC, StatCan, FX, annual/quarterly fiscal, ODA `_upsert` | Insert then update each conflict key | All eight bootstrap tables work with SELECT/DML/sequence rights only; no table owner/schema CREATE needed |
| Ingest — EC `sync_contributions` | Seed old rows, supply bounded valid ZIP/CSV with multiple batches | Only one final commit; replacement row count/amount totals match source; IDs need not reset |
| Ingest — EC failure | Inject second-batch SQL failure, malformed ZIP/read error, all-filtered/empty input | Exception/error heartbeat; previous committed rows and checksum unchanged |
| Ingest — EC concurrency | Pause first refresh after a batch; start second and a reader | Reader sees previous committed dataset; second refresh refuses before DELETE; first publishes once; later refresh can acquire lock |
| Ingest — EC interrupted process | Stop the scratch worker mid-import | Server rolls back; old dataset survives; transaction lock is released |
| Ingest — other jobs | Stub sources; invoke each configured job once with representative rows | Correct row writes and ingest_log heartbeat; no missing table/column/function rights hidden by exception handlers |
| Consumer — state | API-key create/use/revoke, article-view counts, alert enable/delete, newsletter subscribe/unsubscribe | Correct isolated updates; no unintended table writes |
| Consumer — admin | Claim create/edit/status, graph dedup merge/revert and pointer updates | Authorized mutations persist; unauthorized requests still fail closed; imported dynamic helpers have exact required grants |
| Consumer — reads | News/article, AURORA history/map, entity/chain/cost and snapshot-backed pages | Expected status/content from synthetic data; no swallowed permission failures; raw evidence excluded from public payloads |
| Tech — Deep Dive | Stub model result; persist bias, replace fact checks and update article analysis fields | New values survive reload; `sync_article_latest_verdict` trigger updates article as intended under restricted role |
| Tech — flags/API | Insert score flag; read articles/audit/source endpoints | Flag persists; read payloads correct; evidence mutation denied |
| Ingest API — dedicated factory | Boot `consumer.app:create_ingest_app()`; authenticated graph and companies requests | Four graph tables support inserts/upserts/merge-following; no public/admin/billing/static routes registered |
| Ingest API — auth | Missing configured key, wrong request key, valid key with invalid payload | 503, 401 and validation error respectively; no unauthorized writes |
| Every role — denied boundary | Repeat current generated verifier | No evidence UPDATE/DELETE/TRUNCATE, owner escalation, schema creation, or sequence setval; counts/digests unchanged |
| Operator-only | Run migrations through reviewed operator credential | Runtime cannot access migrations ledger/admin identity or perform DDL; owner roles stay NOLOGIN |

Review PostgreSQL view/trigger behavior and extension function permissions from
the schema dump. Consumer dedup requires public unaccent/pg_trgm helpers; the
ingest-api role intentionally has no corresponding consumer permissions.
Exercise the hub scraper login and restricted DR fallback separately before their
configuration changes; those identities were not in the four-service audit.

## EC scale gate

The new refresh trades sequence ownership and partially visible imports for a
single DELETE/INSERT transaction. Before production, measure representative
multi-million-row refresh time, WAL volume, disk headroom, replica/backup effects,
dead tuples/autovacuum recovery, concurrent-reader latency and rollback time.
The 512 MiB schema-only rehearsal container is NOT a scale-test environment.
Only cooperating versions use the advisory lock: drain old workers before release.
If the measured cost is unacceptable, keep cutover blocked and design a separate
operator-controlled staging/publication mechanism; do not restore TRUNCATE or
ownership to the runtime just to pass a test.

## Release gates and evidence

- Record every matrix row as pass/fail with an observable persisted result.
- Re-run the forbidden-grant control and failure injection on copies. A positive
  ACL report alone does not establish application correctness.
- Apply migration 107 through the guarded product procedure only after review;
  then transfer/check owners and restricted grants, then the approved app images
  and service-specific credentials. No production action is authorized by this plan.
- An operator must change ONLY ingest-api's command from
  `consumer.app:create_app()` to `consumer.app:create_ingest_app()` in a separately
  reviewed deployment change. The code factory alone does not change its running
  route surface. Keep consumer on `create_app()`.
- Complete `rotation-checklist.md`; the reported exposed superuser password is
  still live until the operator rotates it. No password value is needed in review.
- Rollback preserves evidence and the previous committed EC dataset. An older
  image's runtime DDL/TRUNCATE is incompatible with the new roles: pause its jobs
  and forward-fix under review rather than reintroducing privileged credentials.

PostgreSQL semantics: [transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html),
[transaction-level advisory locks](https://www.postgresql.org/docs/16/explicit-locking.html).

Results of the workloads defined here are recorded in [workload-results.md](workload-results.md).

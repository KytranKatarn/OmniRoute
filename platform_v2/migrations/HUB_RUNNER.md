# Explicit-allowlist hub migration runner

Task #7276. **Not yet wired to production startup.** Human review/merge and an
owner-controlled deployment hook are required before calling this automatically.
No Compose, Dockerfile, secret, or live database change is part of this PR.

From the platform runtime (using its existing database configuration):

```sh
python -m services.hub_migration_runner --database archie_test
python -m services.hub_migration_runner --database archie_test --apply
```

Without `--apply` the transaction is database-enforced read-only. The database
argument is mandatory and checked against the actual connection. Do not put
passwords on the command line. The apply output reports each migration's status
**before** execution; a subsequent plan must show all entries as `applied`.

## Approval and rollout contract

- Only the ordered files in `hub_allowlist.json` are candidates. Every file is
  pinned by SHA-256 and fully read before database work begins. No directory sweep,
  inferred baseline, or migration-number deduplication is performed.
- The initial allowlist is limited to idempotent 022/023/024. These are incremental
  migrations: **the base platform schema must already exist**, including
  `github_skills` and the hub's `schema_migrations(version)` table. This is not a
  fresh PostgreSQL/bootstrap installer. Migration 023 can seed pending approvals
  for currently analyzed skills; review that effect before the initial rollout.
- All pending SQL and the separate `public.hub_migration_runs` ledger commit in
  **one transaction**. Any failed migration rolls back the entire batch, including
  ledger creation. Earlier successfully committed batches remain unchanged.
- A transaction-scoped advisory lock refuses concurrent runners. DDL lock waits
  are capped at 5 seconds, individual statements at 60 seconds. Transaction failure
  releases the lock automatically; the runner exits nonzero and startup must stop.
- Only plain, transactional SQL is approved. The conservative preflight rejects
  transaction/procedural control keywords even inside comments or quoted text.
  Do not weaken that check to admit scripts with `BEGIN`/`COMMIT`/procedural blocks.
- Applied files cannot be removed or edited, even by repinning their manifest
  hashes: ledger hashes must still agree. Append a new reviewed migration instead.
  Old `schema_migrations` entries are not proof a particular file/hash ran. The
  initial rollout intentionally replays these three idempotent files once.

After review/merge, an infrastructure-authorized lane should run plan/apply/plan
against an isolated, initialized test database, then arrange a maintenance window,
backup, and explicit production target. A **single pre-start migration step** must
finish successfully before starting either platform or scheduler workers. Never
execute migrations in Flask imports or separately in each Gunicorn worker. Do not
mark #7276 complete until the hook is deployed and verified. Failed migrations are
not recorded; inspect and fix via a new reviewed change, never mark failed SQL as
applied or hide the error to let startup continue.

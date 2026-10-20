# WTF restricted-role cutover — implementation review package

Status: **code prepared; current PostgreSQL workload acceptance outstanding**.
No production migration, deployment or credential change was performed.

The earlier boundary rehearsal passed for all four roles in Claude CLI. It found
and fixed evidence-owner schema USAGE and database-readiness bugs; those fixes
are preserved. This revision changes application code and adds one permission,
so the earlier run does not establish acceptance of the new candidate.

## Changes

- GIC, securities and five market ingest modules now execute only DML. Their
  eight bootstrap tables, four indexes and GIC action_type repair are in operator
  migration `107_ingest_schema_bootstrap.sql`. Existing public entrypoints remain.
- Elections Canada refresh uses one DELETE/INSERT transaction with a transaction
  advisory lock. Mid-import failure or an empty result rolls back to the previous
  committed dataset. It refuses autocommit connections and overlapping jobs.
  It never resets IDs or requires TRUNCATE/ownership. The candidate grants ingest
  DELETE only on the existing ec_contributions table in addition to its INSERT.
- `consumer.app:create_ingest_app()` exposes entity ingest, companies, process
  health and version only. Existing internal-key authentication is preserved;
  public/admin/billing/static routes are absent. Consumer `create_app()` retains
  its existing route set. An operator must switch ingest-api's deployment command
  after review; source code alone does not change the running service.
- The rehearsal can apply the bootstrap migration twice before restricted grants.
  Its readiness check uses a real connection to the target database over local
  TCP, avoiding initdb's temporary Unix-socket server.

## Roles and owners

| Identity | Scope |
|---|---|
| wtf_owner | Non-login owner of ordinary audited tables/views/sequences, schemas and database |
| wtf_evidence_owner | Non-login owner of the three evidence tables and their sequences; schema USAGE for FK checks |
| wtf_consumer | Explicit reads and required state/admin/graph write exceptions |
| wtf_tech | Explicit reads; bias scores, fact checks, article analysis state and score flags |
| wtf_ingest | Per-table scheduler DML; evidence SELECT/INSERT only |
| wtf_ingest_api | SELECT/INSERT/UPDATE on four graph tables only |
| Operator login | Separate controlled migration/admin credential, absent from runtime containers |

Runtime roles have no owner membership, superuser, BYPASSRLS, replication,
create-role/database/schema, grant options, TRIGGER, REFERENCES or TRUNCATE rights.
Sequence USAGE is limited to INSERT dependencies; no setval rights. Future objects
receive no automatic runtime grants.

`permissions.json` is the candidate matrix. Its source references originate in
that source inventory; reconcile them and dynamic/imported paths against the
final integrated revision during workload acceptance. The four-service audit
reported 139 relations (including views), 79 sequences and version 160015
(PostgreSQL 16.15). The schema-only dump contains 126 base tables.

`render_grants.py` generates the grants SQL (`python3 render_grants.py > draft_grants.sql`; the file is a GENERATED artifact and is deliberately not committed, so review `render_grants.py` and `permissions.json`, the sources of truth). `rehearse.py` renders it on the fly. The SQL is restricted to the disposable
`wtf_role_rehearsal` database on PostgreSQL 16. Roles are initially NOLOGIN, with
no passwords. This is not a numbered production role migration. No script here
rotates or disables wtfuser.

## Validation and next step

- 71 focused pytest checks pass for runtime DML, API routes/auth, EC success and
  rollback paths, existing market/date behavior and migration-runner contracts.
- Seven offline policy tests pass. A copy with per-batch commits deliberately
  reintroduced makes the rollback regression test fail.
- The complete patch passes `git apply --check --whitespace=error` against the
  current shared checkout. No production/browser/runtime claim is made.
- Current PostgreSQL execution, migration idempotence and application workload
  proof remain unrun here because Docker and Citadel SSH access are sandbox-denied.
- The EC transaction must be measured at representative scale for WAL, storage,
  reader latency and rollback cost before release.

Follow [workload-test-plan.md](workload-test-plan.md) for preparation, exact
acceptance cases and release gates. Follow [rotation-checklist.md](rotation-checklist.md)
for Citadel environment isolation, Docker secret handling, hub jobs, old sessions
and the compromised superuser password. The prior password remains an operator
rotation item, not something this package changed.

## Review and shipping

The source snapshot is based on `309a55a8d33d62f64054fd9d5a56aa3dce5b3d7f` under
`codex/worktrees/wtf-role-dependencies/`. Shared Git metadata was read-only, so no
commit or PR was created. Apply only the explicit review patch to a clean Codex
feature worktree; never stage apparent deletions from the incomplete earlier
`wtf-role-audit` worktree. Recheck migration numbering against current main.

Authoritative behavior: [PostgreSQL transaction isolation](https://www.postgresql.org/docs/16/transaction-iso.html),
[advisory locks](https://www.postgresql.org/docs/16/explicit-locking.html),
[privileges](https://www.postgresql.org/docs/16/ddl-priv.html).

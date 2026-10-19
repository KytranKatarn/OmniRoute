# A.U.R.O.R.A. evidence-history database hardening

## Finding

Migration 106 revokes `UPDATE`, `DELETE`, and `TRUNCATE` from `wtfuser`, but
that grant boundary does not make the evidence ledger append-only when the
runtime connection is itself a PostgreSQL superuser and owns the tables.
Superusers bypass table ACLs, and a table owner can change grants or table
definitions. The application currently writes to these tables through the
same database connection used for its other WTF data. A migration-only revoke,
trigger, or role grant would therefore give a false assurance while that
runtime identity remains privileged.

Read-only verification against the live Citadel PostgreSQL service on
2026-10-19 confirmed that the checked connection was `wtfuser` and that its
role flags include superuser, create-role, create-database, and replication
privileges. The role inventory query found no separate `wtf*` login roles.
Migration 106's ACL changes therefore do not constrain the live account. No
production settings or data were changed during this verification.

This is a security boundary that needs a coordinated database and runtime
change. This repository lane does not own the production environment file,
Docker Compose configuration, credentials, or deployment, so this document
does not claim that the production writer has been restricted.

## Target design

- A non-login `wtf_evidence_owner` owns the three evidence-history tables.
- A non-login `wtf_evidence_reader` role has `SELECT` only.
- A non-login `wtf_evidence_writer` role has `SELECT` and `INSERT` only, plus
  sequence usage needed by the two generated IDs. It has no ownership,
  schema-creation, role-management, or database-management rights.
- Dedicated non-superuser login roles inherit narrowly scoped service roles.
  Build a table/sequence/function privilege matrix from the SQL each service
  actually executes before assigning grants. At minimum, keep the ingest,
  consumer, and tech services on separate credentials; consumer may need
  narrowly scoped writes for user-facing state, while tech should be read-only
  where its routes permit. Do not infer grants from service names alone.
- Do not leave the current superuser `WTF_DATABASE_URL` in any long-running
  application container. A separate evidence pool does not protect against a
  process compromise if that same process can still read and use the
  superuser URL. Migrations and administrative scripts must use a separate,
  operator-controlled credential absent from runtime containers.
- Give the evidence tables a non-login owner and grant the evidence writer
  role only `SELECT`/`INSERT` plus the needed sequence privileges; grant the
  evidence reader `SELECT` only. This is one part of the service-level split,
  not a substitute for removing superuser credentials from app processes.
- The primary database superuser remains a trusted administrator and can
  change records by definition. The control here limits application-service
  compromise; it does not claim to make evidence tamper-proof against a
  database administrator. Independent backup and audit-log retention remain
  necessary for administrator-level tamper evidence.

## Required implementation and cutover sequence

1. Inventory the actual connection identity of every live WTF service and
   administrative job. Record role attributes, table owners, table/sequence
   ACLs, and query-level read/write needs. Never print connection URLs or
   passwords. The 2026-10-19 baseline is that the checked runtime connection is
   `wtfuser`, a superuser; verify each service independently before cutover.
2. Create a least-privilege matrix for `wtf-ingest`, `wtf-consumer`, and
   `wtf-tech`, plus a separate migration/admin path. Test every required read,
   insert, update, delete, sequence, and function operation in a disposable
   copy before writing any production migration.
3. Add an idempotent, guarded migration for non-login owners/group roles,
   per-service grants, and evidence-table ownership. Rehearse against a
   disposable PostgreSQL instance. Negative tests must prove runtime roles
   cannot manage roles/databases, alter/drop evidence tables, or mutate
   append-only evidence, while required application operations still work.
4. Update application configuration to use distinct credentials per service
   and an operator-only migration credential. No runtime container may retain
   the old superuser URL as a fallback. Fail closed when a required restricted
   URL is missing; do not silently fall back to the privileged connection.
5. Provision unique credentials through the host's approved secret mechanism.
   Do not commit them, place them in migration files, put them in URLs in logs,
   or pass them as command-line arguments.
6. Before cutover, take and verify a WTF database backup and confirm a tested
   restore path. Apply the reviewed migration, roll out one service at a time,
   and verify each running process's `current_user`, `rolsuper`, and
   `has_table_privilege` results without exposing credentials. Exercise
   required reads/writes and prove denied writes fail in rollback-only tests.
7. Keep a separately controlled break-glass admin credential for operators.
   If a service fails, roll that service back to its prior image and restore
   only its previous runtime configuration under operator control. Do not put
   the privileged credential back into a long-running app container, and do not
   drop evidence tables or delete captured evidence as rollback.

## Validation and rollback requirements

Validation must prove the security property from the application login, not
from the migration administrator:

```sql
SELECT current_user,
       (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) AS is_superuser,
       has_table_privilege(current_user, 'wtf.aurora_source_version', 'SELECT') AS can_read,
       has_table_privilege(current_user, 'wtf.aurora_source_version', 'INSERT') AS can_insert,
       has_table_privilege(current_user, 'wtf.aurora_source_version', 'UPDATE') AS can_update,
       has_table_privilege(current_user, 'wtf.aurora_source_version', 'DELETE') AS can_delete,
       has_table_privilege(current_user, 'wtf.aurora_source_version', 'TRUNCATE') AS can_truncate;
```

Expected application-writer results are `is_superuser = false`, read/insert
true, and update/delete/truncate false. Repeat against all three evidence
tables and their sequences. In a disposable database, prove that failed
mutations leave row counts and checksums unchanged.

Rollback must preserve evidence. Restore the previous application image and
secret configuration if the new pool fails; restore ownership/grants only
with a reviewed rollback migration and only after the service has reverted.
Take a verified backup before the cutover and record its location and restore
test result in the deployment record.

## Scope of this change

This follow-up records the verified security gap and the complete cutover
contract. The production connection identity cannot be fixed by repository
code alone: it requires host-owned secret/configuration changes and a
coordinated migration. Do not describe migration 106's `REVOKE` as effective
against a superuser runtime connection until the application uses and verifies
the restricted evidence login.

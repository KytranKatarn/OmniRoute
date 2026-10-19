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
- Dedicated non-superuser login roles inherit the reader or writer grants.
  The ingest service uses the writer login for capture-run and source-version
  writes; the consumer uses the reader login. Other WTF database operations
  continue to use their existing connection until a separately reviewed
  least-privilege plan covers those tables.
- Evidence writes use a separate connection pool/configuration so the
  evidence writer login is actually used for these writes. Reusing the
  existing superuser connection would defeat the boundary.
- The primary database superuser remains a trusted administrator and can
  change records by definition. The control here limits application-service
  compromise; it does not claim to make evidence tamper-proof against a
  database administrator. Independent backup and audit-log retention remain
  necessary for administrator-level tamper evidence.

## Required implementation and cutover sequence

1. Confirm the exact runtime database roles and grants from the running WTF
   PostgreSQL instance. Record role attributes, table ownership, table ACLs,
   sequence ACLs, and which services currently use each connection. Do not
   print connection URLs or passwords.
2. Add a guarded, idempotent migration for the role grants and ownership
   transfer. Rehearse it against a disposable PostgreSQL instance, including
   negative tests proving the writer cannot update, delete, truncate, alter,
   or drop evidence tables, while it can insert and the reader can select.
3. Add a separately configured evidence read/write connection in the
   application. Fail startup or collector initialization clearly if the
   evidence writer URL is absent; never silently fall back to the privileged
   general WTF connection.
4. Provision unique random credentials through the host's approved secret
   mechanism. Do not commit them, put them in migration files, or pass them as
   command-line arguments.
5. Back up the WTF database, apply the reviewed migration, deploy the runtime
   connection change, and verify the actual running service's
   `current_user`, `rolsuper`, and `has_table_privilege` results without
   exposing credentials. Verify captures still work and forbidden writes fail
   when attempted in a rollback-only transaction.
6. Keep supervised data capture unchanged if any step fails. Revert the
   application to its previous image/configuration and restore the prior role
   grants/ownership from the reviewed down procedure. Do not drop evidence
   tables or delete captured evidence during rollback.

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

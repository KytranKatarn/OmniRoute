# PR #3986 follow-up

Two confirmed owner-role defects are rejected before ownership changes: existing
owners with LOGIN and any incoming owner membership. Runtime LOGIN remains allowed
for rerunnable rehearsal. No existing identity is silently altered or membership revoked.

The column-grant finding does not describe PostgreSQL 16 REVOKE behavior:
https://www.postgresql.org/docs/16/sql-revoke.html states table revokes also remove
the corresponding column privileges. Added effective column-privilege verification
and runnable scratch controls instead of a redundant revoke. The rehearsal seeds
both direct and PUBLIC column UPDATE grants before reapplying the policy; it also
injects them afterwards to prove the verifier rejects them.

Nine offline policy tests pass. On 2026-10-20 the owner ran the revised script
from a host terminal: the disposable PostgreSQL 16 rehearsal passed for all four
actual runtime logins, including the owner LOGIN/membership rejection controls,
column-grant controls, intentional forbidden-grant detection and restoration.
Evidence row counts/checksums were unchanged. This is grant/evidence verification;
application workload and scale acceptance remain separate cutover requirements.
No production connection, credential, role, or service was changed.

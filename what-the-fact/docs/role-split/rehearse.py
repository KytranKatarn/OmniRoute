"""Rehearse only in a NEW disposable Docker PostgreSQL instance.

Requires an operator-reviewed schema-only dump of the WTF database, exported
with --schema-only --no-owner --no-acl. No production connection is accepted.
Docker socket access is required. Does not publish ports or mount host paths.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
import uuid

from render_grants import HERE, render
from verify_grants import verification_sql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("schema_dump", type=Path)
    parser.add_argument("--bootstrap-migration", type=Path,
                        help="reviewed operator migration to rehearse twice before grants")
    args = parser.parse_args()
    dump = args.schema_dump.read_text()
    if "PostgreSQL database dump" not in dump or "CREATE TABLE" not in dump:
        parser.error("reviewed plain PostgreSQL schema-only dump required")
    # pg_dump table data, database reconnects and psql shell escapes are forbidden.
    for line in dump.splitlines():
        stripped = line.lstrip()
        if stripped.upper().startswith(("COPY ", "INSERT INTO ", "CREATE DATABASE ", "ALTER DATABASE ")):
            parser.error("schema-only dump required, without database commands")
        if stripped.startswith("\\") and not stripped.startswith(("\\restrict ", "\\unrestrict ")):
            parser.error("psql commands are not allowed in schema input")
    manifest = json.loads((HERE / "permissions.json").read_text())
    grant_sql = render(manifest)
    bootstrap_sql = args.bootstrap_migration.read_text() if args.bootstrap_migration else None
    name = "wtf-role-rehearsal-" + uuid.uuid4().hex[:12]

    def command(argv, sql=None, check=True):
        return subprocess.run(argv, input=sql, text=True, capture_output=True, check=check)

    def psql(sql, role="postgres", check=True):
        return command(["docker", "exec", "-i", name, "psql", "-X", "-q",
                        "-v", "ON_ERROR_STOP=1", "-U", role, "-d", "wtf_role_rehearsal"], sql, check)

    created = False
    try:
        # Loopback not needed: no networking, no host socket/volume mounted.
        command(["docker", "run", "-d", "--name", name, "--network", "none",
                 "--memory", "768m", "--cpus", "1", "--tmpfs",
                 "/var/lib/postgresql/data:rw,size=512m", "-e", "POSTGRES_HOST_AUTH_METHOD=trust",
                 "-e", "POSTGRES_DB=wtf_role_rehearsal", "pgvector/pgvector:pg16"])
        created = True
        for _ in range(30):
            # pg_isready goes green during initdb's temporary server, before POSTGRES_DB exists.
            ready = command(["docker", "exec", name, "psql", "-X", "-q", "-U", "postgres",
                             "-h", "127.0.0.1", "-d", "wtf_role_rehearsal", "-c", "select 1"], check=False)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise RuntimeError("scratch database did not become ready")
        psql(dump)
        if bootstrap_sql:
            psql("BEGIN;\n" + bootstrap_sql + "\nCOMMIT;")
            psql("BEGIN;\n" + bootstrap_sql + "\nCOMMIT;")
        psql(grant_sql)
        psql(grant_sql)  # Idempotence on the same schema, not a fresh fixture.
        # Existing owner identities must fail closed; never silently revoke an
        # unknown operator's access. Each failed grant transaction is rolled back.
        for owner in ("wtf_owner", "wtf_evidence_owner"):
            psql(f'ALTER ROLE "{owner}" LOGIN;')
            bad = psql(grant_sql, check=False)
            if bad.returncode == 0 or "owner role must be NOLOGIN" not in bad.stderr:
                raise RuntimeError("LOGIN owner negative control was not rejected")
            psql(f'ALTER ROLE "{owner}" NOLOGIN;')
            psql('CREATE ROLE unexpected_owner_member NOLOGIN;')
            psql(f'GRANT "{owner}" TO unexpected_owner_member;')
            bad = psql(grant_sql, check=False)
            if bad.returncode == 0 or "owner role has unexpected members" not in bad.stderr:
                raise RuntimeError("owner membership negative control was not rejected")
            psql(f'REVOKE "{owner}" FROM unexpected_owner_member; DROP ROLE unexpected_owner_member;')
            psql(grant_sql)
        # PostgreSQL table revokes also revoke matching column ACLs. Prove that
        # behavior for both direct and PUBLIC grants instead of adding a redundant reset.
        # Choose a real column, so this check does not depend on schema naming.
        column = command(["docker", "exec", name, "psql", "-X", "-qAt", "-U", "postgres", "-d", "wtf_role_rehearsal", "-c", "SELECT attname FROM pg_attribute WHERE attrelid='wtf.aurora_source_version'::regclass AND attnum>0 AND NOT attisdropped ORDER BY attnum LIMIT 1;"]).stdout.strip()
        if not column or not column.replace('_', '').isalnum():
            raise RuntimeError("no safe evidence column for ACL control")
        column_grant = f'GRANT UPDATE ("{column}") ON wtf.aurora_source_version TO wtf_consumer, PUBLIC;'
        psql(column_grant)
        psql(grant_sql)

        snapshot_sql = "\n".join(
            f"SELECT count(*)::text || ':' || coalesce(md5(string_agg(row_to_json(t)::text, '' ORDER BY row_to_json(t)::text)), '') FROM {table} t;"
            for table in manifest["evidence_tables"]
        )
        before = psql(snapshot_sql).stdout
        for role in sorted(manifest["roles"]):
            psql(f'ALTER ROLE "{role}" LOGIN;')  # Trust auth inside this networkless scratch container only.
            psql(verification_sql(manifest, role), role)
            print(f"PASS: {role}: catalog rights, executable reads, evidence boundary")
        # Prove the verifier detects a real ACL regression, then restore it.
        psql("GRANT UPDATE ON wtf.aurora_source_version TO wtf_consumer;")
        bad = psql(verification_sql(manifest, "wtf_consumer"), "wtf_consumer", check=False)
        if bad.returncode == 0 or "unexpected UPDATE: wtf.aurora_source_version" not in bad.stderr:
            raise RuntimeError("negative control did not detect the intentional grant")
        psql("REVOKE UPDATE ON wtf.aurora_source_version FROM wtf_consumer;")
        psql(verification_sql(manifest, "wtf_consumer"), "wtf_consumer")
        psql(column_grant)
        bad = psql(verification_sql(manifest, "wtf_consumer"), "wtf_consumer", check=False)
        if bad.returncode == 0 or "unexpected column UPDATE: wtf.aurora_source_version" not in bad.stderr:
            raise RuntimeError("column grant negative control was not detected")
        psql(grant_sql)
        psql(verification_sql(manifest, "wtf_consumer"), "wtf_consumer")
        if psql(snapshot_sql).stdout != before:
            raise RuntimeError("evidence counts or checksums changed")
        print("PASS: intentional forbidden grant detected; restored boundary passes")
        print("PASS: evidence row counts and checksums unchanged after rollback-only tests")
        print("Workload acceptance remains separate: this verifies ACLs and evidence I/O, not every application query.")
    except subprocess.CalledProcessError:
        # Never print DSNs, command environments, dump contents or raw DB errors.
        raise SystemExit("Scratch rehearsal failed; inspect the reviewed schema and grants locally.") from None
    finally:
        if created:
            command(["docker", "rm", "-f", name], check=False)


if __name__ == "__main__":
    main()

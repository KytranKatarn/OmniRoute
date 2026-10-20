"""Render the reviewed draft allowlist as scratch-only PostgreSQL SQL.

No network, credentials, or database connection. Production migration creation is
a separate reviewed step after real workload rehearsal.
"""
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
SERVICES = {"wtf_consumer", "wtf_tech", "wtf_ingest", "wtf_ingest_api"}


def ident(value):
    if not re.fullmatch(r"[a-z_][a-z_0-9]*", value):
        raise ValueError("invalid identifier")
    return '"' + value + '"'


def qualified(value):
    schema, table = value.split(".")
    return ident(schema) + "." + ident(table)


def validate(manifest):
    if set(manifest["roles"]) != SERVICES:
        raise ValueError("exactly four distinct runtime roles required")
    evidence = set(manifest["evidence_tables"])
    for table, kind in manifest["audited_relations"].items():
        qualified(table)
        if kind not in {"r", "p", "v", "m"}:
            raise ValueError("unsupported relation kind")
    for sequence in manifest["audited_sequences"]:
        qualified(sequence)
    if evidence != {"wtf.aurora_capture_run", "wtf.aurora_source_version",
                    "wtf.aurora_capture_run_record"}:
        raise ValueError("evidence boundary changed")
    for name, role in manifest["roles"].items():
        ident(name)
        for schema in role.get("extra_schema_usage", []):
            ident(schema)
        for table in set(role["select"]) | set(role["write"]):
            qualified(table)
            if table not in manifest["audited_relations"]:
                raise ValueError("unaudited relation")
        for table, rights in role["write"].items():
            if not rights or not set(rights) <= {"INSERT", "UPDATE", "DELETE"}:
                raise ValueError("unsupported write permission")
            if manifest["audited_relations"][table] not in {"r", "p"}:
                raise ValueError("write grant requires a base table")
            if table in evidence and (name != "wtf_ingest" or set(rights) != {"INSERT"}):
                raise ValueError("evidence must remain append-only to ingest")
    if set(manifest["roles"]["wtf_ingest_api"]["write"]) != {
        "shared.entities", "shared.entity_mentions", "shared.entity_relationships",
        "shared.entity_external_ids",
        # push receipt (entity_push_receipts.record_push), INSERT-only; found by workload_ingest_api.py
        "parliament.ingest_log",
    } or set(manifest["roles"]["wtf_ingest_api"]["write"]["parliament.ingest_log"]) != {"INSERT"}:
        raise ValueError("ingest API write scope widened")


def render(manifest):
    validate(manifest)
    roles = sorted(manifest["roles"])
    schemas = sorted({t.split(".")[0] for t in manifest["audited_relations"]})
    lines = [
        "-- DRAFT. Scratch-only; not a production migration. No passwords.",
        "-- Run under psql -X -v ON_ERROR_STOP=1 in a disposable PG16 instance.",
        "BEGIN;",
        "DO $$ BEGIN",
        " IF current_database() <> 'wtf_role_rehearsal' THEN",
        "  RAISE EXCEPTION 'scratch database required'; END IF;",
        " IF current_setting('server_version_num')::int / 10000 <> 16 THEN",
        "  RAISE EXCEPTION 'PostgreSQL 16 required'; END IF;",
        " IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace",
        "  WHERE p.prosecdef AND n.nspname NOT LIKE 'pg_%') THEN",
        "  RAISE EXCEPTION 'review SECURITY DEFINER functions first'; END IF;",
        "END $$;",
    ]
    for name in ["wtf_owner", "wtf_evidence_owner"] + roles:
        q = ident(name)
        lines += [
            f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{name}') THEN",
            f" CREATE ROLE {q} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE",
            "  NOREPLICATION NOBYPASSRLS; END IF; END $$;",
            f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='{name}'",
            " AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls))",
            " THEN RAISE EXCEPTION 'unsafe existing role'; END IF;",
            f" IF EXISTS (SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname='{name}'))",
            " THEN RAISE EXCEPTION 'unexpected role membership'; END IF; END $$;",
        ]
    # Schema/database ownership cannot remain reachable from runtime identities.
    lines += ["ALTER DATABASE wtf_role_rehearsal OWNER TO wtf_owner;",
              "REVOKE ALL ON DATABASE wtf_role_rehearsal FROM PUBLIC;"]
    for name in roles:
        lines += [f"REVOKE ALL ON DATABASE wtf_role_rehearsal FROM {ident(name)};",
                  f"GRANT CONNECT ON DATABASE wtf_role_rehearsal TO {ident(name)};"]
    for schema in schemas:
        qs = ident(schema)
        lines += [f"ALTER SCHEMA {qs} OWNER TO wtf_owner;",
                  f"REVOKE ALL ON SCHEMA {qs} FROM PUBLIC;",
                  f"REVOKE ALL ON ALL TABLES IN SCHEMA {qs} FROM PUBLIC;",
                  f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {qs} FROM PUBLIC;"]
        for name in roles:
            lines += [f"REVOKE ALL ON SCHEMA {qs} FROM {ident(name)};",
                      f"REVOKE ALL ON ALL TABLES IN SCHEMA {qs} FROM {ident(name)};",
                      f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {qs} FROM {ident(name)};"]
    # Explicit audited objects only. Missing objects cause the transaction to fail.
    for table, kind in sorted(manifest["audited_relations"].items()):
        command = {"r": "TABLE", "p": "TABLE", "v": "VIEW", "m": "MATERIALIZED VIEW"}[kind]
        owner = "wtf_evidence_owner" if table in manifest["evidence_tables"] else "wtf_owner"
        lines.append(f"ALTER {command} {qualified(table)} OWNER TO {owner};")
    # Owned sequences follow their table owner; explicit statements also cover
    # standalone audited sequences. Rehearsal rejects inconsistent dependencies.
    for sequence in manifest["audited_sequences"]:
        owner = "wtf_evidence_owner" if sequence in {
            "wtf.aurora_capture_run_id_seq", "wtf.aurora_source_version_id_seq",
        } else "wtf_owner"
        lines.append(f"ALTER SEQUENCE {qualified(sequence)} OWNER TO {owner};")
    # FK checks on evidence INSERTs execute as the table OWNER, which must resolve the schema
    # (found by the first real PostgreSQL rehearsal, 2026-10-20). NOLOGIN, no runtime membership.
    for schema in sorted({t.split(".")[0] for t in manifest["evidence_tables"]}):
        lines.append(f"GRANT USAGE ON SCHEMA {ident(schema)} TO wtf_evidence_owner;")
    for name, role in sorted(manifest["roles"].items()):
        qr = ident(name)
        needed = sorted({t.split(".")[0] for t in role["select"] + list(role["write"])} | set(role.get("extra_schema_usage", [])))
        for schema in needed:
            lines.append(f"GRANT USAGE ON SCHEMA {ident(schema)} TO {qr};")
        for table in sorted(role["select"]):
            lines.append(f"GRANT SELECT ON TABLE {qualified(table)} TO {qr};")
        for table, rights in sorted(role["write"].items()):
            lines.append(f"GRANT {', '.join(sorted(rights))} ON TABLE {qualified(table)} TO {qr};")
            if "INSERT" in rights:
                # Discover sequence dependencies by column, not by guessed names.
                lines += ["DO $$ DECLARE s text; BEGIN FOR s IN",
                          f" SELECT pg_get_serial_sequence('{table}', attname)",
                          f" FROM pg_attribute WHERE attrelid='{table}'::regclass",
                          " AND attnum > 0 AND NOT attisdropped",
                          " LOOP IF s IS NOT NULL THEN",
                          f" EXECUTE format('GRANT USAGE ON SEQUENCE %s TO {qr}', s);",
                          " END IF; END LOOP; END $$;"]
    lines += [
        "-- No default runtime grants: future objects require explicit review.",
        "ALTER DEFAULT PRIVILEGES FOR ROLE wtf_owner REVOKE ALL ON TABLES FROM PUBLIC;",
        "ALTER DEFAULT PRIVILEGES FOR ROLE wtf_evidence_owner REVOKE ALL ON TABLES FROM PUBLIC;",
        "COMMIT;",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(render(json.loads((HERE / "permissions.json").read_text())), end="")

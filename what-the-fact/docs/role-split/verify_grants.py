"""Render verification for an actual runtime login in the scratch instance."""
import json
import sys
from render_grants import HERE, SERVICES, ident, qualified, validate


def verification_sql(manifest, name):
    validate(manifest)
    if name not in SERVICES:
        raise ValueError("unknown runtime role")
    role = manifest["roles"][name]
    lines = ["BEGIN;", "DO $$ BEGIN",
             " IF current_database() <> 'wtf_role_rehearsal' THEN RAISE EXCEPTION 'scratch only'; END IF;",
             f" IF current_user <> '{name}' OR session_user <> '{name}' THEN",
             " RAISE EXCEPTION 'must connect as actual runtime login'; END IF;",
             " IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND",
             " (rolsuper OR rolcreaterole OR rolcreatedb OR rolreplication OR rolbypassrls))",
             " THEN RAISE EXCEPTION 'privileged runtime'; END IF;",
             " IF EXISTS (SELECT 1 FROM pg_auth_members WHERE member=(SELECT oid FROM pg_roles WHERE rolname=current_user))",
             " THEN RAISE EXCEPTION 'runtime membership'; END IF;",
             " IF has_database_privilege(current_user, current_database(), 'CREATE')",
             " OR has_database_privilege(current_user, current_database(), 'TEMP')",
             " THEN RAISE EXCEPTION 'database creation rights'; END IF;"]
    for table, kind in sorted(manifest["audited_relations"].items()):
        schema, relname = table.split(".")
        oid = f"(SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='{schema}' AND c.relname='{relname}')"
        expected = set(role["write"].get(table, []))
        if table in role["select"]:
            expected.add("SELECT")
        for privilege in ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]:
            want = "true" if privilege in expected else "false"
            lines += [f" IF has_table_privilege(current_user, {oid}, '{privilege}') IS DISTINCT FROM {want}",
                      f" THEN RAISE EXCEPTION 'unexpected {privilege}: {table}'; END IF;"]
        # Table ACL checks alone cannot detect a later column-only grant.
        for privilege in ["SELECT", "INSERT", "UPDATE", "REFERENCES"]:
            want = "true" if privilege in expected else "false"
            lines += [f" IF EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid={oid} AND a.attnum>0 AND NOT a.attisdropped",
                      f" AND has_column_privilege(current_user, a.attrelid, a.attnum, '{privilege}') IS DISTINCT FROM {want})",
                      f" THEN RAISE EXCEPTION 'unexpected column {privilege}: {table}'; END IF;"]
        owner = "wtf_evidence_owner" if table in manifest["evidence_tables"] else "wtf_owner"
        lines += [f" IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid={oid}) <> '{owner}'",
                  f" THEN RAISE EXCEPTION 'wrong owner: {table}'; END IF;"]
    for schema in sorted({t.split('.')[0] for t in manifest['audited_relations']}):
        lines += [f" IF has_schema_privilege(current_user, '{schema}', 'CREATE')",
                  " THEN RAISE EXCEPTION 'schema creation rights'; END IF;"]
    lines += ["END $$;"]
    inserted = [t for t, rights in role["write"].items() if "INSERT" in rights]
    insert_array = "ARRAY[" + ",".join("'" + t + "'" for t in inserted) + "]::text[]"
    for sequence in manifest["audited_sequences"]:
        schema, relname = sequence.split(".")
        oid = f"(SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='{schema}' AND c.relname='{relname}')"
        expected = f"EXISTS (SELECT 1 FROM pg_depend d JOIN pg_class c ON c.oid=d.refobjid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE d.classid='pg_class'::regclass AND d.refclassid='pg_class'::regclass AND d.objid={oid} AND d.deptype IN ('a','i') AND n.nspname || '.' || c.relname = ANY ({insert_array}))"
        owner = "wtf_evidence_owner" if sequence in {
            "wtf.aurora_capture_run_id_seq", "wtf.aurora_source_version_id_seq",
        } else "wtf_owner"
        lines += ["DO $$ BEGIN",
                  f" IF has_sequence_privilege(current_user, {oid}, 'USAGE') IS DISTINCT FROM ({expected})",
                  f" THEN RAISE EXCEPTION 'unexpected sequence USAGE: {sequence}'; END IF;",
                  f" IF has_sequence_privilege(current_user, {oid}, 'UPDATE') OR has_sequence_privilege(current_user, {oid}, 'SELECT')",
                  " THEN RAISE EXCEPTION 'excess sequence rights'; END IF;",
                  f" IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid={oid}) <> '{owner}'",
                  " THEN RAISE EXCEPTION 'wrong sequence owner'; END IF; END $$;"]
    # Execute reads under the login, so schema USAGE/view dependencies are tested.
    for table in role["select"]:
        lines.append(f"SELECT 1 FROM {qualified(table)} LIMIT 0;")
    lines += ["DO $$ DECLARE t text; col text; seq text; BEGIN",
              " FOR t IN SELECT unnest(ARRAY['wtf.aurora_capture_run', 'wtf.aurora_source_version', 'wtf.aurora_capture_run_record']) LOOP",
              " SELECT attname INTO col FROM pg_attribute WHERE attrelid=(SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=split_part(t,'.',1) AND c.relname=split_part(t,'.',2)) AND attnum>0 AND NOT attisdropped ORDER BY attnum LIMIT 1;",
              " BEGIN EXECUTE format('UPDATE %s SET %I=%I WHERE false',t,col,col);",
              "  RAISE EXCEPTION 'forbidden evidence UPDATE succeeded'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;",
              " BEGIN EXECUTE format('DELETE FROM %s WHERE false',t);",
              "  RAISE EXCEPTION 'forbidden evidence DELETE succeeded'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;",
              " BEGIN EXECUTE format('TRUNCATE %s CASCADE',t);",
              "  RAISE EXCEPTION 'forbidden evidence TRUNCATE succeeded'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;",
              " BEGIN EXECUTE format('ALTER TABLE %s ADD COLUMN forbidden_rehearsal_column int',t);",
              "  RAISE EXCEPTION 'forbidden ALTER succeeded'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;",
              " BEGIN EXECUTE format('DROP TABLE %s CASCADE',t);",
              "  RAISE EXCEPTION 'forbidden DROP succeeded'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;",
              " END LOOP;",
              " FOR seq IN SELECT unnest(ARRAY['wtf.aurora_capture_run_id_seq','wtf.aurora_source_version_id_seq']) LOOP",
              " BEGIN PERFORM setval(seq::regclass, 1);",
              "  RAISE EXCEPTION 'forbidden setval succeeded'; EXCEPTION WHEN insufficient_privilege THEN NULL; END;",
              " END LOOP;",
              " BEGIN EXECUTE 'SET ROLE wtf_evidence_owner'; RAISE EXCEPTION 'owner escalation succeeded';",
              " EXCEPTION WHEN insufficient_privilege THEN NULL; END;",
              " BEGIN EXECUTE 'SET ROLE wtf_owner'; RAISE EXCEPTION 'owner escalation succeeded';",
              " EXCEPTION WHEN insufficient_privilege THEN NULL; END;",
              "END $$;"]
    insert_run = "INSERT INTO wtf.aurora_capture_run(dataset_key,source_url,started_at,retrieved_at,status) VALUES ('role_rehearsal','https://example.invalid',now(),now(),'complete')"
    if name == "wtf_ingest":
        lines += ["DO $$ DECLARE run_id bigint; version_id bigint; BEGIN",
                  insert_run + " RETURNING id INTO run_id;",
                  "INSERT INTO wtf.aurora_source_version(dataset_key,source_record_key,source_url,payload_sha256,first_retrieved_at,payload)",
                  "VALUES ('role_rehearsal',run_id::text,'https://example.invalid',repeat('a',64),now(),'{}'::jsonb) RETURNING id INTO version_id;",
                  "INSERT INTO wtf.aurora_capture_run_record VALUES (run_id,version_id);",
                  "END $$;"]
    else:
        lines += ["DO $$ BEGIN BEGIN " + insert_run + ";",
                  "RAISE EXCEPTION 'reader inserted evidence'; EXCEPTION WHEN insufficient_privilege THEN NULL; END; END $$;"]
    lines += ["ROLLBACK;"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    print(verification_sql(json.loads((HERE / "permissions.json").read_text()), sys.argv[1]), end="")

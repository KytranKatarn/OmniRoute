"""Offline safety checks. These do not replace PostgreSQL rehearsal."""
import copy
import json
import unittest
from render_grants import HERE, render, validate
from verify_grants import verification_sql


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((HERE / "permissions.json").read_text())

    def test_reviewed_draft_renders(self):
        sql = render(self.manifest)
        self.assertIn("scratch database required", sql)
        self.assertNotIn("WITH GRANT OPTION", sql)
        self.assertNotIn("PASSWORD", sql)

    def test_evidence_owner_can_resolve_fk_schema_without_runtime_membership(self):
        sql = render(self.manifest)
        self.assertIn('GRANT USAGE ON SCHEMA "wtf" TO wtf_evidence_owner;', sql)
        self.assertNotIn("GRANT wtf_evidence_owner TO", sql)

    def test_cannot_widen_evidence_mutations(self):
        for name in self.manifest["roles"]:
            for operation in ("UPDATE", "DELETE", "TRUNCATE", "TRIGGER", "REFERENCES"):
                bad = copy.deepcopy(self.manifest)
                bad["roles"][name]["write"]["wtf.aurora_source_version"] = [operation]
                with self.assertRaises(ValueError):
                    validate(bad)

    def test_cannot_make_another_service_an_evidence_writer(self):
        bad = copy.deepcopy(self.manifest)
        bad["roles"]["wtf_tech"]["write"]["wtf.aurora_capture_run"] = ["INSERT"]
        with self.assertRaises(ValueError):
            validate(bad)

    def test_ingest_api_cannot_gain_editorial_writes(self):
        bad = copy.deepcopy(self.manifest)
        bad["roles"]["wtf_ingest_api"]["write"]["wtf.articles"] = ["UPDATE"]
        with self.assertRaises(ValueError):
            validate(bad)

    def test_unknown_objects_and_identifier_injection_fail_closed(self):
        for table in ("wtf.unaudited_table", 'wtf.articles; DROP ROLE postgres'):
            bad = copy.deepcopy(self.manifest)
            bad["roles"]["wtf_tech"]["select"].append(table)
            with self.assertRaises(ValueError):
                validate(bad)

    def test_existing_owners_cannot_login_or_have_members(self):
        sql = render(self.manifest)
        for owner in ("wtf_owner", "wtf_evidence_owner"):
            self.assertIn(f"rolname='{owner}' AND rolcanlogin", sql)
            self.assertIn(f"WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='{owner}')", sql)
        self.assertIn("owner role must be NOLOGIN", sql)
        self.assertIn("owner role has unexpected members", sql)

    def test_verifier_checks_column_only_acl_leaks(self):
        sql = verification_sql(self.manifest, "wtf_consumer")
        self.assertIn("has_column_privilege(current_user", sql)
        self.assertIn("unexpected column UPDATE: wtf.aurora_source_version", sql)

    def test_actual_login_and_negative_control_present(self):
        sql = verification_sql(self.manifest, "wtf_consumer")
        self.assertIn("session_user <> 'wtf_consumer'", sql)
        self.assertIn("unexpected UPDATE: wtf.aurora_source_version", sql)
        self.assertIn("forbidden evidence UPDATE succeeded", sql)
        self.assertTrue(sql.endswith("ROLLBACK;\n"))


if __name__ == "__main__":
    unittest.main()

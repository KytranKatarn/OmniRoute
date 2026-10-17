"""Isolated unittest checks; PostgreSQL tests require human_access_test* DB."""

import ast
from collections import Counter
from contextlib import contextmanager
import os
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import Mock, patch

from flask import Blueprint, Flask
from flask_login import LoginManager, UserMixin
import psycopg2
from psycopg2.extras import RealDictCursor

from rbac import Role, Permission, get_user_role, has_permission, can_access_module
from tools.email_manager import access_control, compose_routes, draft_proposal_service as drafts
from tools.email_manager import draft_proposal_jobs


def user(uid=1, **kw):
    fields = dict(
        id=uid,
        role="COLLABORATOR",
        subscription_tier="free",
        is_admin=False,
        is_super_admin=False,
        is_authenticated=True,
        is_active=True,
    )
    fields.update(kw)
    return SimpleNamespace(**fields)


class RoleTests(unittest.TestCase):
    def test_stored_collaborator_role_survives_free_tier(self):
        for role in ("COLLABORATOR", "collaborator"):
            self.assertEqual(get_user_role(user(role=role)), Role.COLLABORATOR)
            self.assertTrue(has_permission(Permission.EMAIL_INBOX_VIEW, user(role=role)))

    def test_collaborator_never_gets_admin(self):
        self.assertFalse(has_permission(Permission.ADMIN_ACCESS, user()))
        self.assertFalse(can_access_module("account_center", user()))
        self.assertTrue(can_access_module("email_manager", user()))

    def test_admin_keeps_mail_access(self):
        self.assertTrue(can_access_module("email_manager", user(is_admin=True)))
        self.assertIsNone(access_control.get_visible_mailbox_ids(user(is_admin=True)))

    def test_no_admin_from_role_text_or_subscription(self):
        self.assertFalse(has_permission(Permission.ADMIN_ACCESS, user(role="admin")))
        self.assertEqual(get_user_role(user(role="user", subscription_tier="premium")), Role.PREMIUM)
        self.assertFalse(can_access_module("email_manager", user(role="user")))

    def test_unauthenticated_has_no_collaborator_access(self):
        self.assertEqual(get_user_role(user(is_authenticated=False)), Role.PUBLIC)

    def test_actual_user_loader_source_hydrates_department(self):
        # Compile only the actual User/load_user definitions in an isolated copy;
        # never import app.py or start its scheduler against a real installation.
        tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text())
        nodes = [
            n for n in tree.body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in ("User", "load_user")
        ]
        self.assertEqual(len(nodes), 2)
        for node in nodes:
            if isinstance(node, ast.FunctionDef):
                node.decorator_list = []
        row = dict(
            id=1,
            username="alice",
            email="alice@example.test",
            role="COLLABORATOR",
            is_admin=False,
            subscription_tier="free",
            agent_department="Creative & Design",
        )
        cur = Mock()
        cur.fetchone.return_value = row
        conn = Mock()
        conn.cursor.return_value = cur
        ns = {"UserMixin": UserMixin, "get_db": lambda: conn, "RealDictCursor": RealDictCursor}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), "<loader-copy>", "exec"), ns)
        loaded = ns["load_user"]("1")
        self.assertEqual(loaded.agent_department, "Creative & Design")
        self.assertEqual(get_user_role(loaded), Role.COLLABORATOR)


class BusinessDraftTests(unittest.TestCase):
    def test_assigned_business_uses_owners_persona_pipeline(self):
        c = {"mailbox_type": "business", "business_owner_agent_id": 10, "collaborator_agent_id": 10}
        with patch.object(draft_proposal_jobs, "_collaborators_enabled", return_value=True), patch.object(
            draft_proposal_jobs, "_create_collaborator_proposal", return_value=True
        ) as create:
            self.assertTrue(drafts._create_proposal(c))
            create.assert_called_once_with(c)

    def test_disabled_or_unavailable_owner_does_not_fall_back_to_another_voice(self):
        for enabled, owner in [(False, 10), (True, None)]:
            c = {"mailbox_type": "business", "business_owner_agent_id": 10, "collaborator_agent_id": owner}
            with patch.object(draft_proposal_jobs, "_collaborators_enabled", return_value=enabled), patch.object(
                draft_proposal_jobs, "_create_collaborator_proposal"
            ) as create:
                self.assertFalse(drafts._create_proposal(c))
                create.assert_not_called()


@unittest.skipUnless(os.environ.get("HUMAN_ACCESS_TEST_DSN"), "isolated PostgreSQL required")
class MailboxScopeTests(unittest.TestCase):
    def setUp(self):
        self.dsn = os.environ["HUMAN_ACCESS_TEST_DSN"]
        conn = psycopg2.connect(self.dsn)
        self.addCleanup(conn.close)
        self.assertTrue(conn.info.dbname.startswith("human_access_test"), "refusing non-test DB")
        with conn.cursor() as cur:
            cur.execute(
                """
                DROP SCHEMA public CASCADE; CREATE SCHEMA public;
                CREATE TABLE users(id INT PRIMARY KEY,email TEXT,is_active BOOLEAN);
                INSERT INTO users VALUES(1,'alice@example.test',true),(2,'bob@example.test',true),(3,'inactive@example.test',false);
                CREATE TABLE email_mailboxes(id INT PRIMARY KEY,address TEXT,mailbox_type TEXT,
                    owner_agent_id INT,department TEXT,active BOOLEAN,provisioned BOOLEAN,
                    display_name TEXT,imap_password TEXT);
                INSERT INTO email_mailboxes VALUES
                    (1,'alice@example.test','human_agent',10,'Same Dept',true,true,'Alice','test-placeholder'),
                    (2,'bob@example.test','human_agent',20,'Same Dept',true,true,'Bob','test-placeholder'),
                    (3,'sales@example.test','business',10,NULL,true,true,'Sales','test-placeholder'),
                    (4,'unassigned@example.test','business',NULL,NULL,true,true,'Unassigned','test-placeholder'),
                    (5,'bob-business@example.test','business',20,NULL,true,true,'Bob Biz','test-placeholder'),
                    (6,'inactive@example.test','business',NULL,NULL,false,true,'Inactive','test-placeholder'),
                    (7,'shared@example.test','business',NULL,NULL,true,true,'Shared','test-placeholder');
                CREATE TABLE user_mailbox_grants(user_id INT,mailbox_id INT);
                INSERT INTO user_mailbox_grants VALUES(1,7),(1,6),(3,7);
            """
            )
        conn.commit()

        @contextmanager
        def cursor(commit=False):
            c = psycopg2.connect(self.dsn)
            try:
                with c.cursor(cursor_factory=RealDictCursor) as cur:
                    yield c, cur
                if commit:
                    c.commit()
            finally:
                c.close()

        for module in (access_control, compose_routes):
            p = patch.object(module, "get_db_cursor", cursor)
            p.start()
            self.addCleanup(p.stop)

    def test_own_assigned_business_and_explicit_grant_only(self):
        self.assertEqual(access_control.get_visible_mailbox_ids(user(agent_department="Same Dept")), [1, 3, 7])
        self.assertEqual(access_control.get_visible_mailbox_ids(user(2)), [2, 5])

    def test_forged_email_or_department_does_not_choose_the_owner(self):
        self.assertEqual(
            access_control.get_visible_mailbox_ids(user(email="bob@example.test", agent_department="Same Dept")),
            [1, 3, 7],
        )

    def test_missing_or_inactive_account_gets_no_mail(self):
        self.assertEqual(access_control.get_visible_mailbox_ids(user(99)), [])
        self.assertEqual(access_control.get_visible_mailbox_ids(user(3)), [])

    def test_scope_query_failure_is_closed(self):
        with patch.object(access_control, "get_db_cursor", side_effect=RuntimeError("DB failed")):
            self.assertEqual(access_control.get_visible_mailbox_ids(user()), [])

    def test_compose_rejects_other_person_same_department_and_unassigned_business(self):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "isolated-test-only"
        login = LoginManager(app)
        login.user_loader(lambda _: user())
        bp = Blueprint("test_mail", __name__)
        compose_routes.register_compose_routes(bp, access_control.email_access_required)
        app.register_blueprint(bp)
        send = Mock(return_value={"success": True})
        stub = SimpleNamespace(send_email_via_stalwart=send)
        sla = SimpleNamespace(record_human_reply=Mock())
        with app.test_client() as client, patch.dict(
            sys.modules, {"tools.email_manager.send_service": stub, "tools.email_manager.human_sla_service": sla}
        ):
            with client.session_transaction() as session:
                session["_user_id"] = "1"
                session["_fresh"] = True
            for address in ("bob@example.test", "bob-business@example.test", "unassigned@example.test"):
                response = client.post(
                    "/api/email/compose/send",
                    json={
                        "from_address": address,
                        "to_address": "test@example.test",
                        "subject": "Test",
                        "body": "Test",
                    },
                )
                self.assertEqual(response.status_code, 403)
            send.assert_not_called()
            response = client.post(
                "/api/email/compose/send",
                json={
                    "from_address": "sales@example.test",
                    "to_address": "test@example.test",
                    "subject": "Test",
                    "body": "Test",
                },
            )
            self.assertEqual(response.status_code, 200)
            send.assert_called_once()


if __name__ == "__main__":
    unittest.main()

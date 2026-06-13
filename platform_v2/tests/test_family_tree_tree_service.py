import sys
from contextlib import contextmanager
from pathlib import Path

import psycopg2
import pytest

PLATFORM_DIR = Path(__file__).resolve().parents[1]
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

from tools.family_tree.services import tree_service


class FakeCursor:
    def __init__(self, *, fetchone_values=None, fetchall_values=None, rowcount=0, execute_error=None):
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_values = list(fetchall_values or [])
        self.rowcount = rowcount
        self.execute_error = execute_error
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.execute_error:
            raise self.execute_error

    def fetchone(self):
        return self.fetchone_values.pop(0) if self.fetchone_values else None

    def fetchall(self):
        return self.fetchall_values


def patch_cursor(monkeypatch, cursor):
    @contextmanager
    def fake_get_db_cursor(*args, **kwargs):
        yield None, cursor

    monkeypatch.setattr(tree_service, "get_db_cursor", fake_get_db_cursor)
    return cursor


@pytest.mark.parametrize(
    ("func", "args", "message"),
    [
        (tree_service.list_persons, (0,), "user_id must be a positive integer"),
        (tree_service.get_person, (1, "not-an-id"), "person_id must be a positive integer"),
        (tree_service.delete_person, (1, -3), "person_id must be a positive integer"),
    ],
)
def test_tree_service_validates_ids(func, args, message):
    with pytest.raises(tree_service.FamilyTreeServiceError, match=message):
        func(*args)


def test_list_persons_wraps_psycopg2_errors(monkeypatch):
    cursor = FakeCursor(execute_error=psycopg2.OperationalError("connection failed"))
    patch_cursor(monkeypatch, cursor)

    with pytest.raises(tree_service.FamilyTreeServiceError, match="Database error while listing persons"):
        tree_service.list_persons(1)


def test_add_relationship_returns_person_not_found(monkeypatch):
    cursor = FakeCursor(fetchone_values=[None])
    patch_cursor(monkeypatch, cursor)

    with pytest.raises(tree_service.FamilyTreeServiceError, match="Person 10 not found"):
        tree_service.add_relationship(1, 10, 20, "parent_child")


def test_add_relationship_rejects_self_relationship():
    with pytest.raises(tree_service.FamilyTreeServiceError, match="Circular relationship"):
        tree_service.add_relationship(1, 10, 10, "parent_child")


def test_add_relationship_rejects_parent_child_cycle(monkeypatch):
    cursor = FakeCursor(fetchone_values=[{"exists": 1}, {"exists": 1}, {"exists": 1}])
    patch_cursor(monkeypatch, cursor)

    with pytest.raises(tree_service.FamilyTreeServiceError, match="would create a cycle"):
        tree_service.add_relationship(1, 10, 20, "parent_child")


def test_add_relationship_inserts_when_persons_exist_and_no_cycle(monkeypatch):
    row = {
        "id": 33,
        "user_id": 1,
        "person_a_id": 10,
        "person_b_id": 20,
        "relationship_type": "parent_child",
    }
    cursor = FakeCursor(fetchone_values=[{"exists": 1}, {"exists": 1}, None, row])
    patch_cursor(monkeypatch, cursor)

    assert tree_service.add_relationship(1, 10, 20, "parent_child") == row


def test_get_ancestors_returns_person_not_found(monkeypatch):
    cursor = FakeCursor(fetchone_values=[None])
    patch_cursor(monkeypatch, cursor)

    with pytest.raises(tree_service.FamilyTreeServiceError, match="Person 99 not found"):
        tree_service.get_ancestors(1, 99)


def test_get_descendants_uses_cycle_safe_recursive_cte(monkeypatch):
    cursor = FakeCursor(
        fetchone_values=[{"exists": 1}],
        fetchall_values=[{"id": 2, "first_name": "Child", "depth": 1}],
    )
    patch_cursor(monkeypatch, cursor)

    assert tree_service.get_descendants(1, 1) == [{"id": 2, "first_name": "Child", "depth": 1}]
    recursive_sql = cursor.executed[-1][0]
    assert "WITH RECURSIVE descendants" in recursive_sql
    assert "NOT p.id = ANY(d.path)" in recursive_sql


def test_update_person_and_list_persons_have_type_hints():
    assert tree_service.update_person.__annotations__["user_id"] is int
    assert tree_service.update_person.__annotations__["person_id"] is int
    assert tree_service.list_persons.__annotations__["user_id"] is int
    assert "return" in tree_service.list_persons.__annotations__

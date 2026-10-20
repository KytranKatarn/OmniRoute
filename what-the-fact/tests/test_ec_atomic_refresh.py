"""Exercise the real CSV/batch path with transactional failure injection."""
import csv
import io
import zipfile

import pytest
import psycopg2.extras
from ingest.parliament import elections_canada as ec


class Connection:
    def __init__(self, *, busy=False):
        self.visible = ["previous committed dataset"]
        self.pending = list(self.visible)
        self.busy = busy
        self.commits = self.rollbacks = 0
        self.closed = False
        self.statements = []

    def cursor(self):
        return self

    def execute(self, sql):
        self.statements.append(sql)
        if sql.startswith("DELETE FROM"):
            self.pending.clear()
        elif "pg_try_advisory_xact_lock" not in sql:
            raise PermissionError("unexpected SQL")

    def fetchone(self):
        return (not self.busy,)

    def commit(self):
        self.commits += 1
        self.visible = list(self.pending)

    def rollback(self):
        self.rollbacks += 1
        self.pending = list(self.visible)

    def close(self):
        self.closed = True


@pytest.fixture
def source(tmp_path, monkeypatch):
    path = tmp_path / "contributions.zip"
    monkeypatch.setattr(ec, "_CACHE_PATH", str(path))
    monkeypatch.setattr(ec, "_download_zip", lambda: None)
    monkeypatch.setattr(ec, "_BATCH_SIZE", 1)

    def write(count):
        data = io.StringIO()
        writer = csv.writer(data)
        writer.writerow(["header"] * 27)
        for i in range(count):
            row = [""] * 27
            row[0], row[2], row[9], row[22], row[23] = "Party", f"Recipient {i}", "2025-01-01", "2025-01-01", "10.00"
            writer.writerow(row)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(ec._EC_CSV, data.getvalue())
    return write


class Engine:
    def __init__(self, conn):
        self.conn = conn

    def raw_connection(self):
        return self.conn


def test_success_publishes_only_after_all_batches(source, monkeypatch):
    source(2)
    conn = Connection()

    def insert(cur, sql, rows, page_size):
        assert conn.visible == ["previous committed dataset"]
        conn.pending.extend(rows)
    monkeypatch.setattr(psycopg2.extras, "execute_values", insert)
    result = ec.sync_contributions(Engine(conn))
    assert result["inserted"] == 2
    assert len(conn.visible) == 2
    assert conn.commits == 1 and conn.rollbacks == 0 and conn.closed


def test_second_batch_failure_preserves_previous_dataset(source, monkeypatch):
    source(2)
    conn = Connection()
    calls = 0

    def insert(cur, sql, rows, page_size):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected batch failure")
        conn.pending.extend(rows)
    monkeypatch.setattr(psycopg2.extras, "execute_values", insert)
    with pytest.raises(RuntimeError, match="injected"):
        ec.sync_contributions(Engine(conn))
    assert conn.visible == conn.pending == ["previous committed dataset"]
    assert conn.commits == 0 and conn.rollbacks == 1 and conn.closed


def test_empty_refresh_is_rejected_without_publishing(source):
    source(0)
    conn = Connection()
    with pytest.raises(ValueError, match="empty refresh"):
        ec.sync_contributions(Engine(conn))
    assert conn.visible == ["previous committed dataset"]
    assert conn.commits == 0 and conn.rollbacks == 1 and conn.closed


def test_busy_refresh_does_not_delete_or_import(source):
    source(1)
    conn = Connection(busy=True)
    with pytest.raises(RuntimeError, match="in progress"):
        ec.sync_contributions(Engine(conn))
    assert not any(s.startswith("DELETE") for s in conn.statements)
    assert conn.visible == ["previous committed dataset"]
    assert conn.commits == 0 and conn.rollbacks == 1 and conn.closed


def test_autocommit_connection_is_refused_before_writing(source):
    source(1)
    conn = Connection()
    conn.autocommit = True
    with pytest.raises(RuntimeError, match="transactional connection required"):
        ec.sync_contributions(Engine(conn))
    assert conn.statements == []
    assert conn.visible == ["previous committed dataset"]
    assert conn.commits == 0 and conn.closed

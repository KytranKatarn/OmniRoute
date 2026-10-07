"""scripts/migrations_apply.py — the writer must refuse the wrong target, refuse unsafe files, rehearse without a trace,
and only call a migration applied when the LEDGER says so (not when psql merely exited 0)."""
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrations_apply.py"
spec = importlib.util.spec_from_file_location("migrations_apply", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

GOOD = "CREATE TABLE t{v}();\nINSERT INTO public.schema_migrations (version, filename, applied_at) VALUES ('{v}', '{v}_x.sql', now());\n"


def _dir(tmp_path, versions, body=GOOD):
    for v in versions:
        (tmp_path / f"{v}_x.sql").write_text(body.format(v=v))
    return tmp_path


class Fake:
    """Scripted psql: answers the target check, the ledger read, and records every statement sent."""
    def __init__(self, ledger=("088",), db="wtf", recovery="f", filename="t", fail_on=None, log_rows=True):
        self.ledger, self.db, self.recovery, self.filename = set(ledger), db, recovery, filename
        self.fail_on, self.log_rows, self.sent = fail_on, log_rows, []

    def __call__(self, sql, extra=None):
        self.sent.append((sql, extra))
        if "current_database()" in sql:
            return 0, f"{self.db}|{self.recovery}|{self.filename}\n"
        if "SELECT version FROM public.schema_migrations" in sql:
            return 0, "\n".join(sorted(self.ledger)) + "\n"
        if self.fail_on and f"CREATE TABLE t{self.fail_on}" in sql:
            return 3, "ERROR: boom"
        if extra == ["-1"] and self.log_rows:
            self.ledger.add(sql.split("VALUES ('")[1][:3])
        return 0, ""


def test_pending_is_ledger_era_numeric_and_excludes_recorded(tmp_path):
    d = _dir(tmp_path, ["087", "088", "099", "100"])
    got = [v for v, _ in m.pending(m.on_disk(d), {"088"})]
    assert got == ["099", "100"]  # 087 is pre-ledger baseline, 100 sorts after 099 numerically


def test_wrong_target_is_refused_before_anything_else(tmp_path):
    for kw in ({"db": "archie"}, {"recovery": "t"}, {"filename": "f"}):
        out = []
        f = Fake(**kw)
        assert m.run("apply", True, psql=f, migrations_dir=_dir(tmp_path, ["099"]), out=out.append) == 2
        assert any("REFUSED" in o for o in out)
        assert all("CREATE TABLE" not in s for s, _ in f.sent)


def test_unsafe_files_are_refused_not_sent(tmp_path):
    for body in ("CREATE TABLE a();\n",                                       # never logs itself
                 "BEGIN;\nCREATE TABLE a();\nINSERT INTO public.schema_migrations VALUES ('099');\nCOMMIT;\n"):
        out, f = [], Fake()
        d = tmp_path / str(abs(hash(body)))
        d.mkdir()
        (d / "099_x.sql").write_text(body)
        assert m.run("rehearse", psql=f, migrations_dir=d, out=out.append) == 2
        assert all("CREATE TABLE a" not in s for s, _ in f.sent)


def test_plpgsql_and_comments_are_not_mistaken_for_transaction_control():
    sql = ("-- COMMIT; mentioned in a comment\nDO $$ BEGIN PERFORM 1; END $$;\n"
           "INSERT INTO public.schema_migrations (version) VALUES ('099');")
    assert m.problems("099", sql) == []


def test_rehearsal_is_one_transaction_ending_in_rollback(tmp_path):
    f = Fake()
    assert m.run("rehearse", psql=f, migrations_dir=_dir(tmp_path, ["099", "100"]), out=lambda *_: None) == 0
    sql = [s for s, _ in f.sent if "CREATE TABLE t099" in s][0]
    assert sql.startswith("BEGIN;") and sql.rstrip().endswith("ROLLBACK;")
    assert sql.index("t099") < sql.index("t100")          # ordered, so a later file sees an earlier one's objects
    assert f.ledger == {"088"}                            # and nothing was recorded


def test_apply_needs_yes(tmp_path):
    f = Fake()
    assert m.run("apply", False, psql=f, migrations_dir=_dir(tmp_path, ["099"]), out=lambda *_: None) == 2
    assert all(extra != ["-1"] for _, extra in f.sent)


def test_apply_runs_each_in_a_single_transaction_and_records(tmp_path):
    f = Fake()
    assert m.run("apply", True, psql=f, migrations_dir=_dir(tmp_path, ["099", "100"]), out=lambda *_: None) == 0
    assert [e for _, e in f.sent if e == ["-1"]] == [["-1"], ["-1"]] and {"099", "100"} <= f.ledger


def test_apply_stops_at_the_first_failure(tmp_path):
    f = Fake(fail_on="099")
    out = []
    assert m.run("apply", True, psql=f, migrations_dir=_dir(tmp_path, ["099", "100"]), out=out.append) == 1
    assert not any("CREATE TABLE t100" in s for s, _ in f.sent)


def test_exit_zero_without_a_ledger_row_is_a_failure(tmp_path):
    f = Fake(log_rows=False)
    out = []
    assert m.run("apply", True, psql=f, migrations_dir=_dir(tmp_path, ["099"]), out=out.append) == 1
    assert any("ledger has no row" in o for o in out)


def test_nothing_pending_is_a_clean_no_op(tmp_path):
    f = Fake(ledger=("088", "099"))
    assert m.run("apply", True, psql=f, migrations_dir=_dir(tmp_path, ["099"]), out=lambda *_: None) == 0
    assert all(extra != ["-1"] for _, extra in f.sent)

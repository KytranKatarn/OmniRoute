"""Ingest-role workload acceptance against a DISPOSABLE scratch PostgreSQL 16.

Runs the REAL ingest functions (GIC/BoC/FX upserts, Elections Canada refresh) through the
actual `wtf_ingest` login, after the reviewed schema + migration 107 + restricted grants.
Scratch only: a new container bound to 127.0.0.1 on an ephemeral port, trust auth, synthetic
fixtures, no production URL or secret accepted. The container is removed on exit.

    python3 workload_ingest.py /path/to/reviewed-wtf-schema.sql ../../migrations/107_ingest_schema_bootstrap.sql

Each case prints PASS/FAIL with an observable persisted result (an independent operator read),
because a clean return is not proof: helpers can swallow persistence errors.
Covers: ingest-role rows of workload-test-plan.md (GIC, BoC, FX, EC success/failure/empty/
concurrency, TRUNCATE denied, ingest_log). Consumer/tech/ingest-api rows are NOT covered here.
"""
import csv
import io
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import date
from pathlib import Path

import psycopg2
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))  # what-the-fact/

from render_grants import render  # noqa: E402
import json  # noqa: E402

DB = "wtf_role_rehearsal"
results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f": {name}" + (f" — {detail}" if detail and not ok else ""))


def sh(argv, sql=None, check_rc=True):
    return subprocess.run(argv, input=sql, text=True, capture_output=True, check=check_rc)


def main():
    # psql meta-commands (\restrict/\unrestrict) are not SQL for psycopg2
    schema = "\n".join(l for l in Path(sys.argv[1]).read_text().splitlines() if not l.startswith("\\"))
    bootstrap = Path(sys.argv[2]).read_text()
    manifest = json.loads((HERE / "permissions.json").read_text())
    name = "wtf-workload-" + uuid.uuid4().hex[:12]
    try:
        sh(["docker", "run", "-d", "--name", name, "--memory", "768m", "--cpus", "1",
            "-p", "127.0.0.1::5432", "--tmpfs", "/var/lib/postgresql/data:rw,size=512m",
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "-e", f"POSTGRES_DB={DB}",
            "pgvector/pgvector:pg16"])
        port = sh(["docker", "port", name, "5432/tcp"]).stdout.split(":")[-1].strip()

        def op():
            c = psycopg2.connect(host="127.0.0.1", port=port, user="postgres", dbname=DB)
            c.autocommit = True
            return c

        for _ in range(60):
            try:
                op().close()
                break
            except psycopg2.OperationalError:
                time.sleep(1)
        else:
            raise RuntimeError("scratch db not ready")

        o = op()
        cur = o.cursor()
        cur.execute(schema)
        cur.execute("BEGIN;\n" + bootstrap + "\nCOMMIT;")
        cur.execute(render(manifest))
        cur.execute('ALTER ROLE wtf_ingest LOGIN;')

        eng = sa.create_engine(f"postgresql+psycopg2://wtf_ingest@127.0.0.1:{port}/{DB}")
        with eng.connect() as c:
            who = c.execute(sa.text("select current_user, (select rolsuper from pg_roles where rolname=current_user)")).one()
        check("connected as the restricted ingest login", who[0] == "wtf_ingest" and who[1] is False, str(who))

        def scalar(sql, *a):
            cur.execute(sql, a or None)
            row_ = cur.fetchone()
            assert row_ is not None
            return row_[0]

        # ---- GIC ----
        from ingest.gov import gic_appointments as gic
        row = dict(pc_number="2026-0001", oic_date=date(2026, 1, 5), department="PCO", subject="S",
                   precis="p", oic_url="u", appointee_name="A", organization="O", action_type="appointment")
        gic._upsert(eng, [row])
        gic._upsert(eng, [dict(row, action_type="resignation")])
        check("GIC upsert: one row, action_type updated",
              scalar("select count(*) from gov_watch.gic_appointments where pc_number='2026-0001'") == 1 and
              scalar("select action_type from gov_watch.gic_appointments where pc_number='2026-0001'") == "resignation")

        # ---- BoC / FX ----
        from ingest.market import boc_rates, fx_rates
        b = dict(decision_date=date(2026, 1, 28), rate_pct=2.25, change_bps=0, press_release_url="u")
        boc_rates._upsert(eng, [b]); boc_rates._upsert(eng, [dict(b, rate_pct=2.0, change_bps=-25)])
        check("BoC upsert: one row, rate updated",
              scalar("select count(*) from market_watch.boc_rate_decisions") == 1 and
              float(scalar("select rate_pct from market_watch.boc_rate_decisions")) == 2.0)
        f = dict(rate_date=date(2026, 1, 28), usd_cad=1.4)
        fx_rates._upsert(eng, [f]); fx_rates._upsert(eng, [dict(f, usd_cad=1.41)])
        check("FX upsert: one row, rate updated",
              scalar("select count(*) from market_watch.fx_rates") == 1 and
              float(scalar("select usd_cad from market_watch.fx_rates")) == 1.41)

        # ---- Elections Canada ----
        from ingest.parliament import elections_canada as ec
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="wtf-ec-"))
        zpath = tmp / "c.zip"
        ec._CACHE_PATH = str(zpath)
        ec._download_zip = lambda: None
        ec._BATCH_SIZE = 2

        def write_zip(rows):
            data = io.StringIO(); w = csv.writer(data); w.writerow(["h"] * 27)
            for d, amt, who_ in rows:
                r = [""] * 27
                r[0], r[2], r[9], r[22], r[23] = "Party", who_, d, d, amt
                w.writerow(r)
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("contributions.csv", data.getvalue())

        def seed_old():
            cur.execute("delete from parliament.ec_contributions")
            cur.execute("insert into parliament.ec_contributions (political_entity, recipient_name, contribution_date, monetary_amount) "
                        "values ('Old','OLD1','2024-01-01',5),('Old','OLD2','2024-01-02',7)")

        def snap():
            return scalar("select count(*)::text || ':' || coalesce(sum(monetary_amount)::text,'0') || ':' || "
                          "coalesce(md5(string_agg(recipient_name, ',' order by recipient_name)),'') from parliament.ec_contributions")

        # success
        seed_old()
        write_zip([("2025-01-01", "10.00", f"NEW{i}") for i in range(5)])
        res = ec.sync_contributions(eng)
        check("EC success: old rows replaced by exactly the new set",
              res["inserted"] == 5 and scalar("select count(*) from parliament.ec_contributions") == 5 and
              scalar("select count(*) from parliament.ec_contributions where recipient_name like 'OLD%'") == 0 and
              float(scalar("select sum(monetary_amount) from parliament.ec_contributions")) == 50.0, str(res))

        # mid-import failure -> rollback
        seed_old(); before = snap()
        write_zip([("2025-01-01", "10.00", f"NEW{i}") for i in range(5)])
        import psycopg2.extras as pe
        real = pe.execute_values
        calls = {"n": 0}

        def flaky(cur_, sql, argslist, **kw):
            calls["n"] += 1
            if calls["n"] == 2:
                raise psycopg2.errors.UniqueViolation("injected second-batch failure")
            return real(cur_, sql, argslist, **kw)
        pe.execute_values = flaky
        try:
            ec.sync_contributions(eng); raised = False
        except Exception:
            raised = True
        finally:
            pe.execute_values = real
        check("EC mid-import failure: raises and previous committed dataset is unchanged", raised and snap() == before)

        # empty / all-filtered
        seed_old(); before = snap()
        write_zip([("1980-01-01", "10.00", "TOOOLD")])
        try:
            ec.sync_contributions(eng); raised = False
        except ValueError:
            raised = True
        check("EC empty/all-filtered input: refused and previous dataset unchanged", raised and snap() == before)

        # concurrency: another session holds the refresh lock
        seed_old(); before = snap()
        write_zip([("2025-01-01", "10.00", "NEW0")])
        holder = psycopg2.connect(host="127.0.0.1", port=port, user="postgres", dbname=DB)
        hc = holder.cursor(); hc.execute("SELECT pg_advisory_xact_lock(1976543821, 1)")
        try:
            ec.sync_contributions(eng); raised = None
        except RuntimeError as e:
            raised = "another refresh" in str(e)
        # reader during the held lock still sees the previous dataset
        during = snap()
        holder.rollback(); holder.close()
        check("EC overlap: second refresh refused before DELETE; reader sees previous dataset",
              raised is True and during == before and snap() == before)
        res = ec.sync_contributions(eng)
        check("EC after lock released: refresh publishes once", res["inserted"] == 1 and scalar("select count(*) from parliament.ec_contributions") == 1)

        # run_ec_sync heartbeat through restricted role
        run = ec.run_ec_sync(eng)
        check("run_ec_sync writes the ingest_log heartbeat as wtf_ingest",
              "error" not in run and scalar("select count(*) from parliament.ingest_log where task='ec_contributions' and error is null") >= 1, str(run))

        # denied: TRUNCATE / DDL as the restricted login
        for label, stmt in [("TRUNCATE ec_contributions", "TRUNCATE parliament.ec_contributions"),
                            ("CREATE TABLE in parliament", "CREATE TABLE parliament.x(i int)"),
                            ("ALTER TABLE gic", "ALTER TABLE gov_watch.gic_appointments ADD COLUMN z int")]:
            try:
                with eng.begin() as c:
                    c.execute(sa.text(stmt))
                denied = False
            except sa_exc.ProgrammingError:
                denied = True
            check(f"denied for wtf_ingest: {label}", denied)
        eng.dispose()
    finally:
        sh(["docker", "rm", "-f", name], check_rc=False)
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

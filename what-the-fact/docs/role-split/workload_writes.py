"""Write-path workload acceptance for wtf_consumer and wtf_tech (real code, real restricted logins, scratch PG16).

Every effect is verified by an independent OPERATOR read: these code paths swallow persistence errors by design
(`try/except: return redirect`, `_persist_on_demand` logs and carries on), so a 200/redirect proves nothing.
External collaborators (hub LLM dispatch, SSO) are not exercised: sessions are set directly, and the LLM result handed
to tech's persistence function is synthetic.

    python3 workload_writes.py /path/to/schema.sql ../../migrations/107_ingest_schema_bootstrap.sql
Needs flask-cors (tech) and PYTHONPATH=what-the-fact/kytran-auth-pkg (kytran_auth).
"""
import importlib
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from scratch_db import scratch, url  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f": {name}" + (f" — {detail}" if detail and not ok else ""))


def fresh_app(module, port, role):
    os.environ["WTF_DATABASE_URL"] = url(port, role)
    for m in [k for k in sys.modules if k.split(".")[0] in ("consumer", "tech")]:
        del sys.modules[m]
    return importlib.import_module(module).create_app()


def seed(cur, table, **vals):
    """Insert one synthetic row, filling any NOT-NULL-without-default column by type. FKs are bypassed (replica role)."""
    schema, name = table.split(".")
    cur.execute("""select column_name, data_type, udt_name from information_schema.columns
                   where table_schema=%s and table_name=%s and is_nullable='NO' and column_default is null
                     and is_generated='NEVER' and is_identity='NO'""", (schema, name))
    fill = {"text": "x", "character varying": "x", "integer": 1, "bigint": 1, "smallint": 1, "boolean": True,
            "numeric": 1, "double precision": 1.0, "real": 1.0, "date": "2026-01-01",
            "timestamp with time zone": "2026-01-01T00:00:00Z", "timestamp without time zone": "2026-01-01",
            "jsonb": "{}", "json": "{}", "ARRAY": "{}", "uuid": "00000000-0000-0000-0000-000000000001"}
    row = dict(vals)
    for col, dt, _udt in cur.fetchall():
        row.setdefault(col, fill.get(dt, "x"))
    cols = ", ".join(f'"{c}"' for c in row)
    ph = ", ".join(["%s"] * len(row))
    cur.execute(f"insert into {table} ({cols}) values ({ph}) returning *", list(row.values()))
    return cur.fetchone()


def main():
    with scratch(sys.argv[1], sys.argv[2], ["wtf_consumer", "wtf_tech"]) as (port, op):
        o = op()
        cur = o.cursor()
        cur.execute("set session_replication_role = replica")

        def scalar(sql, *a):
            cur.execute(sql, a or None)
            r = cur.fetchone()
            assert r is not None
            return r[0]

        os.environ["WTF_BILLING_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="wtf-bill-"), "billing.db")
        os.environ.setdefault("FLASK_SECRET_KEY", "scratch-secret")
        os.environ["WTF_ADMIN_KEY"] = "scratch-admin"

        seed(cur, "wtf.sources", slug="s1", name="Source One")
        cur.execute("select id from wtf.sources where slug='s1'")
        sid = cur.fetchone()[0]
        seed(cur, "wtf.articles", id=1001, source_id=sid)

        # ============ consumer ============
        app = fresh_app("consumer.app", port, "wtf_consumer")
        app.config["TESTING"] = True
        c = app.test_client()
        from consumer import auth
        tier = sorted(auth._SUBSCRIBED_TIERS)[0]

        r = c.post("/api/newsletter/subscribe", json={"email": "a@example.com"})
        check("consumer: newsletter subscribe persists", r.status_code == 200 and
              scalar("select count(*) from wtf.newsletter_subscribers where email='a@example.com' and active") == 1, str(r.status_code))
        tok = scalar("select unsub_token::text from wtf.newsletter_subscribers where email='a@example.com'")
        c.get(f"/newsletter/unsubscribe?token={tok}")
        check("consumer: newsletter unsubscribe persists",
              scalar("select count(*) from wtf.newsletter_subscribers where email='a@example.com' and not active") == 1)

        with c.session_transaction() as s:
            s["wtf_email"] = "sub@example.com"
            s["wtf_tier"] = tier
        r = c.post("/alerts", data={"keyword": "carney", "source_slug": "s1"})
        check("consumer: alert create persists", scalar("select count(*) from wtf.user_alerts where user_email='sub@example.com'") == 1,
              r.headers.get("Location", ""))
        aid = scalar("select id from wtf.user_alerts where user_email='sub@example.com'")
        c.post(f"/alerts/{aid}/delete")
        check("consumer: alert delete persists", scalar("select count(*) from wtf.user_alerts where user_email='sub@example.com'") == 0)

        c.get("/article/1001")
        check("consumer: article view logged for signed-in user",
              scalar("select coalesce(sum(view_count),0) from wtf.user_article_views where user_email='sub@example.com' and article_id=1001") >= 1,
              "the INSERT is inside try/except — a permission error is silent")

        H = {"X-Admin-Key": "scratch-admin"}
        seed(cur, "parliament.mps", id=77)
        r = c.post("/admin/claims", headers=H, json={"mp_id": 77, "politician_slug": "p", "politician_name": "P", "claim_text": "claim"})
        check("consumer: admin claim create persists", r.status_code in (200, 201) and scalar("select count(*) from wtf.claim_tracker") == 1,
              f"{r.status_code} {r.get_data(as_text=True)[:120]}")
        cid = scalar("select id from wtf.claim_tracker limit 1")
        r = c.put(f"/admin/claims/{cid}", headers=H, json={"status": "verified_true", "verdict_summary": "ok"})
        check("consumer: admin claim update persists", scalar("select coalesce(verdict_summary,'') from wtf.claim_tracker where id=%s", cid) == "ok",
              f"{r.status_code} {r.get_data(as_text=True)[:120]}")

        # dedup decision
        seed(cur, "shared.entities", id=501, entity_type="person", canonical_name="A One", slug="a-one", status="active")
        seed(cur, "shared.entities", id=502, entity_type="person", canonical_name="A Onee", slug="a-onee", status="active")
        q = seed(cur, "shared.merge_review_queue", entity_id_a=501, entity_id_b=502, status="pending")
        qid = q[0]
        r = c.post("/admin/dedup/decide", headers=H, json={"queue_id": qid, "decision": "distinct"})
        check("consumer: dedup decide 'distinct' persists", r.status_code == 200 and
              scalar("select status from shared.merge_review_queue where id=%s", qid) != "pending", f"{r.status_code} {r.get_data(as_text=True)[:160]}")

        # dedup 'same' = a real merge (_merge touches entities, mentions, edges, external ids, blocks, merge log)
        seed(cur, "shared.entities", id=601, entity_type="person", canonical_name="B Two", slug="b-two", status="active")
        seed(cur, "shared.entities", id=602, entity_type="person", canonical_name="B Twoo", slug="b-twoo", status="active")
        seed(cur, "shared.entity_mentions", entity_id=602, content_type="article", content_id="9", product="wtf")
        seed(cur, "shared.entity_blocks", entity_id=602, block_key="btwo", block_kind="norm_name")
        qid2 = seed(cur, "shared.merge_review_queue", entity_id_a=601, entity_id_b=602, status="pending")[0]
        r = c.post("/admin/dedup/decide", headers=H, json={"queue_id": qid2, "decision": "same"})
        merged = scalar("select status from shared.entities where id in (601,602) and status='merged' limit 1") if r.status_code == 200 else None
        check("consumer: dedup decide 'same' performs the merge as wtf_consumer",
              r.status_code == 200 and merged == "merged" and scalar("select count(*) from shared.entity_merge_log") >= 1,
              f"{r.status_code} {r.get_data(as_text=True)[:200]}")

        # tier2 upgrade persistence from the consumer (route -> ingest.tier2_upgrade.persist_upgrade)
        import sqlalchemy as sa
        from ingest import tier2_upgrade
        eng = sa.create_engine(url(port, "wtf_consumer"))
        payload = {"agent": "V.E.R.I.F.Y.", "result": {"bias_summary": {"band": "center", "score": 0.0, "rationale": "r"},
                                                       "key_claims": [{"text": "c", "verdict": "verified", "reasoning": "r"}]}}
        try:
            with eng.begin() as conn:
                tier2_upgrade.persist_upgrade(conn, "wtf", 1001, payload)
            ok = True
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"   (tier2 persist raised {type(exc).__name__})")
        check("consumer: /api/upgrade-tier2 persistence (tier2_upgrade.persist_upgrade) as wtf_consumer", ok,
              "OPEN DESIGN DECISION: consumer has no write grants on bias_scores/fact_checks/articles; "
              "do NOT widen the public-facing role — move upgrade to tech or the precompute worker" if not ok else "")
        eng.dispose()

        # ============ tech ============
        app = fresh_app("tech.app", port, "wtf_tech")
        t = app.test_client()
        r = t.post("/api/v1/flag", json={"article_id": 1001, "flag_type": "bias_wrong", "reason": "x"})
        check("tech: score flag persists", r.status_code == 200 and scalar("select count(*) from wtf.score_flags where article_id=1001") == 1,
              f"{r.status_code}")

        from tech import routes as tr
        results_ = {"bias": {"band": "center", "score": 0.1, "rationale": "r", "trigger_phrases": [], "confidence": 0.8},
                    "factcheck": {"overall_verdict": "verified", "claims": [{"text": "claim one", "verdict": "verified", "reasoning": "e"}]}}
        tr._persist_on_demand(1001, results_, "wtf")
        check("tech: deep dive writes bias_scores", scalar("select count(*) from wtf.bias_scores where article_id=1001") == 1,
              "_persist_on_demand logs and continues on failure")
        check("tech: deep dive replaces fact_checks", scalar("select count(*) from wtf.fact_checks where article_id=1001 and analysis_tier='on_demand'") == 1)
        check("tech: deep dive marks the article analysed", scalar("select ai_analyzed from wtf.articles where id=1001") is True)
        lv = scalar("select latest_verdict from wtf.articles where id=1001")
        check("tech: trigger sync_article_latest_verdict set articles.latest_verdict as the restricted login",
              lv == "verified", f"latest_verdict={lv}")
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

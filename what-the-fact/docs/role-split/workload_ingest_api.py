"""ingest-api workload acceptance: consumer.app:create_ingest_app() through the REAL wtf_ingest_api login.

Scratch PostgreSQL only (see scratch_db.py). Every mutation is verified by an independent OPERATOR read, because
record_push() swallows its own errors by design — a clean 200 is not proof the receipt was written.

    python3 workload_ingest_api.py /path/to/reviewed-wtf-schema.sql ../../migrations/107_ingest_schema_bootstrap.sql
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))  # what-the-fact/

from scratch_db import scratch, url  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS" if ok else "FAIL") + f": {name}" + (f" — {detail}" if detail and not ok else ""))


def main():
    with scratch(sys.argv[1], sys.argv[2], ["wtf_ingest_api"]) as (port, op):
        o = op()
        cur = o.cursor()

        def scalar(sql, *a):
            cur.execute(sql, a or None)
            row = cur.fetchone()
            assert row is not None
            return row[0]

        os.environ["WTF_DATABASE_URL"] = url(port, "wtf_ingest_api")
        os.environ["INTERNAL_API_KEY"] = "scratch-key"
        from consumer.app import create_ingest_app
        app = create_ingest_app()
        client = app.test_client()
        H = {"X-Internal-Key": "scratch-key"}

        # surface
        rules = sorted(r.rule for r in app.url_map.iter_rules() if r.endpoint != "static")
        check("route surface is exactly graph ingest + companies + health + version",
              rules == ["/api/internal/entity-graph/companies", "/api/internal/entity-graph/ingest", "/health", "/version"],
              str(rules))

        # auth
        os.environ["INTERNAL_API_KEY"] = ""
        check("auth: key not configured -> 503", client.post("/api/internal/entity-graph/ingest", json={}).status_code == 503)
        os.environ["INTERNAL_API_KEY"] = "scratch-key"
        check("auth: wrong key -> 401", client.post("/api/internal/entity-graph/ingest", json={}, headers={"X-Internal-Key": "x"}).status_code == 401)
        check("auth: valid key, invalid payload -> 400",
              client.post("/api/internal/entity-graph/ingest", json={"product": "nope"}, headers=H).status_code == 400)
        check("auth failures wrote nothing", scalar("select count(*) from shared.entities") == 0)

        # real ingest as the restricted login
        payload = {"product": "gov-watch",
                   "entities": [
                       {"canonical_name": "Acme Corp", "entity_type": "organization",
                        "external_ids": [{"key_type": "sedar_issuer", "key_value": "000012345"}]},
                       {"canonical_name": "Jane Doe", "entity_type": "person", "role": {"type": "mp", "external_id": "x1"}}],
                   "mentions": [{"entity": {"canonical_name": "Acme Corp", "entity_type": "organization"},
                                 "content_type": "article", "content_id": "42", "mention_context": "ctx"}],
                   "relationships": [{"from": {"canonical_name": "Jane Doe", "entity_type": "person"},
                                      "to": {"canonical_name": "Acme Corp", "entity_type": "organization"},
                                      "relationship_type": "contracts_with", "source_id": "s1"}]}
        r = client.post("/api/internal/entity-graph/ingest", json=payload, headers=H)
        body = r.get_json(silent=True) or {}
        check("ingest returns 200 ok", r.status_code == 200 and body.get("ok") is True, f"{r.status_code} {str(body)[:200]}")
        check("entities persisted (2)", scalar("select count(*) from shared.entities") == 2)
        check("external id persisted", scalar("select count(*) from shared.entity_external_ids where key_value='000012345'") == 1)
        check("mention persisted", scalar("select count(*) from shared.entity_mentions where content_id='42'") == 1)
        check("relationship persisted", scalar("select count(*) from shared.entity_relationships where relationship_type='contracts_with'") == 1)

        # idempotent upsert
        r = client.post("/api/internal/entity-graph/ingest", json=payload, headers=H)
        b2 = r.get_json(silent=True) or {}
        check("repeat is an update, not a duplicate",
              r.status_code == 200 and b2.get("entities_updated") == 2 and scalar("select count(*) from shared.entities") == 2,
              str(b2)[:200])

        # receipt (observability) — written through the SAME restricted login
        got = scalar("select count(*) from parliament.ingest_log where task='entity_push_gov-watch'")
        check("push receipt row written to parliament.ingest_log by the restricted login", got == 1,
              "record_push swallows its error; the api role has no grant on parliament.ingest_log")

        # merge-following: a merged entity redirects to its live target
        cur.execute("insert into shared.entities (entity_type, canonical_name, slug, status) values ('organization','Live Co','live-co','active') returning id")
        live = cur.fetchone()[0]
        cur.execute("insert into shared.entities (entity_type, canonical_name, slug, status, merged_into) "
                    "values ('organization','Old Co','old-co','merged', %s)", (live,))
        r = client.post("/api/internal/entity-graph/ingest", headers=H, json={
            "product": "gov-watch", "mentions": [{"entity": {"slug": "old-co"}, "content_type": "article", "content_id": "77"}]})
        check("merge-following: mention lands on the live entity",
              r.status_code == 200 and scalar("select entity_id from shared.entity_mentions where content_id='77'") == live,
              f"{r.status_code} {(r.get_json(silent=True) or {})}")

        # companies read
        r = client.get("/api/internal/entity-graph/companies", headers=H)
        check("companies read works for the restricted login", r.status_code == 200 and "companies" in (r.get_json(silent=True) or {}), str(r.status_code))

        # forbidden surface: the api login cannot touch consumer tables
        import sqlalchemy as sa
        import sqlalchemy.exc as sa_exc
        eng = sa.create_engine(url(port, "wtf_ingest_api"))
        for label, stmt in [("read wtf.api_keys", "select 1 from wtf.api_keys limit 1"),
                            ("write wtf.articles", "update wtf.articles set title=title"),
                            ("delete shared.entities", "delete from shared.entities")]:
            try:
                with eng.begin() as c:
                    c.execute(sa.text(stmt))
                denied = False
            except sa_exc.ProgrammingError:
                denied = True
            check(f"denied for wtf_ingest_api: {label}", denied)
        eng.dispose()
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

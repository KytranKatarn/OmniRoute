"""Crawl every parameter-free GET route of the consumer / tech apps as the RESTRICTED login and as a superuser baseline.

Scratch PostgreSQL only (scratch_db.py), synthetic empty-ish data. A route that behaves differently under the
restricted role, or logs "permission denied" (helpers often swallow it and return an empty page), is a missing grant.
This is READ coverage only: authenticated writes and admin actions are NOT exercised here.

    python3 workload_crawl.py consumer|tech /path/to/schema.sql ../../migrations/107_ingest_schema_bootstrap.sql
"""
import importlib
import logging
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from scratch_db import scratch, url  # noqa: E402

SERVICE = {"consumer": ("consumer.app", "create_app", "wtf_consumer"),
           "tech": ("tech.app", "create_app", "wtf_tech")}


class Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.hits = []

    def emit(self, record):
        msg = record.getMessage()
        if record.exc_info:
            msg += " " + str(record.exc_info[1])
        if "permission denied" in msg.lower() or "insufficientprivilege" in msg.lower():
            self.hits.append(msg[:200].replace("\n", " "))


def crawl(port, role, svc):
    mod, fn, _ = SERVICE[svc]
    os.environ["WTF_DATABASE_URL"] = url(port, role)
    os.environ.setdefault("FLASK_SECRET_KEY", "scratch-secret")
    import tempfile
    os.environ.setdefault("WTF_BILLING_DB_PATH", os.path.join(tempfile.mkdtemp(prefix="wtf-bill-"), "billing.db"))
    for m in [k for k in sys.modules if k.split(".")[0] in ("consumer", "tech")]:
        del sys.modules[m]  # fresh module-level engines per login
    app = getattr(importlib.import_module(mod), fn)()
    cap = Capture()
    logging.getLogger().addHandler(cap)
    client = app.test_client()
    out = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if "GET" not in rule.methods or rule.arguments or rule.endpoint == "static":
            continue
        cap.hits.clear()
        try:
            resp = client.get(rule.rule)
            status = resp.status_code
        except Exception as exc:  # noqa: BLE001
            status = f"EXC:{type(exc).__name__}"
        out[rule.rule] = (status, list(cap.hits))
    logging.getLogger().removeHandler(cap)
    return out


def main():
    svc = sys.argv[1]
    role = SERVICE[svc][2]
    with scratch(sys.argv[2], sys.argv[3], [role]) as (port, _op):
        base = crawl(port, "postgres", svc)
        restricted = crawl(port, role, svc)
    diffs = [(r, base[r][0], restricted[r][0]) for r in base if base[r][0] != restricted[r][0]]
    perms = {r: v[1] for r, v in restricted.items() if v[1] and not base[r][1]}
    print(f"{svc}: {len(base)} parameter-free GET routes crawled")
    print(f"status differs restricted vs superuser: {len(diffs)}")
    for r, b, x in diffs:
        print(f"  DIFF {r}: superuser={b} restricted={x}")
    print(f"routes logging 'permission denied' ONLY under the restricted role: {len(perms)}")
    for r, h in perms.items():
        print(f"  PERM {r}: {h[0][:170]}")
    both = {r for r, v in base.items() if v[1]}
    print(f"(routes logging permission errors even as superuser, i.e. unrelated: {len(both)})")
    sys.exit(1 if diffs or perms else 0)


if __name__ == "__main__":
    main()

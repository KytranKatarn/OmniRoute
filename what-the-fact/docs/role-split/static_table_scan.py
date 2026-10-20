"""Static cross-check: every schema-qualified table the consumer/tech/ingest-api SOURCE references vs the role's grants.

Complements the crawl (which skips parameterised routes and write paths). Heuristic: finds `schema.table` tokens for the audited
schemas in SQL-looking strings; `{S}.`-templated names resolve to `wtf.` when the module defines S = "wtf". Reports a table that
appears in the service's code but is neither SELECT- nor write-granted to its role. False positives are possible (comments, other
services' tables) — review each; false NEGATIVES exist for fully dynamic SQL.

    python3 static_table_scan.py
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
manifest = json.loads((HERE / "permissions.json").read_text())
audited = set(manifest["audited_relations"])
schemas = {t.split(".")[0] for t in audited}
SERVICES = {"wtf_consumer": ["consumer"], "wtf_tech": ["tech"], "wtf_ingest_api": ["consumer/entity_graph_routes.py"]}
TOKEN = re.compile(r"(?<![\w.])(%s)\.([a-z_][a-z0-9_]*)" % "|".join(sorted(schemas)))
TEMPLATED = re.compile(r"\{_?S\}\.([a-z_][a-z0-9_]*)")
KNOWN_FALSE_POSITIVES = set()  # (role, table) mentioned only in prose; review each before adding (minister_travel looked like one and was REAL)
bad = 0
for role, paths in SERVICES.items():
    granted = set(manifest["roles"][role]["select"]) | set(manifest["roles"][role]["write"])
    files = []
    for p in paths:
        pp = ROOT / p
        files += [pp] if pp.is_file() else sorted(pp.rglob("*.py"))
    seen = {}
    for f in files:
        text = f.read_text(errors="ignore")
        found = {f"{a}.{b}" for a, b in TOKEN.findall(text)}
        found |= {f"wtf.{b}" for b in TEMPLATED.findall(text)}  # schema is WTF_SCHEMA (default wtf)
        for t in found & audited:
            seen.setdefault(t, set()).add(f.relative_to(ROOT).as_posix())
    missing = {t: sorted(fs) for t, fs in seen.items() if t not in granted and (role, t) not in KNOWN_FALSE_POSITIVES}
    print(f"{role}: {len(seen)} audited tables referenced in source; granted {len(granted)}; NOT granted: {len(missing)}")
    for t, fs in sorted(missing.items()):
        print(f"   {t}  <- {', '.join(fs[:3])}")
    bad += len(missing)
sys.exit(1 if bad else 0)

#!/usr/bin/env python3
"""Apply pending WTF migrations to CITADEL — plan first, rehearse in a rolled-back transaction, then apply.

    python what-the-fact/scripts/migrations_apply.py plan                # what is pending (default, read-only)
    python what-the-fact/scripts/migrations_apply.py rehearse            # run ALL pending in ONE transaction, ROLLBACK
    python what-the-fact/scripts/migrations_apply.py apply --yes         # apply in order, one transaction each

`migrations_admin.py` stays read-only; this is the writer. The target is fixed (Citadel's `what-the-fact-wtf-postgres-1`
over ssh) because WTF migrations applied to the wrong database REPORT SUCCESS (migrations/README.md, 2026-10-02):

  * before anything runs it checks it is talking to database `wtf`, a PRIMARY (not in recovery), whose ledger has a
    `filename` column (the hub's same-named platform table does not);
  * a pending file that never logs itself in `public.schema_migrations`, or that carries its own BEGIN/COMMIT (which would
    defeat the rollback and the one-transaction guarantee), is REFUSED before any SQL is sent;
  * `rehearse` chains every pending file in a single transaction so a later migration sees an earlier one's objects, then
    rolls everything back — a rehearsal can never leave a trace;
  * `apply` runs each file with `psql -1` (single transaction), stops at the first failure, and re-reads the ledger
    afterwards: exit 0 means the row exists, not merely that psql returned 0.

Only the ledger era (088+) is managed; older files are the unrecorded baseline and are never touched.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
LEDGER_FROM = 88
HOST = "root@100.64.0.10"
CONTAINER = "what-the-fact-wtf-postgres-1"
PSQL = ["psql", "-U", "wtfuser", "-d", "wtf", "-v", "ON_ERROR_STOP=1", "-At"]

_TXN = re.compile(r"(?:^|;)\s*(BEGIN|START\s+TRANSACTION|COMMIT|ROLLBACK)\s*;", re.I)
_DOLLAR = re.compile(r"\$([A-Za-z_]*)\$.*?\$\1\$", re.S)
_LINE_COMMENT = re.compile(r"--[^\n]*")


def _top_level(sql: str) -> str:
    """The SQL with comments and dollar-quoted bodies removed. A DO $$ ... BEGIN ... END $$ block contains PL/pgSQL
    BEGIN/END that are NOT transaction control, and prose in a comment may say 'COMMIT;'."""
    return _DOLLAR.sub("''", _LINE_COMMENT.sub("", sql))


def on_disk(migrations_dir: Path = MIGRATIONS_DIR) -> list[tuple[str, Path]]:
    out = [(p.name[:3], p) for p in migrations_dir.glob("[0-9][0-9][0-9]_*.sql") if p.name[:3].isdigit()]
    return sorted(out, key=lambda v: int(v[0]))


def pending(files: list[tuple[str, Path]], ledger: set[str]) -> list[tuple[str, Path]]:
    """Ledger-era files with no ledger row, in numeric order."""
    return [(v, p) for v, p in files if int(v) >= LEDGER_FROM and v not in ledger]


def problems(version: str, sql: str) -> list[str]:
    """Reasons a migration must not be run by this tool. Empty list = acceptable."""
    out = []
    if "schema_migrations" not in sql or f"'{version}'" not in sql:
        out.append("does not log itself in public.schema_migrations with its own version "
                   "(it would read NOT APPLIED forever)")
    m = _TXN.search(_top_level(sql))
    if m:
        out.append(f"contains its own transaction control ({m.group(1).upper()}), which defeats the rollback / "
                   "one-transaction guarantee")
    return out


def rehearsal_sql(items: list[tuple[str, str]]) -> str:
    """ONE transaction over every pending file, ending in ROLLBACK."""
    body = "\n".join(f"-- >>> {v}\n{sql}\n" for v, sql in items)
    return f"BEGIN;\n{body}\nROLLBACK;\n"


def _psql(sql: str, extra: list[str] | None = None) -> tuple[int, str]:
    cmd = ["ssh", HOST, "docker", "exec", "-i", CONTAINER, *PSQL, *(extra or [])]
    r = subprocess.run(cmd, input=sql, capture_output=True, text=True, timeout=900)
    return r.returncode, (r.stdout + r.stderr)


def check_target(psql=_psql) -> list[str]:
    """Wrong-target guard. Returns problems (empty = this is the live WTF primary)."""
    rc, out = psql("SELECT current_database(), pg_is_in_recovery(), "
                   "EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
                   "AND table_name='schema_migrations' AND column_name='filename');")
    if rc != 0:
        return [f"could not reach the target: {out.strip()[:200]}"]
    parts = out.strip().splitlines()[-1].split("|") if out.strip() else []
    if len(parts) != 3:
        return [f"unexpected answer from target: {out.strip()[:200]}"]
    db, recovery, has_filename = parts
    bad = []
    if db != "wtf":
        bad.append(f"database is {db!r}, not 'wtf'")
    if recovery != "f":
        bad.append("target is in recovery (a replica) — migrations go to the primary")
    if has_filename != "t":
        bad.append("public.schema_migrations has no 'filename' column — this is not the WTF ledger")
    return bad


def read_ledger(psql=_psql) -> set[str]:
    rc, out = psql("SELECT version FROM public.schema_migrations;")
    if rc != 0:
        raise RuntimeError(f"cannot read the ledger: {out.strip()[:200]}")
    return {ln.strip() for ln in out.splitlines() if ln.strip()}


def _load(todo, migrations_dir=MIGRATIONS_DIR):
    items, bad = [], []
    for v, p in todo:
        sql = p.read_text(encoding="utf-8")
        for why in problems(v, sql):
            bad.append(f"{p.name}: {why}")
        items.append((v, sql))
    return items, bad


def run(cmd: str, yes: bool = False, psql=_psql, migrations_dir: Path = MIGRATIONS_DIR, out=print) -> int:
    t = check_target(psql)
    if t:
        for line in t:
            out(f"REFUSED: {line}")
        return 2
    todo = pending(on_disk(migrations_dir), read_ledger(psql))
    if not todo:
        out("Nothing pending — every ledger-era migration on disk is recorded.")
        return 0
    out("Pending: " + ", ".join(p.name for _, p in todo))
    items, bad = _load(todo)
    if bad:
        for line in bad:
            out(f"REFUSED: {line}")
        return 2
    if cmd == "plan":
        return 0
    if cmd == "rehearse":
        rc, res = psql(rehearsal_sql(items))
        out(res.strip()[-1500:])
        out("REHEARSAL OK (rolled back, nothing changed)" if rc == 0 else "REHEARSAL FAILED — nothing was applied")
        return 0 if rc == 0 else 1
    if cmd == "apply":
        if not yes:
            out("apply needs --yes (run `rehearse` first)")
            return 2
        for v, sql in items:
            rc, res = psql(sql, ["-1"])
            if rc != 0:
                out(f"{v} FAILED, stopping (that migration was rolled back):\n{res.strip()[-800:]}")
                return 1
            if v not in read_ledger(psql):
                out(f"{v}: psql returned 0 but the ledger has no row — treating as a failure")
                return 1
            out(f"{v} applied and recorded")
        return 0
    return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", nargs="?", default="plan", choices=["plan", "rehearse", "apply"])
    ap.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)
    return run(a.cmd, a.yes)


if __name__ == "__main__":
    sys.exit(main())

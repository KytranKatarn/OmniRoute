#!/usr/bin/env python3
"""READ-ONLY report: which WTF migrations are on disk, and which are recorded as applied.

Until migration 088 there was no ledger (see that file's header), so the only way to
answer "is 085 actually on Citadel?" was to open psql and look for the objects the file
creates. This reads the ledger instead.

    python what-the-fact/scripts/migrations_admin.py status

Exit status is 1 only for genuine drift — a version recorded as applied whose file no
longer exists on disk. Migrations that predate the ledger are reported as
'baseline (unrecorded by design)' and are NOT an error; that is what migration 088 says
they are. Nothing here writes to the database.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
# Migration 088 is where the ledger begins; anything lower is pre-ledger.
LEDGER_FROM = 88
BASELINE_VERSION = "000-baseline"


def on_disk(migrations_dir: Path = MIGRATIONS_DIR) -> list[tuple[str, str]]:
    """(version, filename) for every migration file, numerically ordered.

    Versions are zero-padded to three digits on disk, so a plain string sort would put
    '100' before '088'. Sort on the integer.
    """
    out = []
    for path in migrations_dir.glob("[0-9][0-9][0-9]_*.sql"):
        version = path.name[:3]
        if not version.isdigit():
            continue
        out.append((version, path.name))
    return sorted(out, key=lambda v: int(v[0]))


def _engine():
    from sqlalchemy import create_engine
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        sys.exit("WTF_DATABASE_URL is not set")
    return create_engine(url)


def collect_status(engine, migrations_dir: Path = MIGRATIONS_DIR,
                   ledger_schema: str = "public") -> dict:
    """Compare the files on disk against the ledger. Pure with respect to the DB.

    `ledger_schema` exists so tests can aim at a throwaway schema. Production leaves it
    at "public" and must: the hub's archie database has a same-named table there holding
    the platform's own migration history, which is precisely what this tool must never
    read from or write to.
    """
    from sqlalchemy import text

    if not ledger_schema.replace("_", "").isalnum():
        raise ValueError(f"unsafe ledger_schema: {ledger_schema!r}")
    q = f'"{ledger_schema}".schema_migrations'

    files = on_disk(migrations_dir)
    tracked: dict[str, str] = {}
    ledger_exists = False
    # The hub's archie database has a same-named table belonging to the PLATFORM, with no
    # 'filename' column. Without this check, running against the hub would quietly report
    # the platform's migration rows as WTF's. Read-only tooling needs the same wrong-target
    # guard that migration 088 gets from its deliberate INSERT failure.
    is_wtf_ledger = False
    with engine.connect() as c:
        reg = c.execute(text(f"SELECT to_regclass('{q}')::text")).scalar()
        ledger_exists = bool(reg)
        if ledger_exists:
            cols = {r[0] for r in c.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema=:s AND table_name='schema_migrations'"),
                {"s": ledger_schema})}
            is_wtf_ledger = "filename" in cols
            if is_wtf_ledger:
                rows = c.execute(text(
                    f"SELECT version, coalesce(applied_at::text, 'NULL') FROM {q}")).all()
                tracked = {str(v): str(t) for v, t in rows}

    disk_versions = {v for v, _ in files}
    entries = []
    for version, filename in files:
        if version in tracked:
            state = "applied" if int(version) >= LEDGER_FROM else "baseline"
            entries.append({"version": version, "file": filename,
                            "state": state, "applied_at": tracked[version]})
        elif int(version) < LEDGER_FROM:
            # Expected: 088 documents these as applied before the ledger existed.
            entries.append({"version": version, "file": filename,
                            "state": "baseline (unrecorded by design)",
                            "applied_at": "-"})
        else:
            # At or after the ledger's start with no row: the file is on disk but
            # nobody applied it, or someone applied it without letting it log.
            entries.append({"version": version, "file": filename,
                            "state": "NOT APPLIED", "applied_at": "-"})

    # A ledger row with no file is real drift: history says applied, repo disagrees.
    orphans = sorted(v for v in tracked
                     if v not in disk_versions and v != BASELINE_VERSION)

    return {
        "ledger_exists": ledger_exists,
        "is_wtf_ledger": is_wtf_ledger,
        "has_baseline_row": BASELINE_VERSION in tracked,
        "entries": entries,
        "orphan_versions": orphans,
        "not_applied": [e["version"] for e in entries if e["state"] == "NOT APPLIED"],
        "drift": bool(orphans),
    }


def _render(status: dict) -> str:
    lines = []
    if status["ledger_exists"] and not status["is_wtf_ledger"]:
        return ("WRONG DATABASE: public.schema_migrations here has no 'filename' column,"
                " so it is the PLATFORM's ledger on the hub's archie database, not WTF's.\n"
                "WTF runs on Citadel's wtf database. Nothing below describes WTF; refusing"
                " to report.")
    if not status["ledger_exists"]:
        lines.append("No public.schema_migrations table — migration 088 has not been "
                     "applied to this database.")
        lines.append("Nothing on disk can be confirmed from a ledger; every file below "
                     "is unknown.")
    elif not status["has_baseline_row"]:
        lines.append("Ledger exists but the '000-baseline' row is missing — this "
                     "database did not get migration 088 as written.")

    width = max((len(e["file"]) for e in status["entries"]), default=10)
    lines.append("")
    lines.append(f"{'version':<8} {'file':<{width}}  {'applied':<32} recorded")
    lines.append("-" * (width + 56))
    for e in status["entries"]:
        lines.append(f"{e['version']:<8} {e['file']:<{width}}  "
                     f"{e['state']:<32} {e['applied_at']}")

    untracked = [e for e in status["entries"] if e["state"].startswith("baseline (")]
    lines.append("")
    lines.append(f"{len(status['entries'])} migration file(s) on disk; "
                 f"{len(untracked)} predate the ledger (unverified, by design); "
                 f"{len(status['not_applied'])} not applied.")
    for version in status["orphan_versions"]:
        lines.append(f"DRIFT: {version} is recorded as applied but has no file on disk.")
    return "\n".join(lines)


def cmd_status(_a) -> int:
    status = collect_status(_engine())
    print(_render(status))
    # Non-zero for the two states where a report would mislead: pointing at the wrong
    # database, or the ledger contradicting the files on disk.
    if status["ledger_exists"] and not status["is_wtf_ledger"]:
        return 1
    return 1 if status["drift"] else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

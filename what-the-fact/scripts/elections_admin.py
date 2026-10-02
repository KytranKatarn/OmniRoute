#!/usr/bin/env python3
"""Verify the curated /elections data — one enforced command instead of hand-written SQL.

The election calendar and non-federal history are CURATED (no feed publishes them), so the
site withholds every row until a human has checked it against a source. This tool is that
human step: it validates what you typed (dates in order, not in the past, a rule and an
https source URL present, history seats adding up), prints what it WOULD write, and only
writes with --apply. Federal history is derived from ingested results and is not edited here.

    # what still needs verifying
    python3 scripts/elections_admin.py list

    # verify a calendar row (writes verified_at = now())
    python3 scripts/elections_admin.py verify QC --last 2022-10-03 --next 2026-10-05 \
        --rule "Election Act (Québec) s.129 — first Monday of October, fourth year" \
        --source https://www.elections.quebec/... --party CAQ --head "François Legault" --apply

    # add a past provincial/municipal result
    python3 scripts/elections_admin.py add-history QC --date 2022-10-03 \
        --results '[{"party":"CAQ","seats":90},{"party":"Liberal","seats":21}]' \
        --seats-total 111 --turnout 66.1 --source https://… --apply

Needs WTF_DATABASE_URL (the consumer container has it). Never writes without --apply.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from shared.election_calendar import (  # noqa: E402
    ValidationError, validate_calendar_update, validate_history_row)


def _engine():
    from sqlalchemy import create_engine
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        sys.exit("WTF_DATABASE_URL is not set")
    return create_engine(url)


def cmd_list(_a) -> int:
    from sqlalchemy import text
    with _engine().connect() as c:
        rows = c.execute(text(
            "SELECT jurisdiction_code, jurisdiction, level, verified_at FROM parliament.election_calendar "
            "ORDER BY (verified_at IS NOT NULL), level, jurisdiction_code")).all()
    for code, name, level, v in rows:
        print(f"{'verified ' + str(v)[:10] if v else 'UNVERIFIED':<20} {level:<10} {code:<22} {name}")
    return 0


def cmd_verify(a) -> int:
    try:
        v = validate_calendar_update(last_election=a.last, next_latest_date=a.next,
                                     rule=a.rule, source_url=a.source)
    except (ValidationError, ValueError) as e:
        print("REFUSED:", e, file=sys.stderr)
        return 2
    params = dict(code=a.code, last=v["last_election"], nxt=v["next_latest_date"], rule=v["rule"],
                  src=v["source_url"], party=a.party, head=a.head)
    print("WOULD UPDATE election_calendar", params)
    if not a.apply:
        print("(dry run — add --apply to write)")
        return 0
    from sqlalchemy import text
    with _engine().begin() as c:
        n = c.execute(text(
            "UPDATE parliament.election_calendar SET last_election=:last, next_latest_date=:nxt, "
            "rule=:rule, source_url=:src, government_party=:party, head_of_government=:head, "
            "verified_at=now() WHERE jurisdiction_code=:code"), params).rowcount
    if n != 1:
        print(f"REFUSED: no calendar row with code {a.code!r} (run `list`)", file=sys.stderr)
        return 2
    print("verified", a.code)
    return 0


def cmd_add_history(a) -> int:
    try:
        results = json.loads(a.results)
        v = validate_history_row(election_date=a.date, results=results, source_url=a.source,
                                 seats_total=a.seats_total, turnout_pct=a.turnout)
    except (ValidationError, ValueError, TypeError) as e:
        print("REFUSED:", e, file=sys.stderr)
        return 2
    print("WOULD INSERT election_history", a.code, v["election_date"], v["results"], v["source_url"])
    if not a.apply:
        print("(dry run — add --apply to write)")
        return 0
    from sqlalchemy import text
    with _engine().begin() as c:
        c.execute(text(
            "INSERT INTO parliament.election_history (jurisdiction_code, election_date, turnout_pct, "
            "seats_total, results, source_url) VALUES (:code, :d, :t, :s, CAST(:r AS jsonb), :src) "
            "ON CONFLICT (jurisdiction_code, election_date) DO UPDATE SET turnout_pct=EXCLUDED.turnout_pct, "
            "seats_total=EXCLUDED.seats_total, results=EXCLUDED.results, source_url=EXCLUDED.source_url, "
            "verified_at=now()"),
            dict(code=a.code, d=v["election_date"], t=v["turnout_pct"], s=v["seats_total"],
                 r=json.dumps(v["results"]), src=v["source_url"]))
    print("recorded", a.code, v["election_date"])
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    v = sub.add_parser("verify"); v.set_defaults(fn=cmd_verify)
    v.add_argument("code"); v.add_argument("--last", required=True); v.add_argument("--next", required=True)
    v.add_argument("--rule", required=True); v.add_argument("--source", required=True)
    v.add_argument("--party"); v.add_argument("--head"); v.add_argument("--apply", action="store_true")
    h = sub.add_parser("add-history"); h.set_defaults(fn=cmd_add_history)
    h.add_argument("code"); h.add_argument("--date", required=True); h.add_argument("--results", required=True)
    h.add_argument("--source", required=True); h.add_argument("--seats-total", type=int, dest="seats_total")
    h.add_argument("--turnout", type=float); h.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())

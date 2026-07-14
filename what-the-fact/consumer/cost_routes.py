"""cost_routes.py -- "What Parliament Costs Canadians" API (project #348, Phase 1: MPs).

Public, read-only, cached endpoints over the cost model. The model itself lives in
ingest.parliament.cost (the single source of truth); these routes are thin HTTP wrappers.

  GET /api/cost/mp/<int:mp_id>   -> mp_cost_5yr(mp_id): per-year + 5-year total for one MP
  GET /api/cost/summary          -> parliament_cost_summary(): national cost of Parliament

Every response carries `_source` (where the figures come from) and `_note` (approximate)
so the public number is never presented as exact. Read-only: connects ONLY to
WTF_DATABASE_URL and never writes. Short TTL cache guards the gunicorn workers.
"""

import hashlib
import json
import os
import time

from flask import Blueprint, jsonify, request
from sqlalchemy import create_engine

from ingest.parliament.cost import (
    cost_reconciliation,
    mp_cost_5yr,
    officials_cost,
    parliament_cost_summary,
    senator_cost_5yr,
)

_MAX_OFFICIALS = 200  # cap the batch — a page shows dozens of officials, never thousands

cost_bp = Blueprint("cost", __name__)

_engine = None
_CACHE: dict = {}                                              # key -> (expiry_epoch, payload)
_CACHE_TTL = int(os.environ.get("COST_CACHE_TTL", "600"))     # 10 min -- reference + quarterly data

_SOURCE = {
    "indemnity": (
        "Library of Parliament, ParlInfo -- Indemnities, Salaries and Allowances "
        "(https://lop.parl.ca/sites/ParlInfo/default/en_CA/People/Salaries), "
        "seeded in parliament.indemnity_rates"
    ),
    "office_expenses": (
        "House of Commons Proactive Disclosure -- Members' Expenditures Report "
        "(parliament.mp_expenses)"
    ),
    "senator_expenses": (
        "Senate of Canada -- Senators' quarterly expenditures "
        "(https://sencanada.ca, parliament.senator_expenses)"
    ),
    "ministerial": (
        "Treasury Board of Canada Secretariat -- Proactive disclosure of travel & "
        "hospitality (https://open.canada.ca, parliament.minister_travel)"
    ),
    "contracts": (
        "CanadaBuys contract award notices (open procurement data), via Gov Watch "
        "(gov_watch.award_notices) -- federal contracts by awarding department, "
        "portfolio-level & approximate"
    ),
}


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(os.environ["WTF_DATABASE_URL"], pool_pre_ping=True)
    return _engine


def _cached(key, fn):
    hit = _CACHE.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    payload = fn()
    _CACHE[key] = (time.time() + _CACHE_TTL, payload)
    return payload


@cost_bp.route("/api/cost/mp/<int:mp_id>")
def api_cost_mp(mp_id):
    """5-year approximate taxpayer cost of one MP. Public, cached."""
    data = dict(_cached(f"mp:{mp_id}", lambda: mp_cost_5yr(_get_engine(), mp_id)))
    data["_source"] = _SOURCE
    return jsonify(data)


@cost_bp.route("/api/cost/senator/<int:senator_id>")
def api_cost_senator(senator_id):
    """5-year approximate taxpayer cost of one senator. Public, cached."""
    data = dict(_cached(f"senator:{senator_id}", lambda: senator_cost_5yr(_get_engine(), senator_id)))
    data["_source"] = _SOURCE
    return jsonify(data)


@cost_bp.route("/api/cost/summary")
def api_cost_summary():
    """National "cost of Parliament" per year + 5-year grand total. Public, cached."""
    data = dict(_cached("summary", lambda: parliament_cost_summary(_get_engine())))
    data["_source"] = _SOURCE
    return jsonify(data)


@cost_bp.route("/api/cost/reconciliation")
def api_cost_reconciliation():
    """Member-by-member reconciliation of the national headline -- the public "show your work".

    Confirms the 5-year total equals the independent sum of every MP + senator (plus the
    ministerial line, reported separately), with data coverage + provenance. Public, cached.
    `?members=all` returns the full roster breakdown; default returns the 25 costliest.
    """
    scope = "all" if request.args.get("members") == "all" else "top"
    data = dict(_cached("reconciliation", lambda: cost_reconciliation(_get_engine())))
    if scope == "top":
        data["members"] = (data.get("members") or [])[:25]
        data["members_truncated"] = True
    data["_source"] = _SOURCE
    return jsonify(data)


@cost_bp.route("/api/cost/officials", methods=["POST"])
def api_cost_officials():
    """Batch: 5-year approximate taxpayer cost for a list of NAMED civic officials.

    Cross-product surface (civic-watch transparency registry). Body:
        {"officials": [{"name": "Given Surname", "role": "minister"|"senator"}, ...]}
    Each is name-matched to the WTF parliamentary roster and costed via the single
    source of truth (cost.officials_cost). Public, cached by request hash. XSS n/a (JSON).
    Unmatched officials come back matched=false with no figures.
    """
    body = request.get_json(silent=True) or {}
    raw = body.get("officials")
    if not isinstance(raw, list):
        raw = []
    # sanitize + cap: only well-formed {name, role} entries, bounded length
    officials = [
        {"name": str(o["name"])[:120], "role": str(o.get("role") or "")[:32]}
        for o in raw[:_MAX_OFFICIALS]
        if isinstance(o, dict) and o.get("name")
    ]
    key = "officials:" + hashlib.sha1(
        json.dumps(officials, sort_keys=True).encode("utf-8")
    ).hexdigest()
    rows = _cached(key, lambda: officials_cost(_get_engine(), officials))
    return jsonify(
        {
            "officials": rows,
            "count": len(rows),
            "matched": sum(1 for r in rows if r.get("matched")),
            "_source": _SOURCE,
            "_note": (
                "approximate 5-year taxpayer cost (office expenses + indemnity; excludes "
                "pensions and central costs); name-matched to the Library of Parliament "
                "roster -- unmatched officials carry no figure"
            ),
        }
    )

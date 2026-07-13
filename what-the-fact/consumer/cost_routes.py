"""cost_routes.py -- "What Parliament Costs Canadians" API (project #348, Phase 1: MPs).

Public, read-only, cached endpoints over the cost model. The model itself lives in
ingest.parliament.cost (the single source of truth); these routes are thin HTTP wrappers.

  GET /api/cost/mp/<int:mp_id>   -> mp_cost_5yr(mp_id): per-year + 5-year total for one MP
  GET /api/cost/summary          -> parliament_cost_summary(): national cost of Parliament

Every response carries `_source` (where the figures come from) and `_note` (approximate)
so the public number is never presented as exact. Read-only: connects ONLY to
WTF_DATABASE_URL and never writes. Short TTL cache guards the gunicorn workers.
"""

import os
import time

from flask import Blueprint, jsonify
from sqlalchemy import create_engine

from ingest.parliament.cost import mp_cost_5yr, parliament_cost_summary, senator_cost_5yr

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

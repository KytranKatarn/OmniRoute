"""Entity-Graph company-layer ingest (Phase 1, Slice D) — join + push.

Builds sector-tagged `organization` entities from:
  • TMX listed companies  -> the SET + sector (tmx_sector.py, automated/free)
  • SEDAR reporting issuers -> the authoritative identity key (sedar_issuers.py,
    human-exported CSV; the fetch is un-automatable — KB #275949)
joined by normalized name, and POSTs them to the shared entity-graph ingest
endpoint (wtf-ingest-api:8106, which accepts metadata + external_ids since the
ADR-EG-001 amendment / Slice A). product='market-watch'.

The TMX listed set IS the v1 benchmark universe (~2,019 operating cos); SEDAR
enriches matched ones with key_type='sedar_issuer' for cross-product resolution.
Runs HUB-SIDE (reaches the endpoint over the mesh). ToU: TMX classification is a
derived input — `market_cap` quotes are deliberately NOT ingested.
"""

from __future__ import annotations

import os
import re

from . import sedar_issuers, tmx_sector

PRODUCT = "market-watch"
ENTITY_INGEST_URL = os.environ.get(
    "ENTITY_INGEST_URL", "http://100.64.0.10:8106/api/internal/entity-graph/ingest"
)
HTTP_TIMEOUT = 180
_BATCH = 2000  # well under the endpoint's 5000 entity cap

# Dropped when normalizing a company name for the cross-source join.
_DROP_TOKENS = frozenset({
    "the", "corp", "corporation", "inc", "incorporated", "ltd", "limited",
    "co", "company", "lp", "llp", "plc", "sa", "nv", "ulc", "trust", "fund",
    "holdings", "group",
})


def _norm_name(name: str) -> str:
    """Normalize a company name for matching (TMX <-> SEDAR).

    Bilingual SEDAR names ('English / Français') -> the English part; lowercase;
    drop punctuation + common corporate suffixes/qualifiers.
    """
    n = name or ""
    if " / " in n:
        n = n.split(" / ", 1)[0]
    n = re.sub(r"[^a-z0-9 ]", " ", n.lower())
    return " ".join(t for t in n.split() if t and t not in _DROP_TOKENS)


def _sedar_index(sedar_records) -> dict:
    idx = {}
    for r in sedar_records or []:
        k = _norm_name(r["name"])
        if k:
            idx.setdefault(k, r["sedar_number"])
    return idx


def build_company_entities(tmx_records, sedar_records=None) -> list:
    """TMX companies -> entity-graph `organization` payloads, SEDAR-enriched.

    Each entity: canonical_name (TMX name), entity_type='organization', empty
    role, metadata.naics_* (tmx_derived) + ticker/exchange/tmx_sector provenance,
    and a sedar_issuer external_id when the name matches a SEDAR record.
    """
    sidx = _sedar_index(sedar_records)
    out = []
    for t in tmx_records:
        meta = {
            "naics_sector": t["naics_sector"],
            "naics_label": t.get("naics_label", ""),
            "naics_source": tmx_sector.NAICS_SOURCE,   # 'tmx_derived'
            "naics_confidence": t["naics_confidence"],
            "tmx_sector": t["tmx_sector"],
            "exchange": t.get("exchange", ""),
        }
        if t.get("ticker"):
            meta["ticker"] = t["ticker"]
        if t.get("tmx_sub_sector"):
            meta["tmx_sub_sector"] = t["tmx_sub_sector"]

        ext = []
        num = sidx.get(_norm_name(t["name"]))
        if num:
            ext.append({"key_type": sedar_issuers.SEDAR_KEY_TYPE, "key_value": num})

        out.append({
            "canonical_name": t["name"],
            "entity_type": "organization",
            "role": {},
            "metadata": meta,
            "external_ids": ext,
        })
    return out


def ingest_payload(entities, product=PRODUCT) -> dict:
    return {"product": product, "entities": entities, "mentions": [], "relationships": []}


def post_ingest(payload, url=None, key=None) -> dict:
    import requests  # lazy — keeps pure logic + dry-run importable without it
    url = url or ENTITY_INGEST_URL
    key = key or os.environ.get("INTERNAL_API_KEY", "")
    resp = requests.post(url, json=payload, headers={"X-Internal-Key": key}, timeout=HTTP_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def run(sedar_csv_path=None, tmx_url=tmx_sector.TMX_URL, post=False, url=None, key=None) -> dict:
    """Load TMX (+ optional SEDAR CSV), build entities, optionally POST in batches."""
    tmx = tmx_sector.load_tmx_companies(tmx_url)
    sedar = (sedar_issuers.operating_issuers(sedar_issuers.load_sedar_export(sedar_csv_path))
             if sedar_csv_path else [])
    entities = build_company_entities(tmx, sedar)
    summary = {
        "tmx_companies": len(tmx),
        "sedar_operating": len(sedar),
        "entities_built": len(entities),
        "with_sedar_key": sum(1 for e in entities if e["external_ids"]),
    }
    if post:
        results = []
        for i in range(0, len(entities), _BATCH):
            results.append(post_ingest(ingest_payload(entities[i:i + _BATCH]), url, key))
        summary["ingest_results"] = results
    return summary


if __name__ == "__main__":  # dry-run by default (no POST, no graph writes)
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Phase-1 company-layer ingest")
    ap.add_argument("--sedar", help="path to a human-exported SEDAR reporting-issuers CSV")
    ap.add_argument("--post", action="store_true", help="actually POST to the graph (else dry-run)")
    args = ap.parse_args()
    s = run(sedar_csv_path=args.sedar, post=args.post)
    print(json.dumps({k: v for k, v in s.items() if k != "ingest_results"}, indent=2))
    for r in s.get("ingest_results", []):
        print("INGEST:", r)

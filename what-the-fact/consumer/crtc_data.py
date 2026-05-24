"""
CRTC media ownership reference data.

Static seed used to backfill sources.owner_name / sources.owner_type
and to drive the ownership concentration panel on the /crtc page.

Outlet names here are matched (case-insensitive substring) against
wtf.sources.name at startup via seed_owner_data() below.
"""

from __future__ import annotations

OWNERSHIP_GROUPS: dict[str, dict] = {
    "Bell Media": {
        "outlets": [
            "CTV News",
            "Globe and Mail",
            "TSN",
            "BNN Bloomberg",
            "CP24",
            "CTV News Channel",
            "RDS",
            "Discovery Canada",
        ],
        "crtc_id": "Bell-Media",
        "type": "corporate",
        "hhi_tier": "high",
        "description": "Telecom and media conglomerate. Owns CTV national network, Globe and Mail, BNN Bloomberg, TSN/RDS.",
    },
    "Rogers Media": {
        "outlets": [
            "Citytv",
            "Sportsnet",
            "Macleans",
            "City News",
            "FX Canada",
        ],
        "crtc_id": "Rogers-Media",
        "type": "corporate",
        "hhi_tier": "high",
        "description": "Telecom and media conglomerate. Owns Citytv network, Sportsnet, Maclean's magazine.",
    },
    "Postmedia": {
        "outlets": [
            "National Post",
            "Ottawa Citizen",
            "Vancouver Sun",
            "Calgary Herald",
            "Edmonton Journal",
            "Montreal Gazette",
            "Windsor Star",
            "Regina Leader-Post",
            "Saskatoon StarPhoenix",
            "Victoria Times Colonist",
            "Province",
            "Financial Post",
        ],
        "crtc_id": "Postmedia",
        "type": "corporate",
        "hhi_tier": "very_high",
        "description": "Largest print newspaper chain in Canada. Owns 100+ daily and community papers including National Post.",
    },
    "Torstar": {
        "outlets": [
            "Toronto Star",
            "Hamilton Spectator",
            "Waterloo Region Record",
            "Peterborough Examiner",
            "St. Catharines Standard",
            "Niagara Falls Review",
        ],
        "crtc_id": "Torstar",
        "type": "corporate",
        "hhi_tier": "medium",
        "description": "Owns Toronto Star, Canada's largest-circulation daily newspaper, and several Ontario regional papers.",
    },
    "Quebecor": {
        "outlets": [
            "TVA",
            "Journal de Montréal",
            "Journal de Québec",
            "Le Journal de Montréal",
            "Le Journal de Québec",
            "TVA Nouvelles",
            "QMI Agency",
            "Sun Media",
            "Canoe",
            "24 heures",
        ],
        "crtc_id": "Quebecor",
        "type": "corporate",
        "hhi_tier": "high",
        "description": "Dominant Quebec media group. Owns TVA (largest French-language private TV network), Journal de Montréal/Québec.",
    },
    "CBC/Radio-Canada": {
        "outlets": [
            "CBC News",
            "Radio-Canada",
            "CBC Radio",
            "CBC News Network",
            "ICI Radio-Canada",
            "ICI Télé",
            "CBC",
        ],
        "crtc_id": "CBC-Radio-Canada",
        "type": "public",
        "hhi_tier": "medium",
        "description": "Canadian public broadcaster. Mandated national news coverage in English and French.",
    },
    "Unifor Media": {
        "outlets": [
            "PressProgress",
            "CanadaLand",
        ],
        "crtc_id": "Unifor",
        "type": "non_profit",
        "hhi_tier": "low",
        "description": "Canada's largest private-sector union, also owns labour-aligned media outlets.",
    },
    "Independent": {
        "outlets": [
            "iPolitics",
            "The Tyee",
            "National Observer",
            "Rabble",
            "Pivot",
            "Discourse Media",
            "Halifax Examiner",
        ],
        "crtc_id": None,
        "type": "independent",
        "hhi_tier": "low",
        "description": "Independently owned outlets without corporate or government affiliation.",
    },
}

# HHI tier labels shown on the concentration badge
HHI_LABELS = {
    "very_high": ("Very High", "#ef4444"),
    "high": ("High", "#f97316"),
    "medium": ("Medium", "#f59e0b"),
    "low": ("Low", "#22c55e"),
}


def get_concentration_badge(owners_data: list[dict], total_sources: int) -> dict:
    """
    Compute a concentration risk badge from live DB ownership data.

    owners_data: list of dicts with keys owner_name, outlet_count
    total_sources: total tracked outlets

    Returns dict with 'label', 'colour', 'pct_top3', 'top3_names'.
    """
    if not total_sources:
        return {"label": "Unknown", "colour": "#6b7280", "pct_top3": 0, "top3_names": []}

    sorted_owners = sorted(owners_data, key=lambda x: x.get("outlet_count", 0), reverse=True)
    top3 = sorted_owners[:3]
    top3_count = sum(o.get("outlet_count", 0) for o in top3)
    pct = round(top3_count / total_sources * 100, 1)
    top3_names = [o["owner_name"] for o in top3 if o.get("owner_name")]

    if pct >= 60:
        label, colour = "High Concentration", "#ef4444"
    elif pct >= 40:
        label, colour = "Moderate Concentration", "#f59e0b"
    else:
        label, colour = "Distributed", "#22c55e"

    return {
        "label": label,
        "colour": colour,
        "pct_top3": pct,
        "top3_names": top3_names,
    }

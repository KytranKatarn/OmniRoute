"""Header tiles and filter-chip counts for /sources, computed from the outlet rows the route already fetched (no extra query).

Pure and stdlib-only. They describe the outlets SHOWN, so a search narrows them. `below_min_n` outlets still count as tracked and still add their
scored articles, but are not counted as having a measured band.
"""

OWNER_TYPES = ("public", "corporate", "non_profit", "independent")
LANGUAGES = ("en", "fr")


def build_stats(sources):
    return {
        "outlets": len(sources),
        "scored_articles": sum(int(d.get("scored_article_count") or 0) for d in sources),
        "owners": len({d["owner_name"] for d in sources if d.get("owner_name")}),
        "measured": sum(1 for d in sources if not d.get("below_min_n")),
        "types": {t: sum(1 for d in sources if d.get("owner_type") == t) for t in OWNER_TYPES},
        "languages": {lg: sum(1 for d in sources if d.get("language") == lg) for lg in LANGUAGES},
    }

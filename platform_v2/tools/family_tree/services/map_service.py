"""Family Tree — Migration map geocoding and data service."""

from database import get_db_cursor

# Hardcoded geocoding lookup for common genealogy locations.
# Covers Portuguese diaspora, French, Canadian, US, and other key cities.
GEOCODE_DB = {
    # Portugal
    "lisboa": {"lat": 38.7223, "lng": -9.1393},
    "lisbon": {"lat": 38.7223, "lng": -9.1393},
    "porto": {"lat": 41.1579, "lng": -8.6291},
    "coimbra": {"lat": 40.2033, "lng": -8.4103},
    "braga": {"lat": 41.5518, "lng": -8.4229},
    "faro": {"lat": 37.0194, "lng": -7.9322},
    "aveiro": {"lat": 40.6405, "lng": -8.6538},
    "funchal": {"lat": 32.6669, "lng": -16.9241},
    "ponta delgada": {"lat": 37.7483, "lng": -25.6666},
    "angra do heroísmo": {"lat": 38.6555, "lng": -27.2208},
    "angra do heroismo": {"lat": 38.6555, "lng": -27.2208},
    "viseu": {"lat": 40.6610, "lng": -7.9097},
    "leiria": {"lat": 39.7437, "lng": -8.8071},
    "setúbal": {"lat": 38.5244, "lng": -8.8882},
    "setubal": {"lat": 38.5244, "lng": -8.8882},
    "évora": {"lat": 38.5710, "lng": -7.9093},
    "evora": {"lat": 38.5710, "lng": -7.9093},
    "guimarães": {"lat": 41.4425, "lng": -8.2918},
    "guimaraes": {"lat": 41.4425, "lng": -8.2918},
    # France
    "paris": {"lat": 48.8566, "lng": 2.3522},
    "lyon": {"lat": 45.7640, "lng": 4.8357},
    "marseille": {"lat": 43.2965, "lng": 5.3698},
    "bordeaux": {"lat": 44.8378, "lng": -0.5792},
    "toulouse": {"lat": 43.6047, "lng": 1.4442},
    "nantes": {"lat": 47.2184, "lng": -1.5536},
    "strasbourg": {"lat": 48.5734, "lng": 7.7521},
    "lille": {"lat": 50.6292, "lng": 3.0573},
    "nice": {"lat": 43.7102, "lng": 7.2620},
    # Canada
    "montréal": {"lat": 45.5017, "lng": -73.5673},
    "montreal": {"lat": 45.5017, "lng": -73.5673},
    "toronto": {"lat": 43.6532, "lng": -79.3832},
    "ottawa": {"lat": 45.4215, "lng": -75.6972},
    "québec": {"lat": 46.8139, "lng": -71.2080},
    "quebec": {"lat": 46.8139, "lng": -71.2080},
    "quebec city": {"lat": 46.8139, "lng": -71.2080},
    "vancouver": {"lat": 49.2827, "lng": -123.1207},
    "halifax": {"lat": 44.6488, "lng": -63.5752},
    "winnipeg": {"lat": 49.8951, "lng": -97.1384},
    "calgary": {"lat": 51.0447, "lng": -114.0719},
    "edmonton": {"lat": 53.5461, "lng": -113.4938},
    "laval": {"lat": 45.5690, "lng": -73.6920},
    "gatineau": {"lat": 45.4765, "lng": -75.7013},
    # United States (common Portuguese immigration destinations)
    "new york": {"lat": 40.7128, "lng": -74.0060},
    "new york city": {"lat": 40.7128, "lng": -74.0060},
    "boston": {"lat": 42.3601, "lng": -71.0589},
    "newark": {"lat": 40.7357, "lng": -74.1724},
    "fall river": {"lat": 41.7015, "lng": -71.1550},
    "providence": {"lat": 41.8240, "lng": -71.4128},
    "new bedford": {"lat": 41.6362, "lng": -70.9342},
    "cambridge": {"lat": 42.3736, "lng": -71.1097},
    "lowell": {"lat": 42.6334, "lng": -71.3162},
    "elizabeth": {"lat": 40.6640, "lng": -74.2107},
    "san jose": {"lat": 37.3382, "lng": -121.8863},
    "san francisco": {"lat": 37.7749, "lng": -122.4194},
    "los angeles": {"lat": 34.0522, "lng": -118.2437},
    "chicago": {"lat": 41.8781, "lng": -87.6298},
    "philadelphia": {"lat": 39.9526, "lng": -75.1652},
    "washington": {"lat": 38.9072, "lng": -77.0369},
    "miami": {"lat": 25.7617, "lng": -80.1918},
    "honolulu": {"lat": 21.3069, "lng": -157.8583},
    # Brazil
    "são paulo": {"lat": -23.5505, "lng": -46.6333},
    "sao paulo": {"lat": -23.5505, "lng": -46.6333},
    "rio de janeiro": {"lat": -22.9068, "lng": -43.1729},
    "salvador": {"lat": -12.9714, "lng": -38.5124},
    "brasília": {"lat": -15.7975, "lng": -47.8919},
    "brasilia": {"lat": -15.7975, "lng": -47.8919},
    # United Kingdom
    "london": {"lat": 51.5074, "lng": -0.1278},
    "manchester": {"lat": 53.4808, "lng": -2.2426},
    "birmingham": {"lat": 52.4862, "lng": -1.8904},
    "edinburgh": {"lat": 55.9533, "lng": -3.1883},
    "glasgow": {"lat": 55.8642, "lng": -4.2518},
    "liverpool": {"lat": 53.4084, "lng": -2.9916},
    # Other common locations
    "dublin": {"lat": 53.3498, "lng": -6.2603},
    "amsterdam": {"lat": 52.3676, "lng": 4.9041},
    "berlin": {"lat": 52.5200, "lng": 13.4050},
    "rome": {"lat": 41.9028, "lng": 12.4964},
    "madrid": {"lat": 40.4168, "lng": -3.7038},
    "barcelona": {"lat": 41.3874, "lng": 2.1686},
    "luanda": {"lat": -8.8390, "lng": 13.2894},
    "maputo": {"lat": -25.9692, "lng": 32.5732},
    "cape town": {"lat": -33.9249, "lng": 18.4241},
    "sydney": {"lat": -33.8688, "lng": 151.2093},
    "melbourne": {"lat": -37.8136, "lng": 144.9631},
    "tokyo": {"lat": 35.6762, "lng": 139.6503},
    "hong kong": {"lat": 22.3193, "lng": 114.1694},
    "macau": {"lat": 22.1987, "lng": 113.5439},
    "goa": {"lat": 15.2993, "lng": 74.1240},
    "mumbai": {"lat": 19.0760, "lng": 72.8777},
    "new delhi": {"lat": 28.6139, "lng": 77.2090},
}


def geocode_place(place_name):
    """Geocode a place name using the hardcoded lookup.

    Tries exact match first, then searches for the place name as a
    substring within known locations (handles "Lisboa, Portugal" style inputs).

    Returns {"lat": float, "lng": float} or None if unknown.
    """
    if not place_name:
        return None

    normalized = place_name.strip().lower()

    # Exact match
    if normalized in GEOCODE_DB:
        return dict(GEOCODE_DB[normalized])

    # Try matching the first part before a comma (e.g. "Lisboa, Portugal")
    if "," in normalized:
        city_part = normalized.split(",")[0].strip()
        if city_part in GEOCODE_DB:
            return dict(GEOCODE_DB[city_part])

    # Try substring match — check if any known city is contained in the input
    for key, coords in GEOCODE_DB.items():
        if key in normalized:
            return dict(coords)

    return None


def get_migration_data(user_id):
    """Query family_persons for migration map data.

    Returns:
        {
            "locations": [{"person_id", "name", "place", "lat", "lng", "year", "event"}],
            "paths": [{"person_id", "name", "from": {lat,lng}, "to": {lat,lng},
                        "year_from", "year_to", "from_place", "to_place"}]
        }
    """
    sql = """
        SELECT
            id, first_name, last_name,
            birth_date, birth_date_approx, birth_place,
            death_date, death_date_approx, death_place
        FROM family_persons
        WHERE user_id = %(user_id)s
          AND (birth_place IS NOT NULL AND birth_place != ''
               OR death_place IS NOT NULL AND death_place != '')
        ORDER BY birth_date ASC NULLS LAST
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(sql, {"user_id": user_id})
        persons = [dict(r) for r in cur.fetchall()]

    locations = []
    paths = []

    for p in persons:
        name = f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
        pid = p["id"]

        birth_geo = geocode_place(p.get("birth_place"))
        death_geo = geocode_place(p.get("death_place"))

        birth_year = _extract_year(p.get("birth_date"), p.get("birth_date_approx"))
        death_year = _extract_year(p.get("death_date"), p.get("death_date_approx"))

        if birth_geo and p.get("birth_place"):
            locations.append(
                {
                    "person_id": pid,
                    "name": name,
                    "place": p["birth_place"],
                    "lat": birth_geo["lat"],
                    "lng": birth_geo["lng"],
                    "year": birth_year,
                    "event": "birth",
                }
            )

        if death_geo and p.get("death_place"):
            locations.append(
                {
                    "person_id": pid,
                    "name": name,
                    "place": p["death_place"],
                    "lat": death_geo["lat"],
                    "lng": death_geo["lng"],
                    "year": death_year,
                    "event": "death",
                }
            )

        # Create migration path if both birth and death places are known and different
        if (
            birth_geo
            and death_geo
            and p.get("birth_place")
            and p.get("death_place")
            and p["birth_place"].strip().lower() != p["death_place"].strip().lower()
        ):
            paths.append(
                {
                    "person_id": pid,
                    "name": name,
                    "from": birth_geo,
                    "to": death_geo,
                    "from_place": p["birth_place"],
                    "to_place": p["death_place"],
                    "year_from": birth_year,
                    "year_to": death_year,
                }
            )

    return {"locations": locations, "paths": paths}


def _extract_year(date_val, approx_val):
    """Extract a year integer from a date or approx string."""
    for val in [date_val, approx_val]:
        if val:
            s = str(val)
            if len(s) >= 4:
                try:
                    return int(s[:4])
                except (ValueError, TypeError):
                    pass
    return None

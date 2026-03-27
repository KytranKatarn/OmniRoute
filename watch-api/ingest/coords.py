"""Canadian coordinate mapping — provinces, territories, and major cities."""

# Federal capital
FEDERAL_COORDS = (-75.70, 45.42)

# Provincial/territorial capitals
PROVINCE_COORDS = {
    "canada": (-75.70, 45.42),
    "ontario": (-79.38, 43.65),
    "british columbia": (-123.12, 49.28),
    "alberta": (-113.49, 53.54),
    "quebec": (-71.21, 46.81),
    "manitoba": (-97.14, 49.90),
    "saskatchewan": (-104.62, 50.45),
    "nova scotia": (-63.57, 44.65),
    "new brunswick": (-66.65, 45.96),
    "newfoundland and labrador": (-52.71, 47.56),
    "prince edward island": (-63.13, 46.24),
    "northwest territories": (-114.37, 62.45),
    "yukon": (-135.05, 60.72),
    "nunavut": (-68.52, 63.75),
}

# Province abbreviation mapping
PROVINCE_ABBREV = {
    "on": "ontario", "bc": "british columbia", "ab": "alberta",
    "qc": "quebec", "mb": "manitoba", "sk": "saskatchewan",
    "ns": "nova scotia", "nb": "new brunswick",
    "nl": "newfoundland and labrador", "pe": "prince edward island",
    "nt": "northwest territories", "yt": "yukon", "nu": "nunavut",
}

# Major city coordinates
CITY_COORDS = {
    "toronto": (-79.38, 43.65),
    "vancouver": (-123.12, 49.28),
    "montreal": (-73.57, 45.50),
    "ottawa": (-75.70, 45.42),
    "calgary": (-114.07, 51.05),
    "edmonton": (-113.49, 53.54),
    "winnipeg": (-97.14, 49.90),
    "halifax": (-63.57, 44.65),
    "victoria": (-123.37, 48.43),
    "quebec city": (-71.21, 46.81),
    "saskatoon": (-106.67, 52.13),
    "regina": (-104.62, 50.45),
    "st. john's": (-52.71, 47.56),
    "fredericton": (-66.65, 45.96),
    "charlottetown": (-63.13, 46.24),
    "whitehorse": (-135.05, 60.72),
    "yellowknife": (-114.37, 62.45),
    "iqaluit": (-68.52, 63.75),
}

import random


def get_coords(jurisdiction, level="federal"):
    """Return (lon, lat) for a jurisdiction with slight jitter to avoid stacking."""
    key = jurisdiction.lower().strip()

    if level == "municipal":
        base = CITY_COORDS.get(key)
    elif level == "provincial":
        base = PROVINCE_COORDS.get(key) or PROVINCE_COORDS.get(
            PROVINCE_ABBREV.get(key, "")
        )
    else:
        base = FEDERAL_COORDS

    if not base:
        base = FEDERAL_COORDS

    jitter_lon = (random.random() - 0.5) * 1.5
    jitter_lat = (random.random() - 0.5) * 1.5
    return (base[0] + jitter_lon, base[1] + jitter_lat)

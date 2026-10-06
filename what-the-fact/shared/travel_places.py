"""Is a Senate travel itinerary international? True / False / None — and NEVER a guess.

The Senate publishes an itinerary as place names only ("Winnipeg - Ottawa - Winnipeg",
"Ottawa - Strasbourg - Ottawa"), with no country and no international flag. A claim such as "senators
spent $1.85M on international travel" therefore needs a classification we make ourselves, and an
inaccurate one would corrupt every figure built on it. So the rule is asymmetric on purpose:

    any leg is a KNOWN FOREIGN place         -> True   (foreign wins even if another leg is unknown)
    EVERY leg is a KNOWN CANADIAN place      -> False
    anything else                            -> None   (unrecognised OR ambiguous — goes to review)

None is "not yet classified", not "domestic". A caller computing an international total must report how
many trips it had to leave out. Ambiguous names (London, Kingston, Victoria, Windsor, Sydney, Perth ...)
exist in both Canada and abroad and are never auto-classified.

The seed lists are a starting point, extended from the real itineraries after the first backfill: the
distinct unrecognised places are listed by ``unreviewed:<place>`` in ``intl_basis`` — a few hundred names
at most, reviewable in one sitting. Add to the sets below, never special-case a trip.
"""
from __future__ import annotations

import re
import unicodedata


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("’", "'").replace(".", " ")
    return re.sub(r"\s+", " ", s).strip()


# Places that exist in Canada AND elsewhere (or are easily confused) — never auto-classified.
AMBIGUOUS = frozenset({
    "london", "kingston", "victoria", "windsor", "sydney", "perth", "richmond", "cambridge", "hamilton",
    "birmingham", "manchester", "paris ontario", "st catharines",  # the last two: leave to a human
})

CANADIAN = frozenset(_norm(x) for x in [
    "Ottawa", "Gatineau", "Toronto", "Montreal", "Québec", "Quebec", "Quebec City", "Winnipeg", "Vancouver",
    "Halifax", "St. John's", "Saint John", "Fredericton", "Moncton", "Charlottetown", "Summerside",
    "Regina", "Saskatoon", "Edmonton", "Calgary", "Red Deer", "Lethbridge", "Medicine Hat", "Yellowknife",
    "Whitehorse", "Iqaluit", "Thunder Bay", "Sudbury", "Sault Ste. Marie", "Kelowna", "Kamloops", "Nanaimo",
    "Prince George", "Abbotsford", "Surrey", "Burnaby", "Sherbrooke", "Trois-Rivières", "Rimouski",
    "Saguenay", "Chicoutimi", "Rouyn-Noranda", "Val-d'Or", "Mont-Joli", "Gaspé", "Bathurst", "Miramichi",
    "Edmundston", "Truro", "Antigonish", "Kentville", "Yarmouth", "Brandon", "Thompson", "Prince Albert",
    "Moose Jaw", "Swift Current", "Grande Prairie", "Fort McMurray", "Brampton", "Mississauga", "Markham",
    "Oakville", "Barrie", "Peterborough", "Oshawa", "Guelph", "Kitchener", "Waterloo", "Brantford",
    "Niagara Falls", "Niagara-on-the-Lake", "North Bay", "Timmins", "Kenora", "Orillia", "Cornwall",
    "Brockville", "Pembroke", "Corner Brook", "Gander", "Happy Valley-Goose Bay", "Stephenville",
    "Dawson City", "Inuvik", "Rankin Inlet", "Cambridge Bay", "Fort Smith", "Hay River", "Saint-Hyacinthe",
    "Granby", "Drummondville", "Longueuil", "Laval", "Lévis", "Terrebonne", "Saint-Jérôme",
])

FOREIGN = frozenset(_norm(x) for x in [
    # Europe
    "Strasbourg", "Paris", "Brussels", "Bruxelles", "Vienna", "Geneva", "Zurich", "Bern", "Berlin", "Munich",
    "Frankfurt", "Hamburg", "Rome", "Milan", "Madrid", "Barcelona", "Lisbon", "Amsterdam", "The Hague",
    "Stockholm", "Copenhagen", "Oslo", "Helsinki", "Reykjavik", "Dublin", "Edinburgh", "Warsaw", "Prague",
    "Budapest", "Bucharest", "Sofia", "Athens", "Kyiv", "Kiev", "Riga", "Vilnius", "Tallinn", "Luxembourg",
    "Valletta", "Brno", "Lviv", "Chisinau", "Belgrade", "Zagreb", "Ljubljana", "Bratislava", "Sarajevo",
    "Tirana", "Skopje", "Podgorica", "Istanbul", "Ankara", "Nicosia", "Monaco", "Andorra",
    # United States
    "Washington", "Washington DC", "New York", "Boston", "Chicago", "Los Angeles", "San Francisco", "Seattle",
    "Miami", "Houston", "Dallas", "Atlanta", "Denver", "Phoenix", "Las Vegas", "Philadelphia", "Detroit",
    "Minneapolis", "San Diego", "Portland", "Anchorage", "Honolulu", "Orlando", "Austin", "New Orleans",
    "Nashville", "Salt Lake City", "Cleveland", "Pittsburgh", "Buffalo", "Albany", "Sacramento",
    # Americas
    "Mexico City", "Santiago", "Buenos Aires", "Brasilia", "Sao Paulo", "Rio de Janeiro", "Lima", "Bogota",
    "Quito", "Caracas", "La Paz", "Montevideo", "Asuncion", "Panama City", "San Jose", "Guatemala City",
    "Santo Domingo", "Port-au-Prince", "Havana", "Nassau", "Bridgetown", "Port of Spain", "Georgetown",
    "Kingston Jamaica", "Belmopan", "San Salvador", "Tegucigalpa", "Managua", "Cancun", "Punta Cana",
    # Asia / Pacific
    "Beijing", "Shanghai", "Hong Kong", "Tokyo", "Osaka", "Seoul", "Taipei", "Delhi", "New Delhi", "Mumbai",
    "Singapore", "Bangkok", "Hanoi", "Ho Chi Minh City", "Manila", "Jakarta", "Kuala Lumpur", "Colombo",
    "Dhaka", "Islamabad", "Kathmandu", "Ulaanbaatar", "Canberra", "Wellington", "Auckland", "Suva",
    "Port Moresby", "Apia", "Nuku'alofa",
    # Middle East / Africa
    "Dubai", "Abu Dhabi", "Doha", "Riyadh", "Muscat", "Kuwait City", "Manama", "Amman", "Beirut", "Baghdad",
    "Tel Aviv", "Jerusalem", "Cairo", "Tunis", "Rabat", "Algiers", "Nairobi", "Kampala", "Kigali",
    "Addis Ababa", "Accra", "Dakar", "Abidjan", "Lagos", "Abuja", "Pretoria", "Johannesburg", "Cape Town",
    "Kinshasa", "Lusaka", "Harare", "Maputo", "Gaborone", "Windhoek", "Dar es Salaam", "Kigali", "Bamako",
    "Ouagadougou", "Niamey", "Libreville", "Yaounde", "Antananarivo", "Port Louis",
])

# A country or US state/territory spelled out in an itinerary leg is foreign evidence by itself.
_FOREIGN_WORDS = re.compile(
    r"\b(usa|u s a|united states|france|germany|italy|spain|portugal|belgium|netherlands|switzerland|austria|"
    r"sweden|norway|denmark|finland|iceland|ireland|poland|czech|hungary|romania|bulgaria|greece|ukraine|latvia|"
    r"lithuania|estonia|china|japan|korea|india|thailand|vietnam|philippines|indonesia|malaysia|australia|"
    r"new zealand|mexico|brazil|argentina|chile|peru|colombia|ecuador|cuba|jamaica|haiti|dominican|egypt|"
    r"kenya|ghana|nigeria|senegal|south africa|ethiopia|israel|jordan|lebanon|turkey|uk|united kingdom|england|"
    r"scotland|wales)\b"
)

_SPLIT = re.compile(r"\s+[-–—]\s+|\s*/\s*|\s*;\s*|\s+to\s+")


def legs(itinerary: str) -> list[str]:
    """Place names in an itinerary, in order, de-duplicated."""
    out, seen = [], set()
    for tok in _SPLIT.split(itinerary or ""):
        base = tok.split(",")[0].strip()
        if base and _norm(base) not in seen:
            seen.add(_norm(base))
            out.append(base)
    return out


def classify_itinerary(itinerary: str) -> tuple[bool | None, str]:
    """-> (is_international, basis). basis explains the call: 'foreign:<place>', 'canadian',
    'unreviewed:<place>[, ...]', or 'empty'."""
    places = legs(itinerary)
    if not places:
        return None, "empty"
    foreign, unknown = [], []
    for raw in places:
        n = _norm(raw)
        if n in AMBIGUOUS:
            unknown.append(raw + " (ambiguous)")  # exists in Canada AND abroad: never auto-classified
        elif n in FOREIGN or _FOREIGN_WORDS.search(n):
            foreign.append(raw)
        elif n in CANADIAN:
            continue
        else:
            unknown.append(raw)
    # a ", DC" / ", NY" tail on the ORIGINAL token is a US marker even when the city is unknown
    for tok in _SPLIT.split(itinerary or ""):
        tail = tok.split(",")[1:]
        if tail and re.fullmatch(r"\s*(dc|d c|ny|ca|tx|fl|wa|ma|il|va|md|pa|oh|mi|ga|az|nv|co|or|mn)\s*",
                                 " ".join(tail).lower()) and tok.split(",")[0].strip() not in foreign:
            foreign.append(tok.split(",")[0].strip())
    if foreign:
        return True, "foreign:" + ", ".join(dict.fromkeys(foreign))
    if unknown:
        return None, "unreviewed:" + ", ".join(dict.fromkeys(unknown))
    return False, "canadian"

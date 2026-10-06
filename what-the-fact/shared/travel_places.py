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


# Extended from the first real backfill (2026-10-06): the distinct places the seed lists did not know.
# Small Canadian communities (incl. First Nations) — every name below was read, not guessed; any that also
# exists abroad was moved to AMBIGUOUS instead.
CANADIAN_TOWNS = frozenset(_norm(x) for x in [
    "St-Bruno-de-Montarville",
    "Abegweit First Nation", "Abram-Village", "Afton Station", "Agassiz", "Airdrie", "Aklavik",
    "Albert Bridge", "Allenford", "Amber Valley", "Amherst Island", "Amqui", "Annapolis Royal", "Argentia",
    "Arichat", "Arnold's Cove", "Arva", "Arviat", "Athabasca", "Baddeck", "Baie-Comeau", "Baie-Sainte-Anne",
    "Banff", "Batoche", "Bay de Verde", "Bayfield", "Bear River First Nation", "Bearspaw", "Beaverton",
    "Becancour", "Bella Bella", "Binbrook", "Blackfoot Crossing", "Blackstock", "Blainville", "Blind Bay",
    "Blyth", "Bon Accord", "Bonavista", "Bouctouche", "Bridgewater", "Brochet", "Brooks Brook",
    "Burwash Landing", "Caledon", "Caledonia", "Campbellford", "Campbellton", "Canmore", "Cape Breton",
    "Cape Broyle", "Cape St. George", "Caraquet", "Carbonear", "Carcross", "Carleton-sur-Mer", "Carp",
    "Catalina", "Catalone", "Centreville", "Chapel Island", "Cheticamp", "Chignecto", "Church Point",
    "Churchill", "Clarenville", "Cobourg", "Come By Chance", "Comox", "Conne River", "Courtenay",
    "Courtright", "Cranbrook", "Creston", "Cross Lake", "Dartmouth", "Dashwood", "Deer Lake", "Deline",
    "Deux-Montagnes", "Digby", "Dollard-des-Ormeaux", "Dorchester", "Dorval", "East Preston", "Elliston",
    "Embro", "Embrun", "Enoch", "Eskasoni", "Esterhazy", "Etobicoke", "Fergus", "Fermeuse", "Fernie",
    "Fleur de Lys", "Fogo Island", "Fort Erie", "Fort McPherson", "Fort Simpson", "Fort St. John",
    "Fox Harbour", "Gimli", "Glooscap First Nation", "Goderich", "Goobies", "Goose Bay", "Grand Falls",
    "Grand Falls-Windsor", "Grand-Métis", "Grassie", "Gravenhurst", "Guysborough", "Haida Gwaii",
    "Haines Junction", "Harbour Breton", "Harbour Grace", "Harriston", "High River", "Hlgaagilda", "Holyrood",
    "Humboldt", "Ingersoll", "Innisfail", "Jasper", "Joliette", "K'uuna Llnagaay", "Kahnawake",
    "Kawartha Lakes", "Kenosee", "Kincardine", "King's Cove", "Kinmount", "Kluane National Park and Reserve",
    "Klukshu", "Kuujjuaq", "La Malbaie", "Lac Brochet", "Lake Louise", "Lakefield", "Larry's River",
    "Larrys River", "Leamington", "Lennox Island", "Les Hauteurs", "Listuguj",
    "Listuguj Mi'gmaq First Nation", "Little Harbour East", "Lockeport", "Lorraine", "Louisbourg", "Maniwaki",
    "Maple Creek", "Marystown", "Masset", "McAdam", "Membertou", "Merrickville", "Middleton", "Millarville",
    "Millbrook First Nation", "Miniku", "Mirabel", "Mont-Laurier", "Mont-Royal", "Mont-Tremblant",
    "Montebello", "Moosomin", "Mount Uniacke", "Musquodoboit Harbour", "Nahanni Butte", "Nanton",
    "Natoaganeg First Nation", "Neepawa", "Nestleton Station", "New Glasgow", "New Maryland", "New Minas",
    "Newmarket", "Norman Wells", "North Sydney", "North York", "O'Leary", "Okotoks", "Old Crow",
    "Old Massett", "Old Perlican", "Olds", "Oliver", "Ompah", "Orono", "Owen Sound", "Pain Court", "Paldi",
    "Paqtnkek First Nation", "Pasadena", "Peguis", "Pelly Farm", "Penticton", "Petawawa", "Petit-de-Grat",
    "Petrolia", "Pickering", "Pictou", "Pictou Landing First Nation", "Pitt Meadows", "Placentia",
    "Pleasant River", "Point Lance", "Pomquet", "Pond Inlet", "Port Blandford", "Port de Grave",
    "Port Hawkesbury", "Port Hood", "Port Rexton", "Port-aux-Basques", "Prince Rupert", "Pubnico",
    "Qualicum Beach", "Rama", "Renews", "Repentigny", "Richelieu", "Richmond Hill", "Ridgetown",
    "Robertville", "Rockwood", "Rogersville", "Round Hill", "Saint Andrews", "Saint-Alexis-des- Monts",
    "Saint-Eustache", "Saint-Jean-sur-Richelieu", "Saint-Lambert", "Saint-Louis-de-Kent",
    "Saint- Léonard-d'Aston", "Saint-Marc-des-Carrières", "Sainte-Anne-des-Plaines",
    "Sainte-Geneviève-de-Batiscan", "Sainte-Luce", "Salt Spring Island", "Sandspit", "Sarnia", "Scarborough",
    "Sept-Îles", "Shawinigan", "Shawiningan", "Shediac", "Shelburne", "Shubenacadie", "Siksika Nation",
    "Simcoe", "Sipekne'katik First Nation", "Smoky Lake", "Southern Harbour", "Springdale", "Springhill",
    "Squamish", "St-Bruno-de- Montarville", "St. Albert", "St. Bride's", "St. Joh'Ns", "St. Mary's",
    "St. Marys", "St. Vincent's-St. Stephen's-Peter's River", "Stoney Creek", "Terra Cotta", "Terrace",
    "Teslin", "Thamesford", "The Pas", "Thetford Mines", "Tignish", "Tiverton", "Tofino", "Tracadie",
    "Trepassey", "Trinity Bay North", "Trinity East", "Tuktoyaktuk", "Twillingate", "Ulukhaktok",
    "Unionville", "Uxbridge", "Vankleek Hill", "Vegreville", "Verner", "Vernon", "Victoriaville", "Vineland",
    "Wadena", "Waskesiu Lake", "Wasoqopa'q First Nation", "Watson Lake", "Waugh", "We'koqma'q",
    "West Montrose", "Western Shore", "Westmount", "Whistler", "Whitby", "Whitecap", "Wikwemikong",
    "Willowbrook", "Winchester", "Wolfville", "Woodville", "Yorkton", "Îles-de-la-Madeleine",

])

# Unambiguous foreign places found in real itineraries.
FOREIGN_EXTRA = frozenset(_norm(x) for x in [
    "Washington D.C.", "Washington, D.C.",
    "Baku", "Boise", "Bozeman", "Houlton", "Indianapolis", "Juno Beach", "San Juan", "Siem Reap", "Skagway",
    "Tromso", "Villers-Cotterets",

])

# Names that exist in Canada AND abroad, found in real itineraries. Resolved by a province/country TAIL when
# the itinerary gives one ("Jackson, USA", "Sydney, NS"); otherwise left unclassified.
AMBIGUOUS = AMBIGUOUS | frozenset(_norm(x) for x in [
    "Acton", "Amherst", "Aurora", "Bath", "Belfast", "Bellevue", "Borden", "Boyle", "Bradford", "Branch",
    "Chatham", "Chelsea", "Claremont", "Clinton", "Cochrane", "Dawson", "Dayton", "Delta", "Edinburg",
    "Farewell", "Gem", "Gillam", "Gray", "Greenville", "Greenwich", "Hull", "Jackson", "Legal", "Lincoln",
    "Lindsay", "Liverpool", "Louisville", "Madoc", "Mayo", "Muenster", "Newcastle", "Norwood", "Plymouth",
    "Salisbury", "Springfield", "Stratford", "Sunderland", "Trinity", "Woodstock",

])

# Itinerary legs that are not places at all (a personal stop inside a trip).
NOT_A_PLACE = frozenset({"personal"})

_CA_REGION = re.compile(
    r"^(on|qc|que|ns|nb|pe|pei|mb|sk|ab|bc|nl|nfld|yt|nt|nu|ontario|quebec|nova scotia|new brunswick|"
    r"prince edward island|manitoba|saskatchewan|alberta|british columbia|newfoundland( and labrador)?|"
    r"yukon|northwest territories|nunavut|canada)$"
)
_US_STATE = re.compile(
    r"^(al|ak|az|ar|ca|co|ct|de|dc|d c|fl|ga|hi|id|il|in|ia|ks|ky|la|me|md|ma|mi|mn|ms|mo|mt|ne|nv|nh|nj|nm|"
    r"ny|nc|nd|oh|ok|or|pa|ri|sc|sd|tn|tx|ut|vt|va|wa|wv|wi|wy|pr|gu|vi)$"
)
_FOREIGN_TAIL = re.compile(r"\b(northern ireland|normandy|kh|cambodia|azerbaijan|norway)\b")

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


def _tokens(itinerary: str) -> list[tuple[str, str]]:
    """(place, tail) per leg, in order, de-duplicated; tail is whatever followed the first comma."""
    out, seen = [], set()
    for tok in _SPLIT.split(itinerary or ""):
        base, _, tail = tok.partition(",")
        base, tail = base.strip(" -–—"), _norm(tail)
        key = (_norm(base), tail)
        if base and _norm(base) not in NOT_A_PLACE and key not in seen:
            seen.add(key)
            out.append((base, tail))
    return out


def classify_itinerary(itinerary: str) -> tuple[bool | None, str]:
    """-> (is_international, basis). basis explains the call: 'foreign:<place>', 'canadian',
    'unreviewed:<place>[, ...]', or 'empty'.

    A tail the Senate wrote after the place name is evidence about THAT leg and beats the name:
    "Jackson, USA" is foreign, "Sydney, NS" is Canadian — which is how an ambiguous name gets resolved
    without ever guessing."""
    toks = _tokens(itinerary)
    if not toks:
        return None, "empty"
    foreign, unknown = [], []
    for raw, tail in toks:
        n = _norm(raw)
        tail_words = tail.replace(",", " ")
        if tail and _CA_REGION.match(tail_words.strip()):
            continue  # an explicit Canadian province/territory
        if tail and (_US_STATE.match(tail_words.strip()) or _FOREIGN_WORDS.search(tail_words)
                     or _FOREIGN_TAIL.search(tail_words)):
            foreign.append(raw)
        elif n in AMBIGUOUS:
            unknown.append(raw + " (ambiguous)")  # exists in Canada AND abroad: never auto-classified
        elif n in FOREIGN or n in FOREIGN_EXTRA or _FOREIGN_WORDS.search(n):
            foreign.append(raw)
        elif n in CANADIAN or n in CANADIAN_TOWNS:
            continue
        else:
            unknown.append(raw)
    if foreign:
        return True, "foreign:" + ", ".join(dict.fromkeys(foreign))
    if unknown:
        return None, "unreviewed:" + ", ".join(dict.fromkeys(unknown))
    return False, "canadian"

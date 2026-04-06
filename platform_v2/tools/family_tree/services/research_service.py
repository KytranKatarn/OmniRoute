"""
Research Service — external API clients for genealogy data sources.
Supports FamilySearch, WikiTree, Chronicling America, NARA, and Europeana.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

FAMILYSEARCH_BASE = "https://api.familysearch.org"
WIKITREE_BASE = "https://api.wikitree.com/api.php"
CHRONICLING_AMERICA_BASE = "https://chroniclingamerica.loc.gov"
NARA_BASE = "https://catalog.archives.gov/api/v2"
EUROPEANA_BASE = "https://api.europeana.eu/record/v2"
REQUEST_TIMEOUT = 15


def search_familysearch(first_name, last_name, **kwargs):
    """Search FamilySearch tree via OAuth2. Returns list of person dicts."""
    token = os.getenv("FAMILYSEARCH_ACCESS_TOKEN")
    if not token:
        logger.warning("FAMILYSEARCH_ACCESS_TOKEN not set — skipping FamilySearch search")
        return []

    params = {
        "q.givenName": first_name,
        "q.surname": last_name,
    }
    if kwargs.get("birth_place"):
        params["q.birthLikePlace"] = kwargs["birth_place"]
    if kwargs.get("birth_date"):
        params["q.birthLikeDate"] = kwargs["birth_date"]
    if kwargs.get("death_date"):
        params["q.deathLikeDate"] = kwargs["death_date"]

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/x-gedcomx-v1+json",
    }

    try:
        resp = requests.get(
            f"{FAMILYSEARCH_BASE}/platform/tree/search",
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for entry in data.get("entries", []):
            content = entry.get("content", {})
            gedcomx = content.get("gedcomx", {})
            persons = gedcomx.get("persons", [])
            score = entry.get("score", 0.0)
            for person in persons:
                names = person.get("names", [])
                given = ""
                surname = ""
                for name in names:
                    for part in name.get("nameForms", [{}])[0].get("parts", []):
                        if part.get("type") == "http://gedcomx.org/Given":
                            given = part.get("value", "")
                        elif part.get("type") == "http://gedcomx.org/Surname":
                            surname = part.get("value", "")

                facts = person.get("facts", [])
                birth_date = birth_place = death_date = death_place = ""
                for fact in facts:
                    fact_type = fact.get("type", "")
                    if "Birth" in fact_type:
                        birth_date = fact.get("date", {}).get("original", "")
                        birth_place = fact.get("place", {}).get("original", "")
                    elif "Death" in fact_type:
                        death_date = fact.get("date", {}).get("original", "")
                        death_place = fact.get("place", {}).get("original", "")

                person_id = person.get("id", "")
                results.append(
                    {
                        "source": "familysearch",
                        "external_id": person_id,
                        "title": f"{given} {surname}".strip(),
                        "first_name": given,
                        "last_name": surname,
                        "birth_date": birth_date,
                        "birth_place": birth_place,
                        "death_date": death_date,
                        "death_place": death_place,
                        "score": score,
                        "url": f"https://www.familysearch.org/tree/person/details/{person_id}",
                    }
                )
        return results

    except requests.RequestException as e:
        logger.error("FamilySearch search failed: %s", e)
        return []


def search_wikitree(first_name, last_name, **kwargs):
    """Search WikiTree for persons. No auth required. Returns list of person dicts."""
    params = {
        "action": "searchPerson",
        "FirstName": first_name,
        "LastName": last_name,
        "format": "json",
    }
    if kwargs.get("birth_year"):
        params["BirthYear"] = kwargs["birth_year"]
    if kwargs.get("death_year"):
        params["DeathYear"] = kwargs["death_year"]

    try:
        resp = requests.get(
            WIKITREE_BASE,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        # WikiTree returns a list; first element is status, rest are matches
        matches = data[1:] if isinstance(data, list) and len(data) > 1 else []
        for match in matches:
            if not isinstance(match, dict):
                continue
            person = match.get("person", match)
            given = person.get("FirstName", "")
            surname = person.get("LastName", person.get("LastNameAtBirth", ""))
            person_id = str(person.get("Id", ""))
            name = person.get("Name", "")
            results.append(
                {
                    "source": "wikitree",
                    "external_id": person_id,
                    "title": f"{given} {surname}".strip() or name,
                    "first_name": given,
                    "last_name": surname,
                    "birth_date": person.get("BirthDate", ""),
                    "birth_place": person.get("BirthLocation", ""),
                    "death_date": person.get("DeathDate", ""),
                    "death_place": person.get("DeathLocation", ""),
                    "score": float(match.get("score", 0.0)),
                    "url": f"https://www.wikitree.com/wiki/{name}" if name else "",
                }
            )
        return results

    except requests.RequestException as e:
        logger.error("WikiTree search failed: %s", e)
        return []


def search_chronicling_america(query, **kwargs):
    """Search Chronicling America newspaper archive. No auth required."""
    params = {
        "andtext": query,
        "format": "json",
        "rows": kwargs.get("rows", 20),
    }
    if kwargs.get("date_from"):
        params["date1"] = kwargs["date_from"]
    if kwargs.get("date_to"):
        params["date2"] = kwargs["date_to"]
    if kwargs.get("state"):
        params["state"] = kwargs["state"]

    try:
        resp = requests.get(
            f"{CHRONICLING_AMERICA_BASE}/search/pages/results/",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("items", []):
            snippet = " ".join(item.get("ocr_eng", "").split())
            results.append(
                {
                    "source": "chronicling_america",
                    "external_id": item.get("id", ""),
                    "title": item.get("title", ""),
                    "date": item.get("date", ""),
                    "newspaper": item.get("title", ""),
                    "snippet": snippet[:500],
                    "url": f"https://chroniclingamerica.loc.gov{item.get('id', '')}",
                    "score": float(item.get("score", 0.0)),
                }
            )
        return results

    except requests.RequestException as e:
        logger.error("Chronicling America search failed: %s", e)
        return []


def search_nara(query, **kwargs):
    """Search National Archives (NARA) catalog. No auth required."""
    params = {
        "q": query,
        "rows": kwargs.get("rows", 20),
        "offset": kwargs.get("offset", 0),
    }
    if kwargs.get("record_type"):
        params["levelOfDescription"] = kwargs["record_type"]

    try:
        resp = requests.get(
            f"{NARA_BASE}/search",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("body", {}).get("hits", {}).get("hits", []):
            source = item.get("_source", {})
            description = source.get("scopeAndContentNote", source.get("description", ""))
            if isinstance(description, list):
                description = " ".join(description)
            results.append(
                {
                    "source": "nara",
                    "external_id": str(source.get("naId", item.get("_id", ""))),
                    "title": source.get("title", ""),
                    "description": str(description)[:500],
                    "date": (
                        source.get("coverageDates", {}).get("coverageStartDate", "")
                        if isinstance(source.get("coverageDates"), dict)
                        else ""
                    ),
                    "url": f"https://catalog.archives.gov/id/{source.get('naId', '')}",
                    "score": float(item.get("_score", 0.0)),
                }
            )
        return results

    except requests.RequestException as e:
        logger.error("NARA search failed: %s", e)
        return []


def search_europeana(query, **kwargs):
    """Search Europeana cultural heritage records. Requires EUROPEANA_API_KEY."""
    api_key = os.getenv("EUROPEANA_API_KEY")
    if not api_key:
        logger.warning("EUROPEANA_API_KEY not set — skipping Europeana search")
        return []

    params = {
        "wskey": api_key,
        "query": query,
        "rows": kwargs.get("rows", 20),
        "profile": "rich",
    }
    if kwargs.get("country"):
        params["qf"] = f"COUNTRY:{kwargs['country']}"

    try:
        resp = requests.get(
            f"{EUROPEANA_BASE}/search.json",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("items", []):
            title_val = item.get("title", [""])
            title = title_val[0] if isinstance(title_val, list) else title_val

            desc_val = item.get("dcDescription", item.get("description", [""]))
            description = desc_val[0] if isinstance(desc_val, list) else desc_val

            date_val = item.get("year", item.get("edmTimespanLabel", [""]))
            date = date_val[0] if isinstance(date_val, list) else date_val

            thumbnail_val = item.get("edmPreview", [""])
            thumbnail = thumbnail_val[0] if isinstance(thumbnail_val, list) else thumbnail_val

            results.append(
                {
                    "source": "europeana",
                    "external_id": item.get("id", ""),
                    "title": title,
                    "description": str(description)[:500],
                    "date": str(date),
                    "url": item.get("guid", ""),
                    "thumbnail": thumbnail,
                    "score": float(item.get("score", 0.0)),
                }
            )
        return results

    except requests.RequestException as e:
        logger.error("Europeana search failed: %s", e)
        return []


def search_all_sources(first_name, last_name, **kwargs):
    """
    Search all 5 genealogy sources and return combined results sorted by score.

    Genealogy-specific sources (FamilySearch, WikiTree) receive first_name + last_name.
    Archive/newspaper sources receive the full name as a query string.
    Europeana auto-detects country from birth_place (portugal/france).
    """
    full_name = f"{first_name} {last_name}".strip()

    # Auto-detect country for Europeana from birth_place
    europeana_kwargs = dict(kwargs)
    birth_place = kwargs.get("birth_place", "").lower()
    if "portugal" in birth_place:
        europeana_kwargs.setdefault("country", "portugal")
    elif "france" in birth_place:
        europeana_kwargs.setdefault("country", "france")

    fs_results = search_familysearch(first_name, last_name, **kwargs)
    wt_results = search_wikitree(first_name, last_name, **kwargs)
    ca_results = search_chronicling_america(full_name, **kwargs)
    nara_results = search_nara(full_name, **kwargs)
    eu_results = search_europeana(full_name, **europeana_kwargs)

    combined = fs_results + wt_results + ca_results + nara_results + eu_results
    combined.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    return combined

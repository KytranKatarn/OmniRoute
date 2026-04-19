"""
Research Service — external API clients for genealogy data sources.
Supports FamilySearch, WikiTree, Chronicling America, NARA, Europeana,
DPLA, Internet Archive, and Library of Congress.
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
DPLA_BASE = "https://api.dp.la/v2"
INTERNET_ARCHIVE_BASE = "https://archive.org/advancedsearch.php"
LOC_BASE = "https://www.loc.gov"
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


def generate_life_story(person_data, relationships, events):
    """
    Use Bridge dispatch to have H.E.R.I.T.A.G.E. generate a narrative biography
    for a person based on their data, relationships, and life events.

    Args:
        person_data: Dict with keys like first_name, last_name, birth_date,
                     birth_place, death_date, death_place, gender, notes.
        relationships: List of dicts with relationship_type and connected person info.
        events: List of dicts with event details (marriages, migrations, etc.).

    Returns:
        str: Generated narrative biography, or error string on failure.
    """
    try:
        from bridge_dispatcher import dispatch

        full_name = (
            f"{person_data.get('first_name', '')} {person_data.get('last_name', '')}".strip() or "Unknown person"
        )

        # Build life details section
        details = []
        if person_data.get("birth_date"):
            birth_line = f"Born: {person_data['birth_date']}"
            if person_data.get("birth_place"):
                birth_line += f" in {person_data['birth_place']}"
            details.append(birth_line)
        if person_data.get("death_date"):
            death_line = f"Died: {person_data['death_date']}"
            if person_data.get("death_place"):
                death_line += f" in {person_data['death_place']}"
            details.append(death_line)
        if person_data.get("gender"):
            details.append(f"Gender: {person_data['gender']}")

        # Detect migration path
        birth_place = person_data.get("birth_place", "")
        death_place = person_data.get("death_place", "")
        if birth_place and death_place and birth_place.lower() != death_place.lower():
            details.append(f"Migration: from {birth_place} to {death_place}")

        # Build relationships section
        rel_lines = []
        for rel in relationships:
            rel_type = rel.get("relationship_type", "related")
            other_name = rel.get("person_name", "unknown")
            rel_lines.append(f"- {rel_type}: {other_name}")

        # Build events section
        event_lines = []
        for evt in events:
            evt_type = evt.get("event_type", "event")
            evt_date = evt.get("date", "")
            evt_place = evt.get("place", "")
            evt_line = f"- {evt_type}"
            if evt_date:
                evt_line += f" ({evt_date})"
            if evt_place:
                evt_line += f" in {evt_place}"
            event_lines.append(evt_line)

        prompt_parts = [f"Write a narrative biography for {full_name}."]
        if details:
            prompt_parts.append("LIFE DETAILS:\n" + "\n".join(details))
        if rel_lines:
            prompt_parts.append("RELATIONSHIPS:\n" + "\n".join(rel_lines))
        if event_lines:
            prompt_parts.append("LIFE EVENTS:\n" + "\n".join(event_lines))
        if person_data.get("notes"):
            prompt_parts.append(f"ADDITIONAL NOTES:\n{person_data['notes']}")

        prompt_parts.append(
            "\nWrite 2-3 paragraphs suitable for a family history book. "
            "Be warm and respectful. Where facts are sparse, acknowledge gaps "
            "gracefully rather than inventing details."
        )

        prompt = "\n\n".join(prompt_parts)

        system_prompt = (
            "You are H.E.R.I.T.A.G.E., an AI genealogy storyteller specializing "
            "in turning raw genealogical data into compelling, respectful narrative "
            "biographies. You write in a warm, literary style suitable for family "
            "history books. You never invent facts but you weave known details into "
            "a vivid portrait of a person's life and times."
        )

        result = dispatch(
            prompt=prompt,
            capability="text_analysis",
            agent_name="H.E.R.I.T.A.G.E.",
            system_prompt=system_prompt,
            temperature=0.7,
        )

        if not result.success:
            logger.error("Bridge dispatch failed for generate_life_story: %s", result.response)
            return f"Story generation failed: {result.response}"

        return result.response.strip()

    except Exception as e:
        logger.error("generate_life_story failed: %s", e)
        return f"Error generating story: {e}"


def search_dpla(query, **kwargs):
    """Search Digital Public Library of America for historical records. Requires DPLA_API_KEY."""
    api_key = os.getenv("DPLA_API_KEY")
    if not api_key:
        logger.warning("DPLA_API_KEY not set — skipping DPLA search")
        return []

    params = {
        "q": query,
        "api_key": api_key,
        "page_size": kwargs.get("rows", 20),
    }
    if kwargs.get("date_from"):
        params["sourceResource.date.after"] = kwargs["date_from"]
    if kwargs.get("date_to"):
        params["sourceResource.date.before"] = kwargs["date_to"]
    if kwargs.get("state"):
        params["sourceResource.spatial.state"] = kwargs["state"]

    try:
        resp = requests.get(
            f"{DPLA_BASE}/items",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("docs", []):
            source_resource = item.get("sourceResource", {})

            title_val = source_resource.get("title", [""])
            title = title_val[0] if isinstance(title_val, list) else title_val

            desc_val = source_resource.get("description", [""])
            description = desc_val[0] if isinstance(desc_val, list) else desc_val

            date_val = source_resource.get("date", [{}])
            date_obj = date_val[0] if isinstance(date_val, list) else date_val
            date = date_obj.get("displayDate", "") if isinstance(date_obj, dict) else str(date_obj)

            item_url = item.get("isShownAt", "")

            results.append(
                {
                    "source": "dpla",
                    "external_id": item.get("id", ""),
                    "title": title,
                    "description": str(description)[:500],
                    "date": date,
                    "url": item_url,
                    "score": float(item.get("score", 0.0)),
                }
            )
        return results

    except requests.RequestException as e:
        logger.error("DPLA search failed: %s", e)
        return []


def search_internet_archive(query, **kwargs):
    """Search Internet Archive for digitised historical records. No auth required."""
    params = {
        "q": query,
        "fl[]": ["identifier", "title", "description", "date", "mediatype", "collection"],
        "rows": kwargs.get("rows", 20),
        "output": "json",
    }
    if kwargs.get("mediatype"):
        params["q"] += f" AND mediatype:{kwargs['mediatype']}"
    if kwargs.get("collection"):
        params["q"] += f" AND collection:{kwargs['collection']}"

    try:
        resp = requests.get(
            INTERNET_ARCHIVE_BASE,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for doc in data.get("response", {}).get("docs", []):
            identifier = doc.get("identifier", "")
            description = doc.get("description", "")
            if isinstance(description, list):
                description = " ".join(description)

            results.append(
                {
                    "source": "internet_archive",
                    "external_id": identifier,
                    "title": doc.get("title", ""),
                    "description": str(description)[:500],
                    "date": doc.get("date", ""),
                    "mediatype": doc.get("mediatype", ""),
                    "url": f"https://archive.org/details/{identifier}",
                    "score": 0.0,
                }
            )
        return results

    except requests.RequestException as e:
        logger.error("Internet Archive search failed: %s", e)
        return []


def search_library_of_congress(query, **kwargs):
    """Search Library of Congress digital collections. No auth required."""
    params = {
        "q": query,
        "fo": "json",
        "c": kwargs.get("rows", 20),
    }
    if kwargs.get("date_from"):
        params["dates"] = f"{kwargs['date_from']}/{kwargs.get('date_to', '')}"
    if kwargs.get("subject"):
        params["fa"] = f"subject:{kwargs['subject']}"

    try:
        resp = requests.get(
            f"{LOC_BASE}/search/",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results_list = data.get("results", [])

        results = []
        for item in results_list:
            if not isinstance(item, dict):
                continue

            title = item.get("title", "")
            description_val = item.get("description", item.get("notes", [""]))
            if isinstance(description_val, list):
                description = " ".join(str(d) for d in description_val[:3])
            else:
                description = str(description_val)

            date_val = item.get("date", "")
            if isinstance(date_val, list):
                date = date_val[0] if date_val else ""
            else:
                date = str(date_val)

            item_url = item.get("url", item.get("id", ""))

            results.append(
                {
                    "source": "library_of_congress",
                    "external_id": item.get("id", ""),
                    "title": title,
                    "description": str(description)[:500],
                    "date": date,
                    "url": item_url,
                    "score": 0.0,
                }
            )
        return results

    except requests.RequestException as e:
        logger.error("Library of Congress search failed: %s", e)
        return []


def analyze_research_results(results, person_context):
    """
    Use Bridge dispatch to have S.C.R.O.L.L. analyze and rank combined
    search results with AI, providing relevance scoring and insights.

    Args:
        results: List of result dicts from search_all_sources().
        person_context: Dict with keys like first_name, last_name, birth_date,
                        birth_place, etc. describing the person being researched.

    Returns:
        Dict with 'ranked_results' (list) and 'summary' (str), or error dict.
    """
    if not results:
        return {"ranked_results": [], "summary": "No results to analyze."}

    try:
        from bridge_dispatcher import dispatch
        import json as _json

        person_desc = (
            f"{person_context.get('first_name', '')} {person_context.get('last_name', '')}".strip() or "Unknown person"
        )
        extra_parts = []
        if person_context.get("birth_date"):
            extra_parts.append(f"born {person_context['birth_date']}")
        if person_context.get("birth_place"):
            extra_parts.append(f"in {person_context['birth_place']}")
        if extra_parts:
            person_desc += f" ({', '.join(extra_parts)})"

        # Trim results to avoid oversized prompts
        trimmed = results[:50]

        system_prompt = (
            "You are S.C.R.O.L.L., an expert genealogy research analyst. "
            "Analyze search results from multiple sources, assess relevance to "
            "the target person, identify duplicates across sources, and provide "
            "a ranked summary. Always respond with valid JSON only."
        )

        prompt = (
            f"Analyze these genealogy search results for: {person_desc}\n\n"
            f"RESULTS ({len(trimmed)} of {len(results)}):\n"
            f"{_json.dumps(trimmed, default=str)}\n\n"
            "Return a JSON object with:\n"
            '- "ranked_results": list of objects with: source, external_id, '
            "title, relevance_score (0.0-1.0), reasoning (short string), "
            "is_likely_match (bool)\n"
            '- "duplicates": list of lists grouping external_ids that refer '
            "to the same person across sources\n"
            '- "summary": 2-3 sentence overview of the findings\n\n'
            "Respond with JSON only."
        )

        result = dispatch(
            prompt=prompt,
            capability="text_analysis",
            agent_name="S.C.R.O.L.L.",
            system_prompt=system_prompt,
            temperature=0.1,
        )

        if not result.success:
            logger.error("Bridge dispatch failed for analyze_research_results: %s", result.response)
            return {"ranked_results": [], "summary": f"Analysis failed: {result.response}"}

        import re

        response_text = result.response.strip()
        response_text = re.sub(r"^```(?:json)?\s*", "", response_text)
        response_text = re.sub(r"\s*```$", "", response_text)
        response_text = response_text.strip()

        return _json.loads(response_text)

    except (ValueError, KeyError) as e:
        logger.error("Failed to parse analysis response: %s", e)
        return {"ranked_results": [], "summary": f"Parse error: {e}"}
    except Exception as e:
        logger.error("analyze_research_results failed: %s", e)
        return {"ranked_results": [], "summary": f"Error: {e}"}


def search_all_sources(first_name, last_name, **kwargs):
    """
    Search all 8 genealogy sources and return combined results sorted by score.

    Genealogy-specific sources (FamilySearch, WikiTree) receive first_name + last_name.
    Archive/newspaper sources receive the full name as a query string.
    Europeana auto-detects country from birth_place (portugal/france).
    DPLA, Internet Archive, and Library of Congress receive the full name query.
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
    dpla_results = search_dpla(full_name, **kwargs)
    ia_results = search_internet_archive(full_name, **kwargs)
    loc_results = search_library_of_congress(full_name, **kwargs)

    combined = (
        fs_results + wt_results + ca_results + nara_results + eu_results + dpla_results + ia_results + loc_results
    )
    combined.sort(key=lambda r: r.get("score", 0.0), reverse=True)
    return combined

"""
HTML -> dicts for each GEDS-SAGE page type.

Built on BeautifulSoup4 (selectolax not available in this container).
Selectors are intentionally loose to survive minor template tweaks; if a
structural change happens, parse failures show up immediately as empty-list
returns + the raw page is preserved 7 days (civic_transparency.geds_raw_pages)
so re-parse without re-crawl is possible.
"""

from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup


def _qs(url: str) -> Dict[str, str]:
    """Extract query-string params from a URL or relative href."""
    q = parse_qs(urlparse(url).query)
    return {k: v[0] for k, v in q.items()}


# ---------------------------------------------------------------------------
# 1. Department list  (?pgid=012)
# ---------------------------------------------------------------------------


def parse_department_list(html: str) -> List[Dict[str, str]]:
    """
    Extract all department entries from the GEDS master listing page (?pgid=012).

    Returns:
        List of {"dn_b64": str, "name": str}
    """
    out: List[Dict[str, str]] = []
    soup = BeautifulSoup(html, "html.parser")
    seen: set = set()

    for a in soup.find_all("a", href=lambda h: h and "pgid=014" in h):
        href = a.get("href", "")
        params = _qs(href)
        dn_b64 = params.get("dn")
        name = (a.get_text(separator=" ", strip=True) or "").strip()
        # Skip nav/language toggle links (no meaningful name or duplicate dn)
        if not dn_b64 or not name:
            continue
        if dn_b64 in seen:
            continue
        seen.add(dn_b64)
        out.append({"dn_b64": dn_b64, "name": name})

    return out


# ---------------------------------------------------------------------------
# 2. Tree node  (?pgid=014&dn=...)
# ---------------------------------------------------------------------------

# Nav links that appear on every page — skip them by name
_NAV_SKIP_NAMES = {"français", "english", "skip to main content", "skip to side navigation"}


def parse_tree_node(html: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Org tree page (?pgid=014). Returns children (sub-OUs) and people (entries).

    Returns:
        {
          "children": [{"dn_b64": str, "name": str}, ...],
          "people":   [{"source_dn_b64": str, "surname": str, "given_name": str|None,
                        "title_en": str|None, "phone": str|None, "email": str|None,
                        "location_en": str|None, "manager_dn_b64": str|None,
                        "classification": str|None}, ...]
        }
    """
    soup = BeautifulSoup(html, "html.parser")
    children: List[Dict[str, str]] = []
    people: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Children: pgid=014 links (sub-organisational units)
    # Exclude nav-bar / language-toggle links by filtering on name.
    # ------------------------------------------------------------------
    seen_children: set = set()
    for a in soup.find_all("a", href=lambda h: h and "pgid=014" in h):
        href = a.get("href", "")
        params = _qs(href)
        dn_b64 = params.get("dn")
        name = (a.get_text(separator=" ", strip=True) or "").strip()
        if not dn_b64 or not name:
            continue
        if name.lower() in _NAV_SKIP_NAMES:
            continue
        if dn_b64 in seen_children:
            continue
        seen_children.add(dn_b64)
        children.append({"dn_b64": dn_b64, "name": name})

    # ------------------------------------------------------------------
    # People: pgid=015 links (individual profile pages)
    # Each person link sits inside a card-like container (li, div, tr, etc.)
    # We walk up to find it and extract metadata from surrounding text/dts.
    # ------------------------------------------------------------------
    seen_persons: set = set()
    for a in soup.find_all("a", href=lambda h: h and "pgid=015" in h):
        href = a.get("href", "")
        params = _qs(href)
        person_dn = params.get("dn")
        if not person_dn or person_dn in seen_persons:
            continue
        seen_persons.add(person_dn)

        # Walk up to nearest card container
        card = a.parent
        for _ in range(6):
            if card is None:
                break
            if card.name in ("li", "div", "tr", "td", "article", "section"):
                break
            card = card.parent

        record: Dict[str, Any] = {
            "source_dn_b64": person_dn,
            "surname": "",
            "given_name": None,
            "title_en": None,
            "phone": None,
            "email": None,
            "location_en": None,
            "manager_dn_b64": None,
            "classification": None,
        }

        # Name comes from the link text: "Surname, Given" or "Given Surname"
        full = (a.get_text(separator=" ", strip=True) or "").strip()
        if "," in full:
            sn, gn = full.split(",", 1)
            record["surname"] = sn.strip()
            record["given_name"] = gn.strip()
        elif full:
            record["surname"] = full

        if card is not None:
            card_text = card.get_text(separator=" ", strip=True)

            # Email — simple token scan
            for tok in card_text.split():
                tok_c = tok.strip(",;()")
                if "@" in tok_c and "." in tok_c:
                    record["email"] = tok_c
                    break

            # Structured fields via <dt>/<dd>
            for dt in card.find_all("dt"):
                label = dt.get_text(strip=True).lower()
                dd = dt.find_next_sibling("dd")
                if dd is None:
                    continue
                value = dd.get_text(separator=" ", strip=True) or None

                if "title" in label and not record["title_en"]:
                    record["title_en"] = value
                elif "class" in label:
                    record["classification"] = value
                elif "manager" in label or "supervisor" in label:
                    mgr_a = dd.find("a", href=lambda h: h and "dn=" in h)
                    if mgr_a:
                        record["manager_dn_b64"] = _qs(mgr_a.get("href", "")).get("dn")
                elif "address" in label or "location" in label:
                    record["location_en"] = value

        people.append(record)

    return {"children": children, "people": people}


# ---------------------------------------------------------------------------
# 3. Quick list  (?pgid=016&fid=...)
# ---------------------------------------------------------------------------


def parse_quick_list(html: str) -> List[Dict[str, Any]]:
    """
    pgid=016 quick lists (Ministers, DMs, Senators, MP Offices).

    Each <li> has the shape:
        <a pgid=015>Surname, Given</a>; phone; <a pgid=014>DEPT</a>;
        Title text; <a pgid=014>OU</a>

    Returns rows with surname/given_name/title_en/phone/source_dn_b64.
    role_tag is set to None — caller fills it from the fid param used.
    """
    out: List[Dict[str, Any]] = []
    soup = BeautifulSoup(html, "html.parser")
    seen: set = set()

    for a in soup.find_all("a", href=lambda h: h and "pgid=015" in h):
        href = a.get("href", "")
        dn = _qs(href).get("dn")
        if not dn or dn in seen:
            continue
        seen.add(dn)

        full = (a.get_text(separator=" ", strip=True) or "").strip()
        surname, given = full, None
        if "," in full:
            sn, gn = full.split(",", 1)
            surname, given = sn.strip(), gn.strip()

        # Title: scan NavigableStrings in the parent <li> for the title phrase.
        # In real GEDS HTML the pattern is:
        #   DEPT_LINK ; \n Title text; \n OU_LINK
        # We collect all bare text segments (NavigableStrings) that are not
        # empty and not just punctuation/phone numbers.
        title = None
        phone = None
        li = a.parent  # usually <li>
        if li is not None:
            for child in li.children:
                from bs4 import NavigableString

                if not isinstance(child, NavigableString):
                    continue
                txt = child.strip().strip(";").strip()
                if not txt:
                    continue
                # Phone: all digits + hyphens, 10–13 chars
                if all(c in "0123456789-+ " for c in txt) and len(txt) >= 8:
                    phone = txt.strip()
                elif txt:
                    # First meaningful text block after DEPT link → title
                    # (skip short tokens like single letters)
                    if len(txt) > 3 and title is None:
                        title = txt

        out.append(
            {
                "source_dn_b64": dn,
                "surname": surname,
                "given_name": given,
                "title_en": title,
                "phone": phone,
                "role_tag": None,
            }
        )

    return out

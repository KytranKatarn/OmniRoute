"""
GEDCOM 5.5.1 import/export service for the Family Tree module.
Requires: ged4py (pip install ged4py) — installed via Dockerfile rebuild.
"""

import io
import logging
import datetime
from datetime import timezone

logger = logging.getLogger(__name__)

# Tree service imports — available once tree_service.py is created (Task 1/2)
from .tree_service import (
    create_person,
    add_relationship,
    add_source,
    link_source_to_person,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def import_gedcom(user_id: int, file_content: bytes) -> dict:
    """
    Parse a GEDCOM 5.5.1 file and persist its data for *user_id*.

    Returns a stats dict::

        {
            "persons_created": int,
            "relationships_created": int,
            "errors": [str, ...],
        }
    """
    from ged4py.parser import GedcomReader  # deferred — not installed until rebuild

    stats = {"persons_created": 0, "relationships_created": 0, "errors": []}

    # Add a source record for this import
    try:
        source_id = add_source(
            user_id=user_id,
            title="GEDCOM Import",
            description=f"Imported via GEDCOM file on {datetime.date.today().isoformat()}",
        )
    except Exception as exc:
        logger.warning("Could not create source record: %s", exc)
        source_id = None

    reader = GedcomReader(io.BytesIO(file_content))

    # ------------------------------------------------------------------
    # Pass 1 — individuals
    # ------------------------------------------------------------------
    indi_map: dict[str, int] = {}  # GEDCOM xref_id  →  our person_id

    for record in reader.records0("INDI"):
        try:
            xref_id: str = record.xref_id

            # --- Name ---
            first_name = ""
            last_name = ""
            name_tag = record.sub_tag("NAME")
            if name_tag is not None:
                raw = name_tag.value or ""
                # GEDCOM NAME value: "Given /Surname/"
                parts = raw.split("/")
                first_name = parts[0].strip() if len(parts) >= 1 else ""
                last_name = parts[1].strip() if len(parts) >= 2 else ""

            # --- Gender ---
            gender = None
            sex_tag = record.sub_tag("SEX")
            if sex_tag is not None:
                raw_sex = (sex_tag.value or "").strip().upper()
                if raw_sex == "M":
                    gender = "male"
                elif raw_sex == "F":
                    gender = "female"
                else:
                    gender = "other"

            # --- Birth ---
            birth_date = None
            birth_place = None
            birt_tag = record.sub_tag("BIRT")
            if birt_tag is not None:
                date_tag = birt_tag.sub_tag("DATE")
                if date_tag is not None:
                    birth_date = _parse_gedcom_date(date_tag.value or "")
                plac_tag = birt_tag.sub_tag("PLAC")
                if plac_tag is not None:
                    birth_place = (plac_tag.value or "").strip() or None

            # --- Death ---
            death_date = None
            death_place = None
            deat_tag = record.sub_tag("DEAT")
            if deat_tag is not None:
                date_tag = deat_tag.sub_tag("DATE")
                if date_tag is not None:
                    death_date = _parse_gedcom_date(date_tag.value or "")
                plac_tag = deat_tag.sub_tag("PLAC")
                if plac_tag is not None:
                    death_place = (plac_tag.value or "").strip() or None

            person_result = create_person(
                user_id=user_id,
                first_name=first_name,
                last_name=last_name,
                gender=gender,
                birth_date=birth_date,
                birth_place=birth_place,
                death_date=death_date,
                death_place=death_place,
            )

            # create_person may return a dict or an int ID
            person_id = person_result["id"] if isinstance(person_result, dict) else person_result
            indi_map[xref_id] = person_id
            stats["persons_created"] += 1

            # Link to source
            if source_id is not None:
                try:
                    link_source_to_person(
                        user_id=user_id,
                        person_id=person_id,
                        source_id=source_id,
                    )
                except Exception as link_exc:
                    logger.debug("Could not link source to person %s: %s", person_id, link_exc)

        except Exception as exc:
            msg = f"Error processing INDI {getattr(record, 'xref_id', '?')}: {exc}"
            logger.warning(msg)
            stats["errors"].append(msg)

    # ------------------------------------------------------------------
    # Pass 2 — families (spouse + parent→child relationships)
    # ------------------------------------------------------------------
    for record in reader.records0("FAM"):
        try:
            husb_id: int | None = None
            wife_id: int | None = None

            husb_tag = record.sub_tag("HUSB")
            if husb_tag is not None:
                husb_xref = (husb_tag.value or "").strip()
                husb_id = indi_map.get(husb_xref)

            wife_tag = record.sub_tag("WIFE")
            if wife_tag is not None:
                wife_xref = (wife_tag.value or "").strip()
                wife_id = indi_map.get(wife_xref)

            # Spouse relationship
            if husb_id is not None and wife_id is not None:
                try:
                    add_relationship(
                        user_id=user_id,
                        person1_id=husb_id,
                        person2_id=wife_id,
                        relationship_type="spouse",
                    )
                    stats["relationships_created"] += 1
                except Exception as exc:
                    msg = f"Error creating spouse relationship ({husb_id}↔{wife_id}): {exc}"
                    logger.warning(msg)
                    stats["errors"].append(msg)

            # Parent → child relationships
            for chil_tag in record.sub_tags("CHIL"):
                chil_xref = (chil_tag.value or "").strip()
                chil_id = indi_map.get(chil_xref)
                if chil_id is None:
                    continue

                for parent_id in filter(None, [husb_id, wife_id]):
                    try:
                        add_relationship(
                            user_id=user_id,
                            person1_id=parent_id,
                            person2_id=chil_id,
                            relationship_type="parent_child",
                        )
                        stats["relationships_created"] += 1
                    except Exception as exc:
                        msg = f"Error creating parent_child relationship " f"({parent_id}→{chil_id}): {exc}"
                        logger.warning(msg)
                        stats["errors"].append(msg)

        except Exception as exc:
            msg = f"Error processing FAM {getattr(record, 'xref_id', '?')}: {exc}"
            logger.warning(msg)
            stats["errors"].append(msg)

    logger.info(
        "GEDCOM import complete — persons: %d, relationships: %d, errors: %d",
        stats["persons_created"],
        stats["relationships_created"],
        len(stats["errors"]),
    )
    return stats


def export_gedcom(user_id: int, persons: list[dict], relationships: list[dict]) -> str:
    """
    Generate a GEDCOM 5.5.1 string from the supplied persons and relationships.

    *persons* — list of person dicts (id, first_name, last_name, gender,
                birth_date, birth_place, death_date, death_place)
    *relationships* — list of relationship dicts (person1_id, person2_id,
                      relationship_type)

    Returns the GEDCOM file content as a string.
    """
    lines: list[str] = []

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    now = datetime.datetime.now(timezone.utc)
    lines += [
        "0 HEAD",
        "1 SOUR ARCHIE-FAMILY-TREE",
        "2 VERS 1.0",
        "1 GEDC",
        "2 VERS 5.5.1",
        "2 FORM LINEAGE-LINKED",
        "1 CHAR UTF-8",
        f"1 DATE {_format_gedcom_date(now.date())}",
    ]

    # ------------------------------------------------------------------
    # Build xref map: person_id → @I{n}@
    # ------------------------------------------------------------------
    person_xref: dict[int, str] = {}
    for i, person in enumerate(persons, start=1):
        person_xref[person["id"]] = f"@I{i}@"

    # ------------------------------------------------------------------
    # INDI records
    # ------------------------------------------------------------------
    for person in persons:
        xref = person_xref[person["id"]]
        first = (person.get("first_name") or "").strip()
        last = (person.get("last_name") or "").strip()
        name_val = f"{first} /{last}/" if last else first

        lines.append(f"0 {xref} INDI")
        if name_val.strip():
            lines.append(f"1 NAME {name_val}")

        gender = (person.get("gender") or "").lower()
        if gender == "male":
            lines.append("1 SEX M")
        elif gender == "female":
            lines.append("1 SEX F")
        elif gender:
            lines.append("1 SEX U")

        birth_date = person.get("birth_date")
        birth_place = person.get("birth_place")
        if birth_date or birth_place:
            lines.append("1 BIRT")
            if birth_date:
                lines.append(f"2 DATE {_format_gedcom_date(birth_date)}")
            if birth_place:
                lines.append(f"2 PLAC {birth_place}")

        death_date = person.get("death_date")
        death_place = person.get("death_place")
        if death_date or death_place:
            lines.append("1 DEAT")
            if death_date:
                lines.append(f"2 DATE {_format_gedcom_date(death_date)}")
            if death_place:
                lines.append(f"2 PLAC {death_place}")

    # ------------------------------------------------------------------
    # FAM records
    # ------------------------------------------------------------------
    families = _build_families(relationships, person_xref)
    for fam_idx, fam in enumerate(families, start=1):
        fam_xref = f"@F{fam_idx}@"
        lines.append(f"0 {fam_xref} FAM")
        if fam.get("husb"):
            lines.append(f"1 HUSB {fam['husb']}")
        if fam.get("wife"):
            lines.append(f"1 WIFE {fam['wife']}")
        for child_xref in fam.get("children", []):
            lines.append(f"1 CHIL {child_xref}")

    # ------------------------------------------------------------------
    # Trailer
    # ------------------------------------------------------------------
    lines.append("0 TRLR")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

_GEDCOM_QUALIFIERS = {"ABT", "BEF", "AFT", "CAL", "EST", "INT", "FROM", "TO", "BET", "AND"}
_DATE_FORMATS = ["%d %b %Y", "%b %Y", "%Y"]


def _parse_gedcom_date(date_str: str) -> datetime.date | None:
    """
    Strip GEDCOM date qualifiers and parse to a Python date.
    Returns None if the string cannot be parsed.
    """
    if not date_str:
        return None

    tokens = date_str.strip().upper().split()
    # Remove leading qualifiers
    while tokens and tokens[0] in _GEDCOM_QUALIFIERS:
        tokens.pop(0)

    clean = " ".join(tokens)
    if not clean:
        return None

    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.datetime.strptime(clean, fmt)
            # For year-only or month-year, default to Jan 1
            return parsed.date()
        except ValueError:
            continue

    logger.debug("Could not parse GEDCOM date: %r", date_str)
    return None


def _format_gedcom_date(date_val) -> str:
    """
    Format a date value to GEDCOM 'DD MMM YYYY' uppercase string.
    Accepts datetime.date, datetime.datetime, or an ISO string.
    """
    if date_val is None:
        return ""

    if isinstance(date_val, str):
        # Try ISO format first
        try:
            date_val = datetime.date.fromisoformat(date_val[:10])
        except ValueError:
            return date_val.upper()

    if isinstance(date_val, (datetime.date, datetime.datetime)):
        return date_val.strftime("%d %b %Y").upper()

    return str(date_val).upper()


def _build_families(relationships: list[dict], person_xref: dict[int, str]) -> list[dict]:
    """
    Group relationships into FAM records suitable for GEDCOM export.

    Spouse pairs form the FAM nucleus; parent_child links attach CHIL tags.
    Single-parent families (no spouse record) are created as needed.

    Returns a list of family dicts::

        {"husb": xref|None, "wife": xref|None, "children": [xref, ...]}
    """
    # fam_key → family dict.  Key is frozenset of parent xrefs (1 or 2 members).
    families: dict[frozenset, dict] = {}

    spouse_pairs: list[tuple[int, int]] = []

    for rel in relationships:
        p1 = rel.get("person1_id")
        p2 = rel.get("person2_id")
        rel_type = (rel.get("relationship_type") or "").lower()

        if rel_type == "spouse":
            spouse_pairs.append((p1, p2))
            key = frozenset([p1, p2])
            if key not in families:
                x1 = person_xref.get(p1)
                x2 = person_xref.get(p2)
                families[key] = {"husb": x1, "wife": x2, "children": []}

    for rel in relationships:
        p1 = rel.get("person1_id")
        p2 = rel.get("person2_id")
        rel_type = (rel.get("relationship_type") or "").lower()

        if rel_type == "parent_child":
            parent_id = p1
            child_id = p2
            child_xref = person_xref.get(child_id)
            if child_xref is None:
                continue

            # Find an existing family where parent_id is husb or wife
            matched_key = None
            for key, fam in families.items():
                husb_xref = fam.get("husb")
                wife_xref = fam.get("wife")
                parent_xref = person_xref.get(parent_id)
                if parent_xref in (husb_xref, wife_xref):
                    matched_key = key
                    break

            if matched_key is not None:
                if child_xref not in families[matched_key]["children"]:
                    families[matched_key]["children"].append(child_xref)
            else:
                # Single-parent family
                parent_xref = person_xref.get(parent_id)
                key = frozenset([parent_id])
                if key not in families:
                    families[key] = {"husb": parent_xref, "wife": None, "children": []}
                if child_xref not in families[key]["children"]:
                    families[key]["children"].append(child_xref)

    return list(families.values())

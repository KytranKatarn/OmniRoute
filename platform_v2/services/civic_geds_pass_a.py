"""
Pass A: walk the GEDS organization tree, persist org_units rows.

Reads pgid=012 for the dept list, then recursively walks pgid=014&dn=...
to depth `max_depth`. Each node is upserted via OrgUnitWriter. Writer
abstracts the DB so tests can swap a fake.
"""

import logging
import re
from typing import Optional, Set

from services.civic_geds_client import GedsClient, GedsFetchError
from services.civic_geds_dn import DnParseError, decode_dn, parse_dn
from services.civic_geds_parsers import parse_department_list, parse_tree_node

log = logging.getLogger(__name__)


def _abbreviation(dn_decoded: str) -> Optional[str]:
    """Innermost OU value, e.g. 'CSIS-SCRS' from 'OU=CSIS-SCRS,O=GC,C=CA'."""
    try:
        parsed = parse_dn(dn_decoded)
        ous = parsed["OU"]
        # Innermost = FIRST in the OU list (leftmost component = the org's own acronym).
        return ous[0] if ous else None
    except DnParseError:
        return None


def _split_abbr(abbr: Optional[str]):
    """'CSIS-SCRS' -> ('CSIS', 'SCRS'). 'TBS' -> ('TBS', None)."""
    if not abbr:
        return None, None
    parts = re.split(r"[-/]", abbr, maxsplit=1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return abbr, None


class OrgUnitWriter:
    """
    DB writer interface — production impl uses psycopg2 against hub.

    Subclass this in tests to inject a fake writer without touching the DB.
    """

    def __init__(self, conn=None):
        self.conn = conn

    def upsert(
        self,
        *,
        parent_id,
        dn,
        dn_b64,
        level,
        name_en,
        abbreviation_en,
        abbreviation_fr,
    ) -> int:
        """Upsert one org_unit row; return its DB id."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO civic_transparency.org_units
                  (parent_id, dn, dn_b64, level, name_en,
                   abbreviation_en, abbreviation_fr)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (dn) DO UPDATE SET
                  parent_id       = EXCLUDED.parent_id,
                  dn_b64          = EXCLUDED.dn_b64,
                  level           = EXCLUDED.level,
                  name_en         = EXCLUDED.name_en,
                  abbreviation_en = EXCLUDED.abbreviation_en,
                  abbreviation_fr = EXCLUDED.abbreviation_fr,
                  last_seen       = now()
                RETURNING id
                """,
                (
                    parent_id,
                    dn,
                    dn_b64,
                    level,
                    name_en,
                    abbreviation_en,
                    abbreviation_fr,
                ),
            )
            return cur.fetchone()[0]

    def commit(self):
        self.conn.commit()


async def walk_org_tree(client: GedsClient, writer: OrgUnitWriter, max_depth: int = 5) -> int:
    """
    Walk the GEDS org tree and upsert every org_unit discovered.

    Returns:
        Count of org_units written (inserted or updated).
    """
    written = 0
    visited: Set[str] = set()

    list_html = await client.get("?pgid=012")
    depts = parse_department_list(list_html)
    log.info("Pass A: %d departments from pgid=012", len(depts))

    for dept in depts:
        dn_b64 = dept["dn_b64"]
        try:
            dn = decode_dn(dn_b64)
        except DnParseError:
            log.warning("Pass A: skip undecodable DN: %s", dn_b64)
            continue

        abbr_en, abbr_fr = _split_abbr(_abbreviation(dn))
        dept_id = writer.upsert(
            parent_id=None,
            dn=dn,
            dn_b64=dn_b64,
            level=0,
            name_en=dept["name"],
            abbreviation_en=abbr_en,
            abbreviation_fr=abbr_fr,
        )
        written += 1
        visited.add(dn)

        try:
            written += await _walk_node(client, writer, dn_b64, dept_id, 1, max_depth, visited)
        except GedsFetchError as e:
            log.warning("Pass A: fetch error walking %s: %s — continuing", dept["name"], e)

    writer.commit()
    log.info("Pass A: %d org_units written", written)
    return written


async def _walk_node(
    client,
    writer: OrgUnitWriter,
    parent_dn_b64: str,
    parent_id: int,
    depth: int,
    max_depth: int,
    visited: Set[str],
) -> int:
    """Recursively walk children of one org node. Returns count written."""
    if depth > max_depth:
        return 0

    written = 0
    try:
        node_html = await client.get(f"?pgid=014&dn={parent_dn_b64}")
    except GedsFetchError as e:
        log.warning("Pass A: walk %s depth %d: %s", parent_dn_b64, depth, e)
        return 0

    parsed = parse_tree_node(node_html)
    for child in parsed["children"]:
        child_b64 = child["dn_b64"]
        try:
            dn = decode_dn(child_b64)
        except DnParseError:
            log.warning("Pass A: skip undecodable child DN: %s", child_b64)
            continue

        if dn in visited:
            continue
        visited.add(dn)

        abbr_en, abbr_fr = _split_abbr(_abbreviation(dn))
        child_id = writer.upsert(
            parent_id=parent_id,
            dn=dn,
            dn_b64=child_b64,
            level=depth,
            name_en=child["name"],
            abbreviation_en=abbr_en,
            abbreviation_fr=abbr_fr,
        )
        written += 1
        written += await _walk_node(client, writer, child_b64, child_id, depth + 1, max_depth, visited)

    return written

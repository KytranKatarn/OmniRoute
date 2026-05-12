"""
Pass B: sweep every leaf org_unit, persist federal_employees rows.
manager_id is left NULL; Pass B-2 (Task 8) resolves it.
"""

import logging
from typing import Dict, List

from services.civic_geds_client import GedsClient, GedsFetchError
from services.civic_geds_dn import DnParseError, decode_dn
from services.civic_geds_parsers import parse_tree_node

log = logging.getLogger(__name__)


class EmployeeWriter:
    def __init__(self, conn):
        self.conn = conn

    def upsert(
        self,
        *,
        source_dn,
        org_unit_id,
        surname,
        given_name,
        title_en,
        classification,
        phone,
        email,
        location_en,
        manager_dn,
    ):
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO civic_transparency.federal_employees
                  (source_dn, org_unit_id, surname, given_name,
                   title_en, classification, phone, email, location_en, manager_dn)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (source_dn) DO UPDATE SET
                  org_unit_id    = EXCLUDED.org_unit_id,
                  surname        = EXCLUDED.surname,
                  given_name     = EXCLUDED.given_name,
                  title_en       = EXCLUDED.title_en,
                  classification = EXCLUDED.classification,
                  phone          = EXCLUDED.phone,
                  email          = EXCLUDED.email,
                  location_en    = EXCLUDED.location_en,
                  manager_dn     = EXCLUDED.manager_dn,
                  last_seen      = now(),
                  departed_at    = NULL
                """,
                (
                    source_dn,
                    org_unit_id,
                    surname,
                    given_name,
                    title_en,
                    classification,
                    phone,
                    email,
                    location_en,
                    manager_dn,
                ),
            )

    def commit(self):
        self.conn.commit()


async def sweep_people(client: GedsClient, leaf_units: List[Dict], writer: EmployeeWriter) -> int:
    """leaf_units is [{id, dn_b64}, ...] from civic_transparency.org_units."""
    seen_persons: set = set()
    written = 0
    for unit in leaf_units:
        try:
            html = await client.get(f"?pgid=014&dn={unit['dn_b64']}")
        except GedsFetchError as e:
            log.warning("Pass B: fetch %s failed: %s", unit["dn_b64"], e)
            continue
        parsed = parse_tree_node(html)
        for p in parsed["people"]:
            try:
                source_dn = decode_dn(p["source_dn_b64"])
            except DnParseError:
                continue
            if source_dn in seen_persons:
                continue
            seen_persons.add(source_dn)

            manager_dn = None
            if p.get("manager_dn_b64"):
                try:
                    manager_dn = decode_dn(p["manager_dn_b64"])
                except DnParseError:
                    pass

            writer.upsert(
                source_dn=source_dn,
                org_unit_id=unit["id"],
                surname=p["surname"],
                given_name=p.get("given_name"),
                title_en=p.get("title_en"),
                classification=p.get("classification"),
                phone=p.get("phone"),
                email=p.get("email"),
                location_en=p.get("location_en"),
                manager_dn=manager_dn,
            )
            written += 1
    writer.commit()
    log.info("Pass B: %d federal_employees written", written)
    return written

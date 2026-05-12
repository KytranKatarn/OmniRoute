"""
Pass C: pgid=016 quick lists. For each row, set role_tag on the matching
federal_employees record (source_dn match). If no match (member not in any
walked org), insert a stub row in a synthetic org_unit '_QUICK_LISTS'.
"""

import logging
from typing import Dict

from services.civic_geds_client import GedsClient, GedsFetchError
from services.civic_geds_dn import DnParseError, decode_dn, encode_dn
from services.civic_geds_parsers import parse_quick_list

log = logging.getLogger(__name__)

QUICK_LIST_FIDS = {
    10: "minister",
    11: "deputy_minister",
    12: "senator",
    13: "mp",
}

_SYNTHETIC_DN = "OU=_QUICK_LISTS,O=GC,C=CA"


def _ensure_quick_list_org(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO civic_transparency.org_units
              (parent_id, dn, dn_b64, level, name_en, coverage)
            VALUES (NULL, %s, %s, 0, %s, 'partial')
            ON CONFLICT (dn) DO UPDATE SET last_seen = now()
            RETURNING id
            """,
            (_SYNTHETIC_DN, encode_dn(_SYNTHETIC_DN), "Quick Lists (synthetic)"),
        )
        return cur.fetchone()[0]


async def enrich_quick_lists(client: GedsClient, conn) -> Dict[str, int]:
    counts: Dict[str, int] = {v: 0 for v in QUICK_LIST_FIDS.values()}
    fallback_org = None

    for fid, role in QUICK_LIST_FIDS.items():
        try:
            html = await client.get(f"?pgid=016&fid={fid}")
        except GedsFetchError as e:
            log.warning("Pass C: fid=%s failed: %s", fid, e)
            continue
        rows = parse_quick_list(html)
        for r in rows:
            try:
                source_dn = decode_dn(r["source_dn_b64"])
            except DnParseError:
                continue
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE civic_transparency.federal_employees
                       SET role_tag = %s, last_seen = now()
                     WHERE source_dn = %s
                    RETURNING id
                    """,
                    (role, source_dn),
                )
                hit = cur.fetchone()
            if hit is None:
                if fallback_org is None:
                    fallback_org = _ensure_quick_list_org(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO civic_transparency.federal_employees
                          (source_dn, org_unit_id, surname, given_name, title_en, role_tag)
                        VALUES (%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (source_dn) DO UPDATE
                          SET role_tag = EXCLUDED.role_tag, last_seen = now()
                        """,
                        (
                            source_dn,
                            fallback_org,
                            r["surname"],
                            r.get("given_name"),
                            r.get("title_en"),
                            role,
                        ),
                    )
            counts[role] += 1
    conn.commit()
    log.info("Pass C: %s", counts)
    return counts

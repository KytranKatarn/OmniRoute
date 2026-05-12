"""
Pass B-2: resolve manager_dn -> manager_id (self-join).

Run after Pass B has written all employees, so every manager_dn that
exists in this snapshot can be resolved in a single UPDATE.
"""

import logging

log = logging.getLogger(__name__)

UPDATE_SQL = """
UPDATE civic_transparency.federal_employees AS e
   SET manager_id = mgr.id
  FROM civic_transparency.federal_employees AS mgr
 WHERE e.manager_dn = mgr.source_dn
   AND e.manager_id IS DISTINCT FROM mgr.id
"""


def resolve_managers(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(UPDATE_SQL)
        n = cur.rowcount
    conn.commit()
    log.info("Pass B-2: resolved %d manager_id links", n)
    return n

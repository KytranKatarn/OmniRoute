"""Register (or refresh) the P.R.O.C.U.R.E. QA suite from its YAML file.

Idempotent: matches by suite name. Run after editing
`qa_suites/ai-command-procure.yaml` to push the change into the
`qa_test_suites` table so the scheduled runner picks it up.

Run inside the archie_platform container:

    docker exec archie_platform python3 \\
        /app/scripts/register_procure_qa_suite.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

# Allow running outside the Flask app context.
_HERE = Path(__file__).resolve()
_PLATFORM_V2 = _HERE.parent.parent
if str(_PLATFORM_V2) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_V2))

import yaml  # noqa: E402

from database import get_db_cursor  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("register_procure_qa")

YAML_PATH = _PLATFORM_V2 / "qa_suites" / "ai-command-procure.yaml"


def main() -> int:
    with open(YAML_PATH) as f:
        spec = yaml.safe_load(f)

    suite = spec.get("suite") or {}
    name = suite.get("name")
    if not name:
        log.error("YAML %s has no suite.name", YAML_PATH)
        return 1

    description = suite.get("description", "")
    target_url = suite.get("base_url", "")
    spec_json = json.dumps(spec)

    with get_db_cursor(commit=True) as (_conn, cur):
        cur.execute("SELECT id FROM qa_test_suites WHERE name = %s", (name,))
        row = cur.fetchone()
        if row:
            cur.execute(
                """UPDATE qa_test_suites
                   SET description = %s, target_url = %s, spec = %s::jsonb,
                       is_active = TRUE, updated_at = NOW()
                   WHERE id = %s""",
                (description, target_url, spec_json, row["id"]),
            )
            log.info("updated suite id=%d (%s)", row["id"], name)
            return 0
        cur.execute(
            """INSERT INTO qa_test_suites
                   (name, description, target_url, spec, suite_type, is_active)
               VALUES (%s, %s, %s, %s::jsonb, 'internal', TRUE)
               RETURNING id""",
            (name, description, target_url, spec_json),
        )
        new_id = cur.fetchone()["id"]
        log.info("inserted suite id=%d (%s)", new_id, name)
    return 0


if __name__ == "__main__":
    sys.exit(main())

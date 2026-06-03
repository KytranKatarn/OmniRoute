"""Register (or refresh) any P.R.O.B.E. QA suite from its YAML file — generic.

Idempotent: matches by ``suite.name``; updates spec/description/target_url if the
suite already exists, otherwise inserts it. Reusable for every suite so we don't
need a bespoke ``register_<name>_qa_suite.py`` per file.

Run inside the archie_platform container:

    # by bare suite name, file name, or path — any of these work:
    docker exec archie_platform python3 \\
        /app/scripts/register_qa_suite_from_yaml.py watch-legal-e2e watch-civic-e2e
    docker exec archie_platform python3 \\
        /app/scripts/register_qa_suite_from_yaml.py qa_suites/watch-legal-e2e.yaml
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
log = logging.getLogger("register_qa_suite")

_SUITES_DIR = _PLATFORM_V2 / "qa_suites"


def _resolve(arg: str) -> Path:
    """Accept a bare suite name, a file name, or a full/relative path."""
    p = Path(arg)
    candidates = [
        p,
        _PLATFORM_V2 / arg,
        _SUITES_DIR / arg,
        _SUITES_DIR / f"{arg}.yaml",
        _SUITES_DIR / (p.name if p.suffix else f"{p.name}.yaml"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(f"cannot locate a YAML for {arg!r}")


def register(path: Path) -> int:
    with open(path) as f:
        spec = yaml.safe_load(f)
    suite = (spec or {}).get("suite") or {}
    name = suite.get("name")
    if not name:
        log.error("%s has no suite.name", path)
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
            log.info("updated suite id=%s (%s) <- %s", row["id"], name, path.name)
        else:
            cur.execute(
                """INSERT INTO qa_test_suites
                       (name, description, target_url, spec, suite_type, is_active)
                   VALUES (%s, %s, %s, %s::jsonb, 'internal', TRUE)
                   RETURNING id""",
                (name, description, target_url, spec_json),
            )
            log.info("inserted suite id=%s (%s) <- %s", cur.fetchone()["id"], name, path.name)
    return 0


def main(argv) -> int:
    if not argv:
        log.error("usage: register_qa_suite_from_yaml.py <suite-name-or-path> [...]")
        return 2
    rc = 0
    for arg in argv:
        try:
            rc |= register(_resolve(arg))
        except Exception as e:  # noqa: BLE001
            log.error("failed for %s: %s", arg, e)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

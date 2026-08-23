"""#5968 — smart_router must resolve the DB password from the Docker SECRET.

`DB_PASSWORD` is EMPTY in every process on this platform. Measured 2026-08-23:
len=0 in PID 1 of BOTH archie_platform and archie_scheduler. The real value lives
only in the Docker secret /run/secrets/db_password, which `database._get_db_password`
(and `db._get_db_password`) read.

smart_router.get_db() passed `password=os.getenv("DB_PASSWORD", "")` straight to
psycopg2.connect, so it sent an EMPTY password on every call and the connection had
never once succeeded:

    fe_sendauth: no password supplied

Every DB-backed lookup — routing_mode, model_tier_configs, task-type complexity
thresholds, the Opus budget cap, v_model_usage_summary, floors — fell back to
hardcoded defaults while the caller logged a WARNING and carried on, so the router
LOOKED healthy while ignoring its own configuration. Measured cost: the DB holds 12
tiers, DEFAULT_MODEL_CONFIGS has 8, and `grok` / `minimax_cloud` / `openai` /
`perplexity` were invisible to routing.

⚠️ SECOND OCCURRENCE of this symptom in the same file. The in-file comment describes
the first (a `from config import get_db` that never resolved, leaving get_db=None
"forever"). The fix copied department_dispatcher's connect() but NOT its password
resolution — the dispatcher uses `from db import _get_db_password`. The shape was
copied; the one line that mattered was not. Hence a guard rather than just a fix.
"""

import ast
import unittest
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "services" / "smart_router.py"


class TestSmartRouterDbPassword(unittest.TestCase):
    def setUp(self):
        self.tree = ast.parse(_SRC.read_text())
        self.get_db = next(
            (n for n in ast.walk(self.tree) if isinstance(n, ast.FunctionDef) and n.name == "get_db"),
            None,
        )
        self.assertIsNotNone(self.get_db, "get_db() vanished from smart_router")

    def test_password_is_not_read_straight_from_the_environment(self):
        """AST, not grep — the docstring/comments legitimately mention DB_PASSWORD."""
        for node in ast.walk(self.get_db):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "attr", None) or getattr(fn, "id", None)
            if name not in ("getenv", "get"):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and arg.value == "DB_PASSWORD":
                    self.fail(
                        "get_db() reads DB_PASSWORD from the environment. That variable "
                        "is EMPTY in every process here (len=0 in PID 1 of both "
                        "archie_platform and archie_scheduler) — the password lives in "
                        "the Docker secret. Use database._get_db_password()."
                    )

    def test_password_comes_from_the_secret_aware_helper(self):
        src = ast.get_source_segment(_SRC.read_text(), self.get_db) or ""
        self.assertIn(
            "_get_db_password",
            src,
            "get_db() must resolve the password through _get_db_password(), the helper "
            "that reads /run/secrets/db_password before falling back to the env.",
        )


if __name__ == "__main__":
    unittest.main()

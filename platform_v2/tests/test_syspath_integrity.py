"""sys.path must contain only strings, for the whole session (#5995).

`tests/test_telegram_consolidation.py` did, at MODULE level:

    ARCHIE_PLATFORM_PATH = os.getenv("ARCHIE_PLATFORM_PATH")   # -> None when unset
    if ARCHIE_PLATFORM_PATH != "":                              # None != "" is TRUE
        sys.path.insert(0, ARCHIE_PLATFORM_PATH)                # inserts None

`importlib.metadata` walks sys.path, and `flask.testing.FlaskClient.__init__` probes the
Werkzeug version on construction — so from that import onward EVERY test using the `client`
fixture died with:

    TypeError: stat: path should be string, bytes, os.PathLike or integer, not NoneType

Measured in the first complete full-suite run: **296 errors across 379 test files**, roughly
two-thirds of the suite's red, from ONE module-level line in ONE test file.

Why this test exists rather than just the fix: the damage is unbounded and the symptom points
nowhere near the cause. The traceback names flask and importlib — neither of which is at
fault — so the next occurrence would cost another full investigation. This fails in one
obvious place instead, naming the offending entry.
"""

import sys


def test_syspath_contains_only_strings():
    bad = [(i, repr(p)) for i, p in enumerate(sys.path) if not isinstance(p, str)]
    assert not bad, (
        f"non-string entries in sys.path: {bad}. importlib.metadata stats every entry, so "
        f"this breaks any later flask test client (and much else). A module-level "
        f'`sys.path.insert(0, os.getenv(...))` guarded with `!= ""` is the usual cause — '
        f"os.getenv returns None when unset, and None != '' is True. Use truthiness."
    )

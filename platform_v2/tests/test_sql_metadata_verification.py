"""Literal metadata access must not block closure or hide dynamic SQL."""

from pathlib import Path

import pytest

from services.code_health_checks import sql_finding_present
from services.code_issue_reconciler import finding_still_reproduces


@pytest.mark.parametrize("field", ["agent_name", "tier"])
@pytest.mark.parametrize("default", ["", ", None"])
def test_literal_metadata_reads_preserve_query_proof(field, default):
    source = f"name = getattr(result, '{field}'{default})\ncur.execute('SELECT 1')"
    assert sql_finding_present(source) is False
    assert finding_still_reproduces("SQL_INJECTION_RISK ", source) is False


@pytest.mark.parametrize(
    "prefix",
    [
        "fn = getattr\n",
        "getattr = replacement\n",
        "try:\n    raise Error()\nexcept Error as getattr:\n    name = getattr(result, 'tier', None)\n",
        "match value:\n    case getattr:\n        name = getattr(result, 'tier', None)\n",
        "def getattr(*args):\n    return replacement(*args)\n",
        "def wrapper(getattr):\n    return getattr(result, 'tier', None)\n",
        "from somewhere import custom as getattr\n",
        "import somewhere as getattr\n",
        "from builtins import getattr as lookup\nlookup(result, 'tier', None)\n",
        "from somewhere import *\n",
        "getattr(cur, 'execute')('SELECT 1')\n",
        "getattr(cur, method)('SELECT 1')\n",
        "getattr(result, 'query', None)\n",
        "getattr(result, '__dict__')\n",
        "getattr(result, 'tier', factory())\n",
        "getattr(result, field, None)\n",
        "builtins.getattr(result, 'tier', None)\n",
        "exec(code)\n",
        "getattr(result, 'tier', None, extra)\n",
    ],
)
def test_ambiguous_access_remains_unverified(prefix):
    source = prefix + "name = getattr(result, 'agent_name', None)\ncur.execute('SELECT 1')"
    assert sql_finding_present(source) is None
    assert finding_still_reproduces("SQL_INJECTION_RISK ", source) is None


@pytest.mark.parametrize("query", ['f"SELECT {value}"', '"SELECT %s" % value'])
def test_metadata_does_not_hide_interpolated_sql(query):
    assert sql_finding_present("name = getattr(result, 'tier', None)\ncur.execute(" + query + ")") is True


def test_unknown_query_builder_remains_unverified():
    assert sql_finding_present("name = getattr(result, 'tier', None)\ncur.execute(query)") is None


def test_metadata_alone_cannot_prove_moved_sql_fixed():
    assert sql_finding_present("name = getattr(result, 'tier', None)") is None


def test_real_jobs_repair_can_close():
    source = (Path(__file__).resolve().parents[1] / "tools/department_hq/jobs.py").read_text()
    assert finding_still_reproduces("SQL_INJECTION_RISK ", source) is False

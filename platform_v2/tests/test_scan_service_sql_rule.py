"""The scanner's SQL-injection rule: flag SQL that is BUILT, never the parameterized form.

The old rule matched any `%s` inside execute("..."), i.e. it flagged the SAFE, parameterized pattern: 200+ open
findings platform-wide were false. These tests pin both sides: what must be flagged and what must not.
"""

import pytest

from services.scan_service import static_analysis

MSG = "Potential SQL injection vulnerability"


def sql_findings(src):
    return [i for i in static_analysis(src, "svc.py")["issues"] if i["message"] == MSG]


@pytest.mark.parametrize(
    "line",
    [
        'cur.execute("SELECT * FROM t WHERE id = %s", (1,))',
        "cur.execute('UPDATE t SET a = %s WHERE id = %s', (a, i))",
        'cur.executemany("INSERT INTO t (a, b) VALUES (%s, %s)", rows)',
        'cur.execute("SELECT 1")',
    ],
)
def test_the_parameterized_form_is_not_flagged(line):
    assert sql_findings(line + "\n") == []


@pytest.mark.parametrize(
    "line",
    [
        'cur.execute(f"SELECT * FROM t WHERE {where}", params)',
        'cur.execute(f"""',
        'cur.execute("SELECT * FROM t WHERE id = %s" % uid)',
        'cur.execute("SELECT * FROM t WHERE name = \'" + name + "\'")',
        'cur.execute("SELECT * FROM {}".format(table))',
        'cur.executemany(f"INSERT INTO {t} VALUES (%s)", rows)',
    ],
)
def test_built_sql_is_still_flagged(line):
    found = sql_findings(line + "\n")
    assert len(found) == 1 and found[0]["severity"] == "high"


def test_an_audited_marker_suppresses_the_flag():
    flagged = 'cur.execute(f"SELECT * FROM t {where}", params)\n'
    marked = 'cur.execute(f"SELECT * FROM t {where}", params)  # sql-safe: where is fixed fragments, values bound\n'
    assert len(sql_findings(flagged)) == 1
    assert sql_findings(marked) == []


def test_the_marker_is_exact_not_a_substring_match_on_prose():
    """A comment merely mentioning safety must not suppress the finding."""
    assert len(sql_findings('cur.execute(f"SELECT {x}")  # this is safe, trust me\n')) == 1


def test_a_marker_on_the_line_directly_above_counts():
    src = '# sql-safe: where is fixed fragments, values bound\ncur.execute(f"SELECT * FROM t {where}", params)\n'
    assert sql_findings(src) == []


def test_a_marker_two_lines_above_does_not_count():
    src = '# sql-safe: reviewed\nx = 1\ncur.execute(f"SELECT * FROM t {where}", params)\n'
    assert len(sql_findings(src)) == 1

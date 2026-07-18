"""Tests for the quote-safe delimiter fix format (#387 fix-yield).

The old JSON contract required the model to escape code inside a JSON string; a 7B
could not do that for triple-quoted SQL (`\"\"\"SELECT ...\"\"\"`), which was the dominant
`unparseable` failure. The delimiter format needs no escaping.
"""

from services.audit_pipeline import (
    _apply_targeted_fix,
    _parse_fix_delimited,
    _parse_fix_response,
)


def test_delimited_basic():
    r = _parse_fix_delimited("<<<FIND>>>\nexcept:\n<<<REPLACE>>>\nexcept Exception:\n<<<END>>>")
    assert r == {"find": "except:", "replace": "except Exception:"}


def test_delimited_triple_quoted_sql_the_json_killer():
    # The exact shape that broke JSON parsing: a triple-quoted SQL string with embedded
    # quotes + newlines. No escaping needed in the delimiter format.
    raw = (
        "<<<FIND>>>\n"
        '    cur.execute(f"""SELECT id FROM t WHERE name = \'{name}\'""")\n'
        "<<<REPLACE>>>\n"
        '    cur.execute("""SELECT id FROM t WHERE name = %s""", (name,))\n'
        "<<<END>>>"
    )
    r = _parse_fix_delimited(raw)
    assert r is not None
    assert "SELECT id FROM t" in r["find"]
    assert "%s" in r["replace"]
    assert r["find"].startswith("    cur.execute")  # indentation preserved


def test_delimited_preserves_indentation_and_end_optional():
    r = _parse_fix_delimited("<<<FIND>>>\n        x = 1\n<<<REPLACE>>>\n        x = 2\n")
    assert r == {"find": "        x = 1", "replace": "        x = 2"}


def test_response_prefers_delimited_falls_back_to_json():
    assert _parse_fix_response("<<<FIND>>>\nfoo\n<<<REPLACE>>>\nbar\n<<<END>>>") == {
        "find": "foo",
        "replace": "bar",
    }
    assert _parse_fix_response('{"find": "a", "replace": "b"}') == {"find": "a", "replace": "b"}


def test_apply_end_to_end_with_delimited_sql():
    source = 'def q():\n    cur.execute("""SELECT * FROM t WHERE id = %d""" % x)\n    return 1\n'
    raw = (
        "<<<FIND>>>\n"
        '    cur.execute("""SELECT * FROM t WHERE id = %d""" % x)\n'
        "<<<REPLACE>>>\n"
        '    cur.execute("""SELECT * FROM t WHERE id = %s""", (x,))\n'
        "<<<END>>>"
    )
    fixed, reason = _apply_targeted_fix(source, raw)
    assert reason == "ok", reason
    assert "%s" in fixed and "(x,)" in fixed
    assert "%d" not in fixed


def test_apply_unparseable_when_no_recognizable_format():
    fixed, reason = _apply_targeted_fix("x=1", "I think you should fix the query somehow")
    assert fixed is None
    assert reason == "unparseable"

from pathlib import Path
from services.civic_geds_parsers import (
    parse_department_list,
    parse_tree_node,
    parse_quick_list,
)

FIX = Path(__file__).parent.parent / "fixtures" / "geds"


def load(name):
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def test_parse_department_list_returns_at_least_100_depts():
    rows = parse_department_list(load("dept_list.html"))
    assert len(rows) >= 100, f"expected >=100 depts in pgid=012, got {len(rows)}"
    for r in rows:
        assert r["dn_b64"], "dn_b64 missing"
        assert r["name"], "name missing"


def test_parse_department_list_includes_known_deps():
    rows = parse_department_list(load("dept_list.html"))
    names = {r["name"] for r in rows}
    assert any("Canadian Space Agency" in n for n in names), "Canadian Space Agency missing from dept list"
    assert any("Canadian Security Intelligence Service" in n for n in names), "CSIS missing from dept list"


def test_parse_tree_node_returns_dict_with_children_and_people():
    parsed = parse_tree_node(load("tree_node.html"))
    assert "children" in parsed and "people" in parsed
    # CSA tree node should have at least 1 child OR 1 person
    assert (
        len(parsed["children"]) + len(parsed["people"])
    ) > 0, "tree node yielded zero children + zero people — selector bug?"


def test_parse_tree_node_people_have_required_fields():
    parsed = parse_tree_node(load("tree_node.html"))
    for p in parsed["people"]:
        assert "source_dn_b64" in p and p["source_dn_b64"], "missing source_dn_b64"
        assert "surname" in p, "missing surname key"


def test_parse_quick_list_returns_deputy_ministers():
    rows = parse_quick_list(load("quick_list.html"))
    assert len(rows) >= 20, f"expected >=20 DMs, got {len(rows)}"
    for r in rows:
        assert r["surname"], "surname missing"

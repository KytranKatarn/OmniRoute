"""
Tests for the GEDCOM 5.5.1 import/export pipeline.

Mocks ged4py (not installed) and tree_service (needs DB).

Run with:
    docker exec archie_platform python3 -m pytest tools/family_tree/tests/test_gedcom.py -v
"""

import datetime
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Ensure platform_v2 is on sys.path so imports resolve inside Docker
# ---------------------------------------------------------------------------
PLATFORM_DIR = Path(__file__).resolve().parents[3]  # platform_v2/
if str(PLATFORM_DIR) not in sys.path:
    sys.path.insert(0, str(PLATFORM_DIR))

SAMPLE_GED = Path(__file__).resolve().parent / "sample_family.ged"

# ---------------------------------------------------------------------------
# In-memory stores for mock tree_service
# ---------------------------------------------------------------------------
_person_counter = 0
_persons_created: list = []
_relationships_created: list = []
_sources_created: list = []
_links_created: list = []


def _reset_stores():
    global _person_counter
    _person_counter = 0
    _persons_created.clear()
    _relationships_created.clear()
    _sources_created.clear()
    _links_created.clear()


def _mock_create_person(user_id, first_name, last_name, **kwargs):
    global _person_counter
    _person_counter += 1
    person = {
        "id": _person_counter,
        "user_id": user_id,
        "first_name": first_name,
        "last_name": last_name,
        **kwargs,
    }
    _persons_created.append(person)
    return person


def _mock_add_relationship(user_id, person1_id, person2_id, relationship_type, **kw):
    rel = {
        "user_id": user_id,
        "person1_id": person1_id,
        "person2_id": person2_id,
        "relationship_type": relationship_type,
    }
    _relationships_created.append(rel)
    return rel


def _mock_add_source(user_id, title=None, description=None, **kw):
    _sources_created.append({"id": 999, "user_id": user_id, "title": title})
    return 999


def _mock_link_source_to_person(user_id=None, person_id=None, source_id=None, **kw):
    _links_created.append({"person_id": person_id, "source_id": source_id})
    return True


# ---------------------------------------------------------------------------
# Minimal ged4py mock — replicates the GedcomReader + record API
# ---------------------------------------------------------------------------


class _MockTag:
    """Mimics a ged4py sub-tag node."""

    def __init__(self, tag, value=None, children=None):
        self.tag = tag
        self.value = value
        self._children = children or []

    def sub_tag(self, tag_name):
        for child in self._children:
            if child.tag == tag_name:
                return child
        return None

    def sub_tags(self, tag_name):
        return [c for c in self._children if c.tag == tag_name]


class _MockRecord(_MockTag):
    """Mimics a ged4py level-0 record."""

    def __init__(self, xref_id, tag, children=None):
        super().__init__(tag, value=None, children=children or [])
        self.xref_id = xref_id


def _parse_ged_file(content: bytes) -> list:
    """
    Minimal GEDCOM parser that builds _MockRecord trees.
    Only supports HEAD, SUBM, INDI, FAM, TRLR at level 0.
    """
    lines = content.decode("utf-8").splitlines()
    records = []
    current_record = None
    stack: list = []  # (level, _MockTag)

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        parts = line.split(" ", 2)
        level = int(parts[0])
        rest = parts[1] if len(parts) > 1 else ""
        value_part = parts[2] if len(parts) > 2 else None

        # Level 0 — new record
        if level == 0:
            if current_record is not None:
                records.append(current_record)
            # Check for xref: @I1@ INDI
            if rest.startswith("@") and value_part:
                xref = rest
                tag = value_part
                current_record = _MockRecord(xref, tag)
            else:
                tag = rest
                current_record = _MockRecord(None, tag)
            stack = [(0, current_record)]
            continue

        # Sub-levels
        tag = rest
        value = value_part

        node = _MockTag(tag, value)

        # Find parent: walk back stack to find level - 1
        while stack and stack[-1][0] >= level:
            stack.pop()

        if stack:
            parent = stack[-1][1]
            parent._children.append(node)

        stack.append((level, node))

    if current_record is not None:
        records.append(current_record)

    return records


class _MockGedcomReader:
    """Mimics ged4py.parser.GedcomReader."""

    def __init__(self, file_obj):
        content = file_obj.read()
        self._records = _parse_ged_file(content)

    def records0(self, tag):
        return [r for r in self._records if r.tag == tag]


# ---------------------------------------------------------------------------
# Install mocks BEFORE importing gedcom_service
# ---------------------------------------------------------------------------

# Mock ged4py.parser
_ged4py_mock = MagicMock()
_ged4py_parser_mock = MagicMock()
_ged4py_parser_mock.GedcomReader = _MockGedcomReader
sys.modules["ged4py"] = _ged4py_mock
sys.modules["ged4py.parser"] = _ged4py_parser_mock

# Mock tree_service
_tree_mock = MagicMock()
_tree_mock.create_person = _mock_create_person
_tree_mock.add_relationship = _mock_add_relationship
_tree_mock.add_source = _mock_add_source
_tree_mock.link_source_to_person = _mock_link_source_to_person
sys.modules["tools.family_tree.services.tree_service"] = _tree_mock

# Now import gedcom_service and rebind module-level imports
from tools.family_tree.services import gedcom_service

gedcom_service.create_person = _mock_create_person
gedcom_service.add_relationship = _mock_add_relationship
gedcom_service.add_source = _mock_add_source
gedcom_service.link_source_to_person = _mock_link_source_to_person


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_person(first_name: str):
    for p in _persons_created:
        if first_name.lower() in p["first_name"].lower():
            return p
    return None


# ---------------------------------------------------------------------------
# Unit tests — date parsing / formatting
# ---------------------------------------------------------------------------


class TestDateHelpers:
    def test_parse_standard_date(self):
        assert gedcom_service._parse_gedcom_date("15 MAR 1890") == datetime.date(1890, 3, 15)

    def test_parse_year_only(self):
        assert gedcom_service._parse_gedcom_date("1920") == datetime.date(1920, 1, 1)

    def test_parse_month_year(self):
        assert gedcom_service._parse_gedcom_date("SEP 1895") == datetime.date(1895, 9, 1)

    def test_parse_with_qualifier(self):
        assert gedcom_service._parse_gedcom_date("ABT 1920") == datetime.date(1920, 1, 1)

    def test_parse_invalid_dates(self):
        assert gedcom_service._parse_gedcom_date("31 FEB 1990") is None
        assert gedcom_service._parse_gedcom_date("32 JAN 2000") is None

    def test_parse_additional_qualifiers(self):
        assert gedcom_service._parse_gedcom_date("CAL 1920") == datetime.date(1920, 1, 1)
        assert gedcom_service._parse_gedcom_date("BET 1900 AND 1902") is None
        assert gedcom_service._parse_gedcom_date("BET 1 JAN 1900 AND 2 JAN 1902") is None

    def test_parse_ambiguous_slash_dates(self):
        assert gedcom_service._parse_gedcom_date("1/2/1900") is None
        assert gedcom_service._parse_gedcom_date("01/02/1900") is None

    def test_parse_empty(self):
        assert gedcom_service._parse_gedcom_date("") is None

    def test_format_date(self):
        assert gedcom_service._format_gedcom_date(datetime.date(1890, 3, 15)) == "15 MAR 1890"

    def test_year_only_round_trip(self):
        parsed = gedcom_service._parse_gedcom_date("1900")
        assert parsed == datetime.date(1900, 1, 1)
        assert gedcom_service._format_gedcom_date(parsed) == "01 JAN 1900"

    def test_format_iso_string(self):
        assert gedcom_service._format_gedcom_date("1920-02-03") == "03 FEB 1920"

    def test_format_none(self):
        assert gedcom_service._format_gedcom_date(None) == ""


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestImport:
    @pytest.fixture(autouse=True)
    def setup(self):
        _reset_stores()
        yield

    def test_import_creates_all_persons(self):
        stats = gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())
        assert stats["persons_created"] == 8
        assert stats["errors"] == []

    def test_import_creates_relationships(self):
        stats = gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())
        # F1: 1 spouse + 2 parent_child = 3
        # F2: 1 spouse + 4 parent_child = 5
        # F3: 0 spouse + 2 parent_child = 2
        assert stats["relationships_created"] == 10

    def test_portuguese_diacritics_preserved(self):
        gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())

        assert _find_person("António") is not None, "António not found"
        assert _find_person("Maria Conceição") is not None, "Maria Conceição not found"
        assert _find_person("João") is not None, "João not found"
        assert _find_person("Françoise") is not None, "Françoise not found"
        assert _find_person("Théodore") is not None, "Théodore not found"
        assert _find_person("Éloïse") is not None, "Éloïse not found"

    def test_birth_death_dates_parsed(self):
        gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())
        antonio = _find_person("António")
        assert antonio["birth_date"] == datetime.date(1890, 3, 15)
        assert antonio["death_date"] == datetime.date(1962, 6, 22)

    def test_places_preserved(self):
        gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())
        assert _find_person("António")["birth_place"] == "Lisboa, Portugal"
        assert _find_person("Françoise")["birth_place"] == "Lyon, France"
        assert _find_person("Théodore")["birth_place"] == "Montréal, Canada"

    def test_gender_parsed(self):
        gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())
        assert _find_person("António")["gender"] == "male"
        assert _find_person("Maria Conceição")["gender"] == "female"


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


class TestExport:
    def _make_persons(self):
        return [
            {
                "id": 1,
                "first_name": "António",
                "last_name": "Silva",
                "gender": "male",
                "birth_date": datetime.date(1890, 3, 15),
                "birth_place": "Lisboa, Portugal",
                "death_date": datetime.date(1962, 6, 22),
                "death_place": "Lisboa, Portugal",
            },
            {
                "id": 2,
                "first_name": "Maria Conceição",
                "last_name": "Ferreira",
                "gender": "female",
                "birth_date": datetime.date(1895, 9, 8),
                "birth_place": "Coimbra, Portugal",
                "death_date": datetime.date(1970, 11, 14),
                "death_place": "Lisboa, Portugal",
            },
            {
                "id": 3,
                "first_name": "João",
                "last_name": "Silva",
                "gender": "male",
                "birth_date": datetime.date(1920, 2, 3),
                "birth_place": "Lisboa, Portugal",
                "death_date": datetime.date(1998, 8, 19),
                "death_place": "Lyon, France",
            },
            {
                "id": 4,
                "first_name": "Françoise",
                "last_name": "Dubois",
                "gender": "female",
                "birth_date": datetime.date(1924, 7, 27),
                "birth_place": "Lyon, France",
                "death_date": datetime.date(2010, 12, 5),
                "death_place": "Lyon, France",
            },
            {
                "id": 5,
                "first_name": "José António",
                "last_name": "Silva",
                "gender": "male",
                "birth_date": datetime.date(1952, 4, 11),
                "birth_place": "Lyon, France",
                "death_date": None,
                "death_place": None,
            },
            {
                "id": 6,
                "first_name": "Madeleine Conceição",
                "last_name": "Silva",
                "gender": "female",
                "birth_date": datetime.date(1955, 10, 30),
                "birth_place": "Lyon, France",
                "death_date": None,
                "death_place": None,
            },
            {
                "id": 7,
                "first_name": "Théodore João",
                "last_name": "Silva",
                "gender": "male",
                "birth_date": datetime.date(1980, 1, 18),
                "birth_place": "Montréal, Canada",
                "death_date": None,
                "death_place": None,
            },
            {
                "id": 8,
                "first_name": "Éloïse",
                "last_name": "Silva",
                "gender": "female",
                "birth_date": datetime.date(1983, 12, 25),
                "birth_place": "Montréal, Canada",
                "death_date": None,
                "death_place": None,
            },
        ]

    def _make_relationships(self):
        return [
            {"person1_id": 1, "person2_id": 2, "relationship_type": "spouse"},
            {"person1_id": 1, "person2_id": 3, "relationship_type": "parent_child"},
            {"person1_id": 2, "person2_id": 3, "relationship_type": "parent_child"},
            {"person1_id": 3, "person2_id": 4, "relationship_type": "spouse"},
            {"person1_id": 3, "person2_id": 5, "relationship_type": "parent_child"},
            {"person1_id": 4, "person2_id": 5, "relationship_type": "parent_child"},
            {"person1_id": 3, "person2_id": 6, "relationship_type": "parent_child"},
            {"person1_id": 4, "person2_id": 6, "relationship_type": "parent_child"},
            {"person1_id": 5, "person2_id": 7, "relationship_type": "parent_child"},
            {"person1_id": 5, "person2_id": 8, "relationship_type": "parent_child"},
        ]

    def test_export_valid_gedcom_structure(self):
        out = gedcom_service.export_gedcom(1, self._make_persons(), self._make_relationships())
        assert out.startswith("0 HEAD\n")
        assert out.strip().endswith("0 TRLR")
        assert "5.5.1" in out
        assert "UTF-8" in out

    def test_export_preserves_diacritics(self):
        out = gedcom_service.export_gedcom(1, self._make_persons(), self._make_relationships())
        for name in [
            "António /Silva/",
            "Maria Conceição /Ferreira/",
            "João /Silva/",
            "Françoise /Dubois/",
            "Théodore João /Silva/",
            "Éloïse /Silva/",
        ]:
            assert name in out, f"Missing: {name}"

    def test_export_preserves_places(self):
        out = gedcom_service.export_gedcom(1, self._make_persons(), self._make_relationships())
        for place in ["Lisboa, Portugal", "Coimbra, Portugal", "Lyon, France", "Montréal, Canada"]:
            assert place in out, f"Missing place: {place}"

    def test_export_preserves_dates(self):
        out = gedcom_service.export_gedcom(1, self._make_persons(), self._make_relationships())
        for d in ["15 MAR 1890", "08 SEP 1895", "03 FEB 1920", "25 DEC 1983"]:
            assert d in out, f"Missing date: {d}"

    def test_export_fam_records(self):
        out = gedcom_service.export_gedcom(1, self._make_persons(), self._make_relationships())
        assert "@F1@ FAM" in out
        assert "HUSB" in out
        assert "WIFE" in out
        assert "CHIL" in out

    def test_export_all_indi_records(self):
        out = gedcom_service.export_gedcom(1, self._make_persons(), self._make_relationships())
        for i in range(1, 9):
            assert f"@I{i}@ INDI" in out

    def test_export_gender_tags(self):
        out = gedcom_service.export_gedcom(1, self._make_persons(), self._make_relationships())
        assert "1 SEX M" in out
        assert "1 SEX F" in out


# ---------------------------------------------------------------------------
# Round-trip tests
# ---------------------------------------------------------------------------


class TestRoundTrip:
    @pytest.fixture(autouse=True)
    def setup(self):
        _reset_stores()
        yield

    def test_round_trip_names_with_diacritics(self):
        gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())
        out = gedcom_service.export_gedcom(1, _persons_created[:], _relationships_created[:])

        for name in [
            "António /Silva/",
            "Maria Conceição /Ferreira/",
            "João /Silva/",
            "Françoise /Dubois/",
            "José António /Silva/",
            "Madeleine Conceição /Silva/",
            "Théodore João /Silva/",
            "Éloïse /Silva/",
        ]:
            assert name in out, f"Round-trip lost: {name}"

    def test_round_trip_places(self):
        gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())
        out = gedcom_service.export_gedcom(1, _persons_created[:], _relationships_created[:])

        for place in ["Lisboa, Portugal", "Coimbra, Portugal", "Lyon, France", "Montréal, Canada"]:
            assert place in out, f"Round-trip lost place: {place}"

    def test_round_trip_dates(self):
        gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())
        out = gedcom_service.export_gedcom(1, _persons_created[:], _relationships_created[:])

        for d in [
            "15 MAR 1890",
            "08 SEP 1895",
            "03 FEB 1920",
            "27 JUL 1924",
            "11 APR 1952",
            "30 OCT 1955",
            "18 JAN 1980",
            "25 DEC 1983",
        ]:
            assert d in out, f"Round-trip lost date: {d}"

    def test_round_trip_relationships(self):
        gedcom_service.import_gedcom(user_id=1, file_content=SAMPLE_GED.read_bytes())
        out = gedcom_service.export_gedcom(1, _persons_created[:], _relationships_created[:])

        assert "FAM" in out
        assert "HUSB" in out
        assert "WIFE" in out
        assert "CHIL" in out
        fam_count = out.count(" FAM\n")
        assert fam_count >= 3, f"Expected >=3 FAM records, got {fam_count}"

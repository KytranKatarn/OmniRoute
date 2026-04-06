# Family Tree — AI-Powered Genealogy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an AI-powered genealogy module with 5 specialized agents that autonomously search public records, OCR documents, match faces in photos, and build family trees — starting as an ARCHIE platform module, designed for standalone extraction.

**Architecture:** Flask Blueprint at `platform_v2/tools/family_tree/` following ADR-045 route splitting. 5 new agents registered via `agent_service.create_agent()`. External API clients (FamilySearch, WikiTree, NARA, Chronicling America, Europeana) wrapped in a services layer. AI inference through Bridge dispatcher (ADR-013). PostgreSQL tables prefixed `family_*` for clean extraction.

**Tech Stack:** Python/Flask, PostgreSQL, d3.js (tree visualization), pytesseract, ged4py, insightface, scikit-learn (DBSCAN clustering), LCARS UI

**Spec:** `docs/superpowers/specs/2026-04-06-family-tree-genealogy-design.md`

---

## File Structure

```
platform_v2/tools/family_tree/
├── __init__.py                  # Blueprint + register_*_routes (ADR-045)
├── routes.py                    # Dashboard, tree CRUD, person CRUD, GEDCOM import/export
├── research_routes.py           # Research queue, findings review, accept/reject
├── document_routes.py           # Upload, OCR trigger, extracted data, link to person
├── photo_routes.py              # Upload, face detection, clustering, restore trigger
├── timeline_routes.py           # Timeline events, migration map data
├── services/
│   ├── tree_service.py          # Person/relationship CRUD, ancestor/descendant queries
│   ├── research_service.py      # FamilySearch, WikiTree, NARA, Chronicling America, Europeana clients
│   ├── ocr_service.py           # Tesseract + Transkribus integration
│   ├── face_service.py          # InsightFace embeddings, DBSCAN clustering
│   └── gedcom_service.py        # GEDCOM 5.5.1 import/export via ged4py
├── templates/
│   └── family_tree.html         # Main template (5 tabs, LCARS themed)
└── static/
    ├── css/family-tree.css      # ft- prefix
    └── js/family-tree.js        # Tree renderer (d3), research UI, uploads, face labeling

database/migrations/
└── 308_family_tree.sql          # All family_* tables

platform_v2/module_registry.py   # Add family_tree entry
platform_v2/rbac.py              # (no changes needed — USER minimum_role, no custom perms)
```

---

## Task 1: Database Migration

**Files:**
- Create: `database/migrations/308_family_tree.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- Family Tree Module — Migration 308
-- AI-powered genealogy tables
-- 2026-04-06

-- Persons in the family tree
CREATE TABLE IF NOT EXISTS family_persons (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    first_name VARCHAR(255),
    last_name VARCHAR(255),
    maiden_name VARCHAR(255),
    gender VARCHAR(20),
    birth_date DATE,
    birth_date_approx BOOLEAN DEFAULT FALSE,
    birth_place VARCHAR(500),
    death_date DATE,
    death_date_approx BOOLEAN DEFAULT FALSE,
    death_place VARCHAR(500),
    notes TEXT,
    confidence_score DECIMAL(3,2) DEFAULT 1.00,
    source_type VARCHAR(50) DEFAULT 'user_input',
    avatar_path VARCHAR(500),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_family_persons_user ON family_persons(user_id);
CREATE INDEX IF NOT EXISTS idx_family_persons_name ON family_persons(user_id, last_name, first_name);

-- Sources for citations
CREATE TABLE IF NOT EXISTS family_sources (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    source_type VARCHAR(50) NOT NULL,
    external_id VARCHAR(500),
    title VARCHAR(500),
    url VARCHAR(1000),
    citation TEXT,
    retrieved_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_family_sources_user ON family_sources(user_id);

-- Relationships between persons
CREATE TABLE IF NOT EXISTS family_relationships (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    person_a_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    person_b_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) NOT NULL,
    start_date DATE,
    end_date DATE,
    confidence_score DECIMAL(3,2) DEFAULT 1.00,
    source_id INTEGER REFERENCES family_sources(id),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(person_a_id, person_b_id, relationship_type)
);
CREATE INDEX IF NOT EXISTS idx_family_rel_user ON family_relationships(user_id);
CREATE INDEX IF NOT EXISTS idx_family_rel_person_a ON family_relationships(person_a_id);
CREATE INDEX IF NOT EXISTS idx_family_rel_person_b ON family_relationships(person_b_id);

-- Person-source junction (which source proves which field)
CREATE TABLE IF NOT EXISTS family_person_sources (
    person_id INTEGER NOT NULL REFERENCES family_persons(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES family_sources(id) ON DELETE CASCADE,
    field_name VARCHAR(100),
    PRIMARY KEY (person_id, source_id, field_name)
);

-- Uploaded documents (certificates, letters, etc.)
CREATE TABLE IF NOT EXISTS family_documents (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    filename VARCHAR(500) NOT NULL,
    file_path VARCHAR(1000) NOT NULL,
    file_type VARCHAR(50),
    document_type VARCHAR(100),
    ocr_text TEXT,
    ocr_status VARCHAR(20) DEFAULT 'pending' CHECK (ocr_status IN ('pending', 'processing', 'completed', 'failed')),
    extracted_data JSONB,
    linked_person_id INTEGER REFERENCES family_persons(id),
    uploaded_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_family_docs_user ON family_documents(user_id);
CREATE INDEX IF NOT EXISTS idx_family_docs_status ON family_documents(ocr_status);

-- AI research queue
CREATE TABLE IF NOT EXISTS family_research_queue (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    person_id INTEGER REFERENCES family_persons(id),
    research_type VARCHAR(50) NOT NULL,
    query_params JSONB,
    status VARCHAR(20) DEFAULT 'queued' CHECK (status IN ('queued', 'searching', 'found_matches', 'reviewed', 'no_results')),
    agent_name VARCHAR(100),
    results JSONB,
    confidence_score DECIMAL(3,2),
    created_at TIMESTAMP DEFAULT NOW(),
    completed_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_family_research_user ON family_research_queue(user_id);
CREATE INDEX IF NOT EXISTS idx_family_research_status ON family_research_queue(status);

-- Face embeddings for photo matching
CREATE TABLE IF NOT EXISTS family_face_embeddings (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    document_id INTEGER NOT NULL REFERENCES family_documents(id) ON DELETE CASCADE,
    person_id INTEGER REFERENCES family_persons(id),
    embedding BYTEA,
    bounding_box JSONB,
    cluster_id INTEGER,
    estimated_era VARCHAR(50),
    confidence_score DECIMAL(3,2),
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_family_faces_user ON family_face_embeddings(user_id);
CREATE INDEX IF NOT EXISTS idx_family_faces_person ON family_face_embeddings(person_id);
CREATE INDEX IF NOT EXISTS idx_family_faces_cluster ON family_face_embeddings(user_id, cluster_id);
```

Note: Using `BYTEA` for embedding instead of `VECTOR(512)` — avoids requiring pgvector extension. Face matching uses Python-side cosine similarity which is fine for the expected data volume (hundreds, not millions of faces).

- [ ] **Step 2: Run the migration**

```bash
docker exec -i archie_database psql -U archie -d archie < database/migrations/308_family_tree.sql
```

Expected: All `CREATE TABLE` and `CREATE INDEX` succeed with no errors.

- [ ] **Step 3: Verify tables exist**

```bash
docker exec archie_database psql -U archie -d archie -c "\dt family_*"
```

Expected: 7 tables listed (family_persons, family_sources, family_relationships, family_person_sources, family_documents, family_research_queue, family_face_embeddings).

- [ ] **Step 4: Commit**

```bash
git add database/migrations/308_family_tree.sql
git commit -m "feat(family-tree): add database migration 308 — 7 family_* tables"
```

---

## Task 2: Tree Service (Core CRUD)

**Files:**
- Create: `platform_v2/tools/family_tree/services/__init__.py`
- Create: `platform_v2/tools/family_tree/services/tree_service.py`

- [ ] **Step 1: Create services package**

```python
# platform_v2/tools/family_tree/services/__init__.py
```

Empty `__init__.py` — services are imported directly by route files.

- [ ] **Step 2: Write tree_service.py**

```python
"""Family tree CRUD — persons, relationships, ancestor/descendant queries."""

from database import get_db_cursor


# ---------------------------------------------------------------------------
# Person CRUD
# ---------------------------------------------------------------------------

def create_person(user_id, first_name, last_name, **kwargs):
    """Create a person in the family tree. Returns person dict."""
    allowed = {
        "maiden_name", "gender", "birth_date", "birth_date_approx",
        "birth_place", "death_date", "death_date_approx", "death_place",
        "notes", "confidence_score", "source_type", "avatar_path",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    cols = ["user_id", "first_name", "last_name"] + list(fields.keys())
    vals = [user_id, first_name, last_name] + list(fields.values())
    placeholders = ", ".join(["%s"] * len(vals))
    col_str = ", ".join(cols)

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"INSERT INTO family_persons ({col_str}) VALUES ({placeholders}) RETURNING *",
            vals,
        )
        return dict(cur.fetchone())


def get_person(user_id, person_id):
    """Get a single person by ID, scoped to user."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM family_persons WHERE id = %s AND user_id = %s",
            (person_id, user_id),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def update_person(user_id, person_id, **kwargs):
    """Update a person's fields. Returns updated dict or None."""
    allowed = {
        "first_name", "last_name", "maiden_name", "gender",
        "birth_date", "birth_date_approx", "birth_place",
        "death_date", "death_date_approx", "death_place",
        "notes", "confidence_score", "source_type", "avatar_path",
    }
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return get_person(user_id, person_id)

    set_clause = ", ".join(f"{k} = %s" for k in fields)
    vals = list(fields.values()) + [person_id, user_id]

    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            f"UPDATE family_persons SET {set_clause}, updated_at = NOW() "
            f"WHERE id = %s AND user_id = %s RETURNING *",
            vals,
        )
        row = cur.fetchone()
        return dict(row) if row else None


def delete_person(user_id, person_id):
    """Delete a person and cascade relationships. Returns True if deleted."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM family_persons WHERE id = %s AND user_id = %s",
            (person_id, user_id),
        )
        return cur.rowcount > 0


def list_persons(user_id):
    """List all persons for a user's tree."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM family_persons WHERE user_id = %s ORDER BY last_name, first_name",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Relationship CRUD
# ---------------------------------------------------------------------------

def add_relationship(user_id, person_a_id, person_b_id, relationship_type, **kwargs):
    """Add a relationship between two persons. Returns relationship dict."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO family_relationships
               (user_id, person_a_id, person_b_id, relationship_type,
                start_date, end_date, confidence_score, source_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (person_a_id, person_b_id, relationship_type) DO NOTHING
               RETURNING *""",
            (
                user_id, person_a_id, person_b_id, relationship_type,
                kwargs.get("start_date"), kwargs.get("end_date"),
                kwargs.get("confidence_score", 1.00), kwargs.get("source_id"),
            ),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def remove_relationship(user_id, relationship_id):
    """Remove a relationship. Returns True if deleted."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "DELETE FROM family_relationships WHERE id = %s AND user_id = %s",
            (relationship_id, user_id),
        )
        return cur.rowcount > 0


def list_relationships(user_id):
    """List all relationships for a user's tree."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT * FROM family_relationships WHERE user_id = %s",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Tree Queries (Recursive CTEs)
# ---------------------------------------------------------------------------

def get_ancestors(user_id, person_id, max_depth=10):
    """Get all ancestors of a person using recursive CTE."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            WITH RECURSIVE ancestors AS (
                SELECT p.*, 1 AS depth, r.relationship_type
                FROM family_persons p
                JOIN family_relationships r ON r.person_a_id = p.id
                WHERE r.person_b_id = %s AND r.relationship_type = 'parent_child'
                  AND r.user_id = %s

                UNION ALL

                SELECT p.*, a.depth + 1, r.relationship_type
                FROM family_persons p
                JOIN family_relationships r ON r.person_a_id = p.id
                JOIN ancestors a ON r.person_b_id = a.id
                WHERE r.relationship_type = 'parent_child'
                  AND a.depth < %s
            )
            SELECT * FROM ancestors ORDER BY depth
            """,
            (person_id, user_id, max_depth),
        )
        return [dict(r) for r in cur.fetchall()]


def get_descendants(user_id, person_id, max_depth=10):
    """Get all descendants of a person using recursive CTE."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """
            WITH RECURSIVE descendants AS (
                SELECT p.*, 1 AS depth
                FROM family_persons p
                JOIN family_relationships r ON r.person_b_id = p.id
                WHERE r.person_a_id = %s AND r.relationship_type = 'parent_child'
                  AND r.user_id = %s

                UNION ALL

                SELECT p.*, d.depth + 1
                FROM family_persons p
                JOIN family_relationships r ON r.person_b_id = p.id
                JOIN descendants d ON r.person_a_id = d.id
                WHERE r.relationship_type = 'parent_child'
                  AND d.depth < %s
            )
            SELECT * FROM descendants ORDER BY depth
            """,
            (person_id, user_id, max_depth),
        )
        return [dict(r) for r in cur.fetchall()]


def get_full_tree(user_id):
    """Get complete tree data for d3 visualization — persons + relationships."""
    persons = list_persons(user_id)
    relationships = list_relationships(user_id)
    return {
        "persons": persons,
        "relationships": relationships,
    }


# ---------------------------------------------------------------------------
# Source Management
# ---------------------------------------------------------------------------

def add_source(user_id, source_type, **kwargs):
    """Add a citation source. Returns source dict."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO family_sources
               (user_id, source_type, external_id, title, url, citation)
               VALUES (%s, %s, %s, %s, %s, %s) RETURNING *""",
            (
                user_id, source_type,
                kwargs.get("external_id"), kwargs.get("title"),
                kwargs.get("url"), kwargs.get("citation"),
            ),
        )
        return dict(cur.fetchone())


def link_source_to_person(person_id, source_id, field_name):
    """Link a source to a person field (e.g., 'birth_date')."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            """INSERT INTO family_person_sources (person_id, source_id, field_name)
               VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
            (person_id, source_id, field_name),
        )


def get_person_sources(person_id):
    """Get all sources for a person."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT s.*, ps.field_name
               FROM family_sources s
               JOIN family_person_sources ps ON ps.source_id = s.id
               WHERE ps.person_id = %s
               ORDER BY s.retrieved_at DESC""",
            (person_id,),
        )
        return [dict(r) for r in cur.fetchall()]
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/family_tree/services/__init__.py
git add platform_v2/tools/family_tree/services/tree_service.py
git commit -m "feat(family-tree): tree service — person/relationship CRUD + recursive ancestor queries"
```

---

## Task 3: GEDCOM Service (Import/Export)

**Files:**
- Create: `platform_v2/tools/family_tree/services/gedcom_service.py`

- [ ] **Step 1: Add ged4py to requirements**

Add to `platform_v2/requirements.txt`:
```
ged4py>=0.4.0
```

- [ ] **Step 2: Write gedcom_service.py**

```python
"""GEDCOM 5.5.1 import/export for family trees via ged4py."""

import io
import logging
from datetime import datetime

from ged4py.parser import GedcomReader

from .tree_service import create_person, add_relationship, add_source, link_source_to_person

logger = logging.getLogger(__name__)


def import_gedcom(user_id, file_content):
    """
    Import a GEDCOM file into the user's family tree.
    Returns dict with counts: {persons_created, relationships_created, errors}.
    """
    stats = {"persons_created": 0, "relationships_created": 0, "errors": []}
    indi_map = {}  # GEDCOM INDI id -> our person_id

    try:
        reader = GedcomReader(io.BytesIO(file_content))
    except Exception as e:
        stats["errors"].append(f"Failed to parse GEDCOM: {e}")
        return stats

    # Pass 1: Create all individuals
    for record in reader.records0("INDI"):
        try:
            name = record.name
            first_name = name.first if name else ""
            last_name = name.surname if name else ""
            maiden_name = name.maiden if hasattr(name, "maiden") else None

            birth = record.sub_tag("BIRT")
            birth_date = _parse_gedcom_date(birth.sub_tag_value("DATE")) if birth else None
            birth_place = birth.sub_tag_value("PLAC") if birth else None

            death = record.sub_tag("DEAT")
            death_date = _parse_gedcom_date(death.sub_tag_value("DATE")) if death else None
            death_place = death.sub_tag_value("PLAC") if death else None

            sex = record.sub_tag_value("SEX")
            gender = {"M": "male", "F": "female"}.get(sex, "unknown")

            person = create_person(
                user_id, first_name, last_name,
                maiden_name=maiden_name,
                gender=gender,
                birth_date=birth_date,
                birth_place=birth_place,
                death_date=death_date,
                death_place=death_place,
                source_type="gedcom_import",
            )
            indi_map[record.xref_id] = person["id"]
            stats["persons_created"] += 1
        except Exception as e:
            stats["errors"].append(f"INDI {getattr(record, 'xref_id', '?')}: {e}")

    # Pass 2: Create relationships from FAM records
    for record in reader.records0("FAM"):
        try:
            husb_ref = record.sub_tag_value("HUSB")
            wife_ref = record.sub_tag_value("WIFE")

            husb_id = indi_map.get(husb_ref) if husb_ref else None
            wife_id = indi_map.get(wife_ref) if wife_ref else None

            # Spouse relationship
            if husb_id and wife_id:
                add_relationship(user_id, husb_id, wife_id, "spouse")
                stats["relationships_created"] += 1

            # Parent-child relationships
            for child_tag in record.sub_tags("CHIL"):
                child_ref = child_tag.value
                child_id = indi_map.get(child_ref)
                if child_id:
                    if husb_id:
                        add_relationship(user_id, husb_id, child_id, "parent_child")
                        stats["relationships_created"] += 1
                    if wife_id:
                        add_relationship(user_id, wife_id, child_id, "parent_child")
                        stats["relationships_created"] += 1
        except Exception as e:
            stats["errors"].append(f"FAM {getattr(record, 'xref_id', '?')}: {e}")

    # Add import source
    source = add_source(user_id, "gedcom_import", title="GEDCOM Import")
    for person_id in indi_map.values():
        link_source_to_person(person_id, source["id"], "all")

    return stats


def export_gedcom(user_id, persons, relationships):
    """
    Export a family tree to GEDCOM 5.5.1 format.
    Returns GEDCOM file content as string.
    """
    lines = []
    lines.append("0 HEAD")
    lines.append("1 SOUR ARCHIE-FAMILY-TREE")
    lines.append("2 VERS 1.0")
    lines.append("1 GEDC")
    lines.append("2 VERS 5.5.1")
    lines.append("2 FORM LINEAGE-LINKED")
    lines.append("1 CHAR UTF-8")
    lines.append(f"1 DATE {datetime.now().strftime('%d %b %Y').upper()}")

    person_xref = {}  # person_id -> @I{n}@

    # Write INDI records
    for i, person in enumerate(persons, 1):
        xref = f"@I{i}@"
        person_xref[person["id"]] = xref
        lines.append(f"0 {xref} INDI")
        first = person.get("first_name", "")
        last = person.get("last_name", "")
        lines.append(f"1 NAME {first} /{last}/")
        if person.get("gender"):
            sex = {"male": "M", "female": "F"}.get(person["gender"], "U")
            lines.append(f"1 SEX {sex}")
        if person.get("birth_date") or person.get("birth_place"):
            lines.append("1 BIRT")
            if person.get("birth_date"):
                lines.append(f"2 DATE {_format_gedcom_date(person['birth_date'])}")
            if person.get("birth_place"):
                lines.append(f"2 PLAC {person['birth_place']}")
        if person.get("death_date") or person.get("death_place"):
            lines.append("1 DEAT")
            if person.get("death_date"):
                lines.append(f"2 DATE {_format_gedcom_date(person['death_date'])}")
            if person.get("death_place"):
                lines.append(f"2 PLAC {person['death_place']}")

    # Build FAM records from relationships
    families = _build_families(relationships, person_xref)
    for i, fam in enumerate(families, 1):
        xref = f"@F{i}@"
        lines.append(f"0 {xref} FAM")
        if fam.get("husb"):
            lines.append(f"1 HUSB {fam['husb']}")
        if fam.get("wife"):
            lines.append(f"1 WIFE {fam['wife']}")
        for child in fam.get("children", []):
            lines.append(f"1 CHIL {child}")

    lines.append("0 TRLR")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_gedcom_date(date_str):
    """Parse a GEDCOM date string to Python date. Returns None on failure."""
    if not date_str:
        return None
    # Strip qualifiers like ABT, BEF, AFT, etc.
    cleaned = date_str.strip()
    for prefix in ("ABT", "BEF", "AFT", "EST", "CAL", "FROM", "TO", "BET", "AND"):
        cleaned = cleaned.replace(prefix, "").strip()
    formats = ["%d %b %Y", "%b %Y", "%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _format_gedcom_date(date_val):
    """Format a date to GEDCOM string."""
    if isinstance(date_val, str):
        try:
            date_val = datetime.strptime(date_val, "%Y-%m-%d").date()
        except ValueError:
            return date_val
    return date_val.strftime("%d %b %Y").upper()


def _build_families(relationships, person_xref):
    """Group relationships into FAM records."""
    families = []
    spouse_pairs = set()

    for rel in relationships:
        if rel["relationship_type"] == "spouse":
            a = person_xref.get(rel["person_a_id"])
            b = person_xref.get(rel["person_b_id"])
            if a and b:
                pair = tuple(sorted([a, b]))
                if pair not in spouse_pairs:
                    spouse_pairs.add(pair)
                    families.append({"husb": pair[0], "wife": pair[1], "children": []})

    # Add children to families
    for rel in relationships:
        if rel["relationship_type"] == "parent_child":
            parent = person_xref.get(rel["person_a_id"])
            child = person_xref.get(rel["person_b_id"])
            if parent and child:
                for fam in families:
                    if parent in (fam.get("husb"), fam.get("wife")):
                        if child not in fam["children"]:
                            fam["children"].append(child)
                        break
                else:
                    # Single parent — create family with just this parent
                    families.append({"husb": parent, "wife": None, "children": [child]})

    return families
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/family_tree/services/gedcom_service.py
git commit -m "feat(family-tree): GEDCOM 5.5.1 import/export service via ged4py"
```

---

## Task 4: Research Service (External API Clients)

**Files:**
- Create: `platform_v2/tools/family_tree/services/research_service.py`

- [ ] **Step 1: Write research_service.py**

```python
"""External API clients for genealogy record searching.

Wraps FamilySearch, WikiTree, Chronicling America, NARA Catalog, and Europeana.
Each search function returns a list of result dicts with confidence scores.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

# API configuration
FAMILYSEARCH_BASE = "https://api.familysearch.org"
WIKITREE_BASE = "https://api.wikitree.com/api.php"
CHRONICLING_AMERICA_BASE = "https://chroniclingamerica.loc.gov"
NARA_BASE = "https://catalog.archives.gov/api/v2"
EUROPEANA_BASE = "https://api.europeana.eu/record/v2"

REQUEST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# FamilySearch (OAuth2 required)
# ---------------------------------------------------------------------------

def search_familysearch(first_name, last_name, **kwargs):
    """
    Search FamilySearch historical records.
    Requires FAMILYSEARCH_ACCESS_TOKEN env var (OAuth2 token).
    kwargs: birth_date, birth_place, death_date, death_place, spouse_name
    """
    token = os.getenv("FAMILYSEARCH_ACCESS_TOKEN")
    if not token:
        logger.warning("FAMILYSEARCH_ACCESS_TOKEN not set — skipping FamilySearch search")
        return []

    params = {
        "q.givenName": first_name,
        "q.surname": last_name,
        "count": 20,
    }
    if kwargs.get("birth_place"):
        params["q.birthLikePlace"] = kwargs["birth_place"]
    if kwargs.get("birth_date"):
        params["q.birthLikeDate"] = str(kwargs["birth_date"])
    if kwargs.get("death_date"):
        params["q.deathLikeDate"] = str(kwargs["death_date"])

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    try:
        resp = requests.get(
            f"{FAMILYSEARCH_BASE}/platform/tree/search",
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for entry in data.get("entries", []):
            person = entry.get("content", {}).get("gedcomx", {}).get("persons", [{}])[0]
            names = person.get("names", [{}])
            name_parts = names[0].get("nameForms", [{}])[0].get("parts", []) if names else []
            given = next((p["value"] for p in name_parts if p.get("type", "").endswith("Given")), "")
            surname = next((p["value"] for p in name_parts if p.get("type", "").endswith("Surname")), "")

            facts = {f.get("type", "").split("/")[-1]: f for f in person.get("facts", [])}
            birth_fact = facts.get("Birth", {})
            death_fact = facts.get("Death", {})

            results.append({
                "source": "familysearch",
                "external_id": entry.get("id", ""),
                "title": f"{given} {surname}",
                "first_name": given,
                "last_name": surname,
                "birth_date": birth_fact.get("date", {}).get("original"),
                "birth_place": birth_fact.get("place", {}).get("original"),
                "death_date": death_fact.get("date", {}).get("original"),
                "death_place": death_fact.get("place", {}).get("original"),
                "score": entry.get("score", 0),
                "url": f"https://www.familysearch.org/tree/person/{entry.get('id', '')}",
            })

        return results

    except requests.RequestException as e:
        logger.error(f"FamilySearch search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# WikiTree (API key)
# ---------------------------------------------------------------------------

def search_wikitree(first_name, last_name, **kwargs):
    """Search WikiTree for matching profiles."""
    try:
        params = {
            "action": "searchPerson",
            "FirstName": first_name,
            "LastName": last_name,
            "format": "json",
        }
        if kwargs.get("birth_date"):
            params["BirthDate"] = str(kwargs["birth_date"])

        resp = requests.get(WIKITREE_BASE, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for person in data.get("searchPerson", []):
            results.append({
                "source": "wikitree",
                "external_id": person.get("Name", ""),
                "title": f"{person.get('FirstName', '')} {person.get('LastNameCurrent', '')}",
                "first_name": person.get("FirstName", ""),
                "last_name": person.get("LastNameCurrent", ""),
                "birth_date": person.get("BirthDate"),
                "birth_place": person.get("BirthLocation"),
                "death_date": person.get("DeathDate"),
                "death_place": person.get("DeathLocation"),
                "score": 0,
                "url": f"https://www.wikitree.com/wiki/{person.get('Name', '')}",
            })

        return results

    except requests.RequestException as e:
        logger.error(f"WikiTree search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Chronicling America (no auth)
# ---------------------------------------------------------------------------

def search_chronicling_america(query, **kwargs):
    """
    Search historical US newspapers for family mentions.
    query: full text search (e.g., "Manuel da Silva immigration")
    """
    try:
        params = {
            "terms": query,
            "format": "json",
            "page": 1,
            "rows": 20,
        }
        if kwargs.get("date_from"):
            params["dateFilterType"] = "range"
            params["date1"] = kwargs["date_from"]
        if kwargs.get("date_to"):
            params["date2"] = kwargs["date_to"]

        resp = requests.get(
            f"{CHRONICLING_AMERICA_BASE}/search/pages/results/",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("items", []):
            results.append({
                "source": "chronicling_america",
                "external_id": item.get("id", ""),
                "title": item.get("title", "Newspaper Article"),
                "date": item.get("date", ""),
                "newspaper": item.get("title", ""),
                "snippet": item.get("ocr_eng", "")[:500],
                "url": item.get("url", ""),
                "score": item.get("score", 0),
            })

        return results

    except requests.RequestException as e:
        logger.error(f"Chronicling America search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# NARA Catalog (no auth)
# ---------------------------------------------------------------------------

def search_nara(query, **kwargs):
    """Search US National Archives catalog for immigration/military records."""
    try:
        params = {
            "q": query,
            "limit": 20,
        }

        resp = requests.get(
            f"{NARA_BASE}/search",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("body", {}).get("hits", {}).get("hits", []):
            source = item.get("_source", {})
            results.append({
                "source": "nara",
                "external_id": source.get("naId", ""),
                "title": source.get("title", ""),
                "description": source.get("scopeAndContentNote", "")[:500],
                "date": source.get("inclusiveDates", {}).get("inclusiveDateText", ""),
                "url": f"https://catalog.archives.gov/id/{source.get('naId', '')}",
                "score": item.get("_score", 0),
            })

        return results

    except requests.RequestException as e:
        logger.error(f"NARA search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Europeana (API key required)
# ---------------------------------------------------------------------------

def search_europeana(query, **kwargs):
    """Search Europeana for European cultural heritage records."""
    api_key = os.getenv("EUROPEANA_API_KEY")
    if not api_key:
        logger.warning("EUROPEANA_API_KEY not set — skipping Europeana search")
        return []

    try:
        params = {
            "query": query,
            "wskey": api_key,
            "rows": 20,
        }
        if kwargs.get("country"):
            params["qf"] = f"COUNTRY:{kwargs['country']}"

        resp = requests.get(
            f"{EUROPEANA_BASE}/search.json",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in data.get("items", []):
            results.append({
                "source": "europeana",
                "external_id": item.get("id", ""),
                "title": (item.get("title", [""])[0] if isinstance(item.get("title"), list)
                          else item.get("title", "")),
                "description": (item.get("dcDescription", [""])[0][:500]
                                if item.get("dcDescription") else ""),
                "date": item.get("year", [""])[0] if item.get("year") else "",
                "url": item.get("guid", ""),
                "thumbnail": item.get("edmPreview", [""])[0] if item.get("edmPreview") else "",
                "score": item.get("score", 0),
            })

        return results

    except requests.RequestException as e:
        logger.error(f"Europeana search failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Unified Search (dispatches to all sources)
# ---------------------------------------------------------------------------

def search_all_sources(first_name, last_name, **kwargs):
    """
    Search all available sources for a person.
    Returns combined results sorted by score descending.
    """
    results = []

    results.extend(search_familysearch(first_name, last_name, **kwargs))
    results.extend(search_wikitree(first_name, last_name, **kwargs))

    # Newspaper/archive search uses full name as query
    full_name = f"{first_name} {last_name}"
    results.extend(search_chronicling_america(full_name, **kwargs))
    results.extend(search_nara(full_name, **kwargs))

    # Europeana with country filter if known
    europeana_kwargs = dict(kwargs)
    if kwargs.get("birth_place"):
        place = kwargs["birth_place"].lower()
        if "portugal" in place:
            europeana_kwargs["country"] = "portugal"
        elif "france" in place or "francia" in place:
            europeana_kwargs["country"] = "france"
    results.extend(search_europeana(full_name, **europeana_kwargs))

    # Sort by score descending
    results.sort(key=lambda r: r.get("score", 0), reverse=True)
    return results
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/family_tree/services/research_service.py
git commit -m "feat(family-tree): research service — FamilySearch, WikiTree, NARA, Chronicling America, Europeana clients"
```

---

## Task 5: OCR Service (Document Processing)

**Files:**
- Create: `platform_v2/tools/family_tree/services/ocr_service.py`

- [ ] **Step 1: Add pytesseract to requirements**

Add to `platform_v2/requirements.txt`:
```
pytesseract>=0.3.10
```

Add to `Dockerfile` (apt-get section):
```
tesseract-ocr tesseract-ocr-por tesseract-ocr-fra
```

- [ ] **Step 2: Write ocr_service.py**

```python
"""OCR service — Tesseract for print, Transkribus API for handwriting."""

import json
import logging
import os

import pytesseract
from PIL import Image

from bridge_dispatcher import dispatch

logger = logging.getLogger(__name__)

TRANSKRIBUS_BASE = "https://transkribus.eu/TrpServer/rest"


def ocr_document(file_path, language="por+fra+eng"):
    """
    Run OCR on a document image using Tesseract.
    Returns extracted text string.
    """
    try:
        image = Image.open(file_path)
        text = pytesseract.image_to_string(image, lang=language)
        return text.strip()
    except Exception as e:
        logger.error(f"OCR failed for {file_path}: {e}")
        return ""


def extract_structured_data(ocr_text, document_type="unknown"):
    """
    Use LLM via Bridge dispatch to extract structured genealogy data from OCR text.
    Returns dict with extracted fields.
    """
    prompt = f"""Extract genealogy information from this {document_type} document text.
Return ONLY valid JSON with these fields (use null for missing):
{{
    "persons": [
        {{
            "first_name": "",
            "last_name": "",
            "role": "subject/parent/spouse/witness",
            "birth_date": "YYYY-MM-DD or null",
            "birth_place": "",
            "death_date": "YYYY-MM-DD or null",
            "death_place": "",
            "gender": "male/female/unknown"
        }}
    ],
    "event_type": "birth/marriage/death/immigration/baptism/other",
    "event_date": "YYYY-MM-DD or null",
    "event_place": "",
    "notes": ""
}}

Document text:
{ocr_text}"""

    result = dispatch(
        prompt=prompt,
        capability="text_analysis",
        system_prompt="You are a genealogy document analyst. Extract structured data from OCR text. Return only valid JSON.",
        temperature=0.1,
    )

    if not result.success:
        logger.error(f"Bridge dispatch failed for data extraction: {result.error}")
        return {}

    try:
        # Try to parse JSON from the response
        response_text = result.response.strip()
        # Handle markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(response_text)
    except (json.JSONDecodeError, IndexError) as e:
        logger.error(f"Failed to parse extracted data: {e}")
        return {}


def process_document(file_path, document_type="unknown", language="por+fra+eng"):
    """
    Full pipeline: OCR → structured extraction.
    Returns (ocr_text, extracted_data) tuple.
    """
    ocr_text = ocr_document(file_path, language)
    if not ocr_text:
        return "", {}

    extracted_data = extract_structured_data(ocr_text, document_type)
    return ocr_text, extracted_data
```

- [ ] **Step 3: Commit**

```bash
git add platform_v2/tools/family_tree/services/ocr_service.py
git commit -m "feat(family-tree): OCR service — Tesseract + Bridge LLM extraction pipeline"
```

---

## Task 6: Face Service (Photo Analysis)

**Files:**
- Create: `platform_v2/tools/family_tree/services/face_service.py`

- [ ] **Step 1: Write face_service.py**

```python
"""Face detection, embedding, and clustering for family photo matching.

Uses InsightFace for detection/embedding and DBSCAN for clustering.
Falls back to a stub if insightface is not installed (graceful degradation).
"""

import json
import logging

import numpy as np
from database import get_db_cursor

logger = logging.getLogger(__name__)

# Lazy-load InsightFace (heavy dependency, may not be installed)
_face_app = None


def _get_face_app():
    """Lazy-init InsightFace model. Returns None if not available."""
    global _face_app
    if _face_app is not None:
        return _face_app
    try:
        from insightface.app import FaceAnalysis
        _face_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        _face_app.prepare(ctx_id=0, det_size=(640, 640))
        return _face_app
    except ImportError:
        logger.warning("insightface not installed — face detection disabled")
        return None
    except Exception as e:
        logger.error(f"Failed to init InsightFace: {e}")
        return None


def detect_faces(image_path):
    """
    Detect faces in an image and return embeddings + bounding boxes.
    Returns list of dicts: [{embedding: np.array(512), bbox: [x1,y1,x2,y2], ...}]
    """
    app = _get_face_app()
    if app is None:
        return []

    try:
        import cv2
        img = cv2.imread(image_path)
        if img is None:
            logger.error(f"Could not read image: {image_path}")
            return []

        faces = app.get(img)
        results = []
        for face in faces:
            results.append({
                "embedding": face.embedding,  # numpy array, 512-dim
                "bbox": face.bbox.tolist(),  # [x1, y1, x2, y2]
                "det_score": float(face.det_score),
                "age": int(face.age) if hasattr(face, "age") else None,
                "gender": "female" if (hasattr(face, "gender") and face.gender == 0) else "male",
            })
        return results

    except Exception as e:
        logger.error(f"Face detection failed for {image_path}: {e}")
        return []


def save_face_embeddings(user_id, document_id, faces):
    """Save detected face embeddings to database."""
    with get_db_cursor(commit=True) as (conn, cur):
        for face in faces:
            cur.execute(
                """INSERT INTO family_face_embeddings
                   (user_id, document_id, embedding, bounding_box, confidence_score)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (
                    user_id, document_id,
                    face["embedding"].tobytes(),
                    json.dumps(face["bbox"]),
                    face.get("det_score", 0.0),
                ),
            )


def cluster_faces(user_id):
    """
    Cluster all face embeddings for a user using DBSCAN.
    Updates cluster_id on family_face_embeddings rows.
    Returns number of clusters found.
    """
    with get_db_cursor() as (conn, cur):
        cur.execute(
            "SELECT id, embedding FROM family_face_embeddings WHERE user_id = %s AND embedding IS NOT NULL",
            (user_id,),
        )
        rows = cur.fetchall()

    if len(rows) < 2:
        return 0

    embeddings = []
    ids = []
    for row in rows:
        emb = np.frombuffer(row["embedding"], dtype=np.float32)
        if emb.shape[0] == 512:
            embeddings.append(emb)
            ids.append(row["id"])

    if len(embeddings) < 2:
        return 0

    from sklearn.cluster import DBSCAN

    # Normalize embeddings for cosine distance
    matrix = np.array(embeddings)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    matrix = matrix / norms

    clustering = DBSCAN(eps=0.5, min_samples=2, metric="cosine").fit(matrix)

    with get_db_cursor(commit=True) as (conn, cur):
        for face_id, label in zip(ids, clustering.labels_):
            cluster_id = int(label) if label >= 0 else None
            cur.execute(
                "UPDATE family_face_embeddings SET cluster_id = %s WHERE id = %s",
                (cluster_id, face_id),
            )

    n_clusters = len(set(clustering.labels_) - {-1})
    return n_clusters


def get_face_clusters(user_id):
    """Get face clusters with document info for the photo gallery UI."""
    with get_db_cursor() as (conn, cur):
        cur.execute(
            """SELECT fe.id, fe.document_id, fe.person_id, fe.cluster_id,
                      fe.bounding_box, fe.confidence_score, fe.estimated_era,
                      fd.filename, fd.file_path
               FROM family_face_embeddings fe
               JOIN family_documents fd ON fd.id = fe.document_id
               WHERE fe.user_id = %s
               ORDER BY fe.cluster_id NULLS LAST, fe.id""",
            (user_id,),
        )
        return [dict(r) for r in cur.fetchall()]


def label_face(face_id, person_id):
    """Link a detected face to a person in the tree."""
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "UPDATE family_face_embeddings SET person_id = %s WHERE id = %s",
            (person_id, face_id),
        )


## NOTE: Move `import json` to the top of face_service.py (used in save_face_embeddings)
```

- [ ] **Step 2: Commit**

```bash
git add platform_v2/tools/family_tree/services/face_service.py
git commit -m "feat(family-tree): face service — InsightFace detection, DBSCAN clustering, labeling"
```

---

## Task 7: Blueprint, Routes & Module Registration

**Files:**
- Create: `platform_v2/tools/family_tree/__init__.py`
- Create: `platform_v2/tools/family_tree/routes.py`
- Create: `platform_v2/tools/family_tree/research_routes.py`
- Create: `platform_v2/tools/family_tree/document_routes.py`
- Create: `platform_v2/tools/family_tree/photo_routes.py`
- Create: `platform_v2/tools/family_tree/timeline_routes.py`
- Modify: `platform_v2/module_registry.py`

- [ ] **Step 1: Write __init__.py**

```python
"""Family Tree — AI-Powered Genealogy Module.

5 specialized agents (H.E.R.I.T.A.G.E., S.C.R.O.L.L., Q.U.I.L.L.,
V.I.S.A.G.E., R.E.S.T.O.R.E.) that autonomously search public records,
OCR documents, match faces in photos, and build family trees.
"""

from functools import wraps

from flask import Blueprint, redirect, url_for
from flask_login import current_user

family_tree_bp = Blueprint(
    "family_tree",
    __name__,
    url_prefix="/tools/family-tree",
    template_folder="templates",
    static_folder="static",
)


def admin_required(f):
    """Require admin access — matches pattern used across all modules."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


from . import routes  # noqa: E402, F401
from .research_routes import register_research_routes  # noqa: E402
from .document_routes import register_document_routes  # noqa: E402
from .photo_routes import register_photo_routes  # noqa: E402
from .timeline_routes import register_timeline_routes  # noqa: E402

register_research_routes(family_tree_bp, admin_required)
register_document_routes(family_tree_bp, admin_required)
register_photo_routes(family_tree_bp, admin_required)
register_timeline_routes(family_tree_bp, admin_required)
```

- [ ] **Step 2: Write routes.py (main dashboard + tree CRUD)**

```python
"""Family Tree — main dashboard, tree CRUD, GEDCOM import/export."""

import io

from flask import jsonify, render_template, request, send_file
from flask_login import current_user, login_required

from . import family_tree_bp
from .services.tree_service import (
    add_relationship,
    create_person,
    delete_person,
    get_full_tree,
    get_person,
    get_person_sources,
    list_persons,
    remove_relationship,
    update_person,
)
from .services.gedcom_service import export_gedcom, import_gedcom


@family_tree_bp.route("/")
@login_required
def index():
    """Family Tree dashboard."""
    return render_template("family_tree.html")


@family_tree_bp.route("/api/status")
@login_required
def status():
    """Health check endpoint."""
    return jsonify({"status": "ok", "module": "family_tree"})


# ---------------------------------------------------------------------------
# Tree Data
# ---------------------------------------------------------------------------

@family_tree_bp.route("/api/tree")
@login_required
def api_tree():
    """Get full tree data for d3 visualization."""
    data = get_full_tree(current_user.id)
    return jsonify(data)


# ---------------------------------------------------------------------------
# Person CRUD
# ---------------------------------------------------------------------------

@family_tree_bp.route("/api/persons", methods=["GET"])
@login_required
def api_list_persons():
    """List all persons in user's tree."""
    return jsonify(list_persons(current_user.id))


@family_tree_bp.route("/api/persons", methods=["POST"])
@login_required
def api_create_person():
    """Create a new person."""
    data = request.get_json()
    if not data or not data.get("first_name"):
        return jsonify({"error": "first_name is required"}), 400
    person = create_person(
        current_user.id,
        data["first_name"],
        data.get("last_name", ""),
        **{k: v for k, v in data.items() if k not in ("first_name", "last_name")},
    )
    return jsonify(person), 201


@family_tree_bp.route("/api/persons/<int:person_id>", methods=["GET"])
@login_required
def api_get_person(person_id):
    """Get a single person with their sources."""
    person = get_person(current_user.id, person_id)
    if not person:
        return jsonify({"error": "Not found"}), 404
    person["sources"] = get_person_sources(person_id)
    return jsonify(person)


@family_tree_bp.route("/api/persons/<int:person_id>", methods=["PUT"])
@login_required
def api_update_person(person_id):
    """Update a person."""
    data = request.get_json()
    person = update_person(current_user.id, person_id, **data)
    if not person:
        return jsonify({"error": "Not found"}), 404
    return jsonify(person)


@family_tree_bp.route("/api/persons/<int:person_id>", methods=["DELETE"])
@login_required
def api_delete_person(person_id):
    """Delete a person (cascades relationships)."""
    if delete_person(current_user.id, person_id):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Not found"}), 404


# ---------------------------------------------------------------------------
# Relationships
# ---------------------------------------------------------------------------

@family_tree_bp.route("/api/relationships", methods=["POST"])
@login_required
def api_add_relationship():
    """Add a relationship between two persons."""
    data = request.get_json()
    required = ["person_a_id", "person_b_id", "relationship_type"]
    if not data or not all(data.get(k) for k in required):
        return jsonify({"error": "person_a_id, person_b_id, relationship_type required"}), 400
    rel = add_relationship(
        current_user.id,
        data["person_a_id"],
        data["person_b_id"],
        data["relationship_type"],
        **{k: v for k, v in data.items() if k not in required},
    )
    if not rel:
        return jsonify({"error": "Relationship already exists"}), 409
    return jsonify(rel), 201


@family_tree_bp.route("/api/relationships/<int:rel_id>", methods=["DELETE"])
@login_required
def api_remove_relationship(rel_id):
    """Remove a relationship."""
    if remove_relationship(current_user.id, rel_id):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Not found"}), 404


# ---------------------------------------------------------------------------
# GEDCOM Import/Export
# ---------------------------------------------------------------------------

@family_tree_bp.route("/api/gedcom/import", methods=["POST"])
@login_required
def api_import_gedcom():
    """Import a GEDCOM file."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file.filename.lower().endswith((".ged", ".gedcom")):
        return jsonify({"error": "File must be .ged or .gedcom"}), 400
    content = file.read()
    stats = import_gedcom(current_user.id, content)
    return jsonify(stats)


@family_tree_bp.route("/api/gedcom/export")
@login_required
def api_export_gedcom():
    """Export user's tree as GEDCOM file."""
    data = get_full_tree(current_user.id)
    gedcom_str = export_gedcom(current_user.id, data["persons"], data["relationships"])
    return send_file(
        io.BytesIO(gedcom_str.encode("utf-8")),
        mimetype="text/plain",
        as_attachment=True,
        download_name="family_tree.ged",
    )
```

- [ ] **Step 3: Write research_routes.py**

```python
"""Research routes — AI research queue, findings review, accept/reject."""

from flask import jsonify, request
from flask_login import current_user, login_required
from psycopg2.extras import Json

from database import get_db_cursor


def register_research_routes(bp, admin_required):
    """Register research routes on the family_tree blueprint."""

    @bp.route("/api/research/queue", methods=["GET"])
    @login_required
    def api_research_queue():
        """Get all research queue items for user."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT rq.*, fp.first_name, fp.last_name
                   FROM family_research_queue rq
                   LEFT JOIN family_persons fp ON fp.id = rq.person_id
                   WHERE rq.user_id = %s
                   ORDER BY rq.created_at DESC""",
                (current_user.id,),
            )
            return jsonify([dict(r) for r in cur.fetchall()])

    @bp.route("/api/research/start", methods=["POST"])
    @login_required
    def api_start_research():
        """Queue a new research task for a person."""
        data = request.get_json()
        if not data or not data.get("person_id") or not data.get("research_type"):
            return jsonify({"error": "person_id and research_type required"}), 400

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO family_research_queue
                   (user_id, person_id, research_type, query_params, agent_name)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (
                    current_user.id,
                    data["person_id"],
                    data["research_type"],
                    Json(data.get("params", {})),
                    "S.C.R.O.L.L.",
                ),
            )
            return jsonify(dict(cur.fetchone())), 201

    @bp.route("/api/research/<int:research_id>/accept", methods=["POST"])
    @login_required
    def api_accept_finding(research_id):
        """Accept a research finding — adds data to tree."""
        data = request.get_json() or {}

        with get_db_cursor(commit=True) as (conn, cur):
            # Mark as reviewed
            cur.execute(
                """UPDATE family_research_queue SET status = 'reviewed'
                   WHERE id = %s AND user_id = %s RETURNING *""",
                (research_id, current_user.id),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Not found"}), 404

            return jsonify({"status": "accepted", "research": dict(row)})

    @bp.route("/api/research/<int:research_id>/reject", methods=["POST"])
    @login_required
    def api_reject_finding(research_id):
        """Reject a research finding."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE family_research_queue SET status = 'reviewed',
                   results = results || '{"rejected": true}'::jsonb
                   WHERE id = %s AND user_id = %s RETURNING *""",
                (research_id, current_user.id),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Not found"}), 404
            return jsonify({"status": "rejected"})
```

- [ ] **Step 4: Write document_routes.py**

```python
"""Document routes — upload, OCR trigger, extracted data, link to person."""

import os
import uuid

from flask import current_app, jsonify, request
from flask_login import current_user, login_required

from database import get_db_cursor
from psycopg2.extras import Json


UPLOAD_DIR = "/mnt/archie_brain/platform_v2/uploads/family_tree"


def register_document_routes(bp, admin_required):
    """Register document routes on the family_tree blueprint."""

    @bp.route("/api/documents", methods=["GET"])
    @login_required
    def api_list_documents():
        """List all documents for user."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT * FROM family_documents
                   WHERE user_id = %s ORDER BY uploaded_at DESC""",
                (current_user.id,),
            )
            return jsonify([dict(r) for r in cur.fetchall()])

    @bp.route("/api/documents/upload", methods=["POST"])
    @login_required
    def api_upload_document():
        """Upload a document (image or PDF)."""
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        document_type = request.form.get("document_type", "other")

        # Save file
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        ext = os.path.splitext(file.filename)[1].lower()
        safe_name = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        file.save(file_path)

        # Create DB record
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO family_documents
                   (user_id, filename, file_path, file_type, document_type)
                   VALUES (%s, %s, %s, %s, %s) RETURNING *""",
                (current_user.id, file.filename, file_path, ext.lstrip("."), document_type),
            )
            doc = dict(cur.fetchone())

        return jsonify(doc), 201

    @bp.route("/api/documents/<int:doc_id>/ocr", methods=["POST"])
    @login_required
    def api_trigger_ocr(doc_id):
        """Trigger OCR processing on a document."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT * FROM family_documents WHERE id = %s AND user_id = %s",
                (doc_id, current_user.id),
            )
            doc = cur.fetchone()
            if not doc:
                return jsonify({"error": "Not found"}), 404

            # Update status to processing
            cur.execute(
                "UPDATE family_documents SET ocr_status = 'processing' WHERE id = %s",
                (doc_id,),
            )

        # Run OCR (synchronous for now — can be moved to agent loop job later)
        from .services.ocr_service import process_document

        ocr_text, extracted_data = process_document(
            doc["file_path"], doc["document_type"]
        )

        status = "completed" if ocr_text else "failed"
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE family_documents
                   SET ocr_text = %s, extracted_data = %s, ocr_status = %s
                   WHERE id = %s""",
                (ocr_text, Json(extracted_data), status, doc_id),
            )
            cur.execute(
                "SELECT * FROM family_documents WHERE id = %s",
                (doc_id,),
            )
            return jsonify(dict(cur.fetchone()))

    @bp.route("/api/documents/<int:doc_id>/link", methods=["POST"])
    @login_required
    def api_link_document(doc_id):
        """Link a document to a person."""
        data = request.get_json()
        if not data or not data.get("person_id"):
            return jsonify({"error": "person_id required"}), 400

        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """UPDATE family_documents SET linked_person_id = %s
                   WHERE id = %s AND user_id = %s RETURNING *""",
                (data["person_id"], doc_id, current_user.id),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Not found"}), 404
            return jsonify(dict(row))

    @bp.route("/api/documents/<int:doc_id>", methods=["DELETE"])
    @login_required
    def api_delete_document(doc_id):
        """Delete a document and its file."""
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                "SELECT file_path FROM family_documents WHERE id = %s AND user_id = %s",
                (doc_id, current_user.id),
            )
            row = cur.fetchone()
            if not row:
                return jsonify({"error": "Not found"}), 404

            # Delete file
            if row["file_path"] and os.path.exists(row["file_path"]):
                os.remove(row["file_path"])

            cur.execute("DELETE FROM family_documents WHERE id = %s", (doc_id,))
            return jsonify({"status": "deleted"})
```

- [ ] **Step 5: Write photo_routes.py**

```python
"""Photo routes — upload, face detection, clustering, restore trigger."""

import os
import uuid

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from database import get_db_cursor


UPLOAD_DIR = "/mnt/archie_brain/platform_v2/uploads/family_tree"


def register_photo_routes(bp, admin_required):
    """Register photo routes on the family_tree blueprint."""

    @bp.route("/api/photos", methods=["GET"])
    @login_required
    def api_list_photos():
        """List all photos (documents with photo file types)."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT * FROM family_documents
                   WHERE user_id = %s AND file_type IN ('jpg', 'jpeg', 'png', 'webp', 'tiff')
                   ORDER BY uploaded_at DESC""",
                (current_user.id,),
            )
            return jsonify([dict(r) for r in cur.fetchall()])

    @bp.route("/api/photos/upload", methods=["POST"])
    @login_required
    def api_upload_photo():
        """Upload a photo and auto-detect faces."""
        if "file" not in request.files:
            return jsonify({"error": "No file uploaded"}), 400

        file = request.files["file"]
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".tiff"):
            return jsonify({"error": "Must be an image file"}), 400

        os.makedirs(UPLOAD_DIR, exist_ok=True)
        safe_name = f"{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(UPLOAD_DIR, safe_name)
        file.save(file_path)

        # Create document record
        with get_db_cursor(commit=True) as (conn, cur):
            cur.execute(
                """INSERT INTO family_documents
                   (user_id, filename, file_path, file_type, document_type, ocr_status)
                   VALUES (%s, %s, %s, %s, 'photo', 'completed') RETURNING *""",
                (current_user.id, file.filename, file_path, ext.lstrip(".")),
            )
            doc = dict(cur.fetchone())

        # Auto-detect faces
        from .services.face_service import detect_faces, save_face_embeddings

        faces = detect_faces(file_path)
        if faces:
            save_face_embeddings(current_user.id, doc["id"], faces)

        doc["faces_detected"] = len(faces)
        return jsonify(doc), 201

    @bp.route("/api/photos/faces", methods=["GET"])
    @login_required
    def api_face_clusters():
        """Get all face clusters for the photo gallery."""
        from .services.face_service import get_face_clusters
        clusters = get_face_clusters(current_user.id)
        return jsonify(clusters)

    @bp.route("/api/photos/cluster", methods=["POST"])
    @login_required
    def api_run_clustering():
        """Re-run face clustering across all photos."""
        from .services.face_service import cluster_faces
        n_clusters = cluster_faces(current_user.id)
        return jsonify({"clusters_found": n_clusters})

    @bp.route("/api/photos/faces/<int:face_id>/label", methods=["POST"])
    @login_required
    def api_label_face(face_id):
        """Label a detected face with a person from the tree."""
        data = request.get_json()
        if not data or not data.get("person_id"):
            return jsonify({"error": "person_id required"}), 400

        from .services.face_service import label_face
        label_face(face_id, data["person_id"])
        return jsonify({"status": "labeled"})

    @bp.route("/api/photos/<int:doc_id>/restore", methods=["POST"])
    @login_required
    def api_restore_photo(doc_id):
        """Trigger photo restoration via ComfyUI (R.E.S.T.O.R.E. agent)."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT * FROM family_documents WHERE id = %s AND user_id = %s",
                (doc_id, current_user.id),
            )
            doc = cur.fetchone()
            if not doc:
                return jsonify({"error": "Not found"}), 404

        # TODO: Dispatch to ComfyUI restoration workflow
        # This will be connected to the existing ComfyUI integration
        # in a follow-up task when R.E.S.T.O.R.E. agent is configured
        return jsonify({
            "status": "queued",
            "message": "Photo restoration queued for R.E.S.T.O.R.E. agent",
        })

    @bp.route("/api/photos/<int:doc_id>/serve")
    @login_required
    def api_serve_photo(doc_id):
        """Serve a photo file (for img src in UI)."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                "SELECT file_path, file_type FROM family_documents WHERE id = %s AND user_id = %s",
                (doc_id, current_user.id),
            )
            doc = cur.fetchone()
            if not doc or not os.path.exists(doc["file_path"]):
                return jsonify({"error": "Not found"}), 404

        mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                "webp": "image/webp", "tiff": "image/tiff"}.get(doc["file_type"], "image/jpeg")
        return send_file(doc["file_path"], mimetype=mime)
```

- [ ] **Step 6: Write timeline_routes.py**

```python
"""Timeline routes — events timeline and migration map data."""

from flask import jsonify, request
from flask_login import current_user, login_required

from database import get_db_cursor


def register_timeline_routes(bp, admin_required):
    """Register timeline routes on the family_tree blueprint."""

    @bp.route("/api/timeline")
    @login_required
    def api_timeline():
        """Get all family events as a timeline."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT id, first_name, last_name,
                          birth_date, birth_place,
                          death_date, death_place
                   FROM family_persons
                   WHERE user_id = %s
                   ORDER BY COALESCE(birth_date, death_date) NULLS LAST""",
                (current_user.id,),
            )
            persons = [dict(r) for r in cur.fetchall()]

        events = []
        for p in persons:
            name = f"{p['first_name']} {p['last_name']}".strip()
            if p.get("birth_date"):
                events.append({
                    "person_id": p["id"],
                    "name": name,
                    "type": "birth",
                    "date": str(p["birth_date"]),
                    "place": p.get("birth_place", ""),
                    "label": f"{name} born",
                })
            if p.get("death_date"):
                events.append({
                    "person_id": p["id"],
                    "name": name,
                    "type": "death",
                    "date": str(p["death_date"]),
                    "place": p.get("death_place", ""),
                    "label": f"{name} died",
                })

        # Sort by date
        events.sort(key=lambda e: e["date"])
        return jsonify(events)

    @bp.route("/api/timeline/migration")
    @login_required
    def api_migration_map():
        """Get migration path data — unique places from the tree."""
        with get_db_cursor() as (conn, cur):
            cur.execute(
                """SELECT DISTINCT birth_place AS place FROM family_persons
                   WHERE user_id = %s AND birth_place IS NOT NULL
                   UNION
                   SELECT DISTINCT death_place FROM family_persons
                   WHERE user_id = %s AND death_place IS NOT NULL""",
                (current_user.id, current_user.id),
            )
            places = [r["place"] for r in cur.fetchall()]

        return jsonify({"places": places})
```

- [ ] **Step 7: Add to module_registry.py**

Find the APPLICATIONS section in `platform_v2/module_registry.py` and add:

```python
ModuleDefinition(
    id="family_tree",
    name="Family Tree",
    description="AI genealogist<br>Record search • Document OCR • Face matching • Photo restoration",
    icon="git-branch",
    category=ModuleCategory.APPLICATIONS,
    route="/tools/family-tree",
    blueprint_import="tools.family_tree:family_tree_bp",
    required_permissions=[],
    minimum_role="USER",
    enabled=True,
    coming_soon=False,
    health_check=lambda: check_service_health("family_tree", "/tools/family-tree/api/status"),
    priority=2,
    tags=["genealogy", "family", "tree", "ancestry", "ai", "photos", "ocr"],
),
```

- [ ] **Step 8: Commit**

```bash
git add platform_v2/tools/family_tree/__init__.py
git add platform_v2/tools/family_tree/routes.py
git add platform_v2/tools/family_tree/research_routes.py
git add platform_v2/tools/family_tree/document_routes.py
git add platform_v2/tools/family_tree/photo_routes.py
git add platform_v2/tools/family_tree/timeline_routes.py
git add platform_v2/module_registry.py
git commit -m "feat(family-tree): blueprint, all route files, module registry entry"
```

---

## Task 8: LCARS Template & Frontend

**Files:**
- Create: `platform_v2/tools/family_tree/templates/family_tree.html`
- Create: `platform_v2/tools/family_tree/static/css/family-tree.css`
- Create: `platform_v2/tools/family_tree/static/js/family-tree.js`

- [ ] **Step 1: Create template HTML**

```html
{% extends 'base.html' %}
{% block title %}Family Tree — AI Genealogy{% endblock %}
{% block module_name %}family_tree{% endblock %}

{% set cat_accent = '#10b981' %}
{% set cat_icon = 'git-branch' %}
{% set cat_modules = [
    {'url': url_for('family_tree.index'), 'icon': 'git-branch', 'label': 'Family Tree'},
    {'url': url_for('fitness.index'), 'icon': 'dumbbell', 'label': 'Fitness'},
] %}
{% include 'includes/category_nav.html' %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('family_tree.static', filename='css/family-tree.css') }}">
{% endblock %}

{% block content %}
<div class="ft-container">
    <header class="ft-header">
        <h1><i data-lucide="git-branch"></i> FAMILY TREE</h1>
        <div class="ft-header-actions">
            <button class="ft-btn ft-btn-primary" onclick="FamilyTree.addPerson()">
                <i data-lucide="user-plus"></i> Add Person
            </button>
            <button class="ft-btn" onclick="FamilyTree.importGedcom()">
                <i data-lucide="upload"></i> Import GEDCOM
            </button>
            <button class="ft-btn" onclick="FamilyTree.exportGedcom()">
                <i data-lucide="download"></i> Export
            </button>
        </div>
    </header>

    <!-- Tab Navigation -->
    <nav class="ft-tabs">
        <button class="ft-tab ft-tab-active" data-tab="tree" onclick="FamilyTree.switchTab('tree')">
            <i data-lucide="git-branch"></i> Tree
        </button>
        <button class="ft-tab" data-tab="research" onclick="FamilyTree.switchTab('research')">
            <i data-lucide="search"></i> Research
        </button>
        <button class="ft-tab" data-tab="documents" onclick="FamilyTree.switchTab('documents')">
            <i data-lucide="file-text"></i> Documents
        </button>
        <button class="ft-tab" data-tab="photos" onclick="FamilyTree.switchTab('photos')">
            <i data-lucide="camera"></i> Photos
        </button>
        <button class="ft-tab" data-tab="timeline" onclick="FamilyTree.switchTab('timeline')">
            <i data-lucide="calendar"></i> Timeline
        </button>
    </nav>

    <!-- Tab: Tree -->
    <section class="ft-panel" id="ft-tab-tree">
        <div id="ft-tree-canvas" class="ft-tree-canvas">
            <div class="ft-empty-state" id="ft-empty-tree">
                <i data-lucide="git-branch" style="width:48px;height:48px;opacity:0.3"></i>
                <h3>Start Your Family Tree</h3>
                <p>Add your first family member or import a GEDCOM file to begin.</p>
                <button class="ft-btn ft-btn-primary" onclick="FamilyTree.addPerson()">
                    <i data-lucide="user-plus"></i> Add First Person
                </button>
            </div>
            <svg id="ft-tree-svg" width="100%" height="600"></svg>
        </div>
    </section>

    <!-- Tab: Research -->
    <section class="ft-panel ft-hidden" id="ft-tab-research">
        <div class="ft-split">
            <div class="ft-split-left">
                <h3 class="ft-section-title"><i data-lucide="loader"></i> Active Research</h3>
                <div id="ft-research-active" class="ft-card-list"></div>
            </div>
            <div class="ft-split-right">
                <h3 class="ft-section-title"><i data-lucide="check-circle"></i> Findings (Review Required)</h3>
                <div id="ft-research-findings" class="ft-card-list"></div>
            </div>
        </div>
    </section>

    <!-- Tab: Documents -->
    <section class="ft-panel ft-hidden" id="ft-tab-documents">
        <div class="ft-upload-zone" id="ft-doc-dropzone"
             ondrop="FamilyTree.handleDocDrop(event)" ondragover="event.preventDefault()">
            <i data-lucide="upload-cloud" style="width:36px;height:36px;opacity:0.4"></i>
            <p>Drag & drop documents here or <label class="ft-upload-label">
                <input type="file" id="ft-doc-input" accept=".jpg,.jpeg,.png,.pdf,.tiff"
                       onchange="FamilyTree.uploadDocument(this.files[0])" hidden>
                browse
            </label></p>
        </div>
        <div id="ft-doc-list" class="ft-card-list"></div>
    </section>

    <!-- Tab: Photos -->
    <section class="ft-panel ft-hidden" id="ft-tab-photos">
        <div class="ft-upload-zone" id="ft-photo-dropzone"
             ondrop="FamilyTree.handlePhotoDrop(event)" ondragover="event.preventDefault()">
            <i data-lucide="camera" style="width:36px;height:36px;opacity:0.4"></i>
            <p>Drag & drop photos here or <label class="ft-upload-label">
                <input type="file" id="ft-photo-input" accept=".jpg,.jpeg,.png,.webp,.tiff"
                       onchange="FamilyTree.uploadPhoto(this.files[0])" multiple hidden>
                browse
            </label></p>
        </div>
        <div class="ft-photo-actions">
            <button class="ft-btn" onclick="FamilyTree.runClustering()">
                <i data-lucide="scan-face"></i> Re-cluster Faces
            </button>
        </div>
        <div id="ft-photo-gallery" class="ft-photo-grid"></div>
        <div id="ft-face-clusters" class="ft-card-list"></div>
    </section>

    <!-- Tab: Timeline -->
    <section class="ft-panel ft-hidden" id="ft-tab-timeline">
        <div id="ft-timeline" class="ft-timeline"></div>
    </section>
</div>

<!-- Person Detail Modal (LCARS) -->
<div class="bm-overlay ft-hidden" id="ft-person-modal">
    <div class="bm-shell">
        <div class="bm-frame" style="--bm-accent: #10b981">
            <div class="bm-content">
                <div class="bm-header">
                    <h2 id="ft-modal-title">Person Details</h2>
                    <button class="bm-close" onclick="FamilyTree.closeModal()">&times;</button>
                </div>
                <div class="bm-body" id="ft-modal-body"></div>
                <div class="bm-footer">
                    <button class="ft-btn" onclick="FamilyTree.closeModal()">Close</button>
                    <button class="ft-btn ft-btn-primary" id="ft-modal-save"
                            onclick="FamilyTree.savePerson()">Save</button>
                </div>
            </div>
        </div>
    </div>
</div>

<!-- GEDCOM Import Modal -->
<div class="bm-overlay ft-hidden" id="ft-import-modal">
    <div class="bm-shell">
        <div class="bm-frame" style="--bm-accent: #8b5cf6">
            <div class="bm-content">
                <div class="bm-header">
                    <h2>Import GEDCOM</h2>
                    <button class="bm-close" onclick="FamilyTree.closeImportModal()">&times;</button>
                </div>
                <div class="bm-body">
                    <div class="ft-upload-zone" style="min-height:120px">
                        <input type="file" id="ft-gedcom-input" accept=".ged,.gedcom">
                        <p>Select a .ged or .gedcom file</p>
                    </div>
                    <div id="ft-import-results" class="ft-hidden"></div>
                </div>
                <div class="bm-footer">
                    <button class="ft-btn" onclick="FamilyTree.closeImportModal()">Close</button>
                    <button class="ft-btn ft-btn-primary" onclick="FamilyTree.doImport()">Import</button>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script src="https://d3js.org/d3.v7.min.js"></script>
<script src="{{ url_for('family_tree.static', filename='js/family-tree.js') }}"></script>
{% endblock %}
```

- [ ] **Step 2: Create CSS file**

Write a complete LCARS-themed CSS file to `platform_v2/tools/family_tree/static/css/family-tree.css` with `ft-` prefix. Key elements:

- `.ft-container` — full module container
- `.ft-header` — module header with accent color `#10b981`
- `.ft-tabs` / `.ft-tab` / `.ft-tab-active` — tab navigation
- `.ft-panel` / `.ft-hidden` — tab content panels
- `.ft-tree-canvas` / `#ft-tree-svg` — d3 tree container
- `.ft-card-list` / `.ft-card` — research findings, document cards
- `.ft-upload-zone` — drag-and-drop upload areas
- `.ft-photo-grid` — photo gallery grid
- `.ft-timeline` — vertical timeline
- `.ft-split` / `.ft-split-left` / `.ft-split-right` — research split view
- `.ft-btn` / `.ft-btn-primary` — action buttons
- `.ft-empty-state` — empty tree placeholder
- Color coding for tree nodes: cyan (#00e5ff), green (#10b981), orange (#f97316), red (#ef4444)
- Responsive breakpoints: 480px, 768px, 1024px
- LCARS modal integration via `bm-*` classes

- [ ] **Step 3: Create JS file**

Write `platform_v2/tools/family_tree/static/js/family-tree.js` as a `FamilyTree` namespace object with these methods:

```javascript
const FamilyTree = {
    BASE: '/tools/family-tree/api',
    currentTab: 'tree',
    persons: [],
    relationships: [],
    editingPersonId: null,

    // --- Init ---
    init() { /* Load tree data, render */ },

    // --- Tabs ---
    switchTab(tab) { /* Show/hide panels, load tab data */ },

    // --- Tree Rendering (d3) ---
    loadTree() { /* Fetch /api/tree, call renderTree */ },
    renderTree(data) { /* d3 force-directed or hierarchical layout */ },

    // --- Person CRUD ---
    addPerson() { /* Open modal for new person */ },
    editPerson(id) { /* Open modal with person data */ },
    savePerson() { /* POST/PUT to /api/persons */ },
    deletePerson(id) { /* DELETE /api/persons/:id */ },

    // --- Relationships ---
    addRelationship(aId, bId, type) { /* POST /api/relationships */ },

    // --- GEDCOM ---
    importGedcom() { /* Open import modal */ },
    doImport() { /* POST file to /api/gedcom/import */ },
    exportGedcom() { /* Navigate to /api/gedcom/export */ },

    // --- Research ---
    loadResearch() { /* Fetch /api/research/queue */ },
    startResearch(personId, type) { /* POST /api/research/start */ },
    acceptFinding(id) { /* POST /api/research/:id/accept */ },
    rejectFinding(id) { /* POST /api/research/:id/reject */ },

    // --- Documents ---
    loadDocuments() { /* Fetch /api/documents */ },
    uploadDocument(file) { /* POST /api/documents/upload */ },
    handleDocDrop(e) { /* Drag-drop handler */ },
    triggerOcr(docId) { /* POST /api/documents/:id/ocr */ },

    // --- Photos ---
    loadPhotos() { /* Fetch /api/photos + /api/photos/faces */ },
    uploadPhoto(file) { /* POST /api/photos/upload */ },
    handlePhotoDrop(e) { /* Drag-drop handler */ },
    runClustering() { /* POST /api/photos/cluster */ },
    labelFace(faceId, personId) { /* POST /api/photos/faces/:id/label */ },
    restorePhoto(docId) { /* POST /api/photos/:id/restore */ },

    // --- Timeline ---
    loadTimeline() { /* Fetch /api/timeline, render vertical timeline */ },

    // --- Modals ---
    openModal(title, bodyHtml) { /* Show person/import modal */ },
    closeModal() { /* Hide modal */ },
    closeImportModal() { /* Hide import modal */ },

    // --- Helpers ---
    api(path, opts) { /* Fetch wrapper with error handling */ },
    renderPersonForm(person) { /* Generate form HTML for modal */ },
    renderCard(data, type) { /* Render a card (research/document/photo) */ },
};

document.addEventListener('DOMContentLoaded', () => FamilyTree.init());
```

The actual implementation should include:
- d3 hierarchical tree layout with zoom/pan
- Color-coded nodes per spec (cyan=confirmed, green=records, orange=researching, red=unknown)
- Click-to-edit on tree nodes
- Drag-and-drop file upload with progress
- Research findings cards with Accept/Reject/Maybe buttons
- Photo gallery with face overlay indicators
- Vertical timeline with event cards

- [ ] **Step 4: Create static directories**

```bash
mkdir -p platform_v2/tools/family_tree/static/css
mkdir -p platform_v2/tools/family_tree/static/js
mkdir -p platform_v2/tools/family_tree/templates
```

- [ ] **Step 5: Commit**

```bash
git add platform_v2/tools/family_tree/templates/family_tree.html
git add platform_v2/tools/family_tree/static/css/family-tree.css
git add platform_v2/tools/family_tree/static/js/family-tree.js
git commit -m "feat(family-tree): LCARS template, CSS, and JS — 5-tab UI with d3 tree renderer"
```

---

## Task 9: Agent Registration

**Files:**
- None created — uses existing `agent_service.create_agent()` via Python script

- [ ] **Step 1: Create agent registration script**

Run inside Docker container:

```bash
docker exec archie_platform python3 -c "
import sys
sys.path.insert(0, '/app/platform_v2')
from services.agent_service import create_agent

agents = [
    {
        'name': 'heritage',
        'display_name': 'H.E.R.I.T.A.G.E.',
        'department': 'Research & Development',
        'model': 'qwen2.5:7b',
        'system_prompt': 'You are H.E.R.I.T.A.G.E. (Historical Exploration, Research, Investigation & Trace of Ancestral Genealogy Engine). You coordinate genealogy research, analyze tree gaps, and present findings to users.',
        'worker_type': 'ai',
        'shift_state': 'barracked',
    },
    {
        'name': 'scroll',
        'display_name': 'S.C.R.O.L.L.',
        'department': 'Research & Development',
        'model': 'qwen2.5:7b',
        'system_prompt': 'You are S.C.R.O.L.L. (Source, Census & Record Online Lookup Liaison). You search FamilySearch, WikiTree, NARA, Chronicling America, and Europeana for genealogy records.',
        'worker_type': 'ai',
        'shift_state': 'barracked',
    },
    {
        'name': 'quill',
        'display_name': 'Q.U.I.L.L.',
        'department': 'Research & Development',
        'model': 'minicpm-v',
        'system_prompt': 'You are Q.U.I.L.L. (Query, Uncover & Interpret Legacy Letters). You process documents via OCR and extract structured genealogy data from certificates, letters, and records.',
        'worker_type': 'ai',
        'shift_state': 'barracked',
    },
    {
        'name': 'visage',
        'display_name': 'V.I.S.A.G.E.',
        'department': 'Creative & Design',
        'model': 'minicpm-v',
        'system_prompt': 'You are V.I.S.A.G.E. (Visual Identification & Similarity Analysis for Genealogy Evidence). You detect faces in photos, generate embeddings, cluster matching faces, and estimate photo eras.',
        'worker_type': 'ai',
        'shift_state': 'barracked',
    },
    {
        'name': 'restore',
        'display_name': 'R.E.S.T.O.R.E.',
        'department': 'Creative & Design',
        'model': 'sdxl',
        'system_prompt': 'You are R.E.S.T.O.R.E. (Reconstruction & Enhancement of Scarred, Torn or Ruined Evidence). You restore and colorize old family photos using ComfyUI image generation.',
        'worker_type': 'ai',
        'shift_state': 'barracked',
    },
]

for agent_def in agents:
    try:
        agent_id = create_agent(**agent_def)
        print(f'Created {agent_def[\"display_name\"]} (ID: {agent_id})')
    except Exception as e:
        print(f'Failed to create {agent_def[\"display_name\"]}: {e}')
"
```

Expected: 5 agents created successfully.

- [ ] **Step 2: Verify agents in Department HQ**

Open `http://192.168.1.200:3000/tools/department-hq` and verify:
- 3 agents in Research & Development (D.A.R.W.I.N.)
- 2 agents in Creative & Design (M.U.S.E.)
- All 5 show as BARRACKED shift state

- [ ] **Step 3: Commit note (no files changed — agents are DB records)**

No git commit needed — agents are database records, not files.

---

## Task 10: Dockerfile & Dependencies

**Files:**
- Modify: `platform_v2/requirements.txt`
- Modify: `Dockerfile`

- [ ] **Step 1: Add Python dependencies to requirements.txt**

Add these lines to `platform_v2/requirements.txt`:

```
pytesseract>=0.3.10
ged4py>=0.4.0
```

Note: `insightface`, `onnxruntime`, and `scikit-learn` are large dependencies. Add them but document that face detection is optional (graceful degradation in `face_service.py`):

```
insightface>=0.7.3
onnxruntime>=1.16.0
scikit-learn>=1.3.0
```

- [ ] **Step 2: Add Tesseract to Dockerfile**

Add to the `apt-get install` section in `Dockerfile`:

```dockerfile
tesseract-ocr tesseract-ocr-por tesseract-ocr-fra
```

- [ ] **Step 3: Create uploads directory**

```bash
mkdir -p /mnt/archie_brain/platform_v2/uploads/family_tree
```

- [ ] **Step 4: Commit**

```bash
git add platform_v2/requirements.txt Dockerfile
git commit -m "feat(family-tree): add pytesseract, ged4py, insightface, tesseract-ocr to dependencies"
```

---

## Task 11: Deploy & Smoke Test

**Files:** None (deployment and verification)

- [ ] **Step 1: Rebuild and restart container**

```bash
docker compose build archie_platform
docker compose up -d archie_platform
```

- [ ] **Step 2: Check container starts without errors**

```bash
docker logs --tail 50 archie_platform
```

Expected: No import errors for family_tree module.

- [ ] **Step 3: Verify module appears on dashboard**

Open `http://192.168.1.200:3000` — Family Tree module should appear in APPLICATIONS category.

- [ ] **Step 4: Smoke test API endpoints**

```bash
# Health check
curl -s http://192.168.1.200:3000/tools/family-tree/api/status | python3 -m json.tool

# Tree data (requires auth cookie)
# Open http://192.168.1.200:3000/tools/family-tree in browser
```

- [ ] **Step 5: Test basic flow**

1. Navigate to `http://192.168.1.200:3000/tools/family-tree`
2. Add a person (your name)
3. Add a second person (a parent)
4. Create a parent_child relationship
5. Verify tree renders in d3
6. Upload a test photo → verify face detection response
7. Upload a test document → trigger OCR → verify extracted data

---

## Task 12: Post-Implementation Integration

**Files:**
- Modify: Platform directory/org chart (via agent_service)
- Modify: Website product showcase
- Modify: Compare page

- [ ] **Step 1: Update Dev HQ**

```bash
# Via MCP tools:
# mcp create_project "Family Tree — AI Genealogy Module"
# mcp log_decision "Agent-Per-Task architecture for genealogy — 5 agents (H.E.R.I.T.A.G.E., S.C.R.O.L.L., Q.U.I.L.L., V.I.S.A.G.E., R.E.S.T.O.R.E.)"
# mcp update_project_understanding for family-tree project
```

- [ ] **Step 2: Verify agents in directory**

Check that the 5 new agents appear in:
- Department HQ roster
- Agent directory/org chart
- Platform status displays (agent count should increase by 5)

- [ ] **Step 3: Add to compare/showcase page**

Add Family Tree to whatever comparison or feature showcase page exists on the platform. Highlight:
- AI genealogist vs manual Ancestry search
- Automatic record matching with confidence scores
- Photo restoration + face matching
- Privacy-first, self-hosted

- [ ] **Step 4: Update website product listing**

Add Family Tree to kytranempowerment.com product listing when ready for public showcase.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat(family-tree): post-implementation integration — directory, showcase, Dev HQ"
```

---

## Summary

| Task | What | Files | Est. |
|------|------|-------|------|
| 1 | Database migration (7 tables) | 1 SQL file | 5 min |
| 2 | Tree service (person/relationship CRUD) | 2 files | 10 min |
| 3 | GEDCOM service (import/export) | 1 file | 10 min |
| 4 | Research service (5 API clients) | 1 file | 10 min |
| 5 | OCR service (Tesseract + Bridge) | 1 file | 5 min |
| 6 | Face service (InsightFace + DBSCAN) | 1 file | 10 min |
| 7 | Blueprint + routes + registry | 7 files | 15 min |
| 8 | LCARS template + CSS + JS | 3 files | 20 min |
| 9 | Agent registration (5 agents) | DB only | 5 min |
| 10 | Dockerfile + dependencies | 2 files | 5 min |
| 11 | Deploy & smoke test | None | 10 min |
| 12 | Post-implementation integration | Various | 10 min |

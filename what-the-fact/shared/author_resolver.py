"""Resolve raw RSS bylines into shared.entities(entity_type='journalist').

Pure helpers (normalize_name / clean_byline / is_wire_service) are DB-free and unit-
tested in isolation. resolve_byline / tag_article_author take a live SQLAlchemy
connection + schema names so BOTH the ingest path and the (future) LLM backfill job
reuse the exact same logic. Schema names default from env so persist.py can call without
threading them through (WTF_SHARED_SCHEMA / WTF_SCHEMA)."""
import os
import re
import unicodedata

from sqlalchemy import text

# Outlets / wire services that show up in author fields but are NOT personal bylines.
# Lowercased; extendable.
WIRE_SERVICES = {
    "the canadian press", "canadian press", "la presse canadienne",
    "globe newswire", "globenewswire", "cision", "newswire", "associated press",
    "the associated press", "reuters", "afp", "agence france-presse", "bloomberg",
    "bloomberg news", "postmedia news", "postmedia", "business wire", "dpa",
    "globalnews digital", "staff", "editorial", "newsroom", "editorial board",
    "the editorial board", "cbc news", "ctv news", "global news", "none",
}

# Markers that make a byline an outlet/desk/wire string rather than a person's name.
# Conservative (word-boundary 'staff', 'newswire', a literal '@', or a very long blurb)
# so real people are never dropped — e.g. the columnist "David Staples" is safe.
_WIRE_RX = re.compile(
    r"newswire|newsfile|business\s*wire|market\s*wire|access\s*wire|globenewswire|"
    r"/cnw/|cnw\s*group|press\s*release|\bstaff\b|editorial\s*board|\bnewsroom\b|"
    r"^special\s+to\b|@",
    re.IGNORECASE,
)

_BYLINE_SPLIT = re.compile(r"\s*(?:,|&|\band\b|\bwith\b)\s*", re.IGNORECASE)
_OUTLET_SUFFIX = re.compile(r"\s*[,/|-]\s*[A-Z][A-Za-z .]+(?:News|Press|Media|Star|Post|Globe).*$")


def _shared_schema(explicit):
    return explicit or os.environ.get("WTF_SHARED_SCHEMA", "shared")


def _wtf_schema(explicit):
    return explicit or os.environ.get("WTF_SCHEMA", "wtf")


def normalize_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    n = n.lower().replace("'", "").replace("’", "")
    n = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
    return n


def is_wire_service(name: str) -> bool:
    """True when a byline is an outlet / wire service / desk, not a person's name."""
    n = re.sub(r"\s+", " ", name.strip().lower())
    if not n or n in WIRE_SERVICES:
        return True
    if _WIRE_RX.search(n):
        return True
    if len(n) > 80:  # long 'bylines' are bio blurbs / disclaimers, never a name
        return True
    return False


def clean_byline(raw: str) -> list:
    """Split a raw byline into individual plausible person names (co-bylines → many).
    Strips a leading 'By ', trailing outlet suffixes, and drops wire services."""
    if not raw:
        return []
    s = raw.strip()
    s = re.sub(r"^by\s+", "", s, flags=re.IGNORECASE)
    s = _OUTLET_SUFFIX.sub("", s)
    parts = [p.strip() for p in _BYLINE_SPLIT.split(s) if p.strip()]
    return [p for p in parts if len(p) >= 2 and not is_wire_service(p)]


def _find_journalist(conn, s, slug):
    """The ACTIVE journalist row for ``slug``, following merges; None if there is none.

    Returns (row, taken): ``row`` is {"id", "metadata"} for the journalist; ``taken`` is True
    when the slug is held by something that is NOT a live journalist (a vendor, a contact, an
    institution, a suppressed row), in which case the caller must use a journalist-specific slug
    rather than attach the byline to that node.
    """
    cur_slug_row = conn.execute(
        text(f"SELECT id, metadata, entity_type, status, merged_into FROM {s}.entities WHERE slug=:slug"),
        {"slug": slug},
    ).mappings().first()
    for _ in range(5):                       # a merged row keeps its slug: follow it to the survivor
        if not cur_slug_row:
            return None, False
        if cur_slug_row["status"] == "merged" and cur_slug_row["merged_into"] is not None:
            cur_slug_row = conn.execute(
                text(f"SELECT id, metadata, entity_type, status, merged_into FROM {s}.entities WHERE id=:i"),
                {"i": cur_slug_row["merged_into"]},
            ).mappings().first()
            continue
        break
    if not cur_slug_row:
        return None, False
    if cur_slug_row["entity_type"] == "journalist" and cur_slug_row["status"] == "active":
        return cur_slug_row, False
    return None, True


def resolve_byline(conn, raw_byline, source_slug, shared_schema=None):
    """Clean a raw byline → find-or-create one journalist entity per name; append the
    outlet slug to metadata.outlets. Returns the list of entity_ids (co-bylines → many).

    Slugs are ONE namespace across node types, so the lookup must not assume the slug holds a
    journalist: a vendor or contact named "Nick Perry" owns slug ``nick-perry`` and attaching the
    byline there put news articles (and an outlet list) on a procurement node — the mirror of the
    ingest-side collision. A byline whose slug belongs to a non-journalist uses ``<slug>-journalist``.
    """
    s = _shared_schema(shared_schema)
    out = []
    for name in clean_byline(raw_byline):
        slug = normalize_name(name)
        if not slug:
            continue
        row, taken = _find_journalist(conn, s, slug)
        if taken:
            slug = f"{slug}-journalist"
            row, _ = _find_journalist(conn, s, slug)
        if row:
            eid = row["id"]
            outlets = (row["metadata"] or {}).get("outlets", [])
            if source_slug and source_slug not in outlets:
                conn.execute(
                    text(
                        f"UPDATE {s}.entities SET metadata = jsonb_set("
                        f"COALESCE(metadata, '{{}}'::jsonb), '{{outlets}}', "
                        f"(COALESCE(metadata->'outlets', '[]'::jsonb) || to_jsonb(CAST(:o AS text)))), "
                        f"updated_at = NOW() WHERE id = :id"
                    ),
                    {"o": source_slug, "id": eid},
                )
        else:
            eid = conn.execute(
                text(
                    f"INSERT INTO {s}.entities (entity_type, canonical_name, slug, metadata) "
                    f"VALUES ('journalist', :name, :slug, jsonb_build_object('outlets', "
                    f"CASE WHEN :o = '' THEN '[]'::jsonb ELSE jsonb_build_array(:o) END)) "
                    f"RETURNING id"
                ),
                {"name": name, "slug": slug, "o": source_slug or ""},
            ).scalar()
        out.append(eid)
    return out


def tag_article_author(conn, article_id, entity_id, source_slug, wtf_schema=None, shared_schema=None):
    """Dual-write the mention into shared.entity_mentions + the WTF-local article_author_tags
    mirror. Idempotent (ON CONFLICT DO NOTHING)."""
    s = _shared_schema(shared_schema)
    w = _wtf_schema(wtf_schema)
    conn.execute(
        text(
            f"INSERT INTO {s}.entity_mentions (entity_id, product, content_type, content_id, confidence) "
            f"VALUES (:e, 'wtf', 'article', :cid, 1.0) "
            f"ON CONFLICT (entity_id, product, content_type, content_id) DO NOTHING"
        ),
        {"e": entity_id, "cid": str(article_id)},
    )
    conn.execute(
        text(
            f"INSERT INTO {w}.article_author_tags (article_id, entity_id, match_type) "
            f"VALUES (:a, :e, 'rss_author') ON CONFLICT (article_id, entity_id) DO NOTHING"
        ),
        {"a": article_id, "e": entity_id},
    )

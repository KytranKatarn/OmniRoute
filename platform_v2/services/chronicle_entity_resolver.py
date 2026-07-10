"""Chronicle cross-source entity resolution (slice 08) — deterministic, no LLM.

Groups a single owner's per-import mailbox_entities (across ALL their imports — Gmail, LinkedIn,
uploads) by (entity_type, normalized_name) into global chronicle_entity rows + chronicle_entity_link.
The same person appearing in the email import and the LinkedIn import collapses to ONE chronicle_entity
linked to every mailbox_entity occurrence. Idempotent: re-running merges aliases + re-links (ON CONFLICT
DO NOTHING) and never creates duplicates. No DHQ / LLM — pure name-normalization matching.
"""

import logging
import re

from psycopg2.extras import Json

logger = logging.getLogger(__name__)


def _clean(name):
    """Whitespace-collapsed display name (case preserved)."""
    return re.sub(r"\s+", " ", name or "").strip()


def _norm(name):
    """Match key — MIRRORS mailbox_enrich_service normalization (lowercased)."""
    return _clean(name).lower()


def _pick_canonical(members):
    """Pick a stable display name for a group: highest mention_count, ties broken alphabetically.
    members = list of dicts with 'name' and 'mention_count'."""
    best = sorted(members, key=lambda m: (-(m.get("mention_count") or 0), (m.get("name") or "")))
    return _clean(best[0]["name"]) if best else ""


def _scalar(row):
    if row is None:
        return None
    return row["id"] if isinstance(row, dict) else row[0]


def _find_or_create_entity(cur, owner_id, entity_type, norm, canonical, aliases):
    """Return (chronicle_entity_id, created). Matches on owner+type+lower(canonical_name)=norm."""
    cur.execute(
        "SELECT id, aliases FROM chronicle_entity WHERE owner_id IS NOT DISTINCT FROM %s "
        "AND entity_type=%s AND lower(canonical_name)=%s LIMIT 1",
        (owner_id, entity_type, norm),
    )
    row = cur.fetchone()
    if row:
        ent_id = row["id"] if isinstance(row, dict) else row[0]
        existing = row["aliases"] if isinstance(row, dict) else row[1]
        merged = sorted(set((existing or [])) | set(aliases))
        cur.execute(
            "UPDATE chronicle_entity SET aliases=%s, updated_at=now() WHERE id=%s",
            (Json(merged), ent_id),
        )
        return (ent_id, False)
    cur.execute(
        "INSERT INTO chronicle_entity (owner_id, canonical_name, entity_type, aliases) "
        "VALUES (%s,%s,%s,%s) RETURNING id",
        (owner_id, canonical, entity_type, Json(sorted(set(aliases)))),
    )
    return (_scalar(cur.fetchone()), True)


def resolve_entities(owner_id=4):
    """Unify the owner's mailbox_entities into chronicle_entity + chronicle_entity_link.
    Returns {groups, entities_created, entities_matched, links_created}."""
    from database import get_db_cursor

    created = matched = links = 0
    with get_db_cursor(commit=True) as (conn, cur):
        cur.execute(
            "SELECT me.id, me.name, me.entity_type, me.normalized_name, me.mention_count "
            "FROM mailbox_entities me JOIN mailbox_imports i ON me.import_id=i.id "
            "WHERE i.owner_id IS NOT DISTINCT FROM %s",
            (owner_id,),
        )
        rows = cur.fetchall()

        groups = {}  # (entity_type, normalized_name) -> {members:[{id,name,mention_count}], norm}
        for r in rows:
            rid = r["id"] if isinstance(r, dict) else r[0]
            name = r["name"] if isinstance(r, dict) else r[1]
            etype = r["entity_type"] if isinstance(r, dict) else r[2]
            nnorm = r["normalized_name"] if isinstance(r, dict) else r[3]
            mc = r["mention_count"] if isinstance(r, dict) else r[4]
            # re-derive the match key from the raw name so it aligns with our canonical_name
            key_norm = _norm(name) or (nnorm or "")
            if not key_norm:
                continue
            g = groups.setdefault((etype, key_norm), {"members": [], "norm": key_norm})
            g["members"].append({"id": rid, "name": name, "mention_count": mc})

        for (etype, key_norm), g in groups.items():
            canonical = _pick_canonical(g["members"])
            aliases = sorted({_clean(m["name"]) for m in g["members"] if _clean(m["name"])})
            ent_id, was_created = _find_or_create_entity(cur, owner_id, etype, key_norm, canonical, aliases)
            created += 1 if was_created else 0
            matched += 0 if was_created else 1
            for m in g["members"]:
                cur.execute(
                    "INSERT INTO chronicle_entity_link (chronicle_entity_id, mailbox_entity_id) "
                    "VALUES (%s,%s) ON CONFLICT (chronicle_entity_id, mailbox_entity_id) DO NOTHING",
                    (ent_id, m["id"]),
                )
                if cur.rowcount and cur.rowcount > 0:
                    links += 1

    return {
        "groups": len(groups),
        "entities_created": created,
        "entities_matched": matched,
        "links_created": links,
    }

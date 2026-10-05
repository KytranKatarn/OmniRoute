"""entity_graph.py — Seed shared.entities from parliament source tables.

Tasks #3026 (core entity graph schema) + #3126 (person dedup: MPs, senators,
officers, GIC appointees resolve to same shared.entities record).

Dedup key: slug = normalize_name(canonical_name) → hyphens.
Same normalized name across any source table = one shared.entities row,
with a growing `roles` JSONB array recording every institutional role.

Env:  WTF_DATABASE_URL
Run:  python -m ingest.shared.entity_graph   (from what-the-fact/ root)
      python -m ingest.shared.entity_graph --dry-run
"""

import json
import logging
import os
import re
import sys
import unicodedata
from typing import Optional

from sqlalchemy import create_engine, text

logger = logging.getLogger("wtf-ingest.entity_graph")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── Name normalisation ────────────────────────────────────────────────────────

_TITLE_PREFIXES = (
    "the right honourable ",
    "the right hon. ",
    "the honourable ",
    "the hon. ",
    "right honourable ",
    "right hon. ",
    "honourable ",
    "hon. ",
    "sen. ",
    "senator ",
    "dr. ",
    "mr. ",
    "ms. ",
    "mrs. ",
    "mp ",
)


def normalize_name(name: str) -> str:
    """Return a stable lowercase ASCII key for dedup comparison.

    Steps:
    1. Strip leading/trailing whitespace
    2. NFKD decompose → drop combining marks (removes accents: é→e, ç→c)
    3. Lowercase
    4. Strip known honorific prefixes (longest-first, iterative)
    5. Collapse internal whitespace
    """
    name = name.strip()
    # Remove accents via NFKD normalisation + dropping combining characters
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    # Iteratively strip known title prefixes (order matters — longest first)
    changed = True
    while changed:
        changed = False
        for prefix in _TITLE_PREFIXES:
            if name.startswith(prefix):
                name = name[len(prefix):]
                changed = True
    return re.sub(r"\s+", " ", name).strip()


def name_to_slug(normalized: str) -> str:
    """Convert normalized name to URL-safe hyphenated slug."""
    slug = re.sub(r"[^a-z0-9\s-]", "", normalized)
    slug = re.sub(r"\s+", "-", slug.strip())
    return slug


# ── Engine ────────────────────────────────────────────────────────────────────

def _get_engine():
    url = os.environ.get("WTF_DATABASE_URL")
    if not url:
        raise RuntimeError("WTF_DATABASE_URL not set")
    return create_engine(url)


# ── Upsert helper ─────────────────────────────────────────────────────────────

def _live_entity_row(conn, slug: str):
    """The row for `slug`, following dedup merges to the surviving entity.

    A merged entity keeps its slug, so a lookup by slug lands on the OLD row; anything attached to
    its id (appointed_to edges, roles, aliases) is stranded there — the site follows a merge only one
    hop. See consumer.entity_graph_routes._follow_merges for the incident (122,660 stranded edges).
    """
    row = conn.execute(
        text("SELECT id, roles, aliases, status, merged_into FROM shared.entities WHERE slug = :slug"),
        {"slug": slug},
    ).mappings().fetchone()
    for _ in range(5):
        if row is None or row["status"] != "merged" or not row["merged_into"]:
            break
        row = conn.execute(
            text("SELECT id, roles, aliases, status, merged_into FROM shared.entities WHERE id = :id"),
            {"id": row["merged_into"]},
        ).mappings().fetchone()
    return row


def _upsert_entity(conn, *, canonical_name: str, slug: str,
                   entity_type: str, role: dict, raw_name: str,
                   dry_run: bool = False) -> tuple:
    """Insert or update a shared.entities row.

    On conflict (slug):
      - Append role to roles array if not already present (keyed by type + external_id)
      - Append raw_name to aliases if new
      - Touch updated_at

    Returns (entity_id, action) where action is 'created' | 'updated' | 'noop'.
    """
    if dry_run:
        row = _live_entity_row(conn, slug)
        if row is None:
            return -1, "would_create"
        existing_roles = row["roles"] if isinstance(row["roles"], list) else json.loads(row["roles"])
        role_key = (role.get("type"), role.get("external_id"))
        has_role = any((r.get("type"), r.get("external_id")) == role_key for r in existing_roles)
        if has_role and raw_name in list(row["aliases"] or []):
            return row["id"], "noop"
        return row["id"], "would_update"

    # Atomic create: ON CONFLICT (slug) DO NOTHING is race-safe — no UniqueViolation
    # even under concurrent ingest (the non-atomic SELECT-then-INSERT raced two
    # transactions inserting the same vendor slug -> 500 -> batch rollback, #4183).
    # RETURNING id is non-empty only when WE inserted the row.
    created = conn.execute(
        text("""
            INSERT INTO shared.entities
                (entity_type, canonical_name, slug, aliases, roles)
            VALUES
                (:etype, :cname, :slug, ARRAY[:raw_name], CAST(:roles AS JSONB))
            ON CONFLICT (slug) DO NOTHING
            RETURNING id
        """),
        {
            "etype": entity_type,
            "cname": canonical_name,
            "slug": slug,
            "raw_name": raw_name,
            "roles": json.dumps([role]),
        },
    ).fetchone()
    if created is not None:
        return created[0], "created"

    # Conflict: row exists (ours from earlier, or a concurrent txn's). Read + merge.
    row = _live_entity_row(conn, slug)
    entity_id = row["id"]
    existing_roles = row["roles"] if isinstance(row["roles"], list) else json.loads(row["roles"])
    existing_aliases = list(row["aliases"] or [])

    # Deduplicate role by (type + external_id)
    role_key = (role.get("type"), role.get("external_id"))
    already_has_role = any(
        (r.get("type"), r.get("external_id")) == role_key
        for r in existing_roles
    )
    needs_alias = raw_name not in existing_aliases

    if already_has_role and not needs_alias:
        return entity_id, "noop"

    if dry_run:
        return entity_id, "would_update"

    if not already_has_role:
        existing_roles.append(role)
    if needs_alias:
        existing_aliases.append(raw_name)

    conn.execute(
        text("""
            UPDATE shared.entities
            SET roles      = CAST(:roles AS JSONB),
                aliases    = :aliases,
                updated_at = NOW()
            WHERE id = :id
        """),
        {
            "id": entity_id,
            "roles": json.dumps(existing_roles),
            "aliases": existing_aliases,
        },
    )
    return entity_id, "updated"


# ── Seed persons ──────────────────────────────────────────────────────────────

def seed_persons(engine, dry_run: bool = False) -> dict:
    """Load senators, MPs, officers → shared.entities.

    Cross-source dedup: if a senator and MP share the same slug (normalized
    name), they resolve to the same shared.entities row — roles array grows.

    After seeding: UPDATE parliament.senators/mps/officers SET entity_id = ...
    """
    stats = {
        "senators_created": 0, "senators_updated": 0, "senators_noop": 0,
        "mps_created": 0, "mps_updated": 0, "mps_noop": 0,
        "officers_created": 0, "officers_updated": 0, "officers_noop": 0,
        "linked": 0,
    }

    with engine.begin() as conn:

        # ── Senators ─────────────────────────────────────────────────────────
        senators = conn.execute(text("""
            SELECT id, slug, name, given_name, family_name, caucus,
                   province, appointed_at
            FROM parliament.senators
            ORDER BY name
        """)).mappings().all()

        for s in senators:
            norm = normalize_name(s["name"])
            ent_slug = name_to_slug(norm)
            role = {
                "type": "senator",
                "slug": s["slug"],
                "external_id": s["id"],
                "caucus": s["caucus"],
                "province": s["province"],
                "since": str(s["appointed_at"]) if s["appointed_at"] else None,
            }
            ent_id, action = _upsert_entity(
                conn,
                canonical_name=s["name"],
                slug=ent_slug,
                entity_type="person",
                role=role,
                raw_name=s["name"],
                dry_run=dry_run,
            )
            if not dry_run and ent_id > 0:
                conn.execute(
                    text("UPDATE parliament.senators SET entity_id = :eid WHERE id = :id"),
                    {"eid": ent_id, "id": s["id"]},
                )
            key = "senators_" + action.replace("would_", "")
            stats[key] = stats.get(key, 0) + 1
            stats["linked"] += 1
            logger.debug("Senator %s → entity %d (%s)", s["name"], ent_id, action)

        logger.info("Senators done: created=%d updated=%d noop=%d",
                    stats["senators_created"], stats["senators_updated"],
                    stats["senators_noop"])

        # ── MPs ───────────────────────────────────────────────────────────────
        mps = conn.execute(text("""
            SELECT id, slug, name, given_name, family_name, party,
                   riding_name, province_code
            FROM parliament.mps
            ORDER BY name
        """)).mappings().all()

        for m in mps:
            norm = normalize_name(m["name"])
            ent_slug = name_to_slug(norm)
            role = {
                "type": "mp",
                "slug": m["slug"],
                "external_id": m["id"],
                "party": m["party"],
                "riding": m["riding_name"],
                "province": m["province_code"],
            }
            ent_id, action = _upsert_entity(
                conn,
                canonical_name=m["name"],
                slug=ent_slug,
                entity_type="person",
                role=role,
                raw_name=m["name"],
                dry_run=dry_run,
            )
            if not dry_run and ent_id > 0:
                conn.execute(
                    text("UPDATE parliament.mps SET entity_id = :eid WHERE id = :id"),
                    {"eid": ent_id, "id": m["id"]},
                )
            key = "mps_" + action.replace("would_", "")
            stats[key] = stats.get(key, 0) + 1
            stats["linked"] += 1
            logger.debug("MP %s → entity %d (%s)", m["name"], ent_id, action)

        logger.info("MPs done: created=%d updated=%d noop=%d",
                    stats["mps_created"], stats["mps_updated"], stats["mps_noop"])

        # ── Officers of Parliament ────────────────────────────────────────────
        officers = conn.execute(text("""
            SELECT id, slug, title, short_title, current_holder, appointed_at
            FROM parliament.officers
            WHERE is_active = true
              AND current_holder IS NOT NULL AND current_holder != ''
            ORDER BY title
        """)).mappings().all()

        for o in officers:
            holder = o["current_holder"]
            norm = normalize_name(holder)
            ent_slug = name_to_slug(norm)
            role = {
                "type": "officer",
                "office_slug": o["slug"],
                "title": o["title"],
                "external_id": o["id"],
                "since": str(o["appointed_at"]) if o["appointed_at"] else None,
            }
            ent_id, action = _upsert_entity(
                conn,
                canonical_name=holder,
                slug=ent_slug,
                entity_type="person",
                role=role,
                raw_name=holder,
                dry_run=dry_run,
            )
            if not dry_run and ent_id > 0:
                conn.execute(
                    text("UPDATE parliament.officers SET entity_id = :eid WHERE id = :id"),
                    {"eid": ent_id, "id": o["id"]},
                )
            key = "officers_" + action.replace("would_", "")
            stats[key] = stats.get(key, 0) + 1
            stats["linked"] += 1
            logger.debug("Officer %s (%s) → entity %d (%s)", holder, o["slug"], ent_id, action)

        logger.info("Officers done: created=%d updated=%d noop=%d",
                    stats["officers_created"], stats["officers_updated"],
                    stats["officers_noop"])

    total_entities = (
        stats["senators_created"] + stats["mps_created"] + stats["officers_created"]
    )
    total_deduped = (
        stats["senators_updated"] + stats["mps_updated"] + stats["officers_updated"]
    )
    logger.info(
        "seed_persons complete | new_entities=%d cross-source_deduped=%d linked=%d",
        total_entities, total_deduped, stats["linked"],
    )
    return stats


# ── Seed relationships ────────────────────────────────────────────────────────

def seed_relationships(engine, dry_run: bool = False) -> dict:
    """Create entity relationships from GIC appointments.

    For each appointment:
      - Resolve appointee_name → shared.entities (person, upsert if new)
      - Resolve organization    → shared.entities (organization, upsert if new)
      - Insert: person → appointed_to → org  in shared.entity_relationships

    Source: gov_watch.gic_appointments
    """
    stats = {
        "appointments_processed": 0,
        "relationships_created": 0,
        "relationships_noop": 0,
        "skipped_no_org": 0,
    }

    with engine.begin() as conn:
        appointments = conn.execute(text("""
            SELECT id, pc_number, oic_date, department, appointee_name, organization
            FROM gov_watch.gic_appointments
            WHERE appointee_name IS NOT NULL AND appointee_name != ''
            ORDER BY oic_date DESC
        """)).mappings().all()

        for appt in appointments:
            stats["appointments_processed"] += 1

            # Resolve person entity
            person_norm = normalize_name(appt["appointee_name"])
            person_slug = name_to_slug(person_norm)
            person_role = {
                "type": "gic_appointee",
                "pc_number": appt["pc_number"],
                "organization": appt["organization"],
                "since": str(appt["oic_date"]) if appt["oic_date"] else None,
            }
            person_id, _ = _upsert_entity(
                conn,
                canonical_name=appt["appointee_name"],
                slug=person_slug,
                entity_type="person",
                role=person_role,
                raw_name=appt["appointee_name"],
                dry_run=dry_run,
            )

            # Resolve org entity (skip if missing)
            org_name = (appt["organization"] or "").strip()
            if not org_name:
                stats["skipped_no_org"] += 1
                continue

            org_norm = normalize_name(org_name)
            org_slug = "org-" + name_to_slug(org_norm)
            org_role = {"type": "appointed_body", "department": appt["department"]}
            org_id, _ = _upsert_entity(
                conn,
                canonical_name=org_name,
                slug=org_slug,
                entity_type="organization",
                role=org_role,
                raw_name=org_name,
                dry_run=dry_run,
            )

            if dry_run:
                logger.info(
                    "  DRY: %s → appointed_to → %s (pc=%s)",
                    appt["appointee_name"], org_name, appt["pc_number"],
                )
                stats["relationships_created"] += 1
                continue

            # Insert relationship (idempotent)
            result = conn.execute(text("""
                INSERT INTO shared.entity_relationships
                    (from_entity_id, to_entity_id, relationship_type,
                     source_product, source_id, valid_from, metadata)
                VALUES
                    (:from_id, :to_id, 'appointed_to',
                     'gov-watch', :source_id, :valid_from, CAST(:meta AS JSONB))
                ON CONFLICT (from_entity_id, to_entity_id, relationship_type, source_product, source_id)
                DO UPDATE SET
                    valid_from = EXCLUDED.valid_from,
                    metadata   = EXCLUDED.metadata
                RETURNING id
            """), {
                "from_id":   person_id,
                "to_id":     org_id,
                "source_id": appt["pc_number"],
                "valid_from": appt["oic_date"],
                "meta": json.dumps({
                    "pc_number":  appt["pc_number"],
                    "department": appt["department"],
                }),
            })
            stats["relationships_created"] += 1

    logger.info(
        "seed_relationships complete | appointments=%d relationships=%d skipped_no_org=%d",
        stats["appointments_processed"],
        stats["relationships_created"],
        stats["skipped_no_org"],
    )
    return stats


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        logger.info("DRY RUN — no DB writes")

    engine = _get_engine()

    p_stats = seed_persons(engine, dry_run=dry_run)
    r_stats = seed_relationships(engine, dry_run=dry_run)

    print("\n=== Shared Entity Graph Seed Complete ===")
    mode = " (DRY RUN)" if dry_run else ""
    print(f"Persons{mode}:")
    print(f"  Senators : +{p_stats['senators_created']} new  "
          f"~{p_stats['senators_updated']} updated  "
          f"{p_stats['senators_noop']} unchanged")
    print(f"  MPs      : +{p_stats['mps_created']} new  "
          f"~{p_stats['mps_updated']} updated  "
          f"{p_stats['mps_noop']} unchanged")
    print(f"  Officers : +{p_stats['officers_created']} new  "
          f"~{p_stats['officers_updated']} updated  "
          f"{p_stats['officers_noop']} unchanged")
    print(f"  Linked   : {p_stats['linked']} source rows → entity_id")

    print(f"\nRelationships{mode}:")
    print(f"  GIC 'appointed_to' edges: {r_stats['relationships_created']}")
    print(f"  Appointments processed  : {r_stats['appointments_processed']}")

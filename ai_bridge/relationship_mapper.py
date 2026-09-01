"""
Relationship Mapper for ARCHIE Consciousness Intelligence

Creates and manages relationships between knowledge entries in the knowledge graph.
Supports 15 relationship types for rich semantic connections.

Usage:
    from ai_bridge.relationship_mapper import create_relationship, find_related

    # Create relationship
    rel_id = create_relationship(from_id, to_id, "uses", strength=0.8)

    # Find related entries
    related = find_related(knowledge_id, relationship_types=["uses", "extends"])
"""

import json
import logging
from typing import Optional
from dataclasses import dataclass
from psycopg2.extras import RealDictCursor
from db import get_db

logger = logging.getLogger(__name__)

# 15 relationship types for knowledge graph
RELATIONSHIP_TYPES = [
    "related_to",  # General conceptual relation
    "part_of",  # Component/parent relationship
    "uses",  # Depends on or utilizes
    "extends",  # Builds upon or enhances
    "implements",  # Realizes a concept/pattern
    "solves",  # Addresses a problem
    "causes",  # Leads to or triggers
    "contradicts",  # Conflicts with
    "supersedes",  # Replaces older knowledge
    "prerequisite_of",  # Must understand first
    "alternative_to",  # Different approach to same goal
    "learned_from",  # Source attribution
    "similar_to",  # Semantically close
    "example_of",  # Concrete instance
    "applies_to",  # Relevant context/domain
]


@dataclass
class Relationship:
    """A relationship between two knowledge entries"""

    id: int
    from_id: int
    to_id: int
    relationship_type: str
    strength: float
    metadata: dict
    created_at: str


@dataclass
class RelatedEntry:
    """A related knowledge entry with relationship info"""

    id: int
    title: str
    category: str
    relationship_type: str
    strength: float
    direction: str  # 'outgoing' or 'incoming'


class RelationshipMapper:
    """Manages knowledge graph relationships"""

    def create_relationship(
        self,
        from_id: int,
        to_id: int,
        relationship_type: str,
        strength: float = 0.5,
        metadata: Optional[dict] = None,
        created_by: str = "system",
    ) -> Optional[int]:
        """
        Create a relationship between two knowledge entries.

        Args:
            from_id: Source knowledge entry ID
            to_id: Target knowledge entry ID
            relationship_type: One of 15 relationship types
            strength: Relationship strength (0.0-1.0)
            metadata: Optional additional metadata
            created_by: Who created this relationship

        Returns:
            Relationship ID if created, None on failure
        """
        if relationship_type not in RELATIONSHIP_TYPES:
            logger.warning(f"Invalid relationship type: {relationship_type}")
            relationship_type = "related_to"  # Default fallback

        if strength < 0 or strength > 1:
            strength = max(0, min(1, strength))

        metadata = metadata or {}
        metadata["created_by"] = created_by

        try:
            conn = get_db()
            try:
                cur = conn.cursor()

                # Use ON CONFLICT to update if exists
                cur.execute(
                    """
                    INSERT INTO knowledge_relationships
                        (from_id, to_id, relationship_type, strength, metadata)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (from_id, to_id, relationship_type)
                    DO UPDATE SET
                        strength = EXCLUDED.strength,
                        metadata = EXCLUDED.metadata
                    RETURNING id
                    """,
                    (from_id, to_id, relationship_type, strength, json.dumps(metadata)),
                )

                result = cur.fetchone()
                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

            logger.debug(f"Created relationship: {from_id} --[{relationship_type}]--> {to_id}")
            return result[0] if result else None

        except Exception as e:
            logger.error(f"Failed to create relationship: {e}")
            return None

    def create_relationships_batch(
        self,
        relationships: list,  # List of ExtractedRelationship from analyzer
        from_knowledge_id: int,
        title_to_id_map: dict,  # Map of titles to knowledge IDs
    ) -> dict:
        """
        Create multiple relationships from analysis results.

        Args:
            relationships: List of ExtractedRelationship objects
            from_knowledge_id: The source knowledge entry ID
            title_to_id_map: Map of known titles to their IDs

        Returns:
            dict with created/skipped counts
        """
        stats = {"created": 0, "skipped": 0, "errors": []}

        for rel in relationships:
            # Try to find target ID
            to_id = None

            # Check if target is in provided map
            if rel.to_title in title_to_id_map:
                to_id = title_to_id_map[rel.to_title]
            else:
                # Try to find by title in database
                to_id = self._find_by_title(rel.to_title)

            if not to_id:
                stats["skipped"] += 1
                continue

            # Create the relationship
            result = self.create_relationship(
                from_id=from_knowledge_id,
                to_id=to_id,
                relationship_type=rel.relationship_type,
                strength=rel.strength,
                metadata={"reasoning": rel.reasoning},
            )

            if result:
                stats["created"] += 1
            else:
                stats["errors"].append(f"{rel.from_title} -> {rel.to_title}")

        return stats

    def _find_by_title(self, title: str) -> Optional[int]:
        """Find knowledge entry ID by title (fuzzy match)"""
        try:
            conn = get_db()
            try:
                cur = conn.cursor()

                # Try exact match first
                cur.execute(
                    "SELECT id FROM knowledge_base WHERE title = %s LIMIT 1",
                    (title,),
                )
                row = cur.fetchone()
                if row:
                    return row[0]

                # Try case-insensitive match
                cur.execute(
                    "SELECT id FROM knowledge_base WHERE LOWER(title) = LOWER(%s) LIMIT 1",
                    (title,),
                )
                row = cur.fetchone()
                if row:
                    return row[0]

                # Try partial match
                cur.execute(
                    """
                    SELECT id FROM knowledge_base
                    WHERE LOWER(title) LIKE LOWER(%s)
                    ORDER BY LENGTH(title)
                    LIMIT 1
                    """,
                    (f"%{title}%",),
                )
                row = cur.fetchone()
                return row[0] if row else None
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"Title lookup failed: {e}")
            return None

    def find_related(
        self,
        knowledge_id: int,
        relationship_types: Optional[list] = None,
        direction: str = "both",  # 'outgoing', 'incoming', 'both'
        min_strength: float = 0.0,
        limit: int = 20,
    ) -> list:
        """
        Find entries related to a knowledge entry.

        Args:
            knowledge_id: The source knowledge entry ID
            relationship_types: Filter by specific types, or None for all
            direction: 'outgoing' (from this), 'incoming' (to this), or 'both'
            min_strength: Minimum relationship strength
            limit: Maximum results

        Returns:
            List of RelatedEntry objects
        """
        results = []

        try:
            conn = get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Build type filter
            type_filter = ""
            type_params = []
            if relationship_types:
                type_filter = "AND r.relationship_type = ANY(%s)"
                type_params = [relationship_types]

            # Outgoing relationships (this entry points to others)
            if direction in ("outgoing", "both"):
                cur.execute(
                    f"""
                    SELECT
                        kb.id, kb.title, kb.category,
                        r.relationship_type, r.strength,
                        'outgoing' as direction
                    FROM knowledge_relationships r
                    JOIN knowledge_base kb ON r.to_id = kb.id
                    WHERE r.from_id = %s AND r.strength >= %s
                    {type_filter}
                    ORDER BY r.strength DESC
                    LIMIT %s
                    """,
                    [knowledge_id, min_strength] + type_params + [limit],
                )
                rows = cur.fetchall()
                for row in rows:
                    results.append(
                        RelatedEntry(
                            id=row["id"],
                            title=row["title"] or "Untitled",
                            category=row["category"] or "",
                            relationship_type=row["relationship_type"],
                            strength=float(row["strength"]),
                            direction="outgoing",
                        )
                    )

            # Incoming relationships (others point to this entry)
            if direction in ("incoming", "both"):
                cur.execute(
                    f"""
                    SELECT
                        kb.id, kb.title, kb.category,
                        r.relationship_type, r.strength,
                        'incoming' as direction
                    FROM knowledge_relationships r
                    JOIN knowledge_base kb ON r.from_id = kb.id
                    WHERE r.to_id = %s AND r.strength >= %s
                    {type_filter}
                    ORDER BY r.strength DESC
                    LIMIT %s
                    """,
                    [knowledge_id, min_strength] + type_params + [limit],
                )
                rows = cur.fetchall()
                for row in rows:
                    results.append(
                        RelatedEntry(
                            id=row["id"],
                            title=row["title"] or "Untitled",
                            category=row["category"] or "",
                            relationship_type=row["relationship_type"],
                            strength=float(row["strength"]),
                            direction="incoming",
                        )
                    )

            # Sort by strength and limit
            results.sort(key=lambda r: r.strength, reverse=True)
            return results[:limit]

        except Exception as e:
            logger.error(f"Find related failed: {e}")
            return []
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                conn.close()
            except Exception:
                pass

    def get_graph_stats(self) -> dict:
        """Get statistics about the knowledge graph"""
        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                # Total relationships
                cur.execute("SELECT COUNT(*) as total FROM knowledge_relationships")
                total = cur.fetchone()["total"]

                # Relationships by type
                cur.execute(
                    """
                    SELECT relationship_type, COUNT(*) as count
                    FROM knowledge_relationships
                    GROUP BY relationship_type
                    ORDER BY count DESC
                    """
                )
                by_type = {row["relationship_type"]: row["count"] for row in cur.fetchall()}

                # Average strength
                cur.execute("SELECT AVG(strength) as avg_strength FROM knowledge_relationships")
                avg_strength = cur.fetchone()["avg_strength"]

                # Entries with relationships
                cur.execute(
                    """
                    SELECT COUNT(DISTINCT id) as connected
                    FROM (
                        SELECT from_id as id FROM knowledge_relationships
                        UNION
                        SELECT to_id as id FROM knowledge_relationships
                    ) t
                    """
                )
                connected = cur.fetchone()["connected"]

                # Total entries
                cur.execute("SELECT COUNT(*) as total FROM knowledge_base")
                total_entries = cur.fetchone()["total"]
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

            return {
                "total_relationships": total,
                "by_type": by_type,
                "average_strength": round(float(avg_strength or 0), 3),
                "connected_entries": connected,
                "total_entries": total_entries,
                "connectivity_percent": (round(connected / total_entries * 100, 1) if total_entries > 0 else 0),
            }

        except Exception as e:
            logger.error(f"Get stats failed: {e}")
            return {"error": str(e)}

    def delete_relationship(
        self,
        from_id: int,
        to_id: int,
        relationship_type: str,
    ) -> bool:
        """Delete a specific relationship"""
        try:
            conn = get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    DELETE FROM knowledge_relationships
                    WHERE from_id = %s AND to_id = %s AND relationship_type = %s
                    """,
                    (from_id, to_id, relationship_type),
                )
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Delete relationship failed: {e}")
            return False


# Singleton instance
_mapper: Optional[RelationshipMapper] = None


def get_relationship_mapper() -> RelationshipMapper:
    """Get or create singleton mapper instance"""
    global _mapper
    if _mapper is None:
        _mapper = RelationshipMapper()
    return _mapper


def create_relationship(
    from_id: int,
    to_id: int,
    relationship_type: str,
    strength: float = 0.5,
) -> Optional[int]:
    """Convenience function to create relationship"""
    mapper = get_relationship_mapper()
    return mapper.create_relationship(from_id, to_id, relationship_type, strength)


def find_related(
    knowledge_id: int,
    relationship_types: Optional[list] = None,
    limit: int = 20,
) -> list:
    """Convenience function to find related entries"""
    mapper = get_relationship_mapper()
    return mapper.find_related(knowledge_id, relationship_types, limit=limit)


def graph_stats() -> dict:
    """Convenience function for graph stats"""
    mapper = get_relationship_mapper()
    return mapper.get_graph_stats()


if __name__ == "__main__":
    # Test when run directly
    logging.basicConfig(level=logging.INFO)

    print("Testing Relationship Mapper...")
    print("-" * 40)

    print(f"\nRelationship Types ({len(RELATIONSHIP_TYPES)}):")
    for rt in RELATIONSHIP_TYPES:
        print(f"  - {rt}")

    # Get stats
    stats = graph_stats()
    print("\nGraph Stats:")
    for key, value in stats.items():
        if key != "by_type":
            print(f"  {key}: {value}")
    if stats.get("by_type"):
        print("  Relationships by type:")
        for rt, count in stats["by_type"].items():
            print(f"    {rt}: {count}")

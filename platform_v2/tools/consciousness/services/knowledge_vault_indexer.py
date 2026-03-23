"""
Knowledge Vault Indexer
Indexes Obsidian vault notes into the knowledge base with embeddings and link graph

Purpose:
- Parse markdown + YAML frontmatter
- Extract [[wikilinks]] and create graph
- Generate 768-dim embeddings (Ollama arctic-embed-cpu)
- Index to knowledge_base table (is_documentation=true)
- Update vault_links table for relationships
- Log to vault_sync_log

Author: A.R.C.H.I.E. Platform
Date: 2026-01-08
"""

import os
import re
import json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path

# Import existing components
from tools.consciousness.services.obsidian_vault_manager import ObsidianVaultManager
from tools.consciousness.services.knowledge_embedding_generator import KnowledgeEmbeddingGenerator
from database import get_db


class KnowledgeVaultIndexer:
    """Indexes Obsidian vault notes into knowledge base"""

    def __init__(self):
        self.vault_manager = ObsidianVaultManager()
        self.embedding_generator = KnowledgeEmbeddingGenerator()
        self.vault_path = "/mnt/archie_brain/knowledge/"

    def _serialize_frontmatter(self, frontmatter: Dict) -> str:
        """Serialize frontmatter to JSON, converting datetime objects to ISO strings"""

        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {k: convert_datetime(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_datetime(item) for item in obj]
            return obj

        cleaned = convert_datetime(frontmatter)
        return json.dumps(cleaned)

    # ========================================================================
    # MAIN INDEXING FUNCTIONS
    # ========================================================================

    def reindex_note(self, file_path: str) -> Tuple[bool, str]:
        """
        Index or re-index a single note

        Args:
            file_path: Absolute path to the .md file

        Returns:
            Tuple of (success, message)
        """
        try:
            print(f"[Vault Indexer] Indexing: {os.path.basename(file_path)}")

            # Get note data from vault manager
            success, msg, note_data = self.vault_manager.get_note(file_path)
            if not success:
                return False, f"Failed to read note: {msg}"

            # Extract data
            title = note_data["title"]
            content = note_data["content"]
            frontmatter = note_data["frontmatter"]
            category = frontmatter.get("category", "Core")
            tags = frontmatter.get("tags", [])

            # Generate embedding
            print(f"[Vault Indexer] Generating embedding for '{title}'...")
            embedding_text = self._prepare_embedding_text(title, content, frontmatter)
            embedding = self.embedding_generator.generate_embedding(embedding_text)

            if not embedding:
                print(f"[Vault Indexer] Warning: No embedding generated for {title}")

            # Extract wikilinks
            wikilinks = self.vault_manager.extract_wikilinks(content)
            print(f"[Vault Indexer] Found {len(wikilinks)} wikilinks")

            # Check if note already exists in database
            note_id = self._get_note_id_by_file_path(file_path)

            if note_id:
                # Update existing note
                success = self._update_note_in_db(
                    note_id=note_id,
                    title=title,
                    content=content,
                    category=category,
                    tags=tags,
                    frontmatter=frontmatter,
                    file_path=file_path,
                    embedding=embedding,
                )
            else:
                # Create new note
                note_id = self._insert_note_to_db(
                    title=title,
                    content=content,
                    category=category,
                    tags=tags,
                    frontmatter=frontmatter,
                    file_path=file_path,
                    embedding=embedding,
                )
                success = note_id is not None

            if not success or not note_id:
                return False, "Failed to save note to database"

            # Update link graph
            if wikilinks:
                self._update_link_graph(note_id, wikilinks)

            print(f"[Vault Indexer] ✓ Indexed note #{note_id}: {title}")
            return True, f"Successfully indexed note: {title}"

        except Exception as e:
            error_msg = f"Error indexing note: {str(e)}"
            print(f"[Vault Indexer] {error_msg}")
            import traceback

            traceback.print_exc()
            return False, error_msg

    def reindex_all_notes(self) -> Dict:
        """
        Re-index all notes in the vault

        Returns:
            Dict with indexing statistics
        """
        try:
            print("[Vault Indexer] Starting full vault re-index...")

            stats = {
                "success": True,
                "total_found": 0,
                "indexed": 0,
                "failed": 0,
                "errors": [],
            }

            # Find all .md files
            for category in self.vault_manager.categories:
                category_path = os.path.join(self.vault_path, category)
                if not os.path.exists(category_path):
                    continue

                for filename in os.listdir(category_path):
                    if not filename.endswith(".md"):
                        continue

                    file_path = os.path.join(category_path, filename)
                    stats["total_found"] += 1

                    # Index note
                    success, msg = self.reindex_note(file_path)

                    if success:
                        stats["indexed"] += 1
                    else:
                        stats["failed"] += 1
                        stats["errors"].append({"file": filename, "error": msg})

            print(f"[Vault Indexer] Re-index complete: {stats['indexed']}/{stats['total_found']} succeeded")

            return stats

        except Exception as e:
            print(f"[Vault Indexer] Error in full re-index: {e}")
            return {"success": False, "error": str(e)}

    def delete_note_from_index(self, file_path: str) -> Tuple[bool, str]:
        """
        Remove a note from the index (called when file is deleted)

        Args:
            file_path: Path to deleted file

        Returns:
            Tuple of (success, message)
        """
        try:
            note_id = self._get_note_id_by_file_path(file_path)

            if not note_id:
                return True, "Note not found in index (already removed)"

            conn = None
            cursor = None
            try:
                conn = get_db()
                cursor = conn.cursor()

                # Delete from knowledge_base (CASCADE will delete vault_links)
                cursor.execute("DELETE FROM knowledge_base WHERE id = %s", (note_id,))

                conn.commit()
                print(f"[Vault Indexer] Deleted note #{note_id} from index")
                return True, "Note removed from index"
            finally:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()

        except Exception as e:
            print(f"[Vault Indexer] Error deleting note from index: {e}")
            return False, str(e)

    # ========================================================================
    # DATABASE OPERATIONS
    # ========================================================================

    def _insert_note_to_db(
        self,
        title: str,
        content: str,
        category: str,
        tags: List[str],
        frontmatter: Dict,
        file_path: str,
        embedding: Optional[List[float]] = None,
    ) -> Optional[int]:
        """Insert new note into knowledge_base table"""
        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Prepare embedding as JSON
            embedding_json = json.dumps(embedding) if embedding else None

            # Insert into knowledge_base
            cursor.execute(
                """
                INSERT INTO knowledge_base
                (knowledge_type, title, content, category, tags,
                 is_documentation, file_path, frontmatter_metadata,
                 embedding, last_synced_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """,
                (
                    "vault_note",  # knowledge_type (unified schema)
                    title,
                    content,
                    category,
                    [str(t) for t in tags],  # Convert all tags to strings
                    True,  # is_documentation
                    file_path,
                    self._serialize_frontmatter(frontmatter),  # frontmatter_metadata (handles datetime)
                    embedding_json,  # embedding vector
                    datetime.now(),  # last_synced_at
                    datetime.now(),  # created_at
                    datetime.now(),  # updated_at
                ),
            )

            note_id = cursor.fetchone()[0]

            conn.commit()
            return note_id

        except Exception as e:
            print(f"[Vault Indexer] Error inserting note to DB: {e}")
            import traceback

            traceback.print_exc()
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _update_note_in_db(
        self,
        note_id: int,
        title: str,
        content: str,
        category: str,
        tags: List[str],
        frontmatter: Dict,
        file_path: str,
        embedding: Optional[List[float]] = None,
    ) -> bool:
        """Update existing note in knowledge_base table"""
        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Prepare embedding as JSON
            embedding_json = json.dumps(embedding) if embedding else None

            # Update knowledge_base (include embedding if provided)
            cursor.execute(
                """
                UPDATE knowledge_base
                SET title = %s,
                    content = %s,
                    category = %s,
                    tags = %s,
                    frontmatter_metadata = %s,
                    embedding = COALESCE(%s, embedding),
                    last_synced_at = %s,
                    updated_at = %s
                WHERE id = %s
            """,
                (
                    title,
                    content,
                    category,
                    [str(t) for t in tags],  # Convert all tags to strings
                    self._serialize_frontmatter(frontmatter),  # Handle datetime objects
                    embedding_json,  # Update embedding if provided, keep existing otherwise
                    datetime.now(),
                    datetime.now(),
                    note_id,
                ),
            )

            conn.commit()
            return True

        except Exception as e:
            print(f"[Vault Indexer] Error updating note in DB: {e}")
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def _get_note_id_by_file_path(self, file_path: str) -> Optional[int]:
        """Get note ID from database by file path"""
        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id FROM knowledge_base WHERE file_path = %s AND is_documentation = TRUE",
                (file_path,),
            )

            result = cursor.fetchone()
            return result[0] if result else None

        except Exception as e:
            print(f"[Vault Indexer] Error getting note ID: {e}")
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # ========================================================================
    # WIKILINK GRAPH OPERATIONS
    # ========================================================================

    def _update_link_graph(self, source_note_id: int, wikilinks: List[str]):
        """
        Update vault_links table with wikilink relationships

        Args:
            source_note_id: ID of the source note
            wikilinks: List of wikilink texts extracted from content
        """
        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()

            # First, delete existing links from this source
            cursor.execute("DELETE FROM vault_links WHERE source_note_id = %s", (source_note_id,))

            # Resolve each wikilink to a target note ID
            for link_text in wikilinks:
                # Try to resolve wikilink to file path
                target_file_path = self.vault_manager.resolve_wikilink(link_text)

                if not target_file_path:
                    print(f"[Vault Indexer] Warning: Could not resolve wikilink '[[{link_text}]]'")
                    continue

                # Get target note ID
                target_note_id = self._get_note_id_by_file_path(target_file_path)

                if not target_note_id:
                    print(f"[Vault Indexer] Warning: Target note not indexed: {link_text}")
                    continue

                # Insert link
                cursor.execute(
                    """
                    INSERT INTO vault_links
                    (source_note_id, target_note_id, link_text, link_type, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_note_id, target_note_id, link_type) DO NOTHING
                """,
                    (
                        source_note_id,
                        target_note_id,
                        link_text,
                        "wikilink",
                        datetime.now(),
                    ),
                )

            conn.commit()
            print(f"[Vault Indexer] Updated link graph for note #{source_note_id}")

        except Exception as e:
            print(f"[Vault Indexer] Error updating link graph: {e}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def get_backlinks(self, note_id: int) -> List[Dict]:
        """
        Get all notes that link to this note

        Args:
            note_id: ID of the target note

        Returns:
            List of source notes with link information
        """
        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT
                    vl.source_note_id,
                    kb.title,
                    kb.category,
                    kb.file_path,
                    vl.link_text,
                    vl.created_at
                FROM vault_links vl
                JOIN knowledge_base kb ON vl.source_note_id = kb.id
                WHERE vl.target_note_id = %s
                ORDER BY vl.created_at DESC
            """,
                (note_id,),
            )

            backlinks = []
            for row in cursor.fetchall():
                backlinks.append(
                    {
                        "note_id": row[0],
                        "title": row[1],
                        "category": row[2],
                        "file_path": row[3],
                        "link_text": row[4],
                        "created_at": row[5],
                    }
                )

            return backlinks

        except Exception as e:
            print(f"[Vault Indexer] Error getting backlinks: {e}")
            return []
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    def get_link_graph(self, limit: int = 100) -> Dict:
        """
        Get full link graph for visualization

        Args:
            limit: Maximum number of links to return

        Returns:
            Dict with nodes and edges for graph visualization
        """
        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Get all links
            cursor.execute(
                """
                SELECT
                    vl.source_note_id,
                    vl.target_note_id,
                    vl.link_text,
                    s.title as source_title,
                    t.title as target_title
                FROM vault_links vl
                JOIN knowledge_base s ON vl.source_note_id = s.id
                JOIN knowledge_base t ON vl.target_note_id = t.id
                LIMIT %s
            """,
                (limit,),
            )

            edges = []
            nodes = {}

            for row in cursor.fetchall():
                source_id, target_id, link_text, source_title, target_title = row

                # Add nodes
                if source_id not in nodes:
                    nodes[source_id] = {"id": source_id, "title": source_title}
                if target_id not in nodes:
                    nodes[target_id] = {"id": target_id, "title": target_title}

                # Add edge
                edges.append({"source": source_id, "target": target_id, "link_text": link_text})

            return {"nodes": list(nodes.values()), "edges": edges}

        except Exception as e:
            print(f"[Vault Indexer] Error getting link graph: {e}")
            return {"nodes": [], "edges": []}
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    # ========================================================================
    # HELPER FUNCTIONS
    # ========================================================================

    def _prepare_embedding_text(self, title: str, content: str, frontmatter: Dict) -> str:
        """
        Prepare text for embedding generation

        Combines title, category, tags, and content
        """
        parts = [f"Title: {title}"]

        category = frontmatter.get("category", "")
        if category:
            parts.append(f"Category: {category}")

        tags = frontmatter.get("tags", [])
        if tags:
            parts.append(f"Tags: {', '.join(str(t) for t in tags)}")

        # Limit content to first 2000 chars to avoid token limits
        content_excerpt = content[:2000]
        parts.append(f"Content: {content_excerpt}")

        return "\n\n".join(parts)

    def get_indexing_stats(self) -> Dict:
        """Get indexing statistics"""
        conn = None
        cursor = None
        try:
            conn = get_db()
            cursor = conn.cursor()

            # Count vault notes
            cursor.execute("SELECT COUNT(*) FROM knowledge_base WHERE is_documentation = TRUE")
            note_count = cursor.fetchone()[0]

            # Count with embeddings
            cursor.execute(
                """
                SELECT COUNT(*) FROM knowledge_base
                WHERE is_documentation = TRUE
                AND embedding IS NOT NULL
            """
            )
            embedded_count = cursor.fetchone()[0]

            # Count links
            cursor.execute("SELECT COUNT(*) FROM vault_links")
            link_count = cursor.fetchone()[0]

            # Get recent sync events
            cursor.execute(
                """
                SELECT event_type, COUNT(*)
                FROM vault_sync_log
                WHERE detected_at > NOW() - INTERVAL '24 hours'
                GROUP BY event_type
            """
            )
            recent_events = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                "total_notes": note_count,
                "notes_with_embeddings": embedded_count,
                "total_links": link_count,
                "recent_events_24h": recent_events,
            }

        except Exception as e:
            print(f"[Vault Indexer] Error getting stats: {e}")
            return {}
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()


# ============================================================================
# STANDALONE FUNCTIONS (for import by watcher and API)
# ============================================================================


def reindex_note(file_path: str) -> Tuple[bool, str]:
    """Index a single note (called by file watcher)"""
    indexer = KnowledgeVaultIndexer()
    return indexer.reindex_note(file_path)


def reindex_all_notes() -> Dict:
    """Re-index entire vault (admin function)"""
    indexer = KnowledgeVaultIndexer()
    return indexer.reindex_all_notes()


def delete_note_from_index(file_path: str) -> Tuple[bool, str]:
    """Remove note from index (called when deleted)"""
    indexer = KnowledgeVaultIndexer()
    return indexer.delete_note_from_index(file_path)


def get_indexing_stats() -> Dict:
    """Get indexing statistics"""
    indexer = KnowledgeVaultIndexer()
    return indexer.get_indexing_stats()


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("=== Knowledge Vault Indexer Test ===\n")

    indexer = KnowledgeVaultIndexer()

    # Test 1: Index a single note
    test_note_path = "/mnt/archie_brain/knowledge/Core/Test_Note.md"

    if os.path.exists(test_note_path):
        print("Test 1: Indexing single note")
        success, msg = indexer.reindex_note(test_note_path)
        print(f"  Result: {msg}\n")
    else:
        print("Test 1: Skipped (test note not found)\n")

    # Test 2: Get indexing stats
    print("Test 2: Get indexing statistics")
    stats = indexer.get_indexing_stats()
    print(f"  Total notes: {stats.get('total_notes', 0)}")
    print(f"  Notes with embeddings: {stats.get('notes_with_embeddings', 0)}")
    print(f"  Total links: {stats.get('total_links', 0)}")
    print(f"  Recent events: {stats.get('recent_events_24h', {})}\n")

    # Test 3: Full re-index (commented out for safety)
    # print("Test 3: Full vault re-index")
    # result = indexer.reindex_all_notes()
    # print(f"  Indexed: {result.get('indexed', 0)}/{result.get('total_found', 0)}")
    # print(f"  Failed: {result.get('failed', 0)}")

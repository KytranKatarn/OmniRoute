"""
Obsidian Vault Manager
Core business logic for Obsidian vault operations

Purpose:
- Create, read, update, delete notes in /mnt/archie_brain/knowledge/
- Generate and parse YAML frontmatter
- Manage [[wikilinks]] and backlinks
- Search vault (hybrid keyword + semantic)
- Integrate with existing knowledge base

Author: A.R.C.H.I.E. Platform
Date: 2026-01-08
"""

import os
import re
import yaml
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from pathlib import Path


class ObsidianVaultManager:
    """Manages all Obsidian vault operations"""

    def __init__(self, vault_path: str = "/mnt/archie_brain/knowledge/"):
        self.vault_path = vault_path
        self.categories = [
            "Core",
            "Features",
            "Development",
            "Agents",
            "APIs",
            "Workflows",
        ]

    # ========================================================================
    # CRUD OPERATIONS
    # ========================================================================

    def create_note(
        self,
        title: str,
        content: str,
        category: str = "Core",
        tags: List[str] = None,
        metadata: Dict = None,
        author: str = "archie",
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Create a new note with YAML frontmatter

        Args:
            title: Note title
            content: Note body content
            category: Category folder (Core, Features, etc.)
            tags: List of tags
            metadata: Additional metadata
            author: Author name

        Returns:
            Tuple of (success, message, file_path)
        """
        try:
            # Validate category
            if category not in self.categories:
                return (
                    False,
                    f"Invalid category. Must be one of: {', '.join(self.categories)}",
                    None,
                )

            # Sanitize filename
            filename = self.sanitize_filename(title)
            file_path = os.path.join(self.vault_path, category, f"{filename}.md")

            # Check if file already exists
            if os.path.exists(file_path):
                return False, f"Note '{title}' already exists in {category}", None

            # Generate frontmatter
            frontmatter = self.generate_frontmatter(
                title=title,
                category=category,
                tags=tags or [],
                author=author,
                metadata=metadata or {},
            )

            # Create full content
            full_content = f"---\n{frontmatter}---\n\n{content}"

            # Ensure category directory exists
            os.makedirs(os.path.join(self.vault_path, category), exist_ok=True)

            # Write file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_content)

            return True, f"Note '{title}' created successfully", file_path

        except Exception as e:
            return False, f"Error creating note: {str(e)}", None

    def get_note(self, file_path: str) -> Tuple[bool, str, Optional[Dict]]:
        """
        Get note with parsed frontmatter

        Args:
            file_path: Absolute or relative path to note

        Returns:
            Tuple of (success, message, note_data)
            note_data contains: {title, content, frontmatter, file_path}
        """
        try:
            # Handle relative paths
            if not file_path.startswith("/"):
                file_path = os.path.join(self.vault_path, file_path)

            if not os.path.exists(file_path):
                return False, f"Note not found: {file_path}", None

            with open(file_path, "r", encoding="utf-8") as f:
                raw_content = f.read()

            # Parse frontmatter
            frontmatter_data, body = self.parse_frontmatter(raw_content)

            note_data = {
                "title": frontmatter_data.get("title", os.path.basename(file_path).replace(".md", "")),
                "content": body,
                "frontmatter": frontmatter_data,
                "file_path": file_path,
            }

            return True, "Note retrieved successfully", note_data

        except Exception as e:
            return False, f"Error reading note: {str(e)}", None

    def update_note(
        self,
        file_path: str,
        content: Optional[str] = None,
        frontmatter_updates: Optional[Dict] = None,
    ) -> Tuple[bool, str]:
        """
        Update existing note

        Args:
            file_path: Path to note
            content: New content (if None, keep existing)
            frontmatter_updates: Dict of frontmatter fields to update

        Returns:
            Tuple of (success, message)
        """
        try:
            # Get existing note
            success, msg, note_data = self.get_note(file_path)
            if not success:
                return False, msg

            # Update frontmatter
            frontmatter = note_data["frontmatter"]
            if frontmatter_updates:
                frontmatter.update(frontmatter_updates)

            # Always update the 'updated' timestamp
            frontmatter["updated"] = datetime.now().isoformat()

            # Use existing content if not provided
            body = content if content is not None else note_data["content"]

            # Generate updated frontmatter YAML
            frontmatter_yaml = yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)

            # Create full content
            full_content = f"---\n{frontmatter_yaml}---\n\n{body}"

            # Write file
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_content)

            return True, "Note updated successfully"

        except Exception as e:
            return False, f"Error updating note: {str(e)}"

    def delete_note(self, file_path: str) -> Tuple[bool, str]:
        """
        Delete a note

        Args:
            file_path: Path to note

        Returns:
            Tuple of (success, message)
        """
        try:
            if not os.path.exists(file_path):
                return False, f"Note not found: {file_path}"

            os.remove(file_path)
            return True, "Note deleted successfully"

        except Exception as e:
            return False, f"Error deleting note: {str(e)}"

    # ========================================================================
    # FRONTMATTER OPERATIONS
    # ========================================================================

    def generate_frontmatter(
        self,
        title: str,
        category: str,
        tags: List[str],
        author: str = "archie",
        metadata: Dict = None,
    ) -> str:
        """
        Generate YAML frontmatter

        Returns:
            YAML string (without --- delimiters)
        """
        now = datetime.now().isoformat()

        frontmatter_dict = {
            "title": title,
            "created": now,
            "updated": now,
            "category": category,
            "tags": tags,
            "status": "active",
            "author": author,
            "version": "1.0",
        }

        # Add any additional metadata
        if metadata:
            for key, value in metadata.items():
                if key not in frontmatter_dict:  # Don't override core fields
                    frontmatter_dict[key] = value

        return yaml.dump(frontmatter_dict, default_flow_style=False, allow_unicode=True)

    def parse_frontmatter(self, content: str) -> Tuple[Dict, str]:
        """
        Parse YAML frontmatter from markdown content

        Args:
            content: Full markdown content with frontmatter

        Returns:
            Tuple of (frontmatter_dict, body_content)
        """
        # Match frontmatter between --- delimiters
        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content, re.DOTALL)

        if match:
            frontmatter_yaml = match.group(1)
            body = match.group(2).strip()

            try:
                frontmatter_dict = yaml.safe_load(frontmatter_yaml) or {}
            except yaml.YAMLError:
                frontmatter_dict = {}

            return frontmatter_dict, body
        else:
            # No frontmatter found, return empty dict and full content
            return {}, content.strip()

    # ========================================================================
    # WIKILINK OPERATIONS
    # ========================================================================

    def extract_wikilinks(self, content: str) -> List[str]:
        """
        Extract [[wikilinks]] from content

        Args:
            content: Markdown content

        Returns:
            List of wikilink targets (without brackets)
        """
        pattern = r"\[\[([^\]]+)\]\]"
        matches = re.findall(pattern, content)
        return matches

    def resolve_wikilink(self, link_text: str) -> Optional[str]:
        """
        Resolve a wikilink to a file path

        Args:
            link_text: The text inside [[brackets]]

        Returns:
            File path if found, None otherwise
        """
        # Search all categories for matching note
        for category in self.categories:
            category_path = os.path.join(self.vault_path, category)
            if not os.path.exists(category_path):
                continue

            for filename in os.listdir(category_path):
                if not filename.endswith(".md"):
                    continue

                # Check if title matches (with or without .md)
                title = filename.replace(".md", "")
                if title.lower() == link_text.lower():
                    return os.path.join(category_path, filename)

                # Also check frontmatter title
                file_path = os.path.join(category_path, filename)
                success, _, note_data = self.get_note(file_path)
                if success and note_data:
                    note_title = note_data["frontmatter"].get("title", "")
                    if note_title.lower() == link_text.lower():
                        return file_path

        return None

    def get_backlinks(self, file_path: str) -> List[str]:
        """
        Find all notes that link to this note

        Args:
            file_path: Path to note

        Returns:
            List of file paths that contain links to this note
        """
        backlinks = []

        # Get the title of the target note
        success, _, note_data = self.get_note(file_path)
        if not success:
            return backlinks

        target_title = note_data["frontmatter"].get("title", "")

        # Search all notes for links to this title
        for category in self.categories:
            category_path = os.path.join(self.vault_path, category)
            if not os.path.exists(category_path):
                continue

            for filename in os.listdir(category_path):
                if not filename.endswith(".md"):
                    continue

                check_path = os.path.join(category_path, filename)
                if check_path == file_path:  # Skip self
                    continue

                success, _, check_note = self.get_note(check_path)
                if success and check_note:
                    content = check_note["content"]
                    wikilinks = self.extract_wikilinks(content)

                    # Check if any wikilinks match our title
                    for link in wikilinks:
                        if link.lower() == target_title.lower():
                            backlinks.append(check_path)
                            break

        return backlinks

    # ========================================================================
    # SEARCH OPERATIONS
    # ========================================================================

    def search_vault(
        self,
        query: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """
        Search vault with keyword matching

        Args:
            query: Search query
            category: Filter by category
            tags: Filter by tags
            limit: Max results

        Returns:
            List of matching notes with metadata
        """
        results = []
        query_lower = query.lower()

        # Determine which categories to search
        categories_to_search = [category] if category else self.categories

        for cat in categories_to_search:
            category_path = os.path.join(self.vault_path, cat)
            if not os.path.exists(category_path):
                continue

            for filename in os.listdir(category_path):
                if not filename.endswith(".md"):
                    continue

                file_path = os.path.join(category_path, filename)
                success, _, note_data = self.get_note(file_path)

                if not success:
                    continue

                # Apply tag filter
                if tags:
                    note_tags = note_data["frontmatter"].get("tags", [])
                    if not any(tag in note_tags for tag in tags):
                        continue

                # Check if query matches title or content
                title = note_data["frontmatter"].get("title", "").lower()
                content = note_data["content"].lower()

                if query_lower in title or query_lower in content:
                    # Calculate simple relevance score
                    title_match = query_lower in title
                    score = 2.0 if title_match else 1.0

                    results.append(
                        {
                            "title": note_data["frontmatter"].get("title", ""),
                            "category": cat,
                            "tags": note_data["frontmatter"].get("tags", []),
                            "content": note_data["content"][:300],  # Preview
                            "file_path": file_path,
                            "score": score,
                        }
                    )

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)

        return results[:limit]

    def list_notes(self, category: Optional[str] = None) -> List[Dict]:
        """
        List all notes in vault

        Args:
            category: Filter by category (optional)

        Returns:
            List of note metadata
        """
        notes = []
        categories_to_list = [category] if category else self.categories

        for cat in categories_to_list:
            category_path = os.path.join(self.vault_path, cat)
            if not os.path.exists(category_path):
                continue

            for filename in os.listdir(category_path):
                if not filename.endswith(".md"):
                    continue

                file_path = os.path.join(category_path, filename)
                success, _, note_data = self.get_note(file_path)

                if success and note_data:
                    notes.append(
                        {
                            "title": note_data["frontmatter"].get("title", ""),
                            "category": cat,
                            "tags": note_data["frontmatter"].get("tags", []),
                            "created": note_data["frontmatter"].get("created", ""),
                            "updated": note_data["frontmatter"].get("updated", ""),
                            "file_path": file_path,
                        }
                    )

        return notes

    # ========================================================================
    # UTILITY FUNCTIONS
    # ========================================================================

    def sanitize_filename(self, title: str) -> str:
        """
        Convert title to safe filename

        Args:
            title: Note title

        Returns:
            Sanitized filename (without .md extension)
        """
        # Remove special characters, replace spaces with underscores
        safe_title = re.sub(r"[^\w\s-]", "", title)
        safe_title = re.sub(r"[\s]+", "_", safe_title)
        return safe_title.strip("_")

    def get_vault_stats(self) -> Dict:
        """
        Get vault statistics from both file system AND database

        Returns:
            Dict with note count, category breakdown, tag counts
        """
        stats = {"total_notes": 0, "by_category": {}, "tags": {}}

        # 1. Get file system stats (original behavior)
        for category in self.categories:
            category_path = os.path.join(self.vault_path, category)
            if not os.path.exists(category_path):
                continue

            note_count = len([f for f in os.listdir(category_path) if f.endswith(".md")])
            if note_count > 0:
                stats["by_category"][category] = note_count
                stats["total_notes"] += note_count

            # Count tags from files
            for filename in os.listdir(category_path):
                if not filename.endswith(".md"):
                    continue

                file_path = os.path.join(category_path, filename)
                success, _, note_data = self.get_note(file_path)

                if success and note_data:
                    tags = note_data["frontmatter"].get("tags", [])
                    for tag in tags:
                        stats["tags"][tag] = stats["tags"].get(tag, 0) + 1

        # 2. Get database stats (knowledge_base categories)
        try:
            from database import get_db

            conn = get_db()
            cursor = conn.cursor()

            # Get category counts from database
            cursor.execute(
                """
                SELECT category, COUNT(*) as count
                FROM knowledge_base
                WHERE category IS NOT NULL AND category != ''
                GROUP BY category
                ORDER BY count DESC
            """
            )

            for row in cursor.fetchall():
                category = row[0]
                count = row[1]
                # Add to stats (merge with file system stats)
                if category in stats["by_category"]:
                    stats["by_category"][category] += count
                else:
                    stats["by_category"][category] = count
                stats["total_notes"] += count

            # Get tag counts from database
            cursor.execute(
                """
                SELECT unnest(tags) as tag, COUNT(*) as count
                FROM knowledge_base
                WHERE tags IS NOT NULL AND array_length(tags, 1) > 0
                GROUP BY tag
                ORDER BY count DESC
                LIMIT 50
            """
            )

            for row in cursor.fetchall():
                tag = row[0]
                count = row[1]
                stats["tags"][tag] = stats["tags"].get(tag, 0) + count

            cursor.close()

        except Exception as e:
            # If database fails, still return file system stats
            print(f"[VaultManager] Database stats error: {e}")

        return stats


# ============================================================================
# STANDALONE FUNCTIONS (for CLI usage)
# ============================================================================


def get_watcher_status() -> Dict:
    """
    Get status of vault file watcher

    Returns:
        Dict with running status and stats
    """
    # This will be implemented in obsidian_vault_watcher.py
    # Placeholder for now
    return {"running": False, "notes_indexed": 0, "last_sync": None}


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    # Test vault manager
    manager = ObsidianVaultManager()

    print("=== Obsidian Vault Manager Test ===\n")

    # Test 1: Create note
    success, msg, file_path = manager.create_note(
        title="Test Note",
        content="This is a test note with [[Test Link]] and #test-tag",
        category="Core",
        tags=["test", "demo"],
    )
    print(f"Create Note: {msg}")

    if success:
        # Test 2: Get note
        success, msg, note_data = manager.get_note(file_path)
        print(f"Get Note: {msg}")
        if note_data:
            print(f"  Title: {note_data['frontmatter']['title']}")
            print(f"  Tags: {note_data['frontmatter']['tags']}")

        # Test 3: Extract wikilinks
        links = manager.extract_wikilinks(note_data["content"])
        print(f"Wikilinks found: {links}")

        # Test 4: Update note
        success, msg = manager.update_note(file_path, frontmatter_updates={"status": "updated"})
        print(f"Update Note: {msg}")

    # Test 5: Search vault
    results = manager.search_vault("test")
    print(f"\nSearch results for 'test': {len(results)} found")

    # Test 6: Vault stats
    stats = manager.get_vault_stats()
    print(f"\nVault Stats:")
    print(f"  Total notes: {stats['total_notes']}")
    print(f"  By category: {stats['by_category']}")
    print(f"  Tags: {stats['tags']}")

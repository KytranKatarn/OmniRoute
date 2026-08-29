"""
Knowledge Cards Module for ARCHIE Consciousness Intelligence

Handles saving knowledge cards to database and exporting to Markdown files.
Cards are structured extractions from AI analysis, stored persistently.

Usage:
    from ai_bridge.knowledge_cards import save_knowledge_card, export_to_markdown

    # Save a card from analysis
    card_id = save_knowledge_card(knowledge_card, embedding)

    # Export cards to markdown files
    stats = export_to_markdown(card_ids)
"""

import os
import json
import logging
import re
import threading
from datetime import datetime
from typing import Optional
from psycopg2.extras import RealDictCursor
from db import get_db

logger = logging.getLogger(__name__)

# Configuration
KNOWLEDGE_CARDS_DIR = "/mnt/archie_brain/knowledge_cards"
CARD_SUBDIRS = [
    "concepts",
    "patterns",
    "problem-solutions",
    "examples",
    "references",
    "daily-logs",
]


def ensure_directories() -> bool:
    """Ensure knowledge cards directory structure exists"""
    try:
        os.makedirs(KNOWLEDGE_CARDS_DIR, exist_ok=True)
        for subdir in CARD_SUBDIRS:
            os.makedirs(os.path.join(KNOWLEDGE_CARDS_DIR, subdir), exist_ok=True)
        return True
    except OSError as e:
        logger.error(f"Failed to create directories: {e}")
        return False


def slugify(text: str) -> str:
    """Convert text to URL-friendly slug"""
    # Convert to lowercase
    slug = text.lower()
    # Replace spaces with hyphens
    slug = re.sub(r"\s+", "-", slug)
    # Remove special characters
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    # Remove multiple consecutive hyphens
    slug = re.sub(r"-+", "-", slug)
    # Trim hyphens from ends
    slug = slug.strip("-")
    # Limit length
    return slug[:60]


def save_knowledge_card(
    card,  # KnowledgeCard from knowledge_analyzer
    embedding: Optional[list] = None,
    batch_id: Optional[str] = None,
) -> Optional[int]:
    """
    Save a knowledge card to the database.

    Args:
        card: KnowledgeCard dataclass from analyzer
        embedding: Optional 768-dimension vector
        batch_id: Optional batch processing ID

    Returns:
        knowledge_base ID if saved, None on failure
    """
    try:
        conn = get_db()
        try:
            cur = conn.cursor()

            # Build content from card
            content_parts = [card.summary]
            if card.detailed:
                content_parts.append(card.detailed)
            if card.code_examples:
                content_parts.append("\n\n## Code Examples\n")
                for i, example in enumerate(card.code_examples, 1):
                    content_parts.append(f"```\n{example}\n```\n")
            content = "\n\n".join(content_parts)

            # Build metadata
            metadata = {
                "card_type": card.card_type,
                "topics": card.topics,
                "technologies": card.technologies,
                "difficulty": card.difficulty,
                "confidence": card.confidence,
                "source_type": card.source_type,
                "source_ref": card.source_ref,
                "batch_id": batch_id,
                "created_by": "knowledge_analyzer",
                "analysis_version": 1,
            }

            # Build AI analysis structure
            ai_analysis = {
                "card_type": card.card_type,
                "summary": card.summary,
                "detailed": card.detailed,
                "code_examples": card.code_examples,
                "topics": card.topics,
                "technologies": card.technologies,
                "difficulty": card.difficulty,
                "confidence": card.confidence,
                "extraction_date": datetime.now().isoformat(),
            }

            # Insert into knowledge_base (upsert on duplicate title)
            if embedding:
                cur.execute(
                    """
                    INSERT INTO knowledge_base
                        (title, content, knowledge_type, source_type, category,
                         importance_score, memory_metadata, tags, embedding, embedding_generated_at,
                         ai_analysis, analysis_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), %s, 1)
                    ON CONFLICT (title) WHERE title IS NOT NULL DO UPDATE SET
                        content = EXCLUDED.content,
                        ai_analysis = EXCLUDED.ai_analysis,
                        embedding = EXCLUDED.embedding,
                        embedding_generated_at = NOW(),
                        importance_score = EXCLUDED.importance_score,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        card.title,
                        content,
                        f"knowledge_card_{card.card_type}",
                        card.source_type,
                        card.card_type,
                        card.confidence,  # Use confidence as importance
                        json.dumps(metadata),
                        card.topics + card.technologies,
                        embedding,
                        json.dumps(ai_analysis),
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO knowledge_base
                        (title, content, knowledge_type, source_type, category,
                         importance_score, memory_metadata, tags, ai_analysis, analysis_version)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 1)
                    ON CONFLICT (title) WHERE title IS NOT NULL DO UPDATE SET
                        content = EXCLUDED.content,
                        ai_analysis = EXCLUDED.ai_analysis,
                        importance_score = EXCLUDED.importance_score,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    (
                        card.title,
                        content,
                        f"knowledge_card_{card.card_type}",
                        card.source_type,
                        card.card_type,
                        card.confidence,
                        json.dumps(metadata),
                        card.topics + card.technologies,
                        json.dumps(ai_analysis),
                    ),
                )

            result = cur.fetchone()
            conn.commit()

            card_id = result[0]
            logger.info(f"Saved knowledge card '{card.title}' as ID {card_id}")

            # Quality gate: score asynchronously to not block card creation
            if card_id:

                def _score_async(cid, t, c, kt):
                    try:
                        from services.quality_scoring_service import score_entry

                        score_entry(cid, t, c, kt, save_to_db=True)
                    except Exception as e:
                        logger.debug("Async quality scoring failed for card %d: %s", cid, e)

                threading.Thread(
                    target=_score_async,
                    args=(card_id, card.title, card.summary, f"knowledge_card_{card.card_type}"),
                    daemon=True,
                ).start()

            return card_id
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
        logger.error(f"Failed to save knowledge card: {e}")
        return None


def export_to_markdown(
    knowledge_ids: Optional[list] = None,
    since_date: Optional[datetime] = None,
    limit: int = 100,
) -> dict:
    """
    Export knowledge cards to Markdown files.

    Args:
        knowledge_ids: Specific IDs to export, or None for recent
        since_date: Export cards created since this date
        limit: Maximum number to export

    Returns:
        dict with export statistics
    """
    ensure_directories()
    stats = {"exported": 0, "skipped": 0, "errors": [], "files": []}

    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)

            # Build query based on parameters
            if knowledge_ids:
                cur.execute(
                    """
                    SELECT id, title, content, knowledge_type, category,
                           importance_score, memory_metadata, tags, ai_analysis, created_at
                    FROM knowledge_base
                    WHERE id = ANY(%s) AND ai_analysis IS NOT NULL
                    ORDER BY created_at DESC
                    """,
                    (knowledge_ids,),
                )
            elif since_date:
                cur.execute(
                    """
                    SELECT id, title, content, knowledge_type, category,
                           importance_score, memory_metadata, tags, ai_analysis, created_at
                    FROM knowledge_base
                    WHERE ai_analysis IS NOT NULL AND created_at >= %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (since_date, limit),
                )
            else:
                cur.execute(
                    """
                    SELECT id, title, content, knowledge_type, category,
                           importance_score, memory_metadata, tags, ai_analysis, created_at
                    FROM knowledge_base
                    WHERE ai_analysis IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (limit,),
                )

            rows = cur.fetchall()

            for row in rows:
                try:
                    filepath = _export_single_card(dict(row))
                    if filepath:
                        stats["exported"] += 1
                        stats["files"].append(filepath)
                    else:
                        stats["skipped"] += 1
                except Exception as e:
                    stats["errors"].append({"id": row["id"], "error": str(e)})

            return stats
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
        logger.error(f"Export failed: {e}")
        stats["errors"].append({"error": str(e)})
        return stats


def _export_single_card(row: dict) -> Optional[str]:
    """Export a single card to markdown file"""
    ai_analysis = row.get("ai_analysis", {})
    if isinstance(ai_analysis, str):
        ai_analysis = json.loads(ai_analysis)

    metadata = row.get("memory_metadata", {})
    if isinstance(metadata, str):
        metadata = json.loads(metadata)

    # Determine subdirectory
    card_type = ai_analysis.get("card_type", "concepts")
    type_to_dir = {
        "concept": "concepts",
        "pattern": "patterns",
        "problem-solution": "problem-solutions",
        "example": "examples",
        "reference": "references",
    }
    subdir = type_to_dir.get(card_type, "concepts")

    # Generate filename
    slug = slugify(row["title"])
    filename = f"{slug}.md"
    filepath = os.path.join(KNOWLEDGE_CARDS_DIR, subdir, filename)

    # Build markdown content
    md_content = _generate_markdown(row, ai_analysis, metadata)

    # Write file
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md_content)

    return filepath


def _generate_markdown(row: dict, ai_analysis: dict, metadata: dict) -> str:
    """Generate markdown content for a knowledge card"""
    lines = []

    # Title
    lines.append(f"# {row['title']}")
    lines.append("")

    # Frontmatter-style metadata
    card_type = ai_analysis.get("card_type", "concept")
    confidence = ai_analysis.get("confidence", 0.7)
    difficulty = ai_analysis.get("difficulty", "intermediate")
    lines.append(f"**Type:** {card_type} | **Confidence:** {confidence:.2f} | **Difficulty:** {difficulty}")
    lines.append("")

    # Summary
    summary = ai_analysis.get("summary", "")
    if summary:
        lines.append("## Summary")
        lines.append("")
        lines.append(summary)
        lines.append("")

    # Detailed explanation
    detailed = ai_analysis.get("detailed", "")
    if detailed:
        lines.append("## Detailed Explanation")
        lines.append("")
        lines.append(detailed)
        lines.append("")

    # Code examples
    code_examples = ai_analysis.get("code_examples", [])
    if code_examples:
        lines.append("## Code Examples")
        lines.append("")
        for example in code_examples:
            lines.append("```")
            lines.append(example)
            lines.append("```")
            lines.append("")

    # Topics and technologies
    topics = ai_analysis.get("topics", [])
    technologies = ai_analysis.get("technologies", [])
    if topics or technologies:
        lines.append("## Classification")
        lines.append("")
        if topics:
            lines.append(f"**Topics:** {', '.join(topics)}")
        if technologies:
            lines.append(f"**Technologies:** {', '.join(technologies)}")
        lines.append("")

    # Footer
    lines.append("---")
    source_type = metadata.get("source_type", "unknown")
    source_ref = metadata.get("source_ref", "")
    created_at = row.get("created_at", datetime.now())
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    lines.append(f"*Source: {source_type} | Ref: {source_ref} | Created: {created_at.strftime('%Y-%m-%d %H:%M')}*")
    lines.append(f"*Knowledge ID: {row['id']} | Analysis Version: 1*")
    lines.append("")

    return "\n".join(lines)


def get_export_stats() -> dict:
    """Get statistics about exported knowledge cards"""
    stats = {"directory_exists": os.path.exists(KNOWLEDGE_CARDS_DIR), "subdirs": {}}

    if stats["directory_exists"]:
        for subdir in CARD_SUBDIRS:
            path = os.path.join(KNOWLEDGE_CARDS_DIR, subdir)
            if os.path.exists(path):
                files = [f for f in os.listdir(path) if f.endswith(".md")]
                stats["subdirs"][subdir] = len(files)
            else:
                stats["subdirs"][subdir] = 0

        stats["total_files"] = sum(stats["subdirs"].values())

    return stats


def get_card_by_id(knowledge_id: int) -> Optional[dict]:
    """Get a knowledge card by ID"""
    try:
        conn = get_db()
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                """
                SELECT id, title, content, knowledge_type, category,
                       importance_score, memory_metadata, tags, ai_analysis, created_at
                FROM knowledge_base
                WHERE id = %s
                """,
                (knowledge_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
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
        logger.error(f"Failed to get card {knowledge_id}: {e}")
        return None


if __name__ == "__main__":
    # Test when run directly
    logging.basicConfig(level=logging.INFO)

    print("Testing Knowledge Cards Module...")
    print("-" * 40)

    # Ensure directories
    ensure_directories()
    print(f"Knowledge cards directory: {KNOWLEDGE_CARDS_DIR}")

    # Get stats
    stats = get_export_stats()
    print(f"\nExport Stats:")
    print(f"  Directory exists: {stats['directory_exists']}")
    if stats.get("subdirs"):
        for subdir, count in stats["subdirs"].items():
            print(f"  {subdir}/: {count} files")
        print(f"  Total: {stats.get('total_files', 0)} files")

#!/usr/bin/env python3
"""
Conversation Insights Extractor
Phase 64: Claude Code Optimization

Extracts key decisions, learnings, TODOs, and patterns from conversation transcripts.
Stores them as separate knowledge entries for better retrieval.
"""

import os
import re
import json
import sys
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('insights_extractor')

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'archie_database'),
    'database': os.getenv('DB_NAME', 'archie'),
    'user': os.getenv('DB_USER', 'archie'),
    'password': os.getenv('DB_PASSWORD', 'archie_secure_2024')
}


def get_db_connection():
    """Get database connection"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None


# ============================================================================
# EXTRACTION PATTERNS
# ============================================================================

DECISION_PATTERNS = [
    # Direct decisions
    r"(?:I'll|I will|Let's|We'll|We will|Going to)\s+(.{20,200}?)(?:\.|$)",
    r"(?:decided to|choosing to|opting for|going with)\s+(.{20,200}?)(?:\.|$)",
    r"(?:The approach|The solution|The fix|The implementation)\s+(?:is|will be)\s+(.{20,200}?)(?:\.|$)",
    # Recommendations
    r"(?:recommend|suggest|advise)\s+(?:using|implementing|creating)\s+(.{20,200}?)(?:\.|$)",
    r"(?:best approach|better approach|recommended approach)\s+(?:is|would be)\s+(.{20,200}?)(?:\.|$)",
]

LEARNING_PATTERNS = [
    # Discoveries
    r"(?:Found|Discovered|Realized|Learned|Noticed)\s+(?:that\s+)?(.{20,200}?)(?:\.|$)",
    r"(?:The issue|The problem|The cause|The root cause)\s+(?:is|was)\s+(.{20,200}?)(?:\.|$)",
    # Understanding
    r"(?:Now I understand|I see that|It turns out|This means)\s+(.{20,200}?)(?:\.|$)",
    r"(?:The reason|This happens because|This is because)\s+(.{20,200}?)(?:\.|$)",
]

TODO_PATTERNS = [
    r"(?:TODO|FIXME|NOTE|IMPORTANT):\s*(.{10,200}?)(?:\n|$)",
    r"(?:Need to|Should|Must|Have to)\s+(.{20,150}?)(?:\.|$)",
    r"(?:Don't forget to|Remember to|Make sure to)\s+(.{20,150}?)(?:\.|$)",
    r"(?:Next step|Next task|Follow-up):\s*(.{10,200}?)(?:\n|$)",
]

ERROR_PATTERNS = [
    # Common errors
    r"(?:Error|Exception|Failed|Failure):\s*(.{20,300}?)(?:\n|$)",
    r"(?:could not|cannot|unable to)\s+(.{20,200}?)(?:\.|$)",
    r"(?:The fix|Fixed by|Resolved by|Solution was)\s+(.{20,200}?)(?:\.|$)",
]


def extract_insights(transcript: str) -> Dict[str, List[Dict]]:
    """
    Extract key insights from a conversation transcript.

    Returns dict with:
    - decisions: Key decisions made
    - learnings: Things learned/discovered
    - todos: Action items mentioned
    - errors: Error patterns and fixes
    """

    insights = {
        'decisions': [],
        'learnings': [],
        'todos': [],
        'errors': []
    }

    # Remove code blocks to avoid false matches
    clean_text = re.sub(r'```[\s\S]*?```', '[CODE BLOCK]', transcript)
    clean_text = re.sub(r'`[^`]+`', '[CODE]', clean_text)

    # Extract decisions
    for pattern in DECISION_PATTERNS:
        matches = re.findall(pattern, clean_text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            if len(match) > 25:  # Filter noise
                insights['decisions'].append({
                    'content': match.strip(),
                    'pattern': 'decision'
                })

    # Extract learnings
    for pattern in LEARNING_PATTERNS:
        matches = re.findall(pattern, clean_text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            if len(match) > 25:
                insights['learnings'].append({
                    'content': match.strip(),
                    'pattern': 'learning'
                })

    # Extract TODOs
    for pattern in TODO_PATTERNS:
        matches = re.findall(pattern, clean_text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            if len(match) > 15:
                insights['todos'].append({
                    'content': match.strip(),
                    'pattern': 'todo'
                })

    # Extract errors/fixes
    for pattern in ERROR_PATTERNS:
        matches = re.findall(pattern, clean_text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            if len(match) > 20:
                insights['errors'].append({
                    'content': match.strip(),
                    'pattern': 'error_fix'
                })

    # Deduplicate
    for key in insights:
        seen = set()
        unique = []
        for item in insights[key]:
            content_key = item['content'][:100].lower()
            if content_key not in seen:
                seen.add(content_key)
                unique.append(item)
        insights[key] = unique[:10]  # Limit to top 10 per category

    return insights


def store_insights(
    insights: Dict[str, List[Dict]],
    session_name: str,
    git_branch: str,
    session_id: Optional[int] = None
) -> Tuple[int, List[int]]:
    """
    Store extracted insights in knowledge_base.

    Returns (total_stored, list_of_ids)
    """

    conn = get_db_connection()
    if not conn:
        return 0, []

    stored_ids = []
    timestamp = datetime.now().isoformat()

    try:
        cur = conn.cursor()

        # Store decisions as code snippets (high value)
        for decision in insights.get('decisions', [])[:5]:
            cur.execute("""
                INSERT INTO knowledge_base
                (title, content, knowledge_type, category, tags, importance_score,
                 source_type, source_id, memory_metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                f"Decision: {decision['content'][:80]}...",
                f"## Decision Made\n\n{decision['content']}\n\n**Session:** {session_name}\n**Branch:** {git_branch}\n**Date:** {timestamp[:10]}",
                'code_snippet',  # Use high-weight type
                'Decisions/Architecture',
                ['decision', 'extracted', git_branch, session_name[:20]],
                0.85,
                'insights_extractor',
                f"decision-{timestamp[:19].replace(':', '-')}",
                Json({'session_id': session_id, 'extraction_time': timestamp})
            ))
            stored_ids.append(cur.fetchone()[0])

        # Store learnings as conversation_memory
        for learning in insights.get('learnings', [])[:5]:
            cur.execute("""
                INSERT INTO knowledge_base
                (title, content, knowledge_type, category, tags, importance_score,
                 source_type, source_id, memory_metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                f"Learning: {learning['content'][:80]}...",
                f"## Learning\n\n{learning['content']}\n\n**Session:** {session_name}\n**Branch:** {git_branch}",
                'conversation_memory',
                'Learnings/Insights',
                ['learning', 'extracted', git_branch],
                0.75,
                'insights_extractor',
                f"learning-{timestamp[:19].replace(':', '-')}",
                Json({'session_id': session_id})
            ))
            stored_ids.append(cur.fetchone()[0])

        # Store errors/fixes as mistake_learned (highest weight!)
        for error in insights.get('errors', [])[:3]:
            # Check if similar mistake already exists
            cur.execute("""
                SELECT id FROM knowledge_base
                WHERE knowledge_type = 'mistake_learned'
                AND content ILIKE %s
                LIMIT 1
            """, (f"%{error['content'][:50]}%",))

            if not cur.fetchone():  # Only add if not duplicate
                cur.execute("""
                    INSERT INTO knowledge_base
                    (title, content, knowledge_type, category, tags, importance_score,
                     source_type, source_id, memory_metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    f"Error Pattern: {error['content'][:60]}...",
                    f"## Error/Fix Pattern\n\n{error['content']}\n\n**Extracted from:** {session_name}\n**Branch:** {git_branch}",
                    'mistake_learned',
                    'Errors/Patterns',
                    ['error', 'fix', 'extracted', git_branch],
                    0.9,  # High importance for errors
                    'insights_extractor',
                    f"error-{timestamp[:19].replace(':', '-')}",
                    Json({'session_id': session_id})
                ))
                stored_ids.append(cur.fetchone()[0])

        # Store TODOs in a summary entry
        if insights.get('todos'):
            todo_content = "## TODOs Mentioned in Session\n\n"
            for i, todo in enumerate(insights['todos'][:10], 1):
                todo_content += f"{i}. {todo['content']}\n"

            cur.execute("""
                INSERT INTO knowledge_base
                (title, content, knowledge_type, category, tags, importance_score,
                 source_type, source_id, memory_metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                f"Session TODOs: {session_name} ({timestamp[:10]})",
                todo_content + f"\n\n**Branch:** {git_branch}",
                'conversation_memory',
                'TODOs/ActionItems',
                ['todo', 'action-item', 'extracted', git_branch],
                0.7,
                'insights_extractor',
                f"todos-{timestamp[:19].replace(':', '-')}",
                Json({'session_id': session_id, 'todo_count': len(insights['todos'])})
            ))
            stored_ids.append(cur.fetchone()[0])

        conn.commit()
        logger.info(f"Stored {len(stored_ids)} insight entries")

        return len(stored_ids), stored_ids

    except Exception as e:
        logger.error(f"Error storing insights: {e}")
        conn.rollback()
        return 0, []
    finally:
        cur.close()
        conn.close()


def process_transcript_file(filepath: str) -> Dict:
    """Process a transcript file and extract/store insights"""

    if not os.path.exists(filepath):
        return {'success': False, 'error': 'File not found'}

    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        transcript = f.read()

    # Extract session info from filename or content
    filename = os.path.basename(filepath)
    session_name = filename.replace('transcript_', '').replace('.md', '')

    # Try to get git branch from transcript or default
    git_branch_match = re.search(r'Branch:\s*(\S+)', transcript)
    git_branch = git_branch_match.group(1) if git_branch_match else 'unknown'

    # Extract insights
    insights = extract_insights(transcript)

    # Count insights found
    total_found = sum(len(v) for v in insights.values())

    if total_found == 0:
        return {
            'success': True,
            'message': 'No significant insights found',
            'insights': insights
        }

    # Store in database
    stored_count, stored_ids = store_insights(
        insights,
        session_name,
        git_branch
    )

    return {
        'success': True,
        'insights_found': {k: len(v) for k, v in insights.items()},
        'total_found': total_found,
        'stored': stored_count,
        'stored_ids': stored_ids
    }


def main():
    """Main entry point"""
    if len(sys.argv) < 2:
        print("Usage: python conversation_insights_extractor.py <transcript_file>")
        print("  or: python conversation_insights_extractor.py --recent")
        sys.exit(1)

    if sys.argv[1] == '--recent':
        # Process most recent transcript
        log_dir = '/mnt/archie_brain/conversation_logs'
        transcripts = sorted([
            f for f in os.listdir(log_dir)
            if f.startswith('transcript_') and f.endswith('.md')
        ], reverse=True)

        if transcripts:
            filepath = os.path.join(log_dir, transcripts[0])
            print(f"Processing: {filepath}")
            result = process_transcript_file(filepath)
        else:
            print("No transcripts found")
            result = {'success': False, 'error': 'No transcripts'}
    else:
        result = process_transcript_file(sys.argv[1])

    print(json.dumps(result, indent=2))
    return 0 if result.get('success') else 1


if __name__ == '__main__':
    sys.exit(main())

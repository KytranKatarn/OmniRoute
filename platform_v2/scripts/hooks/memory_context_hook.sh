#!/bin/bash
# Memory Context Hook - Injects relevant A.R.C.H.I.E. knowledge into Claude Code context
# Triggered on UserPromptSubmit to provide relevant memories
# Phase 8: Long-Term Memory Integration

# Read the input JSON from stdin
INPUT_JSON=$(cat)

# Extract the user's prompt from the input
USER_PROMPT=$(echo "$INPUT_JSON" | python3 -c "
import sys
import json
try:
    data = json.load(sys.stdin)
    # UserPromptSubmit provides the prompt in 'prompt' field
    prompt = data.get('prompt', data.get('message', ''))
    print(prompt[:500] if prompt else '')  # Limit for search
except:
    print('')
" 2>/dev/null)

# Skip if no prompt or too short
if [ -z "$USER_PROMPT" ] || [ ${#USER_PROMPT} -lt 10 ]; then
    exit 0
fi

# Query the database for relevant memories and output context
docker exec archie_platform python3 -c "
import os
import sys
import json
import psycopg2
from psycopg2.extras import RealDictCursor

# User prompt to search for
search_query = '''$USER_PROMPT'''[:200]

# Skip common commands that don't need memory context
skip_patterns = ['help', 'clear', 'exit', 'quit', 'status', 'git status', 'ls', 'pwd']
if any(search_query.lower().strip().startswith(p) for p in skip_patterns):
    sys.exit(0)

try:
    conn = psycopg2.connect(
        host=os.getenv('DB_HOST', 'archie_database'),
        database=os.getenv('DB_NAME', 'archie'),
        user=os.getenv('DB_USER', 'archie'),
        password=os.getenv('DB_PASSWORD')
    )
    cur = conn.cursor(cursor_factory=RealDictCursor)

    context_parts = []

    # 1. Search for relevant mistakes/solutions
    cur.execute('''
        SELECT content, importance_score, category
        FROM knowledge_base
        WHERE content ILIKE %s
          AND knowledge_type IN ('mistake_learned', 'vault_note')
        ORDER BY importance DESC
        LIMIT 2
    ''', (f'%{search_query}%',))
    mistakes = cur.fetchall()

    if mistakes:
        context_parts.append('## Relevant Knowledge from A.R.C.H.I.E. Memory:')
        for m in mistakes:
            context_parts.append(f'- [{m[\"category\"]}] {m[\"content\"][:300]}...')

    # 2. Search for relevant long-term memories
    cur.execute('''
        SELECT content, memory_type, category, importance_score
        FROM long_term_memory
        WHERE content ILIKE %s
        ORDER BY importance_score DESC, access_count DESC
        LIMIT 3
    ''', (f'%{search_query}%',))
    memories = cur.fetchall()

    if memories:
        if not context_parts:
            context_parts.append('## Relevant Memories:')
        for m in memories:
            context_parts.append(f'- [{m[\"memory_type\"]}] {m[\"content\"][:200]}...')

        # Update access count for recalled memories
        memory_ids = [m['content'][:50] for m in memories]  # Just for logging

    # 3. Get user preferences if available (user_id=1 for admin)
    cur.execute('''
        SELECT category, preference_key, preference_value, confidence
        FROM user_memory_preferences
        WHERE user_id = 1 AND is_active = TRUE AND confidence >= 0.6
        LIMIT 5
    ''')
    prefs = cur.fetchall()

    if prefs:
        context_parts.append('## User Preferences:')
        for p in prefs:
            context_parts.append(f'- {p[\"category\"]}/{p[\"preference_key\"]}: {p[\"preference_value\"]}')

    # Output context if we found anything useful
    if context_parts and len(context_parts) > 1:
        print('<memory-context>')
        print('\\n'.join(context_parts))
        print('</memory-context>')
        print('')

    cur.close()
    conn.close()

except Exception as e:
    # Silent fail - don't interrupt the user's prompt
    pass
" 2>/dev/null

exit 0

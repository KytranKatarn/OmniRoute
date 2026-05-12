-- ============================================================================
-- Fix: auto_categorize_content trigger wipes caller-supplied tags
-- ============================================================================
-- Task #2126 — surfaced during Project #272 Phase 2 / C.O.D.E.X. auto-docs
-- smoke testing. The BEFORE INSERT/UPDATE trigger on knowledge_base
-- unconditionally set ``NEW.tags := ARRAY[]::TEXT[]`` and then conditionally
-- appended based on ``file_extension``. Rows inserted without a file_extension
-- (vault_note, code_snippet, conversation_memory, etc.) lost whatever tags
-- the caller passed in — including C.O.D.E.X. auto-doc rows, D.A.R.W.I.N.
-- project reports, and every ``store_memory(..., tags=...)`` MCP call.
--
-- Fix: preserve caller-supplied tags when non-empty. Only synthesize defaults
-- when the caller didn't specify any — that's the original auto-categorization
-- intent, limited to its real use case (GitHub file ingestion).
--
-- Idempotent: CREATE OR REPLACE FUNCTION re-defines the trigger function.
-- No DDL changes; the trigger itself still binds to the same function name.
-- ============================================================================

CREATE OR REPLACE FUNCTION auto_categorize_content()
RETURNS TRIGGER AS $$
DECLARE
    v_caller_supplied_tags boolean;
BEGIN
    -- Determine if it's code (expanded list)
    NEW.is_code := NEW.file_extension IN (
        '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.cpp', '.c', '.go', '.rs', '.rb',
        '.html', '.css', '.scss', '.less', '.sh', '.bash', '.sql', '.vue', '.svelte',
        '.php', '.swift', '.kt', '.scala', '.r', '.lua', '.pl', '.ex', '.exs',
        '.zig', '.nim', '.dart', '.cs', '.m', '.h', '.hpp'
    );

    -- Determine if it's documentation
    NEW.is_documentation := NEW.file_extension IN ('.md', '.txt', '.rst', '.adoc') OR
                            LOWER(NEW.file_name) LIKE '%readme%' OR
                            LOWER(NEW.file_name) LIKE '%doc%';

    -- Determine if it's configuration
    NEW.is_configuration := NEW.file_extension IN ('.json', '.yaml', '.yml', '.toml', '.ini', '.conf', '.env', '.xml', '.cfg');

    -- Set language
    NEW.language := CASE NEW.file_extension
        WHEN '.py' THEN 'Python'
        WHEN '.js' THEN 'JavaScript'
        WHEN '.jsx' THEN 'JavaScript'
        WHEN '.ts' THEN 'TypeScript'
        WHEN '.tsx' THEN 'TypeScript'
        WHEN '.java' THEN 'Java'
        WHEN '.cpp' THEN 'C++'
        WHEN '.c' THEN 'C'
        WHEN '.go' THEN 'Go'
        WHEN '.rs' THEN 'Rust'
        WHEN '.rb' THEN 'Ruby'
        WHEN '.sh' THEN 'Bash'
        WHEN '.bash' THEN 'Bash'
        WHEN '.sql' THEN 'SQL'
        WHEN '.html' THEN 'HTML'
        WHEN '.css' THEN 'CSS'
        WHEN '.scss' THEN 'SCSS'
        WHEN '.vue' THEN 'Vue'
        WHEN '.svelte' THEN 'Svelte'
        WHEN '.php' THEN 'PHP'
        WHEN '.swift' THEN 'Swift'
        WHEN '.kt' THEN 'Kotlin'
        WHEN '.scala' THEN 'Scala'
        WHEN '.r' THEN 'R'
        WHEN '.lua' THEN 'Lua'
        WHEN '.dart' THEN 'Dart'
        WHEN '.cs' THEN 'C#'
        WHEN '.json' THEN 'JSON'
        WHEN '.yaml' THEN 'YAML'
        WHEN '.yml' THEN 'YAML'
        ELSE 'Unknown'
    END;

    -- Count lines and size
    NEW.line_count := array_length(string_to_array(NEW.content, E'\n'), 1);
    NEW.file_size := length(NEW.content);

    -- Preserve caller-supplied tags (#2126 fix).
    -- array_length on a zero-length array returns NULL, so check both.
    v_caller_supplied_tags := (NEW.tags IS NOT NULL AND array_length(NEW.tags, 1) IS NOT NULL);

    IF NOT v_caller_supplied_tags THEN
        -- Synthesize auto-tags — original behavior, only when caller didn't
        -- supply any. Keeps the GitHub file-ingestion path working without
        -- stomping on store_memory / vault_note / code_snippet inserts.
        NEW.tags := ARRAY[]::TEXT[];

        -- Add language tag
        IF NEW.file_extension = '.py' THEN
            NEW.tags := array_append(NEW.tags, 'python-code');
        ELSIF NEW.file_extension IN ('.js', '.ts', '.jsx', '.tsx') THEN
            NEW.tags := array_append(NEW.tags, 'javascript-code');
        END IF;

        -- Add script tag
        IF NEW.file_extension IN ('.py', '.sh', '.bash') THEN
            NEW.tags := array_append(NEW.tags, 'python-script');
        END IF;

        -- Add documentation tag
        IF NEW.is_documentation THEN
            NEW.tags := array_append(NEW.tags, 'documentation');
            IF LOWER(NEW.file_name) LIKE '%readme%' THEN
                NEW.tags := array_append(NEW.tags, 'readme');
            END IF;
        END IF;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Verification query (run manually after applying):
--   INSERT INTO knowledge_base (title, content, knowledge_type, source_type, source_id, tags)
--   VALUES ('x', 'y', 'vault_note', 'debug', 'debug:1', ARRAY['a','b','c'])
--   RETURNING tags;
-- Expected: {a,b,c}
-- Then: DELETE FROM knowledge_base WHERE source_type = 'debug';

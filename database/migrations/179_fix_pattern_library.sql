-- Migration 179: Fix Pattern Library
-- Inserts 10 reusable fix patterns into knowledge_base for autonomous dev agents.
-- Idempotent: ON CONFLICT updates existing patterns by title.

INSERT INTO knowledge_base (title, knowledge_type, category, content, tags, importance_score, is_code, created_at, updated_at)
VALUES
(
  'fix_pattern:sanitize_error_response',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "sanitize_error_response",
    "description": "Replace str(e) in HTTP error responses with a generic message to prevent internal detail leakage.",
    "search_regex": "return\\s+jsonify\\(.*str\\(e\\).*\\)|return\\s+.*str\\(e\\).*,\\s*[45]\\d{2}",
    "fix_template": "return jsonify({\"error\": \"An internal error occurred\"}), 500",
    "validation_check": {
      "must_not_contain": ["str(e)", "repr(e)"],
      "must_contain": ["logger.error", "logger.exception"],
      "syntax_check": true
    },
    "severity": "medium",
    "estimated_effort": "5min",
    "example_before": "except Exception as e:\n    return jsonify({\"error\": str(e)}), 500",
    "example_after": "except Exception as e:\n    logger.error(f\"Endpoint failed: {e}\")\n    return jsonify({\"error\": \"An internal error occurred\"}), 500"
  }',
  ARRAY['fix-pattern', 'sanitize_error_response', 'medium', 'security', 'error-handling'],
  0.90, true, NOW(), NOW()
),
(
  'fix_pattern:add_admin_required',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "add_admin_required",
    "description": "Add @admin_required decorator to CRUD endpoints (POST/PUT/DELETE) that modify data without authorization checks.",
    "search_regex": "@bp\\.route\\(.*(POST|PUT|DELETE|PATCH).*\\)\\s*\\ndef\\s+\\w+\\(",
    "fix_template": "@bp.route(''{route}'', methods=[''{method}''])\n@admin_required\ndef {func_name}({params}):",
    "validation_check": {
      "must_contain": ["@admin_required", "from platform_v2.rbac import admin_required"],
      "must_not_contain": [],
      "syntax_check": true,
      "import_check": true
    },
    "severity": "high",
    "estimated_effort": "5min",
    "example_before": "@bp.route(''/api/agents'', methods=[''POST''])\ndef create_agent():\n    data = request.json",
    "example_after": "@bp.route(''/api/agents'', methods=[''POST''])\n@admin_required\ndef create_agent():\n    data = request.json"
  }',
  ARRAY['fix-pattern', 'add_admin_required', 'high', 'security', 'authorization'],
  0.90, true, NOW(), NOW()
),
(
  'fix_pattern:fix_fstring_sql',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "fix_fstring_sql",
    "description": "Replace f-string SQL queries with parameterized queries to prevent SQL injection.",
    "search_regex": "cur\\.execute\\(f[\"'']|cursor\\.execute\\(f[\"'']|\\.execute\\(f[\"''].*SELECT|INSERT|UPDATE|DELETE",
    "fix_template": "cur.execute(\"{query}\", ({params},))",
    "validation_check": {
      "must_not_contain": ["execute(f\"", "execute(f''"],
      "must_contain": ["%s"],
      "syntax_check": true
    },
    "severity": "critical",
    "estimated_effort": "10min",
    "example_before": "cur.execute(f\"SELECT * FROM agents WHERE name = ''{agent_name}''\")",
    "example_after": "cur.execute(\"SELECT * FROM agents WHERE name = %s\", (agent_name,))"
  }',
  ARRAY['fix-pattern', 'fix_fstring_sql', 'critical', 'security', 'sql-injection'],
  0.90, true, NOW(), NOW()
),
(
  'fix_pattern:add_logging_to_bare_except',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "add_logging_to_bare_except",
    "description": "Add logger.warning() to bare except blocks that silently swallow errors, and narrow the catch to Exception.",
    "search_regex": "except\\s*:\\s*\\n\\s*(pass|continue|return)",
    "fix_template": "except Exception as e:\n    logger.warning(f\"{context}: {e}\")\n    {original_action}",
    "validation_check": {
      "must_not_contain": ["except:\\n        pass", "except:\\n        continue"],
      "must_contain": ["except Exception", "logger."],
      "syntax_check": true
    },
    "severity": "medium",
    "estimated_effort": "5min",
    "example_before": "try:\n    result = process_data()\nexcept:\n    pass",
    "example_after": "try:\n    result = process_data()\nexcept Exception as e:\n    logger.warning(f\"process_data failed: {e}\")"
  }',
  ARRAY['fix-pattern', 'add_logging_to_bare_except', 'medium', 'reliability', 'error-handling'],
  0.90, true, NOW(), NOW()
),
(
  'fix_pattern:migrate_db_pattern',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "migrate_db_pattern",
    "description": "Replace direct psycopg2.connect() calls with the shared get_db_cursor() context manager to prevent connection leaks.",
    "search_regex": "psycopg2\\.connect\\(|psycopg2\\.extensions|conn\\s*=\\s*psycopg2",
    "fix_template": "from database import get_db_cursor\n\nwith get_db_cursor(commit={needs_commit}) as (conn, cur):\n    {db_operations}",
    "validation_check": {
      "must_not_contain": ["psycopg2.connect("],
      "must_contain": ["from database import get_db_cursor", "with get_db_cursor"],
      "syntax_check": true,
      "import_check": true
    },
    "severity": "high",
    "estimated_effort": "15min",
    "example_before": "import psycopg2\nconn = psycopg2.connect(host=''192.168.1.200'', dbname=''archie'')\ncur = conn.cursor()\ncur.execute(\"SELECT 1\")\nconn.close()",
    "example_after": "from database import get_db_cursor\n\nwith get_db_cursor() as (conn, cur):\n    cur.execute(\"SELECT 1\")"
  }',
  ARRAY['fix-pattern', 'migrate_db_pattern', 'high', 'reliability', 'database', 'connection-leak'],
  0.90, true, NOW(), NOW()
),
(
  'fix_pattern:use_bridge_dispatch',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "use_bridge_dispatch",
    "description": "Replace direct Ollama HTTP calls (/api/generate, /api/chat) with Bridge dispatcher per ADR-013.",
    "search_regex": "requests\\.(post|get)\\(.*(11434|ollama).*(/api/generate|/api/chat)",
    "fix_template": "from ai_bridge.bridge_dispatcher import get_dispatcher\n\ndispatcher = get_dispatcher()\nresult = dispatcher.dispatch(capability=''{capability}'', prompt={prompt_var}, module_id=''{module_id}'')\nresponse_text = result.response if result.success else ''''",
    "validation_check": {
      "must_not_contain": ["requests.post.*11434.*api/generate", "requests.get.*api/generate", "requests.post.*api/chat"],
      "must_contain": ["from ai_bridge.bridge_dispatcher import", "dispatch("],
      "syntax_check": true,
      "import_check": true
    },
    "severity": "high",
    "estimated_effort": "15min",
    "example_before": "resp = requests.post(''http://localhost:11434/api/generate'', json={''model'': ''llama3.2:3b'', ''prompt'': text})\nanswer = resp.json()[''response'']",
    "example_after": "from ai_bridge.bridge_dispatcher import get_dispatcher\n\ndispatcher = get_dispatcher()\nresult = dispatcher.dispatch(capability=''generate'', prompt=text, module_id=''my_module'')\nanswer = result.response if result.success else ''''"
  }',
  ARRAY['fix-pattern', 'use_bridge_dispatch', 'high', 'adr-013', 'architecture'],
  0.90, true, NOW(), NOW()
),
(
  'fix_pattern:constant_time_comparison',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "constant_time_comparison",
    "description": "Replace == comparison for secrets/tokens/API keys with hmac.compare_digest to prevent timing attacks.",
    "search_regex": "(api_key|token|secret|password|key)\\s*==\\s*[\"'']|==\\s*(api_key|token|secret|password)",
    "fix_template": "import hmac\nhmac.compare_digest({actual}, {expected})",
    "validation_check": {
      "must_not_contain": ["== api_key", "== token", "== secret"],
      "must_contain": ["hmac.compare_digest"],
      "syntax_check": true,
      "import_check": true
    },
    "severity": "high",
    "estimated_effort": "5min",
    "example_before": "if request.headers.get(''X-API-Key'') == API_SECRET:\n    return process_request()",
    "example_after": "import hmac\nif hmac.compare_digest(request.headers.get(''X-API-Key'', ''''), API_SECRET):\n    return process_request()"
  }',
  ARRAY['fix-pattern', 'constant_time_comparison', 'high', 'security', 'timing-attack'],
  0.90, true, NOW(), NOW()
),
(
  'fix_pattern:add_input_validation',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "add_input_validation",
    "description": "Add type and range validation checks on POST endpoint fields before processing.",
    "search_regex": "data\\s*=\\s*request\\.(json|form|get_json).*\\n\\s*[^#]*\\s*=\\s*data(\\.get|\\[)",
    "fix_template": "data = request.get_json(silent=True)\nif not data:\n    return jsonify({\"error\": \"Request body required\"}), 400\n\n{field} = data.get(''{field}'')\nif {field} is None or not isinstance({field}, {expected_type}):\n    return jsonify({\"error\": \"{field} is required and must be {expected_type}\"}), 400",
    "validation_check": {
      "must_contain": ["request.get_json", "isinstance", "400"],
      "must_not_contain": [],
      "syntax_check": true
    },
    "severity": "medium",
    "estimated_effort": "10min",
    "example_before": "@bp.route(''/api/items'', methods=[''POST''])\ndef create_item():\n    data = request.json\n    name = data[''name'']\n    price = data[''price'']",
    "example_after": "@bp.route(''/api/items'', methods=[''POST''])\ndef create_item():\n    data = request.get_json(silent=True)\n    if not data:\n        return jsonify({\"error\": \"Request body required\"}), 400\n    name = data.get(''name'')\n    if not name or not isinstance(name, str):\n        return jsonify({\"error\": \"name is required and must be a string\"}), 400\n    price = data.get(''price'')\n    if price is None or not isinstance(price, (int, float)):\n        return jsonify({\"error\": \"price is required and must be a number\"}), 400"
  }',
  ARRAY['fix-pattern', 'add_input_validation', 'medium', 'security', 'input-validation'],
  0.90, true, NOW(), NOW()
),
(
  'fix_pattern:add_login_required',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "add_login_required",
    "description": "Add @login_required decorator to unprotected endpoints that serve user-specific data or perform actions.",
    "search_regex": "@bp\\.route\\(.*\\)\\s*\\ndef\\s+(?!static|health|public)\\w+\\(",
    "fix_template": "@bp.route(''{route}'')\n@login_required\ndef {func_name}({params}):",
    "validation_check": {
      "must_contain": ["@login_required", "from flask_login import login_required"],
      "must_not_contain": [],
      "syntax_check": true,
      "import_check": true
    },
    "severity": "high",
    "estimated_effort": "5min",
    "example_before": "@bp.route(''/api/user/settings'')\ndef get_settings():\n    user_id = session.get(''user_id'')\n    return jsonify(load_settings(user_id))",
    "example_after": "@bp.route(''/api/user/settings'')\n@login_required\ndef get_settings():\n    user_id = current_user.id\n    return jsonify(load_settings(user_id))"
  }',
  ARRAY['fix-pattern', 'add_login_required', 'high', 'security', 'authentication'],
  0.90, true, NOW(), NOW()
),
(
  'fix_pattern:sanitize_error_disclosure',
  'code_snippet',
  'fix_pattern',
  '{
    "pattern_id": "sanitize_error_disclosure",
    "description": "Remove internal file paths, stack traces, and system details from error messages returned to clients.",
    "search_regex": "traceback\\.format_exc\\(\\)|__file__|os\\.path\\.abspath|sys\\.exc_info|/mnt/|/home/|/platform_v2/",
    "fix_template": "logger.error(f\"Error in {context}: {e}\", exc_info=True)\nreturn jsonify({\"error\": \"An error occurred processing your request\"}), 500",
    "validation_check": {
      "must_not_contain": ["traceback.format_exc()", "__file__", "/mnt/", "/platform_v2/"],
      "must_contain": ["logger.error", "exc_info=True"],
      "syntax_check": true
    },
    "severity": "medium",
    "estimated_effort": "10min",
    "example_before": "except Exception as e:\n    tb = traceback.format_exc()\n    return jsonify({\"error\": str(e), \"trace\": tb, \"file\": __file__}), 500",
    "example_after": "except Exception as e:\n    logger.error(f\"Request handler failed: {e}\", exc_info=True)\n    return jsonify({\"error\": \"An error occurred processing your request\"}), 500"
  }',
  ARRAY['fix-pattern', 'sanitize_error_disclosure', 'medium', 'security', 'information-disclosure'],
  0.90, true, NOW(), NOW()
)
ON CONFLICT (title) WHERE title IS NOT NULL
DO UPDATE SET
  knowledge_type = EXCLUDED.knowledge_type,
  category = EXCLUDED.category,
  content = EXCLUDED.content,
  tags = EXCLUDED.tags,
  importance_score = EXCLUDED.importance_score,
  is_code = EXCLUDED.is_code,
  updated_at = NOW();

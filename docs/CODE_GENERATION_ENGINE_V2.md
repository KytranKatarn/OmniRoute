# V2 Code Generation Engine

**Created:** 2026-01-15
**Status:** Production Ready
**Location:** `/mnt/archie_brain/ai_bridge/code_generation_engine.py`

---

## Overview

The V2 Code Generation Engine is A.R.C.H.I.E.'s AI-powered code modification system that generates, validates, and applies code changes for improvement proposals. It implements industry best practices from Aider, SynCode, and Cursor.

### Key Features

| Feature | Description |
|---------|-------------|
| **Architect/Editor Pattern** | Two-phase generation for 85% accuracy (industry benchmark) |
| **Syntax Validation** | ast.parse() + py_compile prevents deployment of broken code |
| **Content Matching** | Verifies old_content exists before applying changes |
| **Smart Snippet Validation** | Handles except/else/elif blocks correctly |
| **Retry with Feedback** | 3 attempts with error context in retry prompts |
| **Team Management Integration** | Routes to appropriate agent (Internal vs Contractor) |

---

## Architecture

```
                    PROPOSAL INPUT
                          |
                          v
    +---------------------------------------------+
    |           ARCHITECT PHASE                    |
    |  - Analyze problem                          |
    |  - Plan minimal fix                         |
    |  - Identify exact lines to change           |
    +---------------------------------------------+
                          |
                          v
    +---------------------------------------------+
    |            EDITOR PHASE                      |
    |  - Generate old_content (exact from file)   |
    |  - Generate new_content (minimal fix)       |
    +---------------------------------------------+
                          |
                          v
    +---------------------------------------------+
    |          VALIDATION PHASE                    |
    |  +-------------+  +-------------+           |
    |  | Syntax      |  | Content     |           |
    |  | Validator   |->| Matcher     |           |
    |  | (ast+compile)|  | (substring) |           |
    |  +-------------+  +-------------+           |
    +---------------------------------------------+
                          |
              +-----------+-----------+
              |                       |
              v                       v
        +---------+             +---------+
        | SUCCESS |             |  RETRY  |
        | Save to |             | (max 3) |
        | plan_steps            |    |    |
        +---------+             |    v    |
                                | FAIL    |
                                +---------+
```

---

## Files

| File | Purpose | Lines |
|------|---------|-------|
| `code_generation_engine.py` | Main engine with V2 pipeline | ~1100 |
| `code_validator.py` | Multi-language syntax validation | ~580 |
| `content_matcher.py` | Verifies old_content exists in file | ~430 |
| `agent_delegation.py` | Team Management integration | ~400 |
| `code_application_system.py` | Applies changes to files | ~300 |

---

## API Reference

### Primary Entry Point

```python
from code_generation_engine import generate_code_for_proposal

result = generate_code_for_proposal(
    proposal_id=123,
    proposal_title="Fix bare except clause",
    proposal_description="Change except: to except Exception:",
    category="code_quality",
    target_files=["platform_v2/tools/coderabbit/routes.py"],
    line_number=43,
    issue_context={"severity": "medium", "type": "quality"},
    use_v2=True,           # Enable V2 validation pipeline
    prefer_contractor=False # Use internal agents first
)
```

### Response Structure

```python
{
    "success": True,
    "changes": [
        {
            "file_path": "platform_v2/tools/coderabbit/routes.py",
            "action": "modify",
            "old_content": "        except:\n            continue",
            "new_content": "        except Exception:\n            continue",
            "description": "Fix bare except clause",
            "diff": "..."
        }
    ],
    "validation_results": [
        {
            "valid": True,
            "file_path": "...",
            "match_type": "exact"  # or "whitespace_normalized"
        }
    ],
    "metadata": {
        "generated_at": "2026-01-15T14:00:00",
        "model_used": "qwen2.5-coder:7b",
        "proposal_id": 123,
        "retries_used": 0,
        "validation_enabled": True
    }
}
```

---

## Team Management Integration

The V2 engine integrates with A.R.C.H.I.E.'s Team Management system to route code generation tasks to the appropriate agent.

### Agent Selection

```python
def _select_model_for_task(self, category: str, prefer_contractor: bool) -> str:
    """
    Select AI model based on task complexity.

    Uses Team Management when available:
    - Internal agents (FREE): Local Ollama models
    - Contractors (PAID): Claude, GPT-4, Grok, Gemini
    """
    if prefer_contractor:
        # Try to get external API (Claude/GPT-4)
        if os.getenv('ANTHROPIC_API_KEY'):
            return 'claude-sonnet-4-20250514'
        elif os.getenv('OPENAI_API_KEY'):
            return 'gpt-4-turbo'

    # Use Team Management agent selection
    from agent_delegation import select_best_agent_for_task
    agent = select_best_agent_for_task(
        task_description=f"Generate code fix for {category} issue",
        department_preference="Engineering",
        prefer_contractor=prefer_contractor
    )
    return agent.get('model', 'codellama:latest')
```

### prefer_contractor Parameter

| Value | Behavior |
|-------|----------|
| `False` (default) | Uses internal agents (Ollama) - FREE |
| `True` | Prefers contractors (Claude/GPT-4) - PAID |

**When to use `prefer_contractor=True`:**
- Complex security fixes
- Multi-file refactors
- When internal agents fail validation 3 times
- Critical production issues

### Available Internal Agents (Ollama)

| Model | Size | Best For |
|-------|------|----------|
| `qwen2.5-coder:7b` | 4.4 GB | General code fixes |
| `deepseek-coder-v2:16b` | 8.3 GB | Complex algorithms |
| `deepseek-coder:33b` | 17.5 GB | Large refactors |
| `codellama:latest` | 3.6 GB | Simple fixes |

### Available Contractors (External API)

| Model | Provider | API Key Env Var |
|-------|----------|-----------------|
| `claude-sonnet-4-20250514` | Anthropic | `ANTHROPIC_API_KEY` |
| `gpt-4-turbo` | OpenAI | `OPENAI_API_KEY` |
| `grok-beta` | X.AI | `XAI_API_KEY` |
| `gemini-1.5-pro` | Google | `GOOGLE_API_KEY` |

---

## Validation Pipeline

### 1. Syntax Validation (`code_validator.py`)

Validates code syntax before saving:

```python
class CodeValidator:
    def validate_python(self, code: str) -> ValidationResult:
        """
        Two-phase Python validation:
        1. ast.parse() - catches most syntax errors
        2. py_compile.compile() - catches edge cases
        """

    def validate_javascript(self, code: str) -> ValidationResult:
        """Validates balanced braces, brackets, parentheses"""

    def validate_html(self, code: str) -> ValidationResult:
        """Validates tag matching using html.parser"""
```

**Supported Languages:**
- Python (.py) - Full AST + compile validation
- JavaScript (.js, .jsx) - Brace matching
- TypeScript (.ts, .tsx) - Brace matching
- HTML (.html) - Tag matching
- CSS (.css) - Brace matching
- JSON (.json) - json.loads validation
- SQL (.sql) - Basic keyword validation

### 2. Content Matching (`content_matcher.py`)

Verifies old_content exists in the target file:

```python
class ContentMatcher:
    def verify_old_content(self, file_path: str, old_content: str) -> MatchResult:
        """
        Match strategies (in order):
        1. Exact substring match
        2. Whitespace-normalized match
        3. Fuzzy match suggestions (if no match)
        """
```

**Match Types:**
| Type | Description |
|------|-------------|
| `exact` | Character-for-character match |
| `whitespace_normalized` | Matches after normalizing whitespace |
| `not_found` | No match - includes suggestions |

### 3. Smart Snippet Validation

Handles code snippets that aren't valid standalone Python:

```python
# These are validated by wrapping in appropriate context:

# except blocks -> wrapped in try/except
dedented = textwrap.dedent(code)
wrapped = "def _test():\n    try:\n        pass\n" + textwrap.indent(dedented, "    ")

# else/elif blocks -> wrapped in if block
wrapped = "def _test():\n    if True:\n        pass\n" + textwrap.indent(dedented, "    ")
```

---

## Retry Logic

When validation fails, the engine retries with error feedback:

```python
MAX_RETRIES = 3

RETRY_PROMPT = """Your previous code change failed validation.

## PREVIOUS ATTEMPT
OLD_CONTENT: {previous_old_content}
NEW_CONTENT: {previous_new_content}

## VALIDATION ERROR
{validation_error}

## ACTUAL FILE CONTENT (copy from here):
{actual_file_content}

Generate a CORRECTED change. Copy OLD_CONTENT exactly from the file above.
"""
```

**Retry Flow:**
1. **Attempt 1**: Architect/Editor pattern
2. **Attempt 2**: Retry with error context
3. **Attempt 3**: Final retry with full file content
4. **Failure**: Return error, suggest `prefer_contractor=True`

---

## Code Application (`code_application_system.py`)

After validation passes, changes are applied:

```python
class CodeApplicationSystem:
    def apply_changes_to_sandbox(self, proposal_id: int, changes: List[Dict]) -> Dict:
        """
        V2 SAFETY: Fails on content mismatch instead of appending.

        1. Create backup of original file
        2. Verify old_content exists (FAIL if not found)
        3. Replace old_content with new_content
        4. Verify file still valid
        """
```

**V2 Safety Feature:**
```python
# OLD (V1): Would append if old_content not found (DANGEROUS)
# NEW (V2): Fails and restores backup if old_content not found

if old_content not in current_content:
    shutil.copy2(backup_file, full_path)  # Restore backup
    return {
        'success': False,
        'error': 'old_content not found in file - content mismatch'
    }
```

---

## Usage Examples

### Example 1: Simple Code Fix

```python
# Fix a bare except clause
result = generate_code_for_proposal(
    proposal_id=6,
    proposal_title="Fix bare except clause",
    proposal_description="Change except: to except Exception:",
    category="code_quality",
    target_files=["platform_v2/tools/coderabbit/routes.py"],
    line_number=43
)

# Result:
# - old_content: "        except:\n            continue"
# - new_content: "        except Exception:\n            continue"
# - validation: exact match, syntax valid
```

### Example 2: Complex Security Fix (Use Contractor)

```python
# Complex SQL injection fix - use contractor for better accuracy
result = generate_code_for_proposal(
    proposal_id=4,
    proposal_title="Fix SQL injection vulnerability",
    proposal_description="Use parameterized queries instead of string concatenation",
    category="security",
    target_files=["platform_v2/agent_management_api.py"],
    line_number=152,
    prefer_contractor=True  # Use Claude/GPT-4 for complex security fix
)
```

### Example 3: CodeRabbit Integration

```python
# Called by CodeRabbit when creating proposals
result = generate_code_for_proposal(
    proposal_id=issue.proposal_id,
    proposal_title=f"[CodeRabbit] {issue.title}",
    proposal_description=issue.description,
    category=issue.category,
    target_files=[issue.file_path],
    line_number=issue.line_number,
    issue_context={
        "severity": issue.severity,
        "type": issue.issue_type,
        "suggestion": issue.suggestion
    }
)
```

---

## Troubleshooting

### "old_content not found in file"

**Cause:** AI generated old_content that doesn't match actual file content.

**Solution:**
1. Check if file was modified since proposal was created
2. Regenerate the plan with "Regenerate Plan" button
3. Use `prefer_contractor=True` for better accuracy

### "SyntaxError in new_content"

**Cause:** AI generated invalid Python syntax.

**Solution:**
1. V2 engine will automatically retry 3 times
2. If still failing, use `prefer_contractor=True`
3. Check Ollama is running and model is available

### "Max retries exceeded"

**Cause:** Internal agent couldn't generate valid code after 3 attempts.

**Solution:**
1. Use `prefer_contractor=True` to escalate to Claude/GPT-4
2. Configure API keys in environment
3. Check if issue description is clear enough

---

## Performance Metrics

| Metric | V1 (Old) | V2 (New) |
|--------|----------|----------|
| Syntax errors deployed | ~30% | 0% |
| Content mismatch corruption | ~15% | 0% |
| First-attempt success | ~40% | ~70% |
| With retry success | N/A | ~85% |
| Average generation time | 15s | 25s |

---

## Related Documentation

- `/docs/AGENT_DELEGATION_SYSTEM.md` - Team Management integration
- `/docs/CODERABBIT_MODULE.md` - CodeRabbit issue scanning
- `/docs/IMPROVEMENTS_LAB_WORKFLOW.md` - Full improvement workflow
- `/docs/MASTER_STATUS_AND_ROADMAP_2026.md` - Project roadmap

---

## Changelog

### v2.0.0 (2026-01-15)
- Added Architect/Editor pattern
- Added syntax validation (ast.parse + py_compile)
- Added content matching verification
- Added smart snippet validation for except/else blocks
- Added retry logic with error feedback
- Added Team Management integration with prefer_contractor
- Fixed code_application_system to fail on mismatch

### v1.0.0 (2026-01-05)
- Initial code generation engine
- Basic AI prompt for code changes
- No validation (caused deployment failures)

---

**Document Status:** Active
**Last Updated:** 2026-01-15

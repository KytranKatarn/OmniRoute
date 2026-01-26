# A.R.C.H.I.E. Code Review

Trigger AI-powered code review using Code Sentinel integration.

## Arguments
$ARGUMENTS - Optional: specific file path or "staged" for git staged changes (default: staged)

## Instructions

### Review Staged Changes (default)
```bash
# Get list of staged files
git diff --cached --name-only
```

### Review Specific File
If $ARGUMENTS is a file path, review that file specifically.

### Perform Review

1. **Static Analysis First** - Quick security/quality checks:
   ```bash
   curl -s -X POST "http://localhost:3000/tools/code_sentinel/api/analyze" \
     -H "Content-Type: application/json" \
     -d '{"files": ["<file_paths>"], "analysis_type": "static"}'
   ```

2. **AI Review** - Deep analysis with Ollama:
   ```bash
   curl -s -X POST "http://localhost:3000/tools/code_sentinel/api/review" \
     -H "Content-Type: application/json" \
     -d '{"diff": "<git_diff_content>", "context": "code review"}'
   ```

3. **Security Scan** - OWASP-focused check:
   ```bash
   curl -s -X POST "http://localhost:3000/tools/code_sentinel/api/security-scan" \
     -H "Content-Type: application/json" \
     -d '{"files": ["<file_paths>"]}'
   ```

### Report Format

Present findings in this format:

**Security Issues** (High Priority)
- [ ] Issue description - file:line - suggested fix

**Quality Issues** (Medium Priority)
- [ ] Issue description - file:line - suggested fix

**Suggestions** (Low Priority)
- [ ] Improvement suggestion

**Summary**
- Files reviewed: X
- Issues found: Y (X high, Y medium, Z low)
- Recommendation: APPROVE / REQUEST CHANGES / NEEDS DISCUSSION

### If Code Sentinel API unavailable

Fall back to manual review:
1. Read the changed files
2. Check for OWASP top 10 vulnerabilities
3. Look for code quality issues (bare except, hardcoded secrets, etc.)
4. Suggest improvements based on A.R.C.H.I.E. patterns from CLAUDE.md

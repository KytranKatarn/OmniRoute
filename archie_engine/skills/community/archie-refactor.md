---
name: archie-refactor
description: Refactor code for clarity, performance, or maintainability while preserving behavior
arguments:
  - name: target
    description: File or function to refactor
    required: true
  - name: goal
    description: "What to improve: clarity, performance, dry, testability, types, or all (default: all)"
    required: false
---

You are an expert software architect specializing in code quality, design patterns, and refactoring.

## Task

Refactor **{{target}}** to improve {{#if goal}}**{{goal}}**{{else}}overall code quality{{/if}}.

## Instructions

1. **Read the code**: Understand the full implementation before changing anything
2. **Identify code smells**: Look for these specific issues:
   - **Long functions** (>30 lines): Extract helper functions
   - **Deep nesting** (>3 levels): Use early returns, guard clauses
   - **Duplication**: Extract shared logic into reusable functions
   - **God objects**: Split classes with too many responsibilities
   - **Magic values**: Replace with named constants
   - **Weak types**: Add type hints, replace dicts with dataclasses
   - **Missing error handling**: Add specific exception handling
   - **Dead code**: Remove unused imports, variables, functions
3. **Plan changes**: List each refactoring with rationale BEFORE applying
4. **Preserve behavior**: Every refactoring must be behavior-preserving
5. **Run tests**: Execute existing tests after changes to verify nothing broke
6. **Summarize**: List all changes made with before/after comparison

## Output Format

```
## Code Smells Found
1. <smell> at <location> — <why it's a problem>
2. ...

## Refactoring Plan
1. <change> — <rationale>
2. ...

## Changes Applied
### <Change 1>
Before: <brief code snippet>
After: <brief code snippet>
Reason: <why this is better>

## Test Results
<pass/fail summary>

## Metrics
- Lines: <before> -> <after>
- Functions: <before> -> <after>
- Complexity: <assessment>
```

## Edge Cases
- If the code has no tests, warn before refactoring and suggest writing tests first
- If behavior changes are needed (not just structure), flag them and get confirmation
- For large files, prioritize the highest-impact refactorings first

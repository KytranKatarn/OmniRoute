---
name: archie-doc
description: Generate documentation for a function, class, or module
arguments:
  - name: target
    description: File path, function name, or class name to document
    required: true
  - name: format
    description: "Output format: docstring, markdown, or readme (default: docstring)"
    required: false
---

You are a technical documentation expert who writes clear, complete, and useful documentation.

## Task

Generate {{#if format}}**{{format}}**{{else}}docstring{{/if}} documentation for **{{target}}**.

## Instructions

1. **Read the code**: Understand the full implementation, including edge cases
2. **Identify the scope**:
   - **Function**: Parameters, return type, exceptions, usage example
   - **Class**: Purpose, constructor, public methods, properties, usage pattern
   - **Module/file**: Overview, public API, internal architecture, dependencies
3. **Write documentation** appropriate to the format:

### Docstring format (Python):
- Use Google-style docstrings
- Include: summary, Args, Returns, Raises, Example
- Add type hints if missing from code

### Markdown format:
- Title, description, API reference table
- Code examples with expected output
- Configuration/environment requirements

### README format:
- Project overview, installation, quick start
- API reference, configuration, examples
- Contributing guidelines placeholder

4. **Verify accuracy**: Every documented parameter, return value, and exception must exist in the code

## Output Format

The generated documentation ready to insert into the codebase, wrapped in appropriate syntax:
- Docstrings: triple-quoted Python strings
- Markdown: complete .md content
- README: full README.md content

## Edge Cases
- If the code already has documentation, improve it rather than replace entirely
- If type hints are missing, infer types from usage and note the inference
- For complex functions, include both simple and advanced usage examples

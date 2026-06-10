---
name: cartographer
description: Maps and documents codebases of any size by orchestrating parallel subagents. Creates docs/CODEBASE_MAP.md with architecture, file purposes, dependencies, and navigation guides. Use when user says "map this codebase", "cartographer", or when onboarding to a new project.
---

# Cartographer

Maps codebases of any size using parallel Sonnet subagents.

**CRITICAL: Opus orchestrates, Sonnet reads.** Never have Opus read codebase files directly. Always delegate file reading to Sonnet subagents.

## Quick Start
1. Run scanner script to get file tree with token counts
2. Analyze scan output to plan subagent work assignments
3. Spawn Sonnet subagents in parallel to read and analyze file groups
4. Synthesize subagent reports into `docs/CODEBASE_MAP.md`
5. Update `CLAUDE.md` with summary

## Workflow

### Step 1: Check for Existing Map
Check if `docs/CODEBASE_MAP.md` exists. If so, check for changes since `last_mapped` timestamp.

### Step 2: Scan the Codebase
```bash
uv run ${CLAUDE_PLUGIN_ROOT}/skills/cartographer/scripts/scan-codebase.py . --format json
```

### Step 3: Plan Subagent Assignments
- **Token budget per subagent:** ~150,000 tokens
- Group files by directory/module
- Balance token counts across groups

### Step 4: Spawn Sonnet Subagents in Parallel
Use Task tool with `subagent_type: "Explore"` and `model: "sonnet"`.
Each subagent analyzes: purpose, key exports, dependencies, patterns, gotchas.

### Step 5: Synthesize Reports
Merge reports, deduplicate, identify cross-cutting concerns, build architecture diagram.

### Step 6: Write CODEBASE_MAP.md
Structure:
- System Overview (Mermaid diagram)
- Directory Structure
- Module Guide (per module: purpose, entry point, key files, exports, dependencies)
- Data Flow (sequence diagrams)
- Conventions
- Gotchas
- Navigation Guide

### Step 7: Update CLAUDE.md
Add codebase summary pointing to the map.

## Update Mode
When updating: identify changed files, spawn subagents only for changed modules, merge with existing map, update timestamp.

## Token Budget Reference
| Model | Context Window | Safe Budget |
|-------|---------------|-------------|
| Sonnet | 200,000 | 150,000 |
| Opus | 200,000 | 100,000 |
| Haiku | 200,000 | 100,000 |

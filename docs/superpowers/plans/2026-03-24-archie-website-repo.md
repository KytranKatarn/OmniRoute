# ARCHIE Website + Public Repo — Implementation Plan (Plan 8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the public-facing GitHub repo structure and landing page for ARCHIE Code CLI. README with screenshots, install instructions, comparison table. Apache 2.0 license. CONTRIBUTING guide for skill authors.

**Architecture:** Files in repo root for public visibility. Landing page as static HTML for code.kytranempowerment.com (deferred to after domain setup).

**Depends on:** Plans 1-7 (complete).

**Rollback:** Additive. Revert commits.

---

## Task Overview (4 Tasks)

| # | Task | Scope |
|---|------|-------|
| 8.1 | LICENSE + CONTRIBUTING | Apache 2.0, skill authoring guide |
| 8.2 | README.md for archie-code | Install, usage, comparison, architecture |
| 8.3 | Final push + decision logging | Push, log all decisions, update memory |
| 8.4 | Session wrap-up | MCP finish_working, memory update |

---

### Task 8.1: LICENSE + CONTRIBUTING

**Files:**
- Create: `LICENSE` (Apache 2.0)
- Create: `CONTRIBUTING.md` (skill authoring guide)

- [ ] **Step 1: Create LICENSE**

Standard Apache 2.0 with copyright: `Copyright 2026 Kytran Empowerment Inc.`

- [ ] **Step 2: Create CONTRIBUTING.md**

Focus on skill authoring — how to create custom skills:
- Skill file format (YAML frontmatter + markdown body)
- Where to put custom skills (~/.archie/skills/)
- How to test skills locally
- How to submit community skills (PR to repo)

- [ ] **Step 3: Commit**

```bash
git add LICENSE CONTRIBUTING.md && git commit -m "docs: Apache 2.0 license and CONTRIBUTING guide for skill authors"
```

---

### Task 8.2: README for archie-code

**Files:**
- Create: `archie-code-README.md` (separate from platform CLAUDE.md/README)

- [ ] **Step 1: Write README**

Sections:
- Hero: ARCHIE Code CLI tagline + one-liner
- What is it: AI-powered terminal development tool
- Features: 6 community skills, hub connectivity, Claude collaboration
- Install: curl one-liner + manual options
- Quick Start: start engine + launch TUI
- Architecture: engine (Python) + TUI (Go) + Hub (optional)
- Comparison: vs Claude Code, Cursor, Copilot CLI
- Distribution tiers: Community / Node / Hub
- Contributing: link to CONTRIBUTING.md
- License: Apache 2.0

- [ ] **Step 2: Commit**

```bash
git add archie-code-README.md && git commit -m "docs: ARCHIE Code CLI README with install, usage, architecture"
```

---

### Task 8.3: Final push + decisions

- [ ] **Step 1: Push all**
- [ ] **Step 2: Log decision for Plan 7 and Plan 8**
- [ ] **Step 3: Update project understanding to 95%**

---

### Task 8.4: Session wrap-up

- [ ] **Step 1: MCP finish_working with full session summary**
- [ ] **Step 2: Update MEMORY.md with project completion status**

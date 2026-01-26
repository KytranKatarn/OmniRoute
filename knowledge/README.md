# ARCHIE Knowledge Vault

**Created:** 2026-01-08
**Status:** Active
**Version:** 1.0

Welcome to the ARCHIE Platform knowledge base powered by Obsidian.

## About This Vault

This is a local-first knowledge management system that replaces the legacy `/docs/` directory. It provides:
- **Bidirectional Links:** Connect related concepts with `[[wikilinks]]`
- **Semantic Search:** AI-powered search with 768-dim embeddings
- **Real-time Sync:** Automatic indexing when you edit files
- **Claude Code Integration:** Access from Claude Code CLI with `/vault` commands
- **ARCHIE Integration:** Notes automatically enhance ARCHIE's context

## Directory Structure

- **[[Core/]]** - Platform core documentation and architecture
- **[[Features/]]** - Feature-specific documentation
- **[[Development/]]** - Development guides and best practices
- **[[Agents/]]** - Agent specifications and workflows
- **[[APIs/]]** - API documentation and references
- **[[Workflows/]]** - Process documentation and procedures

## Quick Start

### Using Obsidian Desktop App (Optional)
1. Open Obsidian
2. Select "Open folder as vault"
3. Choose `/mnt/archie_brain/knowledge/`

### Using Claude Code CLI
```bash
/vault search <query>       # Search the knowledge base
/vault create <title>       # Create a new note
/vault view <note_name>     # View a note
/vault tags                 # List all tags
/vault graph <note>         # Show backlink graph
```

### YAML Frontmatter Format

All notes should include YAML frontmatter:

```yaml
---
title: "Note Title"
created: 2026-01-08T10:00:00
updated: 2026-01-08T15:00:00
category: Core
tags: [tag1, tag2, tag3]
status: active
author: archie
version: 1.0
related:
  - "[[Related Note 1]]"
  - "[[Related Note 2]]"
---
```

## Migration from /docs/

This vault is in **Phase 1: Parallel Operation** with the legacy `/docs/` directory:
- Legacy docs remain at `/docs/` (read-only)
- New content goes in this vault
- Migration planned for Weeks 3-5

## Search & Discovery

Use ARCHIE chat to ask questions - relevant vault notes will automatically be included in context!

Example: "How does the agent system work?"
ARCHIE will search this vault and provide relevant documentation.

---

**Powered by:** ARCHIE Platform v2.0 + Obsidian
**Maintained by:** ARCHIE + Platform Team

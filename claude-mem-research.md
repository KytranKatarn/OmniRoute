# CLAUDE-MEM: Comprehensive Architecture Research

## 1. WHAT IS CLAUDE-MEM?

Claude-Mem is a persistent memory system for Claude Code that automatically captures tool usage observations, generates semantic summaries, and makes them available to future sessions. It **solves the fundamental problem of lost context between sessions** — enabling Claude to maintain continuity of knowledge about projects even after sessions end or reconnect.

**Version:** 10.4.1 / 11.0.0
**License:** AGPL-3.0 (with PolyForm Noncommercial License for ragtime/ directory)
**Author:** Alex Newman (@thedotmack)

---

## 2. CORE PROBLEM SOLVED

When Claude Code sessions end, all context is lost. The next session starts fresh, requiring the user to:
- Explain the project again
- Re-contextualize previous work
- Redundantly analyze code already understood

**Claude-Mem preserves this context automatically** through:
- Capturing tool observations (file edits, code reviews, etc.)
- Generating summaries of completed work
- Injecting compressed context into new sessions
- Progressive disclosure (search before full context fetch) to save tokens

---

## 3. ARCHITECTURE OVERVIEW

### 3.1 Core Components

```
┌─────────────────────────────────────────────────────────┐
│          CLAUDE CODE / GEMINI CLI                        │
│  (Session Running + Hook Lifecycle)                      │
└────────────┬──────────────────────────────────────────────┘
             │
             ├─ SessionStart ──────────┐
             ├─ UserPromptSubmit ──────┤
             ├─ PostToolUse ───────────┤
             ├─ Stop ──────────────────┤
             └─ SessionEnd ────────────┤
                                       │
                    ┌──────────────────▼──────────────────┐
                    │   LIFECYCLE HOOKS                    │
                    │ (6 shell scripts via hooks.json)     │
                    └──────────────────┬──────────────────┘
                                       │
                ┌──────────────────────▼──────────────────────┐
                │    PLUGIN CLI LAYER                         │
                │ (/src/cli/handlers/*.ts)                    │
                │                                             │
                │ • context.ts (SessionStart inject)         │
                │ • session-init.ts (UserPromptSubmit)       │
                │ • observation.ts (PostToolUse capture)     │
                │ • summarize.ts (Stop summary generation)   │
                │ • session-complete.ts (SessionEnd cleanup) │
                └──────────────────┬──────────────────────┘
                                   │
              ┌────────────────────▼────────────────────┐
              │  WORKER SERVICE (HTTP API on :37777)    │
              │  (Bun runtime, managed lifecycle)       │
              │                                         │
              │ /api/context/inject ──────────────────┐│
              │ /api/sessions/init                    ││
              │ /api/sessions/observations            ││
              │ /api/sessions/complete                ││
              │ /api/search (hybrid semantic+keyword) ││
              │ /api/timeline                         ││
              │ /api/observations/{id}                ││
              └────────────┬─────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
    ┌────────┐      ┌──────────┐     ┌─────────────┐
    │ SQLite │      │  Chroma  │     │  Web Viewer │
    │        │      │  Vector  │     │  UI at :37777
    │(FTS5)  │      │  Database│     └─────────────┘
    └────────┘      └──────────┘
```

### 3.2 File Structure

```
src/
├── cli/                          # Hook event handlers
│   ├── handlers/
│   │   ├── context.ts           # SessionStart: inject context
│   │   ├── session-init.ts      # UserPromptSubmit: init session
│   │   ├── observation.ts       # PostToolUse: capture observations
│   │   ├── summarize.ts         # Stop: queue summary generation
│   │   └── session-complete.ts  # SessionEnd: cleanup
│   ├── hook-command.ts          # Hook entry point & JSON serialization
│   └── types.ts                 # Hook input/output types
│
├── services/
│   ├── worker-service.ts        # Main worker server
│   └── worker/
│       ├── http/
│       │   └── routes/
│       │       ├── SearchRoutes.ts
│       │       ├── SessionRoutes.ts
│       │       ├── MemoryRoutes.ts
│       │       └── ViewerRoutes.ts
│       ├── search/
│       │   ├── SearchOrchestrator.ts  # Hybrid search orchestration
│       │   ├── strategies/
│       │   │   ├── SQLiteSearchStrategy.ts
│       │   │   ├── ChromaSearchStrategy.ts
│       │   │   └── HybridSearchStrategy.ts
│       │   └── filters/
│       │       ├── TypeFilter.ts
│       │       ├── ProjectFilter.ts
│       │       └── DateFilter.ts
│       ├── validation/
│       │   └── PrivacyCheckValidator.ts
│       └── session/
│           └── SessionCompletionHandler.ts
│
├── utils/
│   ├── context-injection.ts     # <claude-mem-context> tag insertion
│   ├── transcript-parser.ts     # Extract messages from transcripts
│   ├── tag-stripping.ts         # Remove <private> tags
│   └── project-name.ts          # Project name & context detection
│
├── npx-cli/
│   └── commands/
│       ├── install.ts           # npx claude-mem install
│       ├── uninstall.ts         # npx claude-mem uninstall
│       └── ide-detection.ts     # Auto-detect IDE (~/.claude or ~/.gemini)
│
└── ui/
    └── viewer/                  # React web viewer UI
        └── http://localhost:37777

plugin/
├── .claude-plugin/
│   ├── plugin.json              # Plugin metadata
│   └── marketplace.json         # Marketplace registration
│
├── hooks/
│   └── hooks.json               # Lifecycle hook definitions (6 hooks)
│
├── modes/
│   └── code.json                # Observation types & concepts
│
├── scripts/
│   ├── setup.sh                 # Pre-install setup
│   ├── smart-install.js         # Cached dependency checker
│   ├── worker-service.cjs       # Worker lifecycle management
│   ├── worker-wrapper.cjs       # Bun process wrapper
│   ├── context-generator.cjs    # Context building
│   └── mcp-server.cjs           # MCP tool registration
│
├── skills/
│   └── mem-search/              # mem-search skill for natural language queries
│
└── .mcp.json                     # MCP server registration
```

---

## 4. PERSISTENCE & MEMORY MECHANISM

### 4.1 The Lifecycle Hook Chain (How Context Actually Persists)

Claude-Mem intercepts Claude Code's lifecycle at 6 critical points:

#### **HOOK 1: SessionStart → contextHandler**
- **When:** User starts a new Claude Code session
- **How:** `SessionStart` hook runs → calls `context-generator.cjs` → queries worker API
- **What happens:**
  ```javascript
  // GET /api/context/inject?projects=proj1,proj2&colors=true
  // Worker searches observations by project
  // Returns formatted markdown with relevant context
  ```
- **Output:** `hookSpecificOutput.additionalContext` — markdown injected into system prompt
- **Result:** New session automatically sees previous work

#### **HOOK 2: UserPromptSubmit → sessionInitHandler**
- **When:** User submits first prompt in session
- **How:** `UserPromptSubmit` hook → calls `/api/sessions/init`
- **Data captured:**
  ```json
  {
    "contentSessionId": "session-123",
    "project": "my-app",
    "prompt": "[user message text]"
  }
  ```
- **Result:** Session created in SQLite with project context

#### **HOOK 3: PostToolUse → observationHandler**
- **When:** After Claude executes ANY tool (file edit, bash, etc.)
- **How:** `PostToolUse` hook → calls `/api/sessions/observations`
- **Captured data:**
  ```json
  {
    "contentSessionId": "session-123",
    "tool_name": "write_file",
    "tool_input": { "path": "src/index.ts", "content": "..." },
    "tool_response": { "success": true },
    "cwd": "/home/user/project"
  }
  ```
- **Privacy check:** Strips `<private>...</private>` tags before storage
- **Filtering:** Checks `CLAUDE_MEM_EXCLUDED_PROJECTS` setting
- **Result:** Observation stored in SQLite + indexed in Chroma for semantic search

#### **HOOK 4: Stop → summarizeHandler**
- **When:** User stops the session (120s timeout available here)
- **How:** Extracts last assistant message from transcript → queues summary to worker
- **Worker does:**
  1. Polls for summary completion (max 110s wait)
  2. Generates semantic summary of session
  3. Stores summary in SQLite
- **Result:** Session summary available for future search

#### **HOOK 5: SessionEnd → HTTP fallback**
- **When:** Session ends (only 1.5s timeout available)
- **How:** Lightweight HTTP call to `/api/sessions/complete`
- **Data:** `{ "contentSessionId": "session-123" }`
- **Result:** Session marked complete, ready for cleanup

#### **HOOK 6: Setup → setup.sh**
- **When:** Plugin first loads
- **How:** Runs pre-install dependency checks
- **Result:** Worker service started, database initialized

### 4.2 Context Injection Mechanism

**Context is injected via markdown tags:**

```markdown
<claude-mem-context>
## Previous Session Context

### Bug Fix: Fixed auth token expiration
- Session ID: sess-456
- Date: 2025-04-04
- Files: src/auth.ts, tests/auth.test.ts

Authentication now validates expiration...
</claude-mem-context>
```

**How it works:**
1. `injectContextIntoMarkdownFile()` in `/src/utils/context-injection.ts`
2. Creates/updates file with `<claude-mem-context>...</claude-mem-context>` tags
3. Target files: `CLAUDE.md`, `AGENTS.md`, or custom locations
4. Content placed between tags is replaced on next session
5. Content outside tags is preserved (safe to edit manually)

---

## 5. STORAGE & DATABASE

### 5.1 SQLite Schema (Core Tables)

```sql
-- Sessions (one per Claude Code session)
CREATE TABLE sessions (
  id INTEGER PRIMARY KEY,
  content_session_id TEXT UNIQUE,
  project TEXT,
  prompt TEXT,
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  summary TEXT
);

-- Observations (one per tool use)
CREATE TABLE observations (
  id INTEGER PRIMARY KEY,
  session_id INTEGER,
  tool_name TEXT,
  tool_input TEXT (JSON),
  tool_response TEXT (JSON),
  created_at TIMESTAMP,
  FOREIGN KEY(session_id) REFERENCES sessions(id)
);

-- Full-Text Search (FTS5)
CREATE VIRTUAL TABLE observations_fts USING fts5(
  tool_name,
  tool_input,
  tool_response,
  created_at,
  content=observations,
  content_rowid=id
);

-- Summaries (semantic)
CREATE TABLE summaries (
  id INTEGER PRIMARY KEY,
  observation_id INTEGER,
  summary TEXT,
  embedding BLOB,  -- Vector from Chroma
  FOREIGN KEY(observation_id) REFERENCES observations(id)
);
```

### 5.2 Hybrid Search (SQLite + Chroma)

**3-Layer Search Pattern (Token Efficient):**

1. **Layer 1: Index Search** (`/api/search`)
   - SQLite FTS5 full-text query
   - Returns compact index: `{ id: 123, type: "bugfix", date: "2025-04-04", ... }`
   - ~50-100 tokens per result

2. **Layer 2: Timeline** (`/api/timeline`)
   - Chronological context around a specific observation
   - Shows what was happening before/after
   - ~200-300 tokens

3. **Layer 3: Full Details** (`/api/observations/{ids}`)
   - Fetch ONLY selected observation details by ID
   - Full tool input/output + summary
   - ~500-1000 tokens per observation
   - **~10x token savings** by filtering before full fetch

**Hybrid Strategy** (SearchOrchestrator.ts):
- SQLite for keyword/full-text matching
- Chroma for semantic similarity
- Blend results: keyword precision + semantic relevance
- Project/date/type filters applied at database level

---

## 6. HOOK ARCHITECTURE DETAILS

### 6.1 How Hooks Are Registered

**File: `plugin/hooks/hooks.json`**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "node \"$_R/scripts/smart-install.js\"",
            "timeout": 300
          },
          {
            "type": "command",
            "command": "node \"$_R/scripts/bun-runner.js\" worker-service.cjs start",
            "timeout": 60
          },
          {
            "type": "command",
            "command": "node \"$_R/scripts/bun-runner.js\" worker-service.cjs hook claude-code context",
            "timeout": 60
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "node \"$_R/scripts/bun-runner.js\" worker-service.cjs hook claude-code observation",
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

**Hook Execution Flow:**
1. Claude Code detects lifecycle event (e.g., `SessionStart`)
2. Loads `hooks.json` from plugin
3. Matches against hook matchers (`startup|clear|compact`)
4. Executes shell commands in sequence
5. Each command calls worker service via `bun-runner.js`
6. Worker service delegates to CLI handlers (`/src/cli/handlers/*.ts`)
7. Handler processes input, calls worker HTTP API
8. Result serialized as JSON back to Claude Code

### 6.2 Command Invocation Chain

Example: **PostToolUse hook execution**

```bash
# 1. Claude Code fires PostToolUse hook
# 2. Plugin runs:
node "$_R/scripts/bun-runner.js" worker-service.cjs hook claude-code observation

# 3. bun-runner.js spawns Bun process:
bun run "$_R/scripts/worker-service.cjs" hook claude-code observation

# 4. worker-service.cjs calls CLI:
import { getEventHandler } from '/src/cli/handlers/index.ts'
const handler = getEventHandler('observation');  // ← observationHandler
const result = await handler.execute(input);     // ← Sends to worker API

# 5. CLI handler makes HTTP request:
POST /api/sessions/observations HTTP/1.1
Host: 127.0.0.1:37777
Content-Type: application/json

{
  "contentSessionId": "session-123",
  "tool_name": "write_file",
  "tool_input": { "path": "src/app.ts", ... },
  "tool_response": { "success": true },
  "cwd": "/home/user/project"
}

# 6. Worker processes & stores in database
```

---

## 7. WORKER SERVICE

### 7.1 Worker Lifecycle

**Service managed by:** `plugin/scripts/worker-service.cjs` (Bun executable)

**Commands:**
```bash
npm run worker:start      # Start background worker (HTTP server on :37777)
npm run worker:stop       # Stop background worker
npm run worker:restart    # Restart worker
npm run worker:status     # Check if running
npm run worker:logs       # Tail worker logs
```

**Runtime:**
- Language: Bun (JavaScript/TypeScript runtime)
- Port: 37777 (default, configurable)
- Process: Background daemon
- Logging: `~/.claude-mem/logs/worker-YYYY-MM-DD.log`

### 7.2 Worker HTTP API Endpoints

**Search Endpoints:**
```
GET  /api/search?query=...&type=bugfix&project=myapp&limit=10
GET  /api/timeline?observation_id=123&before=10&after=10
POST /api/observations?ids=123,456,789
```

**Session Management:**
```
POST /api/sessions/init
POST /api/sessions/observations
POST /api/sessions/complete
```

**Context Injection:**
```
GET  /api/context/inject?projects=proj1,proj2&colors=true
```

**Web Viewer:**
```
GET  http://localhost:37777/          # Web UI (React)
GET  /api/stats                        # System stats
GET  /api/observation/{id}             # Individual observation
```

---

## 8. INSTALLATION & CONFIGURATION

### 8.1 Installation Methods

```bash
# Method 1: NPM (registers hooks + starts worker)
npx claude-mem install

# Method 2: Claude Code plugin marketplace
/plugin marketplace add thedotmack/claude-mem
/plugin install claude-mem

# Method 3: Gemini CLI
npx claude-mem install --ide gemini-cli

# Method 4: OpenClaw Gateway
curl -fsSL https://install.cmem.ai/openclaw.sh | bash
```

### 8.2 Configuration Files

**Location:** `~/.claude-mem/`

```
~/.claude-mem/
├── config.json                 # User settings
├── cmem.db                     # SQLite database
├── chroma/                     # Chroma vector store
├── logs/
│   └── worker-2025-04-05.log  # Worker process logs
└── hooks/                      # Compiled hook scripts
```

**User Settings** (`~/.claude-mem/config.json`):
```json
{
  "CLAUDE_MEM_CONTEXT_SHOW_TERMINAL_OUTPUT": "true",
  "CLAUDE_MEM_EXCLUDED_PROJECTS": "node_modules,dist,build",
  "CLAUDE_MEM_CONTEXT_LIMIT_TOKENS": "4000",
  "CLAUDE_MEM_WEB_VIEWER_PORT": "37777"
}
```

---

## 9. PATTERNS & TECHNIQUES TO STEAL

### 9.1 Progressive Disclosure Pattern

**The 3-layer search approach is brilliant:**
1. Get compact index (~50 tokens)
2. Review IDs, decide what's interesting
3. Fetch only relevant details (~500-1000 tokens)
- Result: ~10x token savings compared to fetching everything

**Applicable to:**
- Any memory system
- Context-constrained LLM applications
- Large document retrieval
- Chat history summarization

### 9.2 Observation Typing

**Structured observation types + concepts:**
- Types: `bugfix`, `feature`, `refactor`, `change`, `discovery`, `decision`
- Concepts: `how-it-works`, `why-it-exists`, `what-changed`, `problem-solution`, `gotcha`, `pattern`, `trade-off`

**Why this matters:**
- Searchable categories for future sessions
- Semantic consistency
- Enables intelligent filtering
- Supports semantic search
- Makes observations contextual, not just raw data

### 9.3 Lifecycle Hooks for Automatic Capture

**Key insight:** Intercept at lifecycle events, not in application code

**Why:**
- Zero friction for user
- Works across projects automatically
- No manual context tagging needed
- Automatic vs. manual = 10x adoption

**Events used:**
- `SessionStart`: Inject previous context
- `UserPromptSubmit`: Initialize session
- `PostToolUse`: Capture work (every tool execution)
- `Stop`: Generate summary
- `SessionEnd`: Cleanup

### 9.4 Privacy-First Design

**Technique: Opt-out with tags**
```markdown
<private>
API keys, secrets, PII here
</private>
```

**Why this works:**
- Users know what to hide
- Simple to use
- Strips tags before storage in `tag-stripping.ts`
- Compliance-friendly

### 9.5 Hybrid Search (Keyword + Semantic)

**SQLite FTS5 + Chroma:**
- SQLite: Fast keyword matching, filters
- Chroma: Semantic similarity (embeddings)
- Combined: Precision + relevance
- Fallback: If semantic fails, keyword results still work

### 9.6 Graceful Degradation

**Pattern: All failures are non-blocking**

```typescript
// Example from observation.ts
if (!response.ok) {
  logger.warn('HOOK', 'Storage failed, skipping', { status });
  return { continue: true, suppressOutput: true };  // ← Never block user
}
```

**Why:**
- Worker crash → session continues normally
- Database error → Claude still works
- Network issue → observations queued for retry
- User never sees failures

### 9.7 Markdown Context Tags for Portability

**Technique:** Store context in user's file system

```markdown
<claude-mem-context>
[Previous session summary]
</claude-mem-context>
```

**Why:**
- Portable (works if service moves/changes)
- Readable (inspect what was stored)
- Editable (user can tweak context)
- Backwards compatible (tags are optional)
- Safe (wrapped in delimiters, doesn't break files)

---

## 10. KEY INTEGRATION POINTS

### 10.1 With Claude Code

- **Plugin system:** Registers as marketplace plugin
- **Hook system:** Implements 6 lifecycle hooks
- **Context injection:** Via markdown tags in CLAUDE.md
- **Skill integration:** mem-search skill for natural language queries
- **MCP tools:** 4 tools for memory search (search, timeline, get_observations)

### 10.2 With Gemini CLI

- **Auto-detection:** Checks ~/.gemini directory
- **Same hooks:** Identical hook registration
- **Same persistence:** Unified database across IDEs

### 10.3 With OpenClaw Gateways

- **Agent networks:** Multi-agent memory sharing
- **Real-time feeds:** Telegram, Discord, Slack integration
- **Standalone mode:** Works without Claude Code

---

## 11. RESEARCH CONCLUSION

**Claude-Mem demonstrates:**

1. **Effective persistence architecture** through lifecycle hook interception
2. **Token-efficient search** with progressive disclosure (3-layer pattern)
3. **Automatic capture** with zero user friction
4. **Privacy preservation** through opt-out tagging
5. **Graceful failure modes** that never block the user
6. **Portable storage** via markdown file integration
7. **Hybrid search** combining keyword + semantic techniques
8. **Observation typing** for structured, searchable memory

**The core innovation:** Automatic context preservation through hook-based observation capture + intelligent hybrid search, enabling multi-session continuity without user intervention.

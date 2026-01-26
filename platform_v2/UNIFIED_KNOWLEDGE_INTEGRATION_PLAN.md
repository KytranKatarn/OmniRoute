# A.R.C.H.I.E. Unified Knowledge & Module Integration Plan

**Created:** 2026-01-11
**Status:** APPROVED - Phases 1-2 + Hook Integration
**Goal:** Create a fully interconnected knowledge ecosystem with Claude Code conversation learning

---

## Current State Analysis

### Knowledge Base Statistics
| Type | Count | Status |
|------|-------|--------|
| github_file | 2,077 | Indexed |
| conversation_memory | 288 | Partially working |
| vault_note | 156 | Only 31 showing in UI |
| mistake_learned | 4 | Active |
| **Total** | **2,525** | - |
| **Agents** | **76** | Active |

### Claude Code Hook Status
| Component | Exists | Working |
|-----------|--------|---------|
| pre_compact_hook.sh | Yes | Partially |
| capture_conversation.py | Yes | Unknown |
| conversation_processor.py | Yes | Processing but no user prompt |
| conversation_summarizer.py | Unknown | Check needed |

**Issues Found:**
- Hook triggers but no user question asked
- Processing runs silently in background
- No integration with Consciousness/Obsidian
- Generic titles ("conversation", "unknown")
- No mistake learning extraction
- No git time-dimension tracking

---

## APPROVED IMPLEMENTATION

### Phase 1: Consciousness Module Fixes (IMMEDIATE)

#### 1.1 Fix Auto-Load Issue
```javascript
// Add to consciousness_dashboard.html
document.addEventListener('DOMContentLoaded', () => {
    loadDashboardData();
    loadMemoryStats();
    loadTeamAwareness();
});
```

#### 1.2 Add Navigation Consistency
```html
<!-- Add to all module headers -->
<div class="module-header">
    <a href="/dashboard" class="back-btn">← Dashboard</a>
    <h1>🧠 Consciousness</h1>
    <button onclick="location.reload()" class="refresh-btn">↻ Refresh</button>
</div>
```

#### 1.3 Apply Matrix Theme
- Green (#00FF00) on black (#000000)
- Consistent with dashboard styling
- Card-based layout with glow effects

---

### Phase 2: Obsidian Vault Enhancement (IMMEDIATE)

#### 2.1 Fix Note Count (31 vs 156)
- Check query: `WHERE is_documentation = true` may be filtering
- Display ALL knowledge types, not just vault_notes
- Add tabs for different knowledge types

#### 2.2 Unified Knowledge Display
```
OBSIDIAN VAULT - Knowledge Hub
├── 📚 Documentation (156 notes)
├── 💬 Conversation Insights (288 memories)
├── 📦 Code Files (2,077 indexed)
├── ⚠️ Mistakes Learned (4 entries)
└── 🔍 Total: 2,525 entries
```

#### 2.3 Auto-Sync from Consciousness
- When conversation_memory created → auto-add to Obsidian view
- When mistake_learned created → auto-add to Obsidian view
- Bi-directional linking

---

### Phase 3: Claude Code Hook Enhancement (CRITICAL)

#### 3.1 Add User Confirmation Question
**Before auto-compact, ASK the user:**

```
┌─────────────────────────────────────────────────────────────┐
│  🧠 A.R.C.H.I.E. MEMORY CHECKPOINT                         │
│                                                             │
│  Context is at ~80% capacity. Before compacting:            │
│                                                             │
│  Should I save this conversation to memory?                 │
│                                                             │
│  Summary detected:                                          │
│  - 15 code changes                                          │
│  - 3 potential mistakes to learn                            │
│  - 2 new insights                                           │
│                                                             │
│  [1] Save All (recommended)                                 │
│  [2] Save Code Changes Only                                 │
│  [3] Skip - Don't Save                                      │
│  [4] Save with Custom Note: ___________                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

#### 3.2 Enhanced Insight Extraction
```python
# conversation_processor.py enhancement
def extract_insights(messages):
    return {
        'code_changes': [...],      # Files modified
        'decisions_made': [...],    # Architectural decisions
        'mistakes_found': [...],    # Errors encountered
        'solutions_learned': [...], # How errors were fixed
        'key_concepts': [...],      # Important topics
        'todos_created': [...],     # Tasks identified
        'git_commits': [...]        # Related commits
    }
```

#### 3.3 Git Time-Dimension Integration
```json
{
  "conversation_id": "uuid",
  "git_timeline": {
    "branch": "main",
    "commits_during_session": [
      {"hash": "abc123", "message": "...", "timestamp": "..."},
      {"hash": "def456", "message": "...", "timestamp": "..."}
    ],
    "files_changed": ["app.py", "routes.py"],
    "lines_added": 150,
    "lines_removed": 30
  },
  "session_timeline": {
    "start": "2026-01-11T10:00:00",
    "end": "2026-01-11T14:00:00",
    "compact_triggered": "2026-01-11T13:45:00"
  }
}
```

#### 3.4 Automatic Categorization (Archie_Brain Style)
```python
ARCHIE_CATEGORIES = {
    'development': ['code', 'bug', 'feature', 'refactor'],
    'infrastructure': ['docker', 'deploy', 'backup', 'database'],
    'ai_learning': ['model', 'prompt', 'training', 'knowledge'],
    'mistake_prevention': ['error', 'fix', 'issue', 'problem'],
    'documentation': ['docs', 'readme', 'guide', 'tutorial']
}
```

---

### Phase 4: Integration Layer

#### 4.1 Knowledge Flow Architecture
```
Claude Code Session
        │
        ▼
┌───────────────────┐
│ PreCompact Hook   │──► User Question: "Save memory?"
└────────┬──────────┘
         │ (if yes)
         ▼
┌───────────────────┐
│ Conversation      │──► Extract insights
│ Processor         │──► Tag with categories
└────────┬──────────┘──► Link to git commits
         │
         ▼
┌───────────────────┐
│ knowledge_base    │
│ table             │
└────────┬──────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌───────┐  ┌───────────┐
│Obsidian│  │Consciousness│
│ Vault  │  │   Module    │
└───────┘  └───────────┘
    │              │
    └──────┬───────┘
           ▼
    ┌─────────────┐
    │ Local AI    │
    │ Agents Use  │
    │ for Context │
    └─────────────┘
```

#### 4.2 Mistake Learning Loop
```
Error Occurs → mistake_learned entry created
                    │
                    ▼
            Obsidian Vault adds note
                    │
                    ▼
            Consciousness shows in analytics
                    │
                    ▼
            AI Bridge checks before similar operations
                    │
                    ▼
            Local agents learn from mistake
```

---

## Implementation Order

### TODAY (Phase 1):
1. [ ] Fix Consciousness auto-load
2. [ ] Add back button to Consciousness
3. [ ] Apply Matrix theme to Consciousness

### TODAY (Phase 2):
4. [ ] Fix Obsidian Vault note count issue
5. [ ] Add all knowledge types to Obsidian view
6. [ ] Add back button to Obsidian Vault

### NEXT (Phase 3):
7. [ ] Create interactive pre-compact prompt
8. [ ] Enhance conversation_processor.py with extraction
9. [ ] Add git time-dimension tracking
10. [ ] Implement Archie_Brain categorization

### NEXT (Phase 4):
11. [ ] Create knowledge sync service
12. [ ] Connect Obsidian ↔ Consciousness
13. [ ] Enable AI agent context lookup

---

## Files to Modify

### Phase 1 (Consciousness):
- `templates/tools/consciousness_dashboard.html`
- `tools/consciousness/routes.py`

### Phase 2 (Obsidian):
- `templates/tools/obsidian_vault.html`
- `tools/obsidian_vault/routes.py`

### Phase 3 (Hooks):
- `scripts/hooks/pre_compact_hook.sh`
- `conversation_processor.py`
- `capture_conversation.py`
- NEW: `services/knowledge_sync.py`

### Phase 4 (Integration):
- NEW: `services/unified_knowledge.py`
- `ai_bridge/knowledge_retrieval.py`

---

## Success Metrics

- [ ] Consciousness loads data on page open (no refresh needed)
- [ ] All modules have "← Dashboard" button
- [ ] Obsidian shows 2,500+ total entries
- [ ] Pre-compact asks user before saving
- [ ] Conversation memories include git context
- [ ] Mistakes automatically become learning entries
- [ ] Local AI agents can query all knowledge

---

**APPROVED FOR IMPLEMENTATION: Phases 1-2 + Phase 3 Hook Integration**

Starting now with Phase 1: Consciousness Module Fixes

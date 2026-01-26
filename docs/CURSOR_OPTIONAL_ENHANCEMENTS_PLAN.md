# Optional Enhancements Plan - Cursor Integration
**Date:** 2026-01-06
**Status:** Planning Phase
**Priority Order:** Git Commit Watcher > Knowledge Base RAG > Real-Time Updates

---

## Overview

This plan details three optional enhancements to the Cursor IDE integration system:

1. **Git Commit Watcher** (CRITICAL) - Auto-detect commits and trigger workflow
2. **Enhanced Knowledge Base RAG** (NICE TO HAVE) - Semantic search for better context
3. **Real-Time Status Updates** (POLISH) - WebSocket-based live progress

---

# Enhancement 1: Git Commit Watcher (CRITICAL)

## Goal
Automatically detect when users commit code in Cursor IDE and trigger the workflow without manual intervention.

## Current State
- ❌ User must manually trigger workflow after committing
- ❌ No automatic commit detection
- ❌ No integration between Git commits and workflow system

## Target State
- ✅ Commits detected within 30 seconds
- ✅ Workflow triggers automatically
- ✅ User notified of workflow progress
- ✅ Commit metadata tracked in database

---

## Architecture Design

### Option A: Git Hooks (RECOMMENDED)

**How It Works:**
```
User commits in Cursor
      ↓
Git post-commit hook triggers
      ↓
Hook script calls API endpoint
      ↓
API triggers background workflow
      ↓
Workflow: Apply → Test → Review
```

**Pros:**
- ✅ Instant detection (< 1 second)
- ✅ Native Git integration
- ✅ No polling overhead
- ✅ Works for all Git clients (not just Cursor)

**Cons:**
- ⚠️ Requires Git hook setup
- ⚠️ Hook must be in sandbox branches
- ⚠️ Needs HTTP call from hook

**Implementation:**
```bash
# .git/hooks/post-commit
#!/bin/bash
BRANCH=$(git branch --show-current)

# Only trigger for sandbox branches
if [[ $BRANCH == sandbox-proposal-* ]]; then
    PROPOSAL_ID=$(echo $BRANCH | sed 's/sandbox-proposal-//')
    COMMIT_HASH=$(git rev-parse HEAD)

    # Call API to trigger workflow
    curl -X POST http://localhost:3000/api/cursor/commit-detected \
        -H "Content-Type: application/json" \
        -d "{
            \"proposal_id\": $PROPOSAL_ID,
            \"commit_hash\": \"$COMMIT_HASH\",
            \"branch\": \"$BRANCH\"
        }"
fi
```

### Option B: Polling (FALLBACK)

**How It Works:**
```
Background service runs every 30s
      ↓
Check all sandbox branches for new commits
      ↓
Compare with last known commit
      ↓
If new commit → trigger workflow
```

**Pros:**
- ✅ No Git hook setup needed
- ✅ Works even if hooks disabled
- ✅ Easier to implement

**Cons:**
- ❌ 30-60 second delay
- ❌ Constant polling overhead
- ❌ More resource intensive

**Implementation:**
```python
class GitCommitPoller:
    def __init__(self):
        self.last_commits = {}  # branch_name -> commit_hash
        self.check_interval = 30  # seconds

    def poll_sandbox_branches(self):
        """Check all sandbox branches for new commits"""
        branches = git_manager.list_sandbox_branches()

        for branch in branches:
            current_commit = self._get_latest_commit(branch)
            last_known = self.last_commits.get(branch)

            if current_commit != last_known:
                # New commit detected!
                proposal_id = self._extract_proposal_id(branch)
                self._trigger_workflow(proposal_id, current_commit)
                self.last_commits[branch] = current_commit
```

### Recommended Approach: **Hybrid (Hooks + Polling)**

Use Git hooks as primary, polling as fallback:
- Install hooks automatically when creating sandbox branch
- Run polling service to catch missed commits
- Best of both worlds

---

## Implementation Steps

### Step 1: Create Git Hook Manager

**File:** `/mnt/archie_brain/platform_v2/git_hook_manager.py`

```python
class GitHookManager:
    """Manages Git hooks for automatic commit detection"""

    def install_commit_hook(self, branch_name: str) -> Dict:
        """Install post-commit hook for sandbox branch"""
        hook_path = '/mnt/archie_brain/platform_v2/.git/hooks/post-commit'

        # Create hook script
        hook_content = '''#!/bin/bash
BRANCH=$(git branch --show-current)

if [[ $BRANCH == sandbox-proposal-* ]]; then
    PROPOSAL_ID=$(echo $BRANCH | sed 's/sandbox-proposal-//')
    COMMIT_HASH=$(git rev-parse HEAD)
    COMMIT_MSG=$(git log -1 --pretty=%s)
    AUTHOR=$(git log -1 --pretty=%an)

    # Call webhook
    curl -s -X POST http://localhost:3000/api/cursor/commit-webhook \
        -H "Content-Type: application/json" \
        -H "X-Git-Hook: true" \
        -d "{
            \\"proposal_id\\": $PROPOSAL_ID,
            \\"commit_hash\\": \\"$COMMIT_HASH\\",
            \\"commit_message\\": \\"$COMMIT_MSG\\",
            \\"author\\": \\"$AUTHOR\\",
            \\"branch\\": \\"$BRANCH\\"
        }" &
fi
'''

        # Write and make executable
        with open(hook_path, 'w') as f:
            f.write(hook_content)
        os.chmod(hook_path, 0o755)

        return {'success': True, 'hook_path': hook_path}
```

### Step 2: Add Commit Webhook Endpoint

**File:** `/mnt/archie_brain/platform_v2/cursor_api.py` (add to existing file)

```python
@cursor_bp.route('/commit-webhook', methods=['POST'])
def commit_webhook():
    """
    Webhook called by Git post-commit hook
    Triggers workflow when commit detected
    """
    try:
        data = request.json
        proposal_id = data['proposal_id']
        commit_hash = data['commit_hash']
        commit_message = data.get('commit_message', '')
        author = data.get('author', 'Unknown')

        # Record commit in database
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO git_commits
            (proposal_id, commit_hash, branch_name, commit_message, author_name, committed_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (proposal_id, commit_hash, data['branch'], commit_message, author))
        conn.commit()

        # Trigger background workflow
        from background_workflow_runner import start_workflow_background
        workflow_result = start_workflow_background(proposal_id)

        return jsonify({
            'success': True,
            'message': 'Workflow triggered',
            'workflow_id': workflow_result.get('workflow_id')
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
```

### Step 3: Create Polling Service (Fallback)

**File:** `/mnt/archie_brain/ai_bridge/git_commit_poller.py`

```python
import time
import threading
from typing import Dict
from git_branch_manager import GitBranchManager

class GitCommitPoller:
    """Polls Git for new commits (fallback if hooks fail)"""

    def __init__(self, interval: int = 30):
        self.interval = interval
        self.last_commits = {}
        self.running = False
        self.thread = None
        self.git_manager = GitBranchManager()

    def start(self):
        """Start polling in background thread"""
        self.running = True
        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop polling"""
        self.running = False

    def _poll_loop(self):
        """Main polling loop"""
        while self.running:
            try:
                self._check_for_commits()
            except Exception as e:
                print(f"Polling error: {e}")

            time.sleep(self.interval)

    def _check_for_commits(self):
        """Check all sandbox branches for new commits"""
        branches_result = self.git_manager.list_sandbox_branches()

        if not branches_result['success']:
            return

        for branch_name in branches_result['branches']:
            # Get latest commit
            result = self.git_manager._run_git_command([
                'git', 'rev-parse', branch_name
            ])

            if result['success']:
                current_commit = result['stdout']
                last_known = self.last_commits.get(branch_name)

                if last_known and current_commit != last_known:
                    # New commit detected!
                    proposal_id = int(branch_name.replace('sandbox-proposal-', ''))
                    self._trigger_workflow(proposal_id, current_commit, branch_name)

                self.last_commits[branch_name] = current_commit

    def _trigger_workflow(self, proposal_id: int, commit_hash: str, branch_name: str):
        """Trigger workflow for new commit"""
        print(f"📡 Detected commit on {branch_name}: {commit_hash[:8]}")

        # Trigger via webhook endpoint
        import requests
        requests.post('http://localhost:3000/api/cursor/commit-webhook', json={
            'proposal_id': proposal_id,
            'commit_hash': commit_hash,
            'branch': branch_name,
            'commit_message': '[Auto-detected]',
            'author': '[Poller]'
        })
```

### Step 4: Integrate with Git Branch Manager

Update `git_branch_manager.py` to install hooks automatically:

```python
def create_sandbox_branch(self, proposal_id: int) -> Dict:
    """Create sandbox branch and install commit hook"""
    # ... existing code ...

    if result['success']:
        # Install commit detection hook
        from git_hook_manager import GitHookManager
        hook_manager = GitHookManager()
        hook_manager.install_commit_hook(branch_name)

        return {
            'success': True,
            'branch_name': branch_name,
            'hook_installed': True,
            # ... rest of response ...
        }
```

### Step 5: Update Workflow Integration

Modify `workflow_orchestrator.py` to handle auto-triggered workflows:

```python
def execute_full_workflow(self, proposal_id: int, triggered_by: str = 'manual') -> Dict:
    """Execute workflow with trigger source tracking"""

    # Update proposal with trigger info
    self._update_proposal_metadata(proposal_id, {
        'triggered_by': triggered_by,
        'triggered_at': datetime.now().isoformat()
    })

    # ... rest of workflow execution ...
```

---

## Database Changes

### New Table: git_commits

```sql
CREATE TABLE git_commits (
    id SERIAL PRIMARY KEY,
    proposal_id INTEGER REFERENCES improvement_proposals(id),
    commit_hash VARCHAR(64) UNIQUE NOT NULL,
    branch_name VARCHAR(255) NOT NULL,
    commit_message TEXT,
    author_name VARCHAR(255),
    author_email VARCHAR(255),
    committed_at TIMESTAMP NOT NULL,
    detected_at TIMESTAMP DEFAULT NOW(),
    workflow_triggered BOOLEAN DEFAULT FALSE,
    workflow_id VARCHAR(255),
    metadata JSONB,
    INDEX idx_proposal_commits (proposal_id, committed_at DESC),
    INDEX idx_commit_hash (commit_hash)
);
```

### Update improvement_proposals

```sql
ALTER TABLE improvement_proposals
ADD COLUMN last_commit_hash VARCHAR(64),
ADD COLUMN last_commit_at TIMESTAMP,
ADD COLUMN commits_count INTEGER DEFAULT 0;
```

---

## Testing Strategy

### Unit Tests

```python
def test_commit_detection():
    # Create sandbox branch
    # Make a commit
    # Verify webhook called
    # Verify workflow triggered

def test_polling_fallback():
    # Disable hooks
    # Make commit
    # Wait 30s
    # Verify poller detected commit

def test_duplicate_commit_handling():
    # Same commit detected twice
    # Verify workflow only triggered once
```

### Integration Tests

```python
def test_end_to_end_commit_workflow():
    # 1. Create proposal
    # 2. Open in Cursor (creates branch)
    # 3. Make commit
    # 4. Verify workflow triggered
    # 5. Check sandbox updated
    # 6. Verify ready for review
```

---

## Migration Path

### Phase 1: Add Webhook Endpoint (No Breaking Changes)
- Add commit webhook to cursor_api.py
- Add git_commits table
- No impact on existing functionality

### Phase 2: Add Hook Manager (Optional)
- Create git_hook_manager.py
- Install hooks on new branches
- Existing branches still work (manual trigger)

### Phase 3: Enable Polling (Fallback)
- Start git_commit_poller service
- Catches missed commits
- Works alongside hooks

### Phase 4: Full Integration
- Auto-install hooks on all new branches
- Polling as fallback
- Remove manual trigger option (if desired)

---

## Performance Considerations

### Resource Usage
- **Git Hooks:** Negligible (< 100ms per commit)
- **Polling:** ~50MB RAM, 1-2% CPU
- **Webhook Calls:** < 10ms latency

### Scalability
- Git hooks scale infinitely (per-commit basis)
- Polling scales with number of active branches
- Recommend: < 100 active sandbox branches

### Monitoring
- Track webhook call success rate
- Monitor polling interval timing
- Alert if commits not detected within 2 minutes

---

# Enhancement 2: Enhanced Knowledge Base with RAG

## Goal
Improve .cursorrules generation with semantic search for better code examples and context.

## Current State
- ❌ Simple keyword search (ILIKE queries)
- ❌ No semantic understanding
- ❌ Limited relevance ranking
- ❌ Doesn't learn from successful implementations

## Target State
- ✅ Semantic search (understand meaning)
- ✅ Better code examples in .cursorrules
- ✅ Context-aware suggestions
- ✅ Learn from successful implementations

---

## Architecture Design

### Option A: PostgreSQL pgvector (RECOMMENDED)

**Why:**
- ✅ Same database (no new infrastructure)
- ✅ SQL queries (familiar)
- ✅ Good performance (HNSW index)
- ✅ Easy to integrate

**How It Works:**
```
1. Generate embeddings for code snippets
2. Store in PostgreSQL with pgvector
3. Semantic search using cosine similarity
4. Combine with keyword search (hybrid)
```

**Schema:**
```sql
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE knowledge_base
ADD COLUMN embedding vector(768);  -- 768 dimensions for sentence-transformers

CREATE INDEX ON knowledge_base USING ivfflat (embedding vector_cosine_ops);
```

### Option B: ChromaDB (Separate Vector DB)

**Why:**
- ✅ Purpose-built for vector search
- ✅ Better for large-scale
- ✅ Built-in embedding generation

**Cons:**
- ❌ Additional infrastructure
- ❌ More complex deployment
- ❌ Separate from main DB

### Recommended: **PostgreSQL pgvector** (Simpler, sufficient for our needs)

---

## Implementation Steps

### Step 1: Install pgvector Extension

```sql
-- Run in PostgreSQL
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding column
ALTER TABLE knowledge_base
ADD COLUMN embedding vector(768);

-- Create index for fast similarity search
CREATE INDEX knowledge_embedding_idx
ON knowledge_base USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

### Step 2: Create Embedding Generator

**File:** `/mnt/archie_brain/ai_bridge/embedding_generator.py`

```python
from sentence_transformers import SentenceTransformer
import numpy as np

class EmbeddingGenerator:
    """Generate embeddings for semantic search"""

    def __init__(self, model_name: str = 'all-MiniLM-L6-v2'):
        # Lightweight model, fast, good quality
        self.model = SentenceTransformer(model_name)

    def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding for text"""
        return self.model.encode(text)

    def generate_embeddings_batch(self, texts: List[str]) -> np.ndarray:
        """Generate embeddings for multiple texts"""
        return self.model.encode(texts)
```

**Dependencies to Add:**
```
sentence-transformers==2.2.2
```

### Step 3: Create Hybrid Search System

**File:** `/mnt/archie_brain/ai_bridge/knowledge_retrieval_v2.py`

```python
class HybridKnowledgeRetrieval:
    """Hybrid search: keyword + semantic"""

    def __init__(self):
        self.embedding_gen = EmbeddingGenerator()

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Hybrid search combining keyword and semantic

        Returns results ranked by combined score
        """
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Generate query embedding
        query_embedding = self.embedding_gen.generate_embedding(query)

        # Hybrid search query
        cur.execute("""
            WITH keyword_results AS (
                SELECT
                    *,
                    ts_rank(
                        to_tsvector('english', content),
                        plainto_tsquery('english', %s)
                    ) as keyword_score
                FROM knowledge_base
                WHERE to_tsvector('english', content) @@ plainto_tsquery('english', %s)
            ),
            semantic_results AS (
                SELECT
                    *,
                    1 - (embedding <=> %s::vector) as semantic_score
                FROM knowledge_base
                WHERE embedding IS NOT NULL
                ORDER BY embedding <=> %s::vector
                LIMIT 20
            )
            SELECT
                k.id, k.file_name, k.content, k.tags, k.category,
                COALESCE(k.keyword_score, 0) * 0.3 +
                COALESCE(s.semantic_score, 0) * 0.7 as combined_score
            FROM knowledge_base k
            LEFT JOIN keyword_results kr ON k.id = kr.id
            LEFT JOIN semantic_results s ON k.id = s.id
            WHERE kr.id IS NOT NULL OR s.id IS NOT NULL
            ORDER BY combined_score DESC
            LIMIT %s
        """, (query, query, query_embedding.tolist(), query_embedding.tolist(), limit))

        return [dict(row) for row in cur.fetchall()]
```

### Step 4: Update Cursor Context Generator

Modify `cursor_context_generator.py`:

```python
def get_related_knowledge(self, proposal: Dict, limit: int = 5) -> List[Dict]:
    """Get related knowledge using hybrid search"""
    from knowledge_retrieval_v2 import HybridKnowledgeRetrieval

    retrieval = HybridKnowledgeRetrieval()

    # Build search query from proposal
    search_query = f"{proposal['title']} {proposal['description']} {proposal.get('category', '')}"

    # Hybrid search
    results = retrieval.search(search_query, limit)

    return results
```

### Step 5: Background Embedding Generation

**File:** `/mnt/archie_brain/ai_bridge/embedding_worker.py`

```python
class EmbeddingWorker:
    """Background worker to generate embeddings for knowledge base"""

    def generate_missing_embeddings(self):
        """Generate embeddings for entries without them"""
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Find entries without embeddings
        cur.execute("""
            SELECT id, content
            FROM knowledge_base
            WHERE embedding IS NULL
            LIMIT 100
        """)

        entries = cur.fetchall()

        if not entries:
            return

        # Generate embeddings
        embeddings = self.embedding_gen.generate_embeddings_batch(
            [e['content'] for e in entries]
        )

        # Update database
        for entry, embedding in zip(entries, embeddings):
            cur.execute("""
                UPDATE knowledge_base
                SET embedding = %s
                WHERE id = %s
            """, (embedding.tolist(), entry['id']))

        conn.commit()
```

---

## Database Changes

```sql
-- Add pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Add embedding column
ALTER TABLE knowledge_base
ADD COLUMN IF NOT EXISTS embedding vector(768),
ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(100) DEFAULT 'all-MiniLM-L6-v2',
ADD COLUMN IF NOT EXISTS embedding_generated_at TIMESTAMP;

-- Create index
CREATE INDEX IF NOT EXISTS knowledge_embedding_idx
ON knowledge_base USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- Full-text search index (for hybrid)
CREATE INDEX IF NOT EXISTS knowledge_content_idx
ON knowledge_base USING gin(to_tsvector('english', content));
```

---

## Testing Strategy

```python
def test_semantic_search():
    # Search for "database optimization"
    # Should find results about "query performance" (semantic match)
    # Even if exact words don't match

def test_hybrid_ranking():
    # Query should rank results combining:
    # - Keyword matches (30% weight)
    # - Semantic similarity (70% weight)

def test_embedding_generation():
    # Add new knowledge entry
    # Verify embedding generated
    # Verify searchable
```

---

# Enhancement 3: Real-Time Status Updates

## Goal
Show live workflow progress without polling every 3 seconds.

## Current State
- ❌ JavaScript polls every 3 seconds
- ❌ Inefficient for long workflows
- ❌ Server load from constant polling

## Target State
- ✅ Push updates from server
- ✅ Live progress notifications
- ✅ < 500ms latency
- ✅ Reduced server load

---

## Architecture Design

### Option A: Server-Sent Events (SSE) - RECOMMENDED

**Why:**
- ✅ Simple to implement
- ✅ Built into browsers
- ✅ One-way push (perfect for our use case)
- ✅ Automatic reconnection
- ✅ No special libraries needed

**How It Works:**
```
Browser opens SSE connection
      ↓
Server keeps connection alive
      ↓
Workflow updates → Push to browser
      ↓
Browser updates UI in real-time
```

**Implementation:**
```python
from flask import Response, stream_with_context

@app.route('/api/workflow/stream/<int:proposal_id>')
def stream_workflow_updates(proposal_id):
    """SSE endpoint for live updates"""

    def generate():
        last_state = None

        while True:
            # Check workflow status
            status = get_workflow_status(proposal_id)

            if status['state'] != last_state:
                # State changed, push update
                yield f"data: {json.dumps(status)}\n\n"
                last_state = status['state']

            if status['state'] in ['completed', 'failed']:
                break

            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream'
    )
```

**Frontend:**
```javascript
// Connect to SSE stream
const eventSource = new EventSource(`/api/workflow/stream/${proposalId}`);

eventSource.onmessage = (event) => {
    const status = JSON.parse(event.data);
    updateWorkflowUI(status);
};

eventSource.onerror = () => {
    eventSource.close();
    // Fallback to polling
};
```

### Option B: WebSockets (More Complex)

**Why:**
- ✅ Bidirectional (client can send too)
- ✅ Lower latency

**Cons:**
- ❌ More complex to implement
- ❌ Requires Flask-SocketIO
- ❌ Overkill for one-way updates

### Recommended: **Server-Sent Events** (Simpler, sufficient)

---

## Implementation Steps

### Step 1: Add SSE Endpoint

**File:** `/mnt/archie_brain/platform_v2/cursor_api.py`

```python
from flask import Response, stream_with_context
import json
import time

@cursor_bp.route('/workflow/stream/<int:proposal_id>')
@login_required
def stream_workflow_updates(proposal_id):
    """Server-Sent Events stream for live workflow updates"""

    def generate():
        """Generator function for SSE"""
        last_status = None

        while True:
            # Get current workflow status
            from background_workflow_runner import get_proposal_workflow_status

            status = get_proposal_workflow_status(proposal_id)

            if status and status != last_status:
                # Status changed, push update
                event_data = {
                    'proposal_id': proposal_id,
                    'status': status.get('status'),
                    'state': status.get('result', {}).get('final_state'),
                    'progress': status.get('result', {}).get('states_completed', []),
                    'timestamp': datetime.now().isoformat()
                }

                yield f"data: {json.dumps(event_data)}\n\n"
                last_status = status

            # Check if workflow is complete
            if status and status.get('status') in ['completed', 'failed']:
                yield f"data: {json.dumps({'done': True})}\n\n"
                break

            time.sleep(1)  # Check every second

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'  # Disable nginx buffering
        }
    )
```

### Step 2: Update Frontend

**File:** `/mnt/archie_brain/platform_v2/templates/ (now modular templates)`

```javascript
// Replace polling with SSE
function watchWorkflowProgress(proposalId) {
    // Close existing connection if any
    if (window.workflowEventSource) {
        window.workflowEventSource.close();
    }

    // Open SSE connection
    const eventSource = new EventSource(`/api/cursor/workflow/stream/${proposalId}`);
    window.workflowEventSource = eventSource;

    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.done) {
            // Workflow complete
            eventSource.close();
            showNotification('✅ Workflow complete!', 'success');
            refreshWorkflowPipeline();
        } else {
            // Update UI with new status
            updateWorkflowPipeline(data);
        }
    };

    eventSource.onerror = (error) => {
        console.error('SSE error:', error);
        eventSource.close();

        // Fallback to polling
        console.log('Falling back to polling...');
        startPolling(proposalId);
    };
}

function updateWorkflowPipeline(data) {
    // Update pipeline UI in real-time
    const { state, progress } = data;

    // Update step indicators
    progress.forEach(step => {
        const stepEl = document.querySelector(`[data-step="${step}"]`);
        if (stepEl) {
            stepEl.classList.add('completed');
        }
    });

    // Show current step
    const currentStepEl = document.querySelector(`[data-step="${state}"]`);
    if (currentStepEl) {
        currentStepEl.classList.add('active');
    }
}
```

### Step 3: Add Notification System

```javascript
function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.style.cssText = `
        position: fixed;
        top: 100px;
        right: 20px;
        background: ${type === 'success' ? 'rgba(0,255,0,0.2)' : 'rgba(255,165,0,0.2)'};
        border: 2px solid ${type === 'success' ? '#00FF00' : '#FFA500'};
        color: ${type === 'success' ? '#00FF00' : '#FFA500'};
        padding: 15px 20px;
        border-radius: 4px;
        z-index: 10000;
        animation: slideIn 0.3s ease-out;
    `;
    notification.textContent = message;

    document.body.appendChild(notification);

    setTimeout(() => {
        notification.style.animation = 'slideOut 0.3s ease-in';
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}
```

---

## Performance Considerations

### Resource Usage
- **SSE Connection:** ~1KB per connection
- **Memory:** ~100KB per active stream
- **CPU:** Negligible (< 0.1% per stream)

### Scalability
- Supports 1000+ concurrent connections
- Each workflow stream = 1 connection
- Auto-closes when complete

### Monitoring
- Track active SSE connections
- Monitor connection duration
- Alert if connections stuck open

---

# Summary & Priorities

## Implementation Order

### 1. Git Commit Watcher (CRITICAL) - 2-3 days
**Why First:**
- Makes workflow truly automatic
- Highest user value
- Relatively simple to implement

**Deliverables:**
- Git hook manager
- Commit webhook endpoint
- Polling fallback service
- Database schema updates

### 2. Enhanced Knowledge Base RAG (NICE TO HAVE) - 3-4 days
**Why Second:**
- Improves .cursorrules quality
- Better developer experience
- Independent of other features

**Deliverables:**
- pgvector extension setup
- Embedding generator
- Hybrid search system
- Background embedding worker

### 3. Real-Time Updates (POLISH) - 1-2 days
**Why Last:**
- Improves UX but not essential
- Current polling works fine
- Quick to implement with SSE

**Deliverables:**
- SSE endpoint
- Frontend integration
- Notification system

---

## Total Effort Estimate

- **Git Commit Watcher:** 2-3 days
- **Knowledge Base RAG:** 3-4 days
- **Real-Time Updates:** 1-2 days

**Total:** 6-9 days for all three enhancements

---

## Success Metrics

### Git Commit Watcher
- ✅ 95%+ commit detection rate
- ✅ < 30 second detection latency
- ✅ Zero false positives

### Knowledge Base RAG
- ✅ 50%+ better .cursorrules relevance
- ✅ < 2 seconds to generate context
- ✅ Higher user satisfaction

### Real-Time Updates
- ✅ < 500ms update latency
- ✅ 80%+ reduction in polling requests
- ✅ No connection stability issues

---

**Status:** Ready for implementation
**Next Step:** User approval to begin Enhancement 1 (Git Commit Watcher)

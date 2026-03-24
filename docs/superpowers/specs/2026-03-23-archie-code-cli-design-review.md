# ARCHIE Code CLI -- Design Spec Review

**Reviewer**: Senior Code Reviewer (Claude Opus 4.6)
**Date**: 2026-03-23
**Spec**: `/mnt/archie_brain/docs/superpowers/specs/2026-03-23-archie-code-cli-design.md`

---

## Overall Assessment

The spec is well-structured with a clear vision, sensible 4-layer architecture, and a realistic migration plan. The file sizes in Section 3 match the actual codebase (verified: 152KB total across 8 files). The three-tier distribution model (Community/Node/Hub) cleanly solves the failed node deployment history. Several gaps need addressing before implementation.

---

## CRITICAL Issues

### C1. No Authentication or Trust Model for Hub Connections

Section 9 says nodes "connect to hub" and unlock agent orchestration, knowledge base, sandbox deployment, and model management. Section 4 mentions `hub/auth.py` with "API key auth, node identity" but there is zero detail on:

- How API keys are generated, rotated, or revoked
- How the hub validates a connecting node is authorized (not a random internet client)
- Whether hub connections use TLS (code.kytranempowerment.com is externally routable per Section 8)
- What happens if an API key is compromised -- can an attacker dispatch agents, read the KB, or deploy to sandbox?
- Rate limiting on the hub API surface

**Recommendation**: Add a dedicated Security section covering: key provisioning (node registration flow), mTLS or token-based auth with refresh, per-node permission scopes (read-only KB vs full dispatch), hub API rate limits, and revocation procedure.

### C2. MCP Server Exposes Powerful Tools Without Scoping

Section 6 exposes `archie_dispatch`, `archie_search_kb`, `archie_sandbox_deploy`, and `archie_skill_execute` as MCP tools for Claude CLI. These are powerful operations (deploy code, execute skills, dispatch agents). The spec does not address:

- Who can invoke these tools (any MCP client, or only authenticated ones?)
- Whether there are per-tool permission levels
- Sandbox deployment via MCP could deploy arbitrary branches to a public subdomain

**Recommendation**: Define an MCP auth layer. At minimum, MCP serve mode should require a local API key or only bind to localhost. Sandbox deploy should require explicit user approval in the TUI before executing.

### C3. Shell Execution Sandboxing is Undefined

Section 4 lists `tools/shell_ops.py` with "Command execution with sandboxing" but provides no detail on what sandboxing means. This is the highest-risk tool in the entire system. Without constraints:

- A local model could hallucinate `rm -rf /` and the engine would execute it
- Community edition users running untrusted skills could have arbitrary code execution

**Recommendation**: Define the sandbox model explicitly: allowlist/denylist of commands, working directory confinement, user confirmation for destructive operations (similar to Claude Code's permission system), and whether skills can invoke shell_ops at all.

---

## HIGH Issues

### H1. Go TUI + Python Engine = Two-Process Complexity

The TUI is Go (Bubble Tea), the engine is Python, connected via gRPC. This means:

- Every install requires both a Go binary AND a Python runtime
- `pip install archie-code` installs only the Python engine -- how does the Go TUI get installed?
- The Windows installer bundles both, but pip and Homebrew paths are unclear
- gRPC adds protobuf compilation to the build pipeline

**Recommendation**: Clarify the install matrix. Does `pip install` give you a Python-only CLI (no TUI)? Does the Go binary embed or download the Python engine? Consider whether a Python TUI (Textual) for v1 would halve complexity, with Go TUI as a v2 optimization.

### H2. Offline Mode Inference Quality Not Addressed

Section 4 says offline mode uses "local Ollama model" for intent parsing. The quality of intent classification on a small local model (e.g., phi3.5 or qwen2.5:7b) versus the hub's larger models is vastly different. The spec does not address:

- What is the minimum model size for acceptable intent parsing?
- What happens when the local model misclassifies intents?
- Is there a fallback to keyword/regex matching for basic intents?

**Recommendation**: Define minimum model requirements per tier. Community edition should have a fallback intent parser (rule-based) that works without any LLM for basic commands like `/review`, `/commit`, `/search`.

### H3. Migration Destination for api.py is Ambiguous

Section 3 says api.py (18KB) gets "Split: API routes stay in app.py, chat logic merges into archie_chat." The existing archie_chat already has `routes.py`, `api_routes.py`, and `chat_service.py`. Merging ai_chat.py AND api.py chat logic into archie_chat creates a risk of:

- Duplicate chat logic (archie_chat already has its own chat service)
- Unclear which "API routes" stay in app.py vs move

**Recommendation**: Audit the overlap between `archie_core/api.py` and `archie_chat/api_routes.py` before migration. Document exactly which functions move where. The spec should list function-level mappings, not just file-level.

### H4. No Error Handling or Resilience Patterns

The spec describes the happy path (Section 4 Request Flow) but never addresses:

- What happens when the hub connection drops mid-task?
- How does the engine handle Ollama crashes or model loading failures?
- gRPC reconnection policy between TUI and engine
- Partial failure in multi-file operations (3 files edited, 4th fails)

**Recommendation**: Add a Resilience section covering: connection retry with backoff, graceful degradation (hub disconnect falls back to offline mode), transaction semantics for multi-file operations, and user-visible error states in the TUI.

### H5. No Testing Strategy

The spec has success criteria (Section 11) but no testing plan:

- How will the intent parser's 18 types be validated?
- How will hub/node communication be tested (integration tests)?
- How will the Go TUI be tested (snapshot tests? manual?)
- How will cross-platform builds be verified?

**Recommendation**: Add a Testing section with: unit test requirements per component, integration test plan for hub-node communication, TUI snapshot testing approach, and CI matrix for cross-platform validation.

---

## MEDIUM Issues

### M1. gRPC AND WebSocket on the Same Server

Section 10 says the engine server uses "gRPC for TUI (fast, typed), WebSocket for Web Chat." Running both protocols on the same Python process adds complexity. Consider:

- Two different serialization formats to maintain
- Two different connection lifecycle models
- The Web Chat already works over HTTP/WebSocket to the Flask app -- why route through the engine?

**Recommendation**: Consider using WebSocket only for v1 (simpler), or clarify whether gRPC is truly needed given the TUI's interaction pattern is request-response, not high-throughput streaming.

### M2. Subdomain Routing Assumes DNS Infrastructure

Section 8 references `code.kytranempowerment.com` and `sandbox.kytranempowerment.com` with AdGuard split DNS. This works for the hub operator but:

- Community users cannot use these subdomains
- The spec does not address how community users access their local engine (localhost:port?)
- External access to code.kytranempowerment.com requires port forwarding or Cloudflare tunnel

**Recommendation**: Document the community access model (localhost:PORT) and the hub external access setup (Cloudflare tunnel or port forward + TLS cert).

### M3. Skill Format Lacks Execution Semantics

Section 7 shows skill format with markdown steps like "Read files" and "Search knowledge base." These are human-readable descriptions, not executable instructions. The spec does not explain:

- How does the skill loader translate "Read files" into tool calls?
- Is the skill body sent as a prompt to the LLM which then calls tools?
- What prevents a malicious skill from instructing the LLM to do harmful things?

**Recommendation**: Define skill execution model: are skills prompt templates (sent to LLM as system instructions) or structured tool chains (executed deterministically)? If prompt-based, document the safety guardrails.

### M4. Version Compatibility Between Components Not Addressed

With Go TUI, Python engine, hub platform, and skills all versioning independently:

- What happens when a v1.2 TUI connects to a v1.0 engine?
- What happens when a v1.0 engine connects to a v2.0 hub?
- How are breaking API changes communicated?

**Recommendation**: Define a version negotiation protocol. At minimum: engine reports its version to hub on connect, hub rejects incompatible versions with a clear upgrade message.

### M5. SQLite for Engine-Local Storage May Conflict with Hub PostgreSQL

Section 10 says the engine uses SQLite for "session history, cached skills, offline queue." The hub uses PostgreSQL. When reconnecting after offline work:

- How are offline-queued events reconciled with hub state?
- What if an offline session created a branch that conflicts with hub activity?
- Is there a merge/conflict resolution strategy?

**Recommendation**: Document the offline queue sync protocol: idempotent event replay, conflict detection, and user notification for unresolvable conflicts.

---

## LOW Issues

### L1. The Spec Says "91KB of proven code" but Total is 152KB

Section 1 references "91KB of proven code from archie_core module." This is only the three engine-bound files (intent_parser + command_router + command_interface). The remaining 61KB (ai_chat, archie_core, ha_bridge, api) also needs migration. The "91KB" framing understates the migration scope.

### L2. LCARS Boot Animation Timing

Section 5 specifies a "0.5s LCARS boot animation." For a CLI tool, any mandatory delay on startup will frustrate power users. Consider making it skippable or only showing on first run.

### L3. License Not Decided

Section 8 says "MIT or Apache 2.0" -- this should be decided before the public repo is created, as it affects contribution terms and patent grants.

### L4. No Logging or Observability Strategy

The spec mentions Starbase visibility for hub-connected nodes but does not address local logging: log levels, log file location, log rotation, or debug mode for troubleshooting engine issues.

### L5. Success Criterion #10 is a Migration Task, Not a Product Feature

"archie_core directory fully migrated and deleted" is a housekeeping task, not a success criterion for the CLI product. Consider separating migration milestones from product milestones.

---

## What Was Done Well

- **Architecture diagram** (Section 2) is clear and the 4-layer separation is sound
- **Migration table** (Section 3) is precise with file-level mappings and verified sizes
- **Request flow** (Section 4) traces a complete user interaction end-to-end
- **Tier differentiation** (Section 8) cleanly maps features to distribution levels
- **Claude collaboration** (Section 6) with bidirectional MCP is well thought out
- **Offline mode** (Section 4) is explicitly addressed rather than ignored
- **Problem framing** (Section 8, "Node Problems Solved") honestly acknowledges the 10 failed attempts

---

## Summary

| Severity | Count | Key Themes |
|----------|-------|------------|
| CRITICAL | 3 | Auth/trust model, MCP permission scoping, shell sandboxing |
| HIGH | 5 | Two-language install complexity, offline quality, migration overlap, error handling, testing |
| MEDIUM | 5 | Protocol complexity, DNS assumptions, skill execution model, versioning, offline sync |
| LOW | 5 | Framing, UX polish, license, logging, milestone categorization |

The three CRITICAL issues all relate to security boundaries that must be designed before implementation begins. The spec is strong on vision and architecture but needs hardening on trust boundaries, error paths, and operational details.

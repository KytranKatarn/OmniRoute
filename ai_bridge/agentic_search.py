"""ai_bridge/agentic_search.py — native tool-calling loop for agentic KB retrieval (#3534).

A Department HQ execution primitive. It is invoked by
``tools.department_hq.services.department_dispatcher`` (``request_work``) for
tool-capable agents so an agent can issue its OWN knowledge-base searches
mid-task via Ollama ``/api/chat`` ``tools=[]``, read the results, and refine —
instead of the single-shot, system-injected RAG auto-context.

ADR-013 note: this is NOT a rogue direct-Ollama call. The agent and model are
already DHQ-selected before ``run_tool_loop`` runs, and each tool call is logged
to ``task_execution_log`` by the dispatcher. It sits in the same sanctioned
inference layer as ``ai_bridge.archie_bridge.call_ollama`` (which the dispatcher
also calls directly via ``_execute_llm``).

Phase 1: one read-only tool (``search_knowledge``).
Phase 2: adds ``search_mistakes`` (mistake_learned, 1.3x weight) and
``recall_context`` (vault_note + conversation_memory), a tool-use prompting
preamble, and expands beyond D.A.R.W.I.N. (dispatcher-side). All tools are
read-only and back onto ``services.rag_service.search_knowledge`` (knowledge_type
aware). The loop is bounded (``max_iterations`` + ``timeout``). On any HTTP/parse
error — or when the model emits no tool call — the caller falls back to
single-shot RAG.
"""

import json
import logging
import os
import time

import requests

logger = logging.getLogger("agent_loop")

_MAX_LIMIT = 8


def _kb_tool(name, description):
    """Build an Ollama-native (OpenAI-shape) read-only KB tool schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language search query."},
                    "limit": {"type": "integer", "description": "Max results (default 5, capped at 8)."},
                },
                "required": ["query"],
            },
        },
    }


# Read-only KB tools the agent may call, and the knowledge_type filter each maps
# to in services.rag_service.search_knowledge (None = all types).
TOOLS = [
    _kb_tool(
        "search_knowledge",
        "Search the A.R.C.H.I.E. knowledge base (all types) for facts you do not "
        "already know. Use whenever the question depends on platform-specific detail.",
    ),
    _kb_tool(
        "search_mistakes",
        "Search past mistakes and hard-won lessons (mistake_learned entries). Use to "
        "avoid repeating known errors before proposing an approach or a fix.",
    ),
    _kb_tool(
        "recall_context",
        "Recall prior documentation, decisions (ADRs), and past session context "
        "(vault_note + conversation_memory). Use to ground answers in earlier work.",
    ),
]

_TOOL_KNOWLEDGE_TYPES = {
    "search_knowledge": None,
    "search_mistakes": ["mistake_learned"],
    "recall_context": ["vault_note", "conversation_memory"],
}

# Prepended to the agent's system prompt when the loop runs, so the model knows
# the tools exist and is nudged to use them instead of guessing.
TOOL_PREAMBLE = (
    "You can consult the A.R.C.H.I.E. knowledge base with tools: search_knowledge "
    "(general), search_mistakes (past errors/lessons), recall_context (prior docs "
    "and decisions). When the answer depends on platform-specific facts, CALL a "
    "tool and read the results before answering — do not guess. You may call tools "
    "more than once to refine. When you have enough, answer normally with no tool call."
)

# Models known to emit reliable native tool_calls via Ollama /api/chat.
TOOL_CAPABLE_MODELS = (
    "qwen2.5:7b",
    "qwen2.5:14b",
    "qwen2.5:32b",
    "qwen2.5-coder:7b",
    "mistral:7b",
    "llama3.1",
)


def is_tool_capable_model(model) -> bool:
    """True if the model tag is in the native-tool-calling allow-list."""
    if not model:
        return False
    m = str(model).lower()
    return any(m.startswith(t) or m == t for t in TOOL_CAPABLE_MODELS)


def _execute_kb_tool(name, query, limit=5) -> str:
    """Run one read-only KB search (routed by tool name) and format for the model."""
    try:
        from services.rag_service import search_knowledge as rag_search

        try:
            n = int(limit)
        except (TypeError, ValueError):
            n = 5
        n = max(1, min(n, _MAX_LIMIT))
        knowledge_types = _TOOL_KNOWLEDGE_TYPES.get(name)
        results = rag_search(query or "", limit=n, knowledge_types=knowledge_types)
        if not results:
            return f"No knowledge-base results for: {query!r}"
        blocks = []
        for r in results:
            kid = r.get("id", "?")
            title = r.get("title") or f"KB#{kid}"
            ktype = r.get("knowledge_type") or ""
            rel = r.get("similarity", r.get("score"))
            rel_s = f"{rel:.2f}" if isinstance(rel, (int, float)) else "?"
            content = (r.get("content") or "")[:600]
            tag = f"[{ktype}] " if ktype else ""
            blocks.append(f"{tag}[KB#{kid}] {title} (relevance {rel_s})\n{content}")
        return "\n\n".join(blocks)
    except Exception as exc:
        logger.debug("[agentic_search] %s tool failed: %s", name, exc)
        return f"Knowledge-base search error: {exc}"


# Phase 3 write tool — offered only when the dispatcher passes write_enabled=True
# (flag agentic_tool_write). Writes are quarantined (services.agent_kb_service) —
# the model never controls knowledge_type/source_type/review_status.
STORE_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "store_memory",
        "description": (
            "Save a NEW, durable, reusable fact / lesson / decision you discovered "
            "to the knowledge base for future tasks. Use sparingly — only for "
            "self-contained knowledge worth keeping, not chit-chat. Entries are "
            "reviewed before they become visible to others."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact/lesson, specific and self-contained."},
                "title": {"type": "string", "description": "Short descriptive title."},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags."},
            },
            "required": ["content"],
        },
    },
}


def _execute_store_memory(agent_id, agent_name, content, title=None, tags=None) -> str:
    """Quarantined agent KB write via the sanctioned service. Returns a model-facing string."""
    try:
        from services.agent_kb_service import propose_agent_memory

        res = propose_agent_memory(agent_id, agent_name, content, title=title, tags=tags)
        if res.get("ok"):
            return f"Saved to the knowledge base (pending review) as KB#{res['id']}."
        return f"Not saved: {res.get('reason')}"
    except Exception as exc:
        logger.debug("[agentic_search] store_memory tool failed: %s", exc)
        return f"Knowledge-base write error: {exc}"


def run_tool_loop(
    model,
    system_prompt,
    user_prompt,
    *,
    ollama_url=None,
    agent_name=None,
    agent_id=None,
    capability=None,
    module_id=None,
    max_iterations=3,
    timeout=120,
    write_enabled=False,
):
    """Run a bounded native-tool-calling loop against Ollama ``/api/chat``.

    Returns a dict:
      {success, response, used_tools, tool_calls, tool_queries, iterations,
       error, duration_ms, ollama_url}

    ``tool_queries`` is a list of ``{"tool": <name>, "query": <str>}`` (one per
    call). ``used_tools`` is True only if the model issued >= 1 tool call. The
    dispatcher accepts the result only when ``used_tools and success``; otherwise
    it falls back to the single-shot RAG path. Never raises.
    """
    base = ollama_url or os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
    # OLLAMA_HOST is often set without a scheme (e.g. "host.docker.internal:11434");
    # requests needs an explicit scheme or it raises "No connection adapters".
    if base and not base.startswith(("http://", "https://")):
        base = "http://" + base
    url = f"{base}/api/chat"

    sys_content = f"{TOOL_PREAMBLE}\n\n{system_prompt}" if system_prompt else TOOL_PREAMBLE
    messages = [{"role": "system", "content": sys_content}, {"role": "user", "content": user_prompt}]

    start = time.time()
    tool_queries = []
    tok = {"p": 0, "c": 0}  # summed real token counts across all /api/chat calls (#4230)
    _loop_tools = TOOLS + ([STORE_MEMORY_TOOL] if write_enabled else [])

    def _result(success, response, error=None, iterations=0):
        return {
            "success": success,
            "response": response,
            "used_tools": len(tool_queries) > 0,
            "tool_calls": len(tool_queries),
            "tool_queries": list(tool_queries),
            "iterations": iterations,
            "error": error,
            "duration_ms": int((time.time() - start) * 1000),
            "ollama_url": base,
            # Real Ollama eval counts summed over the loop's /api/chat turns — the
            # dispatcher logs these to task_execution_log (was hardcoded 0, #4230).
            "prompt_tokens": tok["p"],
            "completion_tokens": tok["c"],
        }

    try:
        for iteration in range(max_iterations):
            payload = {"model": model, "messages": messages, "tools": _loop_tools, "stream": False}
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            _j = resp.json() or {}
            tok["p"] += _j.get("prompt_eval_count") or 0
            tok["c"] += _j.get("eval_count") or 0
            msg = _j.get("message", {}) or {}
            calls = msg.get("tool_calls") or []

            if not calls:
                # Model produced a final answer (no further tool use).
                return _result(bool(msg.get("content")), msg.get("content") or "", iterations=iteration + 1)

            # Echo the assistant tool-call message, then run each tool.
            messages.append(msg)
            for call in calls:
                fn = call.get("function", {}) or {}
                tool_name = fn.get("name") or "search_knowledge"
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"query": args}
                if tool_name == "store_memory" and write_enabled:
                    w_content = args.get("content") or ""
                    w_title = args.get("title")
                    w_tags = args.get("tags") if isinstance(args.get("tags"), list) else None
                    tool_output = _execute_store_memory(agent_id, agent_name, w_content, w_title, w_tags)
                    tool_queries.append({"tool": "store_memory", "query": (w_title or w_content[:60])})
                    _label = "store_memory"
                else:
                    if tool_name not in _TOOL_KNOWLEDGE_TYPES:
                        tool_name = "search_knowledge"
                    query = args.get("query") or ""
                    limit = args.get("limit", 5)
                    tool_output = _execute_kb_tool(tool_name, query, limit)
                    tool_queries.append({"tool": tool_name, "query": query})
                    _label = f"{tool_name}({query[:60]!r})"
                messages.append({"role": "tool", "content": tool_output})
                logger.info("[agentic_search] %s %s -> %d chars", agent_name or "?", _label, len(tool_output))

        # Iterations exhausted while still tool-calling: force a final answer
        # with tools disabled so the model must synthesize from what it gathered.
        resp = requests.post(url, json={"model": model, "messages": messages, "stream": False}, timeout=timeout)
        resp.raise_for_status()
        _jf = resp.json() or {}
        tok["p"] += _jf.get("prompt_eval_count") or 0
        tok["c"] += _jf.get("eval_count") or 0
        content = (_jf.get("message", {}) or {}).get("content") or ""
        return _result(bool(content), content, error=None if content else "no final content", iterations=max_iterations)

    except Exception as exc:
        logger.warning(
            "[agentic_search] tool loop failed (%s) — caller falls back to single-shot RAG",
            exc,
        )
        return _result(False, "", error=str(exc))

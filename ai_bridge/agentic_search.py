"""ai_bridge/agentic_search.py — native tool-calling loop for agentic KB retrieval (#3534 Phase 1).

A Department HQ execution primitive. It is invoked by
``tools.department_hq.services.department_dispatcher`` (``request_work``) for
tool-capable agents so an agent can issue its OWN semantic KB searches mid-task
via Ollama ``/api/chat`` ``tools=[]``, read the results, and refine — instead of
the single-shot, system-injected RAG auto-context.

ADR-013 note: this is NOT a rogue direct-Ollama call. The agent and model are
already DHQ-selected before ``run_tool_loop`` runs, and each tool call is logged
to ``task_execution_log`` by the dispatcher. It sits in the same sanctioned
inference layer as ``ai_bridge.archie_bridge.call_ollama`` (which the dispatcher
also calls directly via ``_execute_llm``).

Phase 1 is read-only: one tool, ``search_knowledge``, wrapping
``ai_bridge.semantic_search.search``. The loop is bounded (``max_iterations`` +
``timeout``). On any HTTP/parse error — or when the model emits no tool call —
the caller falls back to the single-shot RAG path.
"""

import json
import logging
import os
import time

import requests

logger = logging.getLogger("agent_loop")

# Ollama-native tool schema (OpenAI function-calling shape). Read-only.
SEARCH_KNOWLEDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "search_knowledge",
        "description": (
            "Search the A.R.C.H.I.E. knowledge base (docs, past decisions, "
            "mistakes, code) for facts you do not already know. Call this before "
            "answering whenever the question depends on platform-specific details. "
            "Returns the most relevant entries with a relevance score."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language search query for the knowledge base.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5, capped at 8).",
                },
            },
            "required": ["query"],
        },
    },
}

# Models known to emit reliable native tool_calls via Ollama /api/chat.
# Conservative allow-list — Phase 1 only needs qwen2.5:7b (D.A.R.W.I.N.).
TOOL_CAPABLE_MODELS = (
    "qwen2.5:7b",
    "qwen2.5:14b",
    "qwen2.5:32b",
    "qwen2.5-coder:7b",
    "mistral:7b",
    "llama3.1",
)

_MAX_LIMIT = 8


def is_tool_capable_model(model) -> bool:
    """True if the model tag is in the native-tool-calling allow-list."""
    if not model:
        return False
    m = str(model).lower()
    return any(m.startswith(t) or m == t for t in TOOL_CAPABLE_MODELS)


def _execute_search_knowledge(query, limit=5) -> str:
    """Run one semantic KB search and format the results for the model."""
    try:
        from ai_bridge.semantic_search import search as semantic_search

        try:
            n = int(limit)
        except (TypeError, ValueError):
            n = 5
        n = max(1, min(n, _MAX_LIMIT))
        results = semantic_search(query or "", limit=n)
        if not results:
            return f"No knowledge-base results for: {query!r}"
        blocks = []
        for r in results:
            score = f"{r.score:.2f}" if getattr(r, "score", None) is not None else "?"
            title = getattr(r, "title", None) or f"KB#{getattr(r, 'id', '?')}"
            content = (getattr(r, "content", None) or "")[:600]
            blocks.append(f"[KB#{getattr(r, 'id', '?')}] {title} (relevance {score})\n{content}")
        return "\n\n".join(blocks)
    except Exception as exc:
        logger.debug("[agentic_search] search_knowledge tool failed: %s", exc)
        return f"Knowledge-base search error: {exc}"


def run_tool_loop(
    model,
    system_prompt,
    user_prompt,
    *,
    ollama_url=None,
    agent_name=None,
    capability=None,
    module_id=None,
    max_iterations=3,
    timeout=120,
):
    """Run a bounded native-tool-calling loop against Ollama ``/api/chat``.

    Returns a dict:
      {success, response, used_tools, tool_calls, tool_queries, iterations,
       error, duration_ms, ollama_url}

    ``used_tools`` is True only if the model issued >= 1 search_knowledge call.
    The dispatcher should accept the result only when ``used_tools and success``;
    otherwise it falls back to the single-shot RAG path. Never raises.
    """
    base = ollama_url or os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
    # OLLAMA_HOST is often set without a scheme (e.g. "host.docker.internal:11434");
    # requests needs an explicit scheme or it raises "No connection adapters".
    if base and not base.startswith(("http://", "https://")):
        base = "http://" + base
    url = f"{base}/api/chat"
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    start = time.time()
    tool_queries = []

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
        }

    try:
        for iteration in range(max_iterations):
            payload = {
                "model": model,
                "messages": messages,
                "tools": [SEARCH_KNOWLEDGE_TOOL],
                "stream": False,
            }
            resp = requests.post(url, json=payload, timeout=timeout)
            resp.raise_for_status()
            msg = (resp.json() or {}).get("message", {}) or {}
            calls = msg.get("tool_calls") or []

            if not calls:
                # Model produced a final answer (no further tool use).
                return _result(
                    bool(msg.get("content")),
                    msg.get("content") or "",
                    iterations=iteration + 1,
                )

            # Echo the assistant tool-call message, then run each tool.
            messages.append(msg)
            for call in calls:
                fn = call.get("function", {}) or {}
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {"query": args}
                query = args.get("query") or ""
                limit = args.get("limit", 5)
                tool_queries.append(query)
                tool_output = _execute_search_knowledge(query, limit)
                messages.append({"role": "tool", "content": tool_output})
                logger.info(
                    "[agentic_search] %s search_knowledge(%r) -> %d chars",
                    agent_name or "?",
                    query[:80],
                    len(tool_output),
                )

        # Iterations exhausted while still tool-calling: force a final answer
        # with tools disabled so the model must synthesize from what it gathered.
        resp = requests.post(
            url,
            json={"model": model, "messages": messages, "stream": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        content = ((resp.json() or {}).get("message", {}) or {}).get("content") or ""
        return _result(bool(content), content, error=None if content else "no final content", iterations=max_iterations)

    except Exception as exc:
        logger.warning(
            "[agentic_search] tool loop failed (%s) — caller falls back to single-shot RAG",
            exc,
        )
        return _result(False, "", error=str(exc))

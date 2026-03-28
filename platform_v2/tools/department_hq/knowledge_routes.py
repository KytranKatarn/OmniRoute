"""Knowledge RAG routes for Department HQ.

Provides API endpoints for semantic search, RAG context injection,
and mistake lookup. Used by CLI, API gateway, and Skills Lab.
"""

from flask import request, jsonify


def register_knowledge_routes(bp, admin_required):
    """Register knowledge/RAG API routes on the Department HQ blueprint."""

    @bp.route("/api/knowledge/search")
    @admin_required
    def knowledge_search():
        """Search the knowledge base with RAG (semantic + text fallback).

        Query params:
            q: Search query (required)
            limit: Max results (default 10, max 50)
            types: Comma-separated knowledge_types filter
            min_importance: Minimum importance_score (default 0.0)
        """
        from services.rag_service import search_knowledge

        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"error": "q parameter required"}), 400

        limit = min(int(request.args.get("limit", 10)), 50)
        types = (
            [t.strip() for t in request.args.get("types", "").split(",") if t.strip()]
            if request.args.get("types")
            else None
        )
        min_importance = float(request.args.get("min_importance", 0.0))

        results = search_knowledge(
            query,
            limit=limit,
            knowledge_types=types,
            min_importance=min_importance,
        )
        return jsonify({"query": query, "results": results, "count": len(results)})

    @bp.route("/api/knowledge/context")
    @admin_required
    def knowledge_context():
        """Get RAG context formatted for prompt injection.

        Query params:
            q: Search query (required)
            max_tokens: Max token budget (default 2000)
            types: Comma-separated knowledge_types filter
        """
        from services.rag_service import get_rag_context

        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"error": "q parameter required"}), 400

        max_tokens = int(request.args.get("max_tokens", 2000))
        types = (
            [t.strip() for t in request.args.get("types", "").split(",") if t.strip()]
            if request.args.get("types")
            else None
        )

        context = get_rag_context(query, max_tokens=max_tokens, knowledge_types=types)
        return jsonify({"query": query, "context": context, "chars": len(context)})

    @bp.route("/api/knowledge/mistakes")
    @admin_required
    def knowledge_mistakes():
        """Search mistake_learned entries specifically.

        Query params:
            q: Search query (required)
            limit: Max results (default 5)
        """
        from services.rag_service import search_mistakes

        query = request.args.get("q", "").strip()
        if not query:
            return jsonify({"error": "q parameter required"}), 400

        limit = min(int(request.args.get("limit", 5)), 20)
        results = search_mistakes(query, limit=limit)
        return jsonify({"query": query, "results": results, "count": len(results)})

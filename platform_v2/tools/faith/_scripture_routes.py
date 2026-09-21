"""Faith scripture routes — multi-tradition reader and search endpoints."""

from __future__ import annotations

from flask import Response, jsonify, request
from flask_login import login_required

from . import faith_bp, routes as _R
from ._constants import JsonDict, JsonResponse, MAX_SEARCH_LIMIT


@faith_bp.route("/api/faith/bible/meta")
@login_required
def bible_meta() -> Response:
    bible = _R._load_web_bible()
    return jsonify(
        {
            "success": True,
            "translation": {
                "id": "web",
                "name": "World English Bible Classic",
                "storage": "local_saved_copy",
                "local_path": "platform_v2/tools/faith/data/web_vpl.txt",
                "source": "eBible.org",
                "license": "Public domain",
                "source_url": "https://ebible.org/find/details.php?id=eng-web",
                "verse_count": len(bible["verses"]),
            },
            "books": [_R._serialize_book(book) for book in bible["books"]],
            "encyclopedia_sources": _R._load_encyclopedia_entries(),
        }
    )


@faith_bp.route("/api/faith/bible/passage")
@login_required
def bible_passage() -> JsonResponse:
    code = _R._lookup_book_code(request.args.get("book", "GEN"))
    if not code:
        return jsonify({"success": False, "error": "unknown book"}), 404
    try:
        chapter = int(request.args.get("chapter", "1"))
    except ValueError:
        return jsonify({"success": False, "error": "chapter must be a number"}), 400

    verses = [v for v in _R._load_web_bible()["verses"] if v["book"] == code and v["chapter"] == chapter]
    if not verses:
        return jsonify({"success": False, "error": "passage not found"}), 404
    return jsonify(
        {
            "success": True,
            "translation": "World English Bible Classic",
            "book": code,
            "book_name": verses[0]["book_name"],
            "chapter": chapter,
            "reference": f"{verses[0]['book_name']} {chapter}",
            "verses": verses,
        }
    )


@faith_bp.route("/api/faith/bible/search")
@login_required
def bible_search() -> JsonResponse:
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    limit = _R._clamped_search_limit(25)

    q = query.lower()
    results: list[JsonDict] = []
    for verse in _R._load_web_bible()["verses"]:
        haystack = f"{verse['reference']} {verse['text']}".lower()
        if q in haystack:
            results.append(verse)
            if len(results) >= limit:
                break
    return jsonify({"success": True, "query": query, "results": results, "count": len(results)})


@faith_bp.route("/api/faith/scriptures/meta")
@login_required
def scriptures_meta() -> Response:
    corpus = _R._load_scripture_corpus()
    return jsonify(
        {
            "success": True,
            "storage": "local_saved_copies",
            "collections": corpus["collections"],
            "passage_count": len(corpus["passages"]),
            "toc": _R._scripture_toc(),
        }
    )


@faith_bp.route("/api/faith/scriptures/passage")
@login_required
def scriptures_passage() -> JsonResponse:
    collection = (request.args.get("collection") or "").strip()
    if not _R._collection_meta(collection):
        return jsonify({"success": False, "error": "unknown collection"}), 404
    toc = _R._scripture_toc()
    entry = toc.get(collection)
    book_requested = (request.args.get("book") or "").strip()
    chapter_requested = (request.args.get("chapter") or "").strip()
    if not book_requested:
        book_requested = entry["books"][0]["key"] if entry and entry["books"] else ""
    book_node = (
        next((book for book in entry["books"] if book["key"] == book_requested), None)
        if entry and book_requested
        else None
    )
    if book_node is None:
        return jsonify({"success": False, "error": "unknown book for collection"}), 404
    if not chapter_requested:
        chapter_requested = book_node["chapters"][0]["key"] if book_node["chapters"] else ""
    chapter_node = (
        next((chapter for chapter in book_node["chapters"] if chapter["key"] == chapter_requested), None)
        if chapter_requested
        else None
    )
    if chapter_node is None:
        return jsonify({"success": False, "error": "unknown chapter for book"}), 404

    passages = [
        _R._public_scripture_record(unit)
        for unit in _R._reader_units()
        if unit["collection"] == collection
        and unit.get("book") == book_requested
        and unit.get("chapter") == chapter_requested
    ]
    if not passages:
        return jsonify({"success": False, "error": "passage not found"}), 404
    if collection in ("web", "jps1917"):
        for passage in passages:
            _ref, sep, tail = passage["reference"].rpartition(":")
            if sep and tail.isdigit():
                passage["verse"] = int(tail)
    return jsonify(
        {
            "success": True,
            "collection": entry["collection"],
            "book": book_node["name"] or book_node["key"],
            "chapter": chapter_node["name"] or chapter_node["key"],
            "passages": passages,
            "count": len(passages),
        }
    )


@faith_bp.route("/api/faith/scriptures/search")
@login_required
def scriptures_search() -> JsonResponse:
    query = (request.args.get("q") or "").strip()
    collection = (request.args.get("collection") or "all").strip()
    if not query:
        return jsonify({"success": False, "error": "query required"}), 400
    limit = _R._clamped_search_limit(40)

    q = query.lower()
    results: list[JsonDict] = []
    for passage in _R._load_scripture_corpus()["passages"]:
        if collection != "all" and passage["collection"] != collection:
            continue
        if q in passage["_search"]:
            results.append(_R._public_scripture_record(passage))
            if len(results) >= limit:
                break
    return jsonify(
        {
            "success": True,
            "query": query,
            "collection": collection,
            "results": results,
            "count": len(results),
        }
    )


@faith_bp.route("/api/faith/encyclopedia/search")
@login_required
def encyclopedia_search() -> Response:
    query = (request.args.get("q") or "").strip().lower()
    limit = _R._clamped_search_limit(MAX_SEARCH_LIMIT)
    entries = _R._load_encyclopedia_entries()
    if query:
        entries = [
            entry
            for entry in entries
            if query
            in " ".join(
                [
                    entry.get("title", ""),
                    entry.get("category", ""),
                    entry.get("summary", ""),
                    " ".join(entry.get("tags", [])),
                ]
            ).lower()
        ]
    entries = entries[:limit]
    return jsonify({"success": True, "query": query, "entries": entries, "count": len(entries)})
"""Opt-in history research preview; no inference, ingestion, or mutations."""

from flask import Blueprint, abort, current_app, jsonify, render_template, request

from .history_data import frame_for_year, load_catalog, matching_events, safe_source_url

history_bp = Blueprint("history", __name__)


@history_bp.before_request
def preview_gate():
    if current_app.config.get("WTF_HISTORY_ATLAS_ENABLED") is not True:
        abort(404)


@history_bp.after_request
def research_headers(response):
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Cache-Control"] = "no-store"
    return response


def catalog():
    try:
        return load_catalog()
    except (OSError, ValueError, KeyError, TypeError):
        current_app.logger.error("History research catalogue unavailable or invalid")
        abort(503, description="History research catalogue is unavailable. Please try again later.")


def filters():
    query = request.args.get("q", "").strip()
    if len(query) > 120 or len(request.args.get("region", "")) > 80 or len(request.args.get("theme", "")) > 100:
        abort(400, description="Search filter is too long.")
    if len(request.args.get("province", "")) > 80:
        abort(400, description="Province filter is too long.")
    raw_year = request.args.get("year", "").strip()
    year = None
    if raw_year:
        try:
            year = int(raw_year)
        except ValueError:
            abort(400, description="Year must be a whole number.")
        if not -20000 <= year <= 2100:
            abort(400, description="Year is outside the supported research range.")
    undated = request.args.get("undated", "") == "1"
    if undated and year is not None:
        abort(400, description="Choose a year or undated events, not both.")
    return dict(
        query=query,
        region=request.args.get("region", ""),
        theme=request.args.get("theme", ""),
        province=request.args.get("province", ""),
        year=year,
        undated=undated,
    )


def page_number():
    try:
        page = int(request.args.get("page", "1"))
    except ValueError:
        abort(400, description="Page must be a whole number.")
    if not 1 <= page <= 1000:
        abort(400, description="Page is out of range.")
    return page


@history_bp.get("/history")
@history_bp.get("/history/atlas")
def atlas():
    data = catalog()
    selected = filters()
    matches = matching_events(data, **selected)
    page = page_number()
    return render_template(
        "history_atlas.html",
        events=matches[(page - 1) * 40 : page * 40],
        total=len(matches),
        page=page,
        selected=selected,
        maps=data["maps"],
        manifest=data["manifest"],
        regions=sorted({r for e in data["events"] for r in e.get("regions", [])}),
        provinces=sorted({e["province_context"] for e in data["events"] if e.get("province_context")}),
        themes=sorted({t for e in data["events"] for t in e.get("themes", [])}),
    )


@history_bp.get("/history/events/<event_id>")
def event_detail(event_id):
    data = catalog()
    event = next((e for e in data["events"] if e["id"] == event_id), None)
    if event is None:
        abort(404)
    sources = [
        dict(data["sources"][sid], safe_url=safe_source_url(data["sources"][sid].get("url")))
        for sid in event["source_ids"]
    ]
    return render_template(
        "history_event.html", event=event, sources=sources, snapshot=frame_for_year(data, event.get("start_year"))
    )


@history_bp.get("/history/movements")
def movements():
    data = catalog()
    return render_template("history_movements.html", movements=data["movements"])


@history_bp.get("/api/history/events")
def events_api():
    data = catalog()
    matches = matching_events(data, **filters())
    page = page_number()
    return jsonify(
        schema_version=1,
        research_only=True,
        total=len(matches),
        page=page,
        page_size=40,
        events=matches[(page - 1) * 40 : page * 40],
    )

"""Browser-ready media paths. Dependency-free so any service (and its tests) can import it without the database."""


def normalize_static_path(p):
    """Browser-ready path for a stored media path.

    The thumbnail writer stores a bare ``media/agents/...`` (relative to the static root) while file_path is
    ``/static/media/...``. A bare path in an <img src> resolves against the page URL and never loads, which is how
    every newly generated agent image showed as a broken tile. Absolute URLs and /static paths pass through.
    """
    if not p or not isinstance(p, str):
        return p
    if p.startswith(("http://", "https://", "data:", "/")):
        return p
    if p.startswith("static/"):
        return "/" + p
    return "/static/" + p

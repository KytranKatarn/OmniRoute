"""Every operator-facing provider route must carry an auth decorator.

`GET /api/providers/<key>/switch-history` shipped without `@auth_decorator` (PR #3659): every
sibling under /api/providers and /api/cloud-providers had one, so anyone able to reach the hub could
read who flipped routing on for a paid provider and when. The scan is by AST so a new sibling that
forgets the decorator fails here instead of in a review.

Node-facing routes in the same file (/api/fleet/*, certificate download, registration) use a node
API key instead and are deliberately out of scope.
"""

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "tools" / "department_hq" / "fleet_provider_routes.py"
AUTH = {"auth_decorator", "login_required"}
SCOPES = ("/api/providers", "/api/cloud-providers")


def _routes(src_text=None):
    tree = ast.parse(src_text if src_text is not None else SRC.read_text())
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.FunctionDef):
            continue
        paths, decos = [], []
        for d in n.decorator_list:
            if isinstance(d, ast.Call) and ast.unparse(d.func).endswith(".route"):
                paths.append(d.args[0].value)
            else:
                decos.append(ast.unparse(d.func if isinstance(d, ast.Call) else d))
        if paths:
            out.append((n.name, paths, decos))
    return out


def _unauthenticated(src_text=None):
    return [
        (name, p)
        for name, paths, decos in _routes(src_text)
        for p in paths
        if p.startswith(SCOPES) and not (AUTH & set(decos))
    ]


def test_every_provider_route_is_authenticated():
    assert _unauthenticated() == []


def test_the_scan_actually_sees_the_provider_routes():
    """A scan that matches nothing passes — pin that it finds the routes it is meant to guard."""
    seen = [p for _, paths, _ in _routes() for p in paths if p.startswith(SCOPES)]
    assert len(seen) >= 10 and "/api/providers/<provider_key>/switch-history" in seen


def test_the_scan_catches_a_missing_decorator():
    broken = SRC.read_text().replace(
        '    @bp.route("/api/providers/<provider_key>/switch-history")\n    @auth_decorator\n',
        '    @bp.route("/api/providers/<provider_key>/switch-history")\n',
        1,
    )
    assert broken != SRC.read_text()
    assert _unauthenticated(broken) == [("api_provider_switch_history", "/api/providers/<provider_key>/switch-history")]

"""Guard: WTF_TECH_URL must never reach the browser (KB #267314, task #5795).

`WTF_TECH_URL` is an INTERNAL mesh address (`http://wtf-tech:8104`). The recorded
rule is: never pass it to browser JavaScript — add a server-side proxy route
first. `consumer/routes.py` already does exactly that, via `_proxy_tech`.

The setup for violating it was live anyway. `index()` and `article()` each read
the env var and passed `wtf_tech_url=` into `render_template`, so it sat in the
Jinja context of the site's two busiest pages. **No template ever used it** —
measured 2026-08-19, zero hits across every .html and .js in the repo — so
nothing leaked. But a template author writing `<script>const T="{{ wtf_tech_url }}"`
would have had it silently work, which is how a latent trap becomes an incident.

Removed rather than documented: a variable that is not in scope cannot be
interpolated by accident.

Both halves are asserted, because they fail independently:
  * no `render_template(...)` may pass a wtf_tech_url kwarg  (the supply)
  * no template or client JS may reference it                (the demand)

Parsed with `ast`, not grepped. A substring scan over this file matches its own
docstring and fails on a correct tree — that exact self-match has burned this
codebase repeatedly.
"""
import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTES = ROOT / "consumer" / "routes.py"

_TAINTED = "wtf_tech_url"
_ENV_KEY = "WTF_TECH_URL"


def _render_template_calls(tree):
    """Every `render_template(...)` Call node, however it is referenced."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name == "render_template":
            yield node


def test_no_render_template_passes_the_internal_tech_url():
    """The supply side. Asserted over the AST so a kwarg cannot hide behind
    formatting, a rename of the import, or a `flask.render_template` prefix."""
    tree = ast.parse(ROUTES.read_text())
    offenders = []
    for call in _render_template_calls(tree):
        for kw in call.keywords:
            if kw.arg and _TAINTED in kw.arg.lower():
                offenders.append((call.lineno, kw.arg))
    assert not offenders, (
        f"render_template puts the internal tech URL in the Jinja context at {offenders} — "
        "KB #267314: proxy it server-side (see _proxy_tech), never hand it to the browser"
    )


def test_no_template_or_client_js_references_it():
    """The demand side. Even with the kwarg gone, a template referencing the name
    would render an empty string and fail silently — worth catching as a signal
    that someone expected it to be there."""
    offenders = []
    for pat in ("*.html", "*.js"):
        for f in ROOT.rglob(pat):
            if any(p in f.parts for p in ("node_modules", ".git", "__pycache__")):
                continue
            try:
                body = f.read_text(errors="ignore")
            except OSError:
                continue
            if _TAINTED in body or _ENV_KEY in body:
                offenders.append(str(f.relative_to(ROOT)))
    assert not offenders, (
        f"these browser-served files reference the internal tech URL: {offenders} — "
        "KB #267314: add a server-side proxy route instead"
    )


def test_the_server_to_server_call_site_is_untouched():
    """Negative half. Removing the dead context must NOT remove the legitimate
    backend use — `/score` is fetched server-side, which is the correct pattern
    and the thing a careless 'remove all references' sweep would break."""
    src = ROUTES.read_text()
    assert _ENV_KEY in src, "the server-side proxy must still read WTF_TECH_URL"
    tree = ast.parse(src)
    reads = [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and n.value == _ENV_KEY
    ]
    assert reads, "expected at least one os.environ.get('WTF_TECH_URL') call site"


def test_env_default_is_the_mesh_name_not_the_public_hostname():
    """Every default must be the internal service name. A public-hostname default
    routes inter-container traffic through the CDN (60s cap) whenever the env var
    is unset — the mesh mandate, and the thing #5794 fixed at four call sites."""
    tree = ast.parse(ROUTES.read_text())
    bad = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
            continue
        args = node.args
        if len(args) == 2 and isinstance(args[0], ast.Constant) and args[0].value == _ENV_KEY:
            default = args[1]
            if isinstance(default, ast.Constant) and "what-the-fact" in str(default.value):
                bad.append((node.lineno, default.value))
    assert not bad, f"public-hostname default for {_ENV_KEY} at {bad} — use http://wtf-tech:8104"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))

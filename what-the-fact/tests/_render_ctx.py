"""Inputs the page templates read that a route never passes explicitly.

`request` is a Flask global, so a template may use `request.args` and the route passes nothing for it.
Rendering a template through a bare Jinja Environment has no such global, which made every test that
renders owners.html fail with "'request' is undefined" once the template started reading it. Give those
environments a stand-in with the same read-only surface the templates use.
"""
from types import SimpleNamespace


class _Args(dict):
    """Behaves like request.args for reads: .get(key, default) with no query string."""


def fake_request(**args):
    return SimpleNamespace(args=_Args(args), path="/", method="GET")

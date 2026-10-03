"""Every consumer template must COMPILE. A stray {% endif %} or </div> pair only fails when
Jinja parses the file — i.e. as a 500 on the first request after a deploy — and a test that
renders just one block of a template cannot see it (#3595 left a duplicate closing pair in
article.html that passed its own block test and was caught afterwards in #3603).

Compile-only: no context needed, so it covers every template, including ones whose route
needs a database. Plain Python — `python3 tests/test_templates_compile.py` — and pytest-compatible.
"""
import pathlib
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError

TPL = pathlib.Path(__file__).resolve().parents[1] / "consumer" / "templates"


def _env():
    return Environment(loader=FileSystemLoader(str(TPL)))


def compile_failures(env=None, root=TPL):
    env = env or _env()
    bad = []
    for p in sorted(root.rglob("*.html")):
        name = str(p.relative_to(root))
        try:
            env.get_template(name)
        except TemplateSyntaxError as e:
            bad.append("%s:%s %s" % (name, e.lineno, e.message))
    return bad


def test_every_template_compiles():
    assert len(list(TPL.rglob("*.html"))) > 40          # the glob found the templates
    assert compile_failures() == []


def test_guard_catches_a_duplicated_closing_pair():
    # Reintroduce the exact #3595 defect in a COPY and prove the guard fails on it.
    import tempfile, shutil
    with tempfile.TemporaryDirectory() as d:
        root = pathlib.Path(d)
        (root / "ok.html").write_text("{% if x %}<div>a</div>{% endif %}")
        (root / "dup.html").write_text("{% if x %}<div>a</div>{% endif %}\n  </div>\n  {% endif %}\n")
        bad = compile_failures(Environment(loader=FileSystemLoader(str(root))), root)
        assert len(bad) == 1 and bad[0].startswith("dup.html")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)

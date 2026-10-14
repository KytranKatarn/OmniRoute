"""/weather/city/<name>: the Temperature and Feels-like tiles must not print the raw entity `&deg;C` (found live 2026-10-14: "12.3&deg;C").

The tiles passed the STRING "&deg;C" into the measurement() macro. Jinja auto-escaping turns an entity inside a string argument into the literal text
`&amp;deg;`, so the page shows the entity source. The real `°` character is not touched by escaping. The macro is rendered for real with autoescape on,
including a control that reproduces the bug.
"""
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

T = Path(__file__).resolve().parents[1] / "consumer" / "templates"
SRC = (T / "weather_city.html").read_text(encoding="utf-8")


def _render(call):
    env = Environment(loader=FileSystemLoader(str(T)), autoescape=select_autoescape(["html"]))
    return env.from_string('{% from "_archetypes.html" import measurement %}' + call).render()


def test_control_an_entity_string_argument_is_double_escaped():
    out = _render('{{ measurement(12.3, "&deg;C") }}')
    assert "&amp;deg;C" in out, "the control must reproduce the bug"


def test_the_real_degree_sign_renders_cleanly():
    out = _render('{{ measurement(12.3, "°C") }}')
    assert "12.3°C" in out and "&amp;" not in out


def test_the_city_template_passes_no_entity_string_into_measurement():
    calls = re.findall(r"measurement\(([^)]*)\)", SRC)
    assert calls, "measurement() calls not found"
    bad = [c for c in calls if re.search(r"&[a-z]+;", c)]
    assert not bad, f"an entity string is passed into measurement(): {bad}"


def test_temperature_and_feels_like_tiles_use_the_degree_sign():
    assert 'measurement(city.temp, "°C")' in SRC and 'measurement(city.humidex, "°C")' in SRC

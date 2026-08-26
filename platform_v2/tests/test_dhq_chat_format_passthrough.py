"""`format` passthrough on /api/internal/dhq/chat (#6038).

Without this the hub branch of the engine's build planner was UNCONSTRAINED: with a
source file injected into the prompt (#380 Phase 2b) the model emitted Python in a
```python fence instead of the JSON op array. Measured live 2026-08-26.

⚠️ `format: "json"` and `format: {schema}` are NOT interchangeable. Bare "json"
constrains only to *valid JSON*, which for an array-shaped contract routinely returns
an OBJECT the array parser rejects — that is precisely why archie-code carries
OPS_SCHEMA. A schema constrains the SHAPE.

The schema rides the EXISTING `json_mode` parameter: a non-empty dict is truthy, so it
flows through all ~34 pass-through sites unchanged and only two leaf sites read its
value. That is why this is additive rather than a 34-site refactor.
"""

import pytest

OPS_SCHEMA = {"type": "array", "items": {"type": "object"}}


class _Result:
    success = True
    response = "ok"
    agent_name = "F.O.R.G.E."
    model_used = "qwen2.5-coder:7b"


def _patch_dispatch(monkeypatch):
    seen = {}
    import tools.department_hq.services.department_dispatcher as dd

    def fake_dispatch(**kwargs):
        seen.update(kwargs)
        return _Result()

    monkeypatch.setattr(dd, "dispatch", fake_dispatch)
    return seen


def _post(client, body):
    return client.post("/api/internal/dhq/chat", json=body, headers={"Authorization": "Bearer k"})


class TestSchemaReachesDispatch:
    def test_schema_object_is_passed_through_verbatim(self, client, monkeypatch):
        seen = _patch_dispatch(monkeypatch)
        monkeypatch.setenv("INTERNAL_API_KEY", "k")
        r = _post(client, {"prompt": "plan it", "format": OPS_SCHEMA})
        assert r.status_code == 200
        assert seen["json_mode"] == OPS_SCHEMA, "the schema itself must reach dispatch, not a bool"

    def test_a_schema_is_truthy_so_every_passthrough_site_still_fires(self, client, monkeypatch):
        """The whole design rests on this — if it were falsy, json handling would silently skip."""
        seen = _patch_dispatch(monkeypatch)
        monkeypatch.setenv("INTERNAL_API_KEY", "k")
        _post(client, {"prompt": "p", "format": OPS_SCHEMA})
        assert bool(seen["json_mode"]) is True

    def test_bare_json_string_still_means_true(self, client, monkeypatch):
        seen = _patch_dispatch(monkeypatch)
        monkeypatch.setenv("INTERNAL_API_KEY", "k")
        assert _post(client, {"prompt": "p", "format": "json"}).status_code == 200
        assert seen["json_mode"] is True

    @pytest.mark.parametrize("raw", ["JSON", " json ", "Json"])
    def test_case_and_space_tolerant(self, client, monkeypatch, raw):
        seen = _patch_dispatch(monkeypatch)
        monkeypatch.setenv("INTERNAL_API_KEY", "k")
        assert _post(client, {"prompt": "p", "format": raw}).status_code == 200
        assert seen["json_mode"] is True


class TestBackwardCompatibility:
    """⚠️ Every existing caller omits `format`. None may change behaviour."""

    def test_no_format_means_json_mode_false(self, client, monkeypatch):
        seen = _patch_dispatch(monkeypatch)
        monkeypatch.setenv("INTERNAL_API_KEY", "k")
        assert _post(client, {"prompt": "hi"}).status_code == 200
        assert seen["json_mode"] is False

    @pytest.mark.parametrize("empty", [None, "", {}])
    def test_explicitly_empty_format_is_also_false(self, client, monkeypatch, empty):
        seen = _patch_dispatch(monkeypatch)
        monkeypatch.setenv("INTERNAL_API_KEY", "k")
        assert _post(client, {"prompt": "hi", "format": empty}).status_code == 200
        assert seen["json_mode"] is False

    def test_cockpit_defaults_are_untouched_by_this_change(self, client, monkeypatch):
        seen = _patch_dispatch(monkeypatch)
        monkeypatch.setenv("INTERNAL_API_KEY", "k")
        _post(client, {"prompt": "hi"})
        assert seen["prefer_agent"] == "A.R.C.H.I.E."
        assert seen["priority"] == "high"
        assert seen["local_only"] is True


class TestFailsLoud:
    """A caller that asked for structure and got free text cannot tell the difference."""

    @pytest.mark.parametrize("bad", ["yaml", "xml", 42, ["not-an-object"]])
    def test_bad_format_rejected(self, client, monkeypatch, bad):
        _patch_dispatch(monkeypatch)
        monkeypatch.setenv("INTERNAL_API_KEY", "k")
        r = _post(client, {"prompt": "p", "format": bad})
        assert r.status_code == 400
        assert "format" in (r.get_json() or {}).get("error", "")

    def test_a_bad_format_never_reaches_dispatch(self, client, monkeypatch):
        seen = _patch_dispatch(monkeypatch)
        monkeypatch.setenv("INTERNAL_API_KEY", "k")
        _post(client, {"prompt": "p", "format": "yaml"})
        assert seen == {}, "must be rejected BEFORE any dispatch is attempted"

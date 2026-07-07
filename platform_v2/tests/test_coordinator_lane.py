import services.coordinator_lane as cl


def setup_function(_):
    cl._reset_cache()


def test_default_when_key_absent(monkeypatch):
    # No DB row → the hard default
    monkeypatch.setattr(cl, "_read_setting", lambda key, default: default)
    assert cl.get_coordinator_model() == "qwen25-classify"


def test_returns_configured_value(monkeypatch):
    monkeypatch.setattr(
        cl,
        "_read_setting",
        lambda key, default: "phi4-mini" if key == "dispatch:coordinator_model" else default,
    )
    cl._reset_cache()
    assert cl.get_coordinator_model() == "phi4-mini"


def test_get_coordinator_model_strips_whitespace(monkeypatch):
    monkeypatch.setattr(cl, "_read_setting", lambda key, default: "  qwen25-classify  ")
    cl._reset_cache()
    assert cl.get_coordinator_model() == "qwen25-classify"


def test_enabled_default_true(monkeypatch):
    monkeypatch.setattr(cl, "_read_setting", lambda key, default: default)
    cl._reset_cache()
    assert cl.coordinator_lane_enabled() is True


def test_enabled_false_when_set(monkeypatch):
    monkeypatch.setattr(
        cl,
        "_read_setting",
        lambda key, default: "false" if key == "dispatch:coordinator_lane_enabled" else default,
    )
    cl._reset_cache()
    assert cl.coordinator_lane_enabled() is False


def test_read_setting_fail_open_on_db_error(monkeypatch):
    # A DB error inside get_db_cursor must fall open to the in-code default, not raise.
    def _boom(*args, **kwargs):
        raise RuntimeError("db is down")

    monkeypatch.setattr("database.get_db_cursor", _boom)
    assert cl._read_setting("dispatch:coordinator_model", "qwen25-classify") == "qwen25-classify"


class _FakeResult:
    success = True
    response = "{}"


def test_coordinator_dispatch_forces_model_and_agent(monkeypatch):
    cl._reset_cache()
    monkeypatch.setattr(cl, "get_coordinator_model", lambda: "qwen25-classify")
    monkeypatch.setattr(cl, "coordinator_lane_enabled", lambda: True)
    seen = {}

    def fake_dispatch(capability, prompt, **kwargs):
        seen.update(capability=capability, **kwargs)
        return _FakeResult()

    monkeypatch.setattr(cl, "_dispatch", lambda: fake_dispatch)
    cl.coordinator_dispatch("classify", "hi", module_id="intent_parser", json_mode=True)
    assert seen["capability"] == "classify"
    assert seen["model_override"] == "qwen25-classify"
    assert seen["prefer_agent"] == "I.R.I.S."
    assert seen["json_mode"] is True


def test_coordinator_dispatch_disabled_is_plain(monkeypatch):
    cl._reset_cache()
    monkeypatch.setattr(cl, "coordinator_lane_enabled", lambda: False)
    seen = {}

    def fake_dispatch(capability, prompt, **kwargs):
        seen.update(capability=capability, **kwargs)
        return _FakeResult()

    monkeypatch.setattr(cl, "_dispatch", lambda: fake_dispatch)
    cl.coordinator_dispatch("classify", "hi")
    assert "model_override" not in seen  # plain routing when disabled
    assert "prefer_agent" not in seen  # disabled branch fully pinned


def test_coordinator_dispatch_explicit_override_wins(monkeypatch):
    cl._reset_cache()
    monkeypatch.setattr(cl, "get_coordinator_model", lambda: "qwen25-classify")
    monkeypatch.setattr(cl, "coordinator_lane_enabled", lambda: True)
    seen = {}

    def fake_dispatch(capability, prompt, **kwargs):
        seen.update(capability=capability, **kwargs)
        return _FakeResult()

    monkeypatch.setattr(cl, "_dispatch", lambda: fake_dispatch)
    cl.coordinator_dispatch("classify", "hi", model_override="custom-model")
    # setdefault must NOT clobber an explicit caller value.
    assert seen["model_override"] == "custom-model"

"""DR red-alert banner — the signal behind it.

The header shows RED ALERT · STARBASE LOST COMMUNICATION when the platform is being
served by the boston-2 standby instead of the hub. That decision reduces to one env
read, so this pins the read: truthy spellings raise the alarm, and EVERY other input
degrades to hub-normal.

The asymmetry is the point. A missed red alert during a real failover is bad; a red
alert painted across a healthy hub every time someone sets the A.R.M.A.D.A. mobility
profile would train everyone to ignore the light, which is worse and permanent.
"""

import pytest

from services.dr_posture_monitor import is_dr_active


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Never inherit the ambient value — the hub sets none, but CI might."""
    monkeypatch.delenv("ARCHIE_DR_MODE", raising=False)


class TestDrActiveTrue:
    def test_compose_value_one_activates(self, monkeypatch):
        # This is the literal value in scripts/dr/docker-compose.standby.yml (#3728).
        monkeypatch.setenv("ARCHIE_DR_MODE", "1")
        assert is_dr_active() is True

    @pytest.mark.parametrize("value", ["true", "TRUE", "True", "yes", "on", " 1 "])
    def test_other_truthy_spellings_activate(self, monkeypatch, value):
        # Tolerated so a hand-edited .env mid-outage still raises the alarm.
        monkeypatch.setenv("ARCHIE_DR_MODE", value)
        assert is_dr_active() is True

    @pytest.mark.parametrize("value", ["1\n", "1\r\n", "\t1"])
    def test_stray_whitespace_from_an_env_file_still_activates(self, monkeypatch, value):
        # A value appended to .env by a heredoc/echo carries a newline. Losing the red
        # alert to a trailing \n during a real failover is exactly the silent-failure
        # class this whole change exists to remove.
        monkeypatch.setenv("ARCHIE_DR_MODE", value)
        assert is_dr_active() is True


class TestDrActiveFalse:
    def test_unset_is_hub_normal(self):
        # The hub sets nothing at all — this is the case that runs 99.9% of the time.
        assert is_dr_active() is False

    @pytest.mark.parametrize("value", ["", "  ", "0", "false", "no", "off", "maybe"])
    def test_falsy_and_garbage_are_hub_normal(self, monkeypatch, value):
        monkeypatch.setenv("ARCHIE_DR_MODE", value)
        assert is_dr_active() is False

    @pytest.mark.parametrize("value", ["1;", "enabled", "TRUE!", "２"])
    def test_unrecognised_value_degrades_instead_of_raising(self, monkeypatch, value):
        # Fail-safe, not fail-loud: an odd value (including a full-width digit that is
        # NOT ascii '1') must degrade to hub-normal, never 500 the alert bell.
        monkeypatch.setenv("ARCHIE_DR_MODE", value)
        assert is_dr_active() is False

    def test_returns_a_real_bool_not_a_truthy_string(self, monkeypatch):
        # The header compares with `data.dr_mode === true` (strict), so anything other
        # than a JSON boolean would silently never fire.
        monkeypatch.setenv("ARCHIE_DR_MODE", "1")
        assert isinstance(is_dr_active(), bool)

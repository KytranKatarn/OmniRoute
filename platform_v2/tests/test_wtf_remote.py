"""services.wtf_remote: the hub's credential-free replacement for the retired hub `wtf` database (#7372).

Pure tests (no DB, no network): the watchdog decision function, the fail-closed flag, error hygiene, headline parsing.
Run with --noconftest.
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import wtf_remote as wr  # noqa: E402

MIN = 60.0


def _count(seq):
    it = iter(seq)

    def fetch():
        v = next(it)
        if isinstance(v, Exception):
            raise v
        return v

    return fetch


# ── watchdog_step ────────────────────────────────────────────────────────────────────────────────────
def test_first_observation_is_a_baseline_never_an_alert():
    s = wr.WatchdogState()
    r = wr.watchdog_step(s, 1000.0, _count([180000]))
    assert r["alert"] is None and r["minutes_unchanged"] == 0.0 and s.last_count == 180000


def test_a_change_in_the_count_proves_liveness_and_resets_the_clock():
    s = wr.WatchdogState()
    f = _count([100, 100, 105])
    wr.watchdog_step(s, 0.0, f)
    r = wr.watchdog_step(s, 100 * MIN, f)  # 100 min unchanged: still under 240
    assert r["alert"] is None and r["minutes_unchanged"] == pytest.approx(100.0)
    r = wr.watchdog_step(s, 200 * MIN, f)  # changed: reset
    assert r["alert"] is None and r["minutes_unchanged"] == 0.0 and s.last_change_ts == 200 * MIN


def test_a_count_that_goes_DOWN_is_still_a_change():
    """Suppression can lower the unsuppressed count; the pipeline is alive."""
    s = wr.WatchdogState()
    f = _count([100, 99])
    wr.watchdog_step(s, 0.0, f)
    assert wr.watchdog_step(s, 10 * MIN, f)["minutes_unchanged"] == 0.0


def test_no_alert_inside_the_largest_gap_ever_observed_but_alert_beyond_it():
    """Real ingest gaps reach 202 min (14d, around the clock): the net must not fire on those."""
    s = wr.WatchdogState()
    f = _count([5] * 5)
    wr.watchdog_step(s, 0.0, f)
    assert wr.watchdog_step(s, 203 * MIN, f)["alert"] is None
    assert wr.watchdog_step(s, 239 * MIN, f)["alert"] is None
    r = wr.watchdog_step(s, 245 * MIN, f)  # >5 min after the previous poll (polls are throttled)
    assert r["alert"] == "stale" and r["minutes_unchanged"] == pytest.approx(245.0)
    assert wr.STALE_AFTER_MIN > 202


def test_stale_realerts_hourly_not_every_tick():
    s = wr.WatchdogState()
    f = _count([5] * 20)
    wr.watchdog_step(s, 0.0, f)
    assert wr.watchdog_step(s, 250 * MIN, f)["alert"] == "stale"
    assert wr.watchdog_step(s, 260 * MIN, f)["alert"] is None
    assert wr.watchdog_step(s, 280 * MIN, f)["alert"] is None
    assert wr.watchdog_step(s, 311 * MIN, f)["alert"] == "stale"


def test_polls_are_throttled_regardless_of_watchdog_tick_rate():
    s = wr.WatchdogState()
    calls = []

    def fetch():
        calls.append(1)
        return 7

    wr.watchdog_step(s, 1000.0, fetch)
    r = wr.watchdog_step(s, 1000.0 + 60, fetch)  # a minute later
    assert r["polled"] is False and len(calls) == 1
    assert wr.watchdog_step(s, 1000.0 + wr.MIN_POLL_INTERVAL_S + 1, fetch)["polled"] is True


def test_blind_alert_fires_once_a_day_not_every_tick():
    """The old watchdog was blind for 18 days behind a per-tick log warning nobody read."""
    s = wr.WatchdogState()
    err = wr.WtfApiError("URLError reading /api/stats")
    f = _count([err] * 10)
    r = wr.watchdog_step(s, 1000.0, f)
    assert r["alert"] == "blind" and r["error"] == "WtfApiError"
    assert wr.watchdog_step(s, 1000.0 + 400, f)["alert"] is None
    assert wr.watchdog_step(s, 1000.0 + 3600 * 5, f)["alert"] is None
    assert wr.watchdog_step(s, 1000.0 + 86400 + 1, f)["alert"] == "blind"


def test_recovering_from_blindness_gives_a_baseline_not_a_false_stale():
    s = wr.WatchdogState()
    f = _count([RuntimeError("x"), 42, 42])
    assert wr.watchdog_step(s, 0.0, f)["alert"] == "blind"
    r = wr.watchdog_step(s, 400.0, f)
    assert r["alert"] is None and r["minutes_unchanged"] == 0.0


# ── flag / config ────────────────────────────────────────────────────────────────────────────────────
def _wc(monkeypatch, fn):
    from services import work_control_service as wc

    monkeypatch.setattr(wc, "is_enabled", fn)


def test_hub_backlog_reads_the_work_control_toggle_with_default_off(monkeypatch):
    seen = {}

    def fake(key, default=True):
        seen["key"], seen["default"] = key, default
        return default

    _wc(monkeypatch, fake)
    assert wr.hub_backlog_enabled() is False
    assert seen == {"key": "wtf_hub_backlog", "default": False}  # default MUST be False or the toggle lies


def test_hub_backlog_on_when_the_control_is_on(monkeypatch):
    _wc(monkeypatch, lambda key, default=True: True)
    assert wr.hub_backlog_enabled() is True


def test_a_control_plane_error_fails_closed(monkeypatch):
    def boom(key, default=True):
        raise RuntimeError("settings down")

    _wc(monkeypatch, boom)
    assert wr.hub_backlog_enabled() is False


def test_the_control_is_registered_default_off_so_armada_shows_it_honestly():
    from services import work_control_service as wc

    meta = wc.BACKLOGS["wtf_hub_backlog"]
    assert meta["default"] is False and meta["backend"] == "platform_settings" and meta["module"] == "What The Fact"
    assert wc._ps_key("wtf_hub_backlog") == wr.FLAG_HUB_BACKLOG == "work:wtf_hub_backlog:enabled"


def test_connect_refuses_to_dial_when_unconfigured(monkeypatch):
    monkeypatch.delenv("WTF_HUB_DATABASE_URL", raising=False)
    with pytest.raises(wr.WtfDbNotConfigured):
        wr.connect()


# ── public API ───────────────────────────────────────────────────────────────────────────────────────
def test_api_errors_never_carry_the_url(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("connection refused https://secret.example/api/stats?token=abc")

    monkeypatch.setattr(wr.urllib.request, "urlopen", boom)
    with pytest.raises(wr.WtfApiError) as exc:
        wr.article_count()
    assert "secret.example" not in str(exc.value) and "token" not in str(exc.value) and exc.value.__cause__ is None


def test_article_count_parses_and_rejects_bad_payloads(monkeypatch):
    monkeypatch.setattr(wr, "_get_json", lambda path, timeout=10: {"articles": "180113"})
    assert wr.article_count() == 180113
    monkeypatch.setattr(wr, "_get_json", lambda path, timeout=10: {"nope": 1})
    with pytest.raises(wr.WtfApiError):
        wr.article_count()


def test_latest_headlines_parsing_and_query(monkeypatch):
    seen = {}

    def fake(path, timeout=10):
        seen["path"] = path
        return {
            "articles": [
                {"title": " Alpha ", "source": {"name": "CBC", "slug": "cbc"}},
                {"title": "Beta", "source": {"slug": "only_slug"}},
                {"title": "", "source": {"name": "Blank"}},
                {"title": "Gamma", "source": None},
                None,
            ]
        }

    monkeypatch.setattr(wr, "_get_json", fake)
    got = wr.latest_headlines(limit=500, days=3)
    assert got == [("Alpha", "CBC"), ("Beta", "only_slug"), ("Gamma", "outlet")]
    assert "limit=100" in seen["path"] and "since=" in seen["path"]  # limit capped at the API's maximum

"""Radar + cloud overlay proxy (WX-1a, task 7250, ADR #1134): allowlist, honest metadata, cache behaviour and the three routes. No network: upstream is faked."""

import pytest

from consumer import wx_overlay as wo

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 64
NOW = 1_760_486_400.0  # 2025-10-15T00:00:00Z

CAPS = """<?xml version="1.0"?>
<WMS_Capabilities xmlns="http://www.opengis.net/wms" version="1.3.0"><Capability><Layer><Layer>
<Name>{layer}</Name><Dimension name="time" units="ISO8601" default="{t}">x</Dimension>{ref}
</Layer></Layer></Capability></WMS_Capabilities>"""


def caps(layer, t="2026-10-15T00:06:00Z", ref=None):
    r = f'<Dimension name="reference_time" units="ISO8601" default="{ref}">y</Dimension>' if ref else ""
    return CAPS.format(layer=layer, t=t, ref=r)


class Upstream:
    def __init__(self, t="2026-10-15T00:06:00Z", png=PNG, fail=False):
        self.t, self.png, self.fail, self.urls = t, png, fail, []

    def text(self, url):
        self.urls.append(url)
        if self.fail:
            raise OSError("down")
        layer = "RADAR_1KM_RRAI" if "RADAR" in url else "HRDPS.CONTINENTAL_NT"
        return caps(layer, self.t, "2026-10-14T18:00:00Z" if "HRDPS" in layer else None)

    def blob(self, url):
        self.urls.append(url)
        if self.fail:
            raise OSError("down")
        return self.png


class TestAllowlist:
    def test_only_two_known_keys(self):
        assert sorted(wo.OVERLAYS) == ["cloud", "radar"] and wo.known("radar") and not wo.known("../etc/passwd") and not wo.known("RADAR_1KM_RRAI")

    def test_getmap_url_is_fixed_except_for_a_validated_time(self):
        u = wo.getmap_url("radar", "2026-10-15T00:06:00Z")
        assert u.startswith("https://geo.weather.gc.ca/geomet?") and "layers=RADAR_1KM_RRAI" in u and "crs=CRS:84" in u and u.endswith("time=2026-10-15T00:06:00Z")

    @pytest.mark.parametrize("bad", ["", None, "now", "2026-10-15", "2026-10-15T00:06:00Z&layers=OTHER", "2026-10-15T00:06:00Z\n"])
    def test_a_time_that_is_not_a_plain_utc_stamp_is_refused(self, bad):
        with pytest.raises(ValueError):
            wo.getmap_url("radar", bad)

    def test_kinds_are_labelled_differently(self):
        assert wo.OVERLAYS["radar"]["kind"] == "observed" and wo.OVERLAYS["cloud"]["kind"] == "forecast"
        assert wo.OVERLAYS["cloud"]["domain_note"] and "forecast" in wo.OVERLAYS["cloud"]["note"].lower()


class TestParseTimes:
    def test_reads_the_layers_own_defaults(self):
        assert wo.parse_times(caps("HRDPS.CONTINENTAL_NT", "2026-10-15T00:00:00Z", "2026-10-14T18:00:00Z"), "HRDPS.CONTINENTAL_NT") == {
            "time": "2026-10-15T00:00:00Z", "reference_time": "2026-10-14T18:00:00Z"}

    def test_missing_layer_or_time_fails_loudly(self):
        with pytest.raises(ValueError):
            wo.parse_times(caps("OTHER"), "RADAR_1KM_RRAI")
        with pytest.raises(ValueError):
            wo.parse_times(caps("RADAR_1KM_RRAI", "latest"), "RADAR_1KM_RRAI")

    def test_an_entity_bomb_is_refused_not_expanded(self):
        bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;">]><WMS_Capabilities>&b;</WMS_Capabilities>'
        with pytest.raises(Exception):
            wo.parse_times(bomb, "RADAR_1KM_RRAI")


class TestEntry:
    def test_image_and_time_come_from_one_entry_and_the_time_is_what_was_requested(self):
        up = Upstream(t="2026-10-15T00:12:00Z")
        e = wo.build_entry("radar", up.text, up.blob, wo.datetime.fromtimestamp(NOW, tz=wo.timezone.utc))
        assert e["valid_time"] == "2026-10-15T00:12:00Z" and "time=2026-10-15T00:12:00Z" in up.urls[-1] and e["png"] == PNG

    def test_a_non_png_reply_is_refused(self):
        up = Upstream(png=b"<html>error</html>")
        with pytest.raises(ValueError):
            wo.build_entry("radar", up.text, up.blob, wo.datetime.now(wo.timezone.utc))

    def test_oversize_png_is_refused(self):
        assert not wo.png_ok(PNG + b"x" * wo.MAX_BYTES)


class TestDescribe:
    def _entry(self, valid, fetched):
        return {"png": PNG, "valid_time": valid, "reference_time": None, "fetched_at": fetched}

    def test_radar_goes_stale_on_its_valid_time(self):
        now = wo.datetime(2026, 10, 15, 1, 0, tzinfo=wo.timezone.utc)
        assert wo.describe("radar", self._entry("2026-10-15T00:50:00Z", "2026-10-15T00:55:00Z"), now)["stale"] is False
        d = wo.describe("radar", self._entry("2026-10-15T00:06:00Z", "2026-10-15T00:59:00Z"), now)
        assert d["stale"] is True and d["age_s"] == 54 * 60   # fetched a minute ago but the frame is 54 minutes old: still stale

    def test_cloud_goes_stale_on_our_copy_not_the_model_hour(self):
        now = wo.datetime(2026, 10, 15, 6, 0, tzinfo=wo.timezone.utc)
        e = self._entry("2026-10-15T12:00:00Z", "2026-10-15T05:00:00Z")   # a forecast hour in the future is not "negative age"
        assert wo.describe("cloud", e, now)["stale"] is False
        assert wo.describe("cloud", self._entry("2026-10-15T12:00:00Z", "2026-10-15T01:00:00Z"), now)["stale"] is True

    def test_metadata_carries_the_labels_and_no_image_bytes(self):
        d = wo.describe("cloud", self._entry("2026-10-15T00:00:00Z", "2026-10-15T00:01:00Z"), wo.datetime(2026, 10, 15, 0, 5, tzinfo=wo.timezone.utc))
        assert "png" not in d and d["kind"] == "forecast" and "Open Government Licence" in d["attribution"] and d["domain_note"]


class TestCache:
    def _cache(self, up, clock):
        return wo.OverlayCache(up.text, up.blob, clock=clock, retry_after_fail=60)

    def test_fresh_entry_makes_no_upstream_call(self):
        up, t = Upstream(), [NOW]
        c = self._cache(up, lambda: t[0])
        c.get("radar"); n = len(up.urls); t[0] += 100
        c.get("radar")
        assert len(up.urls) == n

    def test_expiry_refreshes_once(self):
        up, t = Upstream(), [NOW]
        c = self._cache(up, lambda: t[0])
        c.get("radar"); n = len(up.urls); t[0] += 301
        up.t = "2026-10-15T00:12:00Z"
        assert c.get("radar")["valid_time"] == "2026-10-15T00:12:00Z" and len(up.urls) == n + 2

    def test_outage_keeps_the_old_frame_and_backs_off(self):
        up, t = Upstream(), [NOW]
        c = self._cache(up, lambda: t[0])
        old = c.get("radar"); t[0] += 301; up.fail = True; n = len(up.urls)
        assert c.get("radar") is old                      # served, to be labelled stale by describe()
        calls_after_first_failure = len(up.urls)
        t[0] += 10
        assert c.get("radar") is old and len(up.urls) == calls_after_first_failure   # inside the back-off: no new upstream call
        assert calls_after_first_failure > n
        t[0] += 60; c.get("radar")
        assert len(up.urls) > calls_after_first_failure   # retried after the back-off

    def test_never_answered_means_none_not_an_exception(self):
        up = Upstream(fail=True)
        assert self._cache(up, lambda: NOW).get("cloud") is None


class TestLockDiscipline:
    """The refresh lock is released exactly once per acquire, on every path, and never when it was not acquired (review #3879)."""

    def _free(self, cache, key):
        lk = cache._lock[key]
        got = lk.acquire(blocking=False)
        if got:
            lk.release()
        return got

    def test_lock_is_free_after_a_successful_refresh(self):
        up, t = Upstream(), [NOW]
        c = wo.OverlayCache(up.text, up.blob, clock=lambda: t[0])
        c.get("radar")
        assert self._free(c, "radar")

    def test_lock_is_free_after_a_failed_refresh(self):
        c = wo.OverlayCache(Upstream(fail=True).text, Upstream(fail=True).blob, clock=lambda: NOW)
        assert c.get("radar") is None
        assert self._free(c, "radar")

    def test_the_fresh_entry_fast_path_never_takes_the_lock(self):
        up, t = Upstream(), [NOW]
        c = wo.OverlayCache(up.text, up.blob, clock=lambda: t[0])
        c.get("radar")
        lk = c._lock["radar"]
        lk.acquire()                                   # held by "someone else"; a fresh hit must not need it
        try:
            assert c.get("radar") is not None
        finally:
            lk.release()

    def test_a_lock_we_never_acquired_is_never_released(self):
        up = Upstream()
        c = wo.OverlayCache(up.text, up.blob, clock=lambda: NOW, lock_wait=0.05)
        lk = c._lock["radar"]
        lk.acquire()                                   # another holder
        try:
            assert c.get("radar") is None              # timed out: old entry (none), no exception
            assert lk.locked(), "the other holder's lock must still be held, we must not have released it"
        finally:
            lk.release()

    def test_eight_threads_on_an_expired_entry_cause_one_upstream_build(self):
        import threading
        import time as _t
        up, now = Upstream(), [NOW]
        slow = lambda u: (_t.sleep(0.05), up.text(u))[1]
        c = wo.OverlayCache(slow, up.blob, clock=lambda: now[0])
        results, errors = [], []

        def worker():
            try:
                results.append(c.get("radar"))
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        [th.start() for th in threads]
        [th.join() for th in threads]
        assert not errors and len(results) == 8 and all(r is not None for r in results)
        assert len([u for u in up.urls if "GetCapabilities" in u]) == 1, "exactly one upstream build for eight simultaneous callers"
        assert self._free(c, "radar")


class TestSnapshotConsistency:
    """Readers never see a torn state: an entry paired with another refresh's timestamp (review #3879)."""

    def test_state_is_one_immutable_tuple_replaced_not_edited(self):
        c = wo.OverlayCache(Upstream().text, Upstream().blob, clock=lambda: NOW)
        before = c._snap["radar"]
        c.get("radar")
        after = c._snap["radar"]
        assert isinstance(before, tuple) and isinstance(after, tuple) and before is not after and after[0] is not None

    def test_failed_refresh_replaces_the_snapshot_and_keeps_the_entry(self):
        up, t = Upstream(), [NOW]
        c = wo.OverlayCache(up.text, up.blob, clock=lambda: t[0])
        good = c.get("radar")
        t[0] += 301; up.fail = True
        assert c.get("radar") is good
        entry, stored_at, failed_at = c._snap["radar"]
        assert entry is good and stored_at == NOW and failed_at == NOW + 301

    def test_readers_hammering_while_a_writer_refreshes_never_see_a_mismatched_pair(self):
        import threading
        up, now = Upstream(), [NOW]
        c = wo.OverlayCache(up.text, up.blob, clock=lambda: now[0])
        c.get("radar")
        stop, bad = threading.Event(), []

        def reader():
            while not stop.is_set():
                e, ts, fa = c._snap["radar"]
                # every published snapshot is self-consistent: an entry always comes with the time it was stored, a failure never erases the entry
                if e is None or not isinstance(ts, float) or "png" not in e or (fa is not None and fa < ts):
                    bad.append((e is None, ts, fa))

        readers = [threading.Thread(target=reader) for _ in range(4)]
        [r.start() for r in readers]
        for i in range(200):
            now[0] += 301                                   # expire, then refresh (alternating success and failure)
            up.fail = (i % 3 == 0)
            c.get("radar")
        stop.set()
        [r.join() for r in readers]
        assert not bad, f"{len(bad)} torn snapshots observed"


class TestRoutes:
    @pytest.fixture
    def client(self, monkeypatch):
        import consumer.routes as r
        from flask import Flask
        up = Upstream()
        clock = [NOW]
        monkeypatch.setattr(r, "_WX_OVERLAYS", wo.OverlayCache(up.text, up.blob, clock=lambda: clock[0]))
        monkeypatch.setattr(r, "_wx_http", lambda url, limit, timeout=12: PNG)
        monkeypatch.setattr(r, "_WX_LEGENDS", {})
        app = Flask(__name__)
        app.register_blueprint(r.bp)
        c = app.test_client()
        c.up, c.clock = up, clock
        return c

    def test_unknown_key_is_404_on_every_route(self, client):
        for p in ("/weather/overlay/evil/meta.json", "/weather/overlay/evil.png?v=x", "/weather/overlay/evil/legend.png", "/weather/overlay/RADAR_1KM_RRAI/meta.json"):
            assert client.get(p).status_code == 404

    def test_meta_then_png_round_trip_with_matching_frame(self, client):
        m = client.get("/weather/overlay/radar/meta.json").get_json()
        assert m["kind"] == "observed" and m["valid_time"] == "2026-10-15T00:06:00Z" and "attribution" in m
        r = client.get(m["png_url"])
        assert r.status_code == 200 and r.mimetype == "image/png" and r.data == PNG and "max-age" in r.headers["Cache-Control"]

    def test_png_requires_the_frame_it_was_labelled_with(self, client):
        client.get("/weather/overlay/radar/meta.json")
        assert client.get("/weather/overlay/radar.png").status_code == 400
        r = client.get("/weather/overlay/radar.png?v=2020-01-01T00:00:00Z")
        assert r.status_code == 409 and r.get_json()["valid_time"] == "2026-10-15T00:06:00Z"

    def test_service_never_answered_is_503_not_500(self, client):
        client.up.fail = True
        assert client.get("/weather/overlay/cloud/meta.json").status_code == 503
        assert client.get("/weather/overlay/cloud.png?v=2026-10-15T00:00:00Z").status_code == 503

    def test_legend_is_proxied_and_cached(self, client):
        r = client.get("/weather/overlay/cloud/legend.png")
        assert r.status_code == 200 and r.mimetype == "image/png"

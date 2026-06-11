"""Regression tests for device_registry_service timezone handling.

The scheduler's _suggest_access_policy_conflict warned every 15 minutes with
"can't subtract offset-naive and offset-aware datetimes" because _is_online
forced values naive before subtracting from an aware now(). Two AdGuard
last_query parse sites had the same naive/aware mismatch, silently caught,
so dns_active/dns_online were always False.
"""

from datetime import datetime, timedelta, timezone

from tools.security_network.device_registry_service import DeviceRegistryService


class TestIsOnline:
    def test_naive_datetime_from_db(self):
        # DB hands back naive UTC — must not raise
        recent = datetime.now(timezone.utc).replace(tzinfo=None)
        assert DeviceRegistryService._is_online(recent) is True

    def test_aware_datetime(self):
        recent = datetime.now(timezone.utc)
        assert DeviceRegistryService._is_online(recent) is True

    def test_old_timestamp_is_offline(self):
        old = datetime.now(timezone.utc) - timedelta(hours=2)
        assert DeviceRegistryService._is_online(old) is False
        assert DeviceRegistryService._is_online(old.replace(tzinfo=None)) is False

    def test_iso_string_with_z_suffix(self):
        recent = datetime.now(timezone.utc).replace(tzinfo=None)
        assert DeviceRegistryService._is_online(recent.isoformat() + "Z") is True

    def test_empty_is_offline(self):
        assert DeviceRegistryService._is_online(None) is False
        assert DeviceRegistryService._is_online("") is False


class TestParseQueryTs:
    def test_nanosecond_fraction_with_offset(self):
        # AdGuard's actual format: 9-digit fraction + numeric offset
        dt = DeviceRegistryService._parse_query_ts("2026-06-11T06:25:26.301596188-04:00")
        assert dt.tzinfo is not None
        assert dt == datetime(2026, 6, 11, 10, 25, 26, 301596, tzinfo=timezone.utc)

    def test_z_suffix(self):
        dt = DeviceRegistryService._parse_query_ts("2026-06-11T10:25:26.123456789Z")
        assert dt == datetime(2026, 6, 11, 10, 25, 26, 123456, tzinfo=timezone.utc)

    def test_no_fraction_no_offset_assumed_utc(self):
        dt = DeviceRegistryService._parse_query_ts("2026-06-11T10:25:26")
        assert dt == datetime(2026, 6, 11, 10, 25, 26, tzinfo=timezone.utc)

    def test_result_is_comparable_to_aware_now(self):
        dt = DeviceRegistryService._parse_query_ts("2026-06-11T06:25:26.301596188-04:00")
        # the exact operation that used to raise TypeError
        assert (datetime.now(timezone.utc) - dt).total_seconds() is not None

"""Fixed-date rules + calendar roll-forward (pure). Run: python3 tests/test_election_rules.py"""
import datetime as dt, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from shared.election_rules import RULES, next_latest_date, nth_weekday, anchor_for, LAST, MON
from shared.election_calendar import classify, problems
import types
sys.modules.setdefault("sqlalchemy", types.SimpleNamespace(text=lambda s: s))
from ingest.elections.calendar import plan


def D(s): return dt.date.fromisoformat(s)


def test_known_dates():
    exp = {"CA": ("2025-04-28", "2029-10-15"), "ON": ("2025-02-27", "2029-06-07"),
           "BC": ("2024-10-19", "2028-10-21"), "QC": ("2022-10-03", "2026-10-05"),
           "MB": ("2023-10-03", "2027-10-05"), "SK": ("2024-10-28", "2028-10-30"),
           "NB": ("2024-10-21", "2028-10-16"), "PE": ("2023-04-03", "2027-10-04"),
           "NL": ("2025-10-14", "2029-10-09"),
           "NU": ("2025-10-27", "2029-10-29")}
    for c, (last, nxt) in exp.items():
        assert next_latest_date(c, last) == D(nxt), c
    assert set(exp) == set(RULES)


def test_no_rule_no_date():
    for c in ("AB", "NS", "NT", "YT"):
        assert next_latest_date(c, "2024-01-01") is None


def test_last_weekday_december_edge():
    assert nth_weekday(2027, 12, MON, LAST) == D("2027-12-27")


def test_anchor_prefers_newer_ingested():
    assert anchor_for("CA", None, D("2029-10-01")) == D("2029-10-01")
    assert anchor_for("QC") == D("2022-10-03")


def test_classify_projected_and_overdue():
    row = {"jurisdiction_code": "QC", "jurisdiction": "Québec", "level": "provincial",
           "next_latest_date": D("2026-10-05"), "last_election": D("2022-10-03"),
           "verified_at": None, "derived_at": dt.datetime(2026, 10, 1)}
    c = classify(row, D("2026-10-02"))
    assert c["status"] == "projected" and c["days_until"] == 3
    assert classify(row, D("2026-10-06"))["status"] == "overdue"
    assert classify(dict(row, derived_at=None), D("2026-10-02"))["status"] == "unverified"
    assert problems([row], D("2026-10-02")) == []


def test_plan_never_overwrites_verified():
    rows = {"QC": {"last_election": None, "next_latest_date": D("2026-10-06"), "verified_at": dt.datetime(2026, 9, 1)},
            "ON": {"last_election": None, "next_latest_date": None, "verified_at": None}}
    ups, conf = plan(rows, {}, None, D("2026-10-02"))
    assert [u["code"] for u in ups] == ["ON"] and conf and "QC" in conf[0]


def test_plan_rolls_forward_on_newer_history():
    rows = {"QC": {"last_election": None, "next_latest_date": None, "verified_at": None}}
    ups, _ = plan(rows, {"QC": D("2026-10-05")}, None, D("2026-10-10"))
    assert ups[0]["next"] == D("2030-10-07")


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)


def test_nu_rule_is_labelled_unchecked():
    assert "unchecked" in RULES["NU"][4]

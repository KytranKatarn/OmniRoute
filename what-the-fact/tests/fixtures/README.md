# Test fixtures

`msc_citypage_s0000047_en.xml` is one REAL Environment and Climate Change Canada city-page file (Calgary, site s0000047), fetched 2026-10-14 from
the MSC Datamart (`https://dd.weather.gc.ca/<YYYYMMDD>/WXO-DD/citypage_weather/AB/<HH>/`), unmodified apart from one final newline added by the repo hooks. It is the same feed `ingest/weather/citypage.py`
downloads. It contains, besides what we already parse: 24 `hourlyForecast` entries, `regionalNormals`, `yesterdayConditions`, `riseSet`, and per-period
`iconCode`/`uv`/`humidex`/`relativeHumidity` on the 13 `forecast` periods.

Data licence: Open Government Licence - Canada (the file carries its own `<license>` element). Keep the attribution when displaying derived values.

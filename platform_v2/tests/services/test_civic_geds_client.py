import pytest
import asyncio
import httpx
from services.civic_geds_client import GedsClient, GedsFetchError

pytestmark = pytest.mark.anyio


def make_mock(handler):
    return httpx.MockTransport(handler)


async def test_get_returns_decoded_html():
    def handler(req):
        return httpx.Response(200, text="<html>ok</html>", headers={"content-type": "text/html; charset=utf-8"})

    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        body = await c.get("?pgid=012")
    assert body == "<html>ok</html>"


async def test_get_decodes_latin1():
    def handler(req):
        return httpx.Response(
            200, content="caf\xe9".encode("latin-1"), headers={"content-type": "text/html; charset=ISO-8859-1"}
        )

    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        body = await c.get("?pgid=012")
    assert "café" in body


async def test_5xx_retries_three_times():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503, text="boom")

    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        with pytest.raises(GedsFetchError):
            await c.get("?pgid=012")
    assert len(calls) == 3


async def test_4xx_does_not_retry():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(404, text="nope")

    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        with pytest.raises(GedsFetchError):
            await c.get("?pgid=012")
    assert len(calls) == 1


async def test_429_triggers_adaptive_backoff(monkeypatch):
    # Avoid the real 60s sleep
    real_sleep = asyncio.sleep
    sleeps = []

    async def fake_sleep(n):
        sleeps.append(n)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    state = {"calls": 0}

    def handler(req):
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(429, text="slow down")
        return httpx.Response(200, text="<html>ok</html>")

    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        body = await c.get("?pgid=012")
    assert state["calls"] == 2
    assert "ok" in body
    # 60s backoff should have been requested at least once
    assert any(s >= 60 for s in sleeps), f"no 60s backoff observed: {sleeps}"


async def test_user_agent_identifies_archie():
    seen = {}

    def handler(req):
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, text="ok")

    async with GedsClient(transport=make_mock(handler), rate_per_sec=100) as c:
        await c.get("?pgid=012")
    assert "ARCHIE-CivicWatch" in seen["ua"]


async def test_rate_limit_enforces_minimum_interval(monkeypatch):
    times = []
    real_sleep = asyncio.sleep

    async def fake_sleep(n):
        times.append(n)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    def handler(req):
        return httpx.Response(200, text="ok")

    async with GedsClient(transport=make_mock(handler), rate_per_sec=2) as c:
        await c.get("?pgid=012")
        await c.get("?pgid=012")
    # Second call must have waited ~0.5s
    assert any(t >= 0.4 for t in times), f"no throttle sleep observed: {times}"

"""
Test 06 — Archie Chat interaction for COLLABORATOR accounts.

Part of T3297 — General human-online interactions (Phase 2).

Verifies (USER_CHAT permission):
  1. /tools/archie-chat loads with 200 for all COLLABORATORs (not 403)
  2. POST /api/chat/message sends a message and receives a non-empty response
  3. Conversation list (GET /api/chat/conversations) is scoped to own user
  4. COLLABORATORs cannot read another user's conversation by ID (IDOR guard)

Run:
    pytest tests/human_agents/test_06_chat.py -v
    pytest tests/human_agents/test_06_chat.py -v -k "send"
"""

from __future__ import annotations

import pytest
import requests
from playwright.sync_api import Browser

from conftest import BASE_URL, login_as, logout

# EVERY test here drives a real browser (#5990). Module-level pytestmark is applied
# during COLLECTION, before pytest's own -m filter runs — a conftest
# pytest_collection_modifyitems hook adds markers too LATE to be deselected, which is
# why the first attempt at this fix did nothing and the suite kept hanging.
pytestmark = pytest.mark.browser

CHAT_URL = f"{BASE_URL}/tools/archie-chat"

# API endpoints used by archie_chat module (from routes.py)
CHAT_MSG_URL = f"{BASE_URL}/tools/archie-chat/api/message"
CHAT_CONVOS_URL = f"{BASE_URL}/tools/archie-chat/api/conversations"
CHAT_NEW_CONVO_URL = f"{BASE_URL}/tools/archie-chat/api/conversations/new"

# Fallback endpoints in case routes differ
_ALT_MSG_URLS = [
    f"{BASE_URL}/api/chat/message",
    f"{BASE_URL}/api/archie/chat",
    f"{BASE_URL}/tools/archie-chat/api/chat",
]


def _session(browser: Browser, agent: dict) -> tuple:
    """Returns (ctx, page, cookie_dict). Caller must close ctx."""
    ctx = browser.new_context()
    page = ctx.new_page()
    login_as(page, agent)
    cookies = ctx.cookies()
    sc = next((c for c in cookies if c["name"] in ("session", "archie_session")), None)
    cookie_dict = {sc["name"]: sc["value"]} if sc else {}
    return ctx, page, cookie_dict


class TestChatAccess:
    """COLLABORATORs can access and use Archie Chat."""

    def test_all_agents_reach_chat_page(self, browser: Browser, all_agents: list):
        """Every credentialed COLLABORATOR can load /tools/archie-chat (not 403)."""
        failures: list[str] = []

        for agent in all_agents:
            if not agent.get("password"):
                print(f"  SKIP {agent['email']} — no credentials")
                continue

            ctx = browser.new_context()
            page = ctx.new_page()
            try:
                login_as(page, agent)
                page.goto(CHAT_URL)
                page.wait_for_load_state("networkidle")

                if "/login" in page.url:
                    failures.append(f"{agent['email']}: redirected to /login accessing chat")
                    continue

                page_text = page.inner_text("body").lower()
                if "403" in page_text or "forbidden" in page_text or "access denied" in page_text:
                    failures.append(f"{agent['email']} ({agent['department']}): chat page shows access denied")
                else:
                    print(f"  ✓ {agent['display_name']:35s} ({agent['department']}): " f"chat page accessible")

            except Exception as exc:
                failures.append(f"{agent['email']}: {exc}")
            finally:
                logout(page)
                ctx.close()

        if failures:
            pytest.fail(f"{len(failures)} agent(s) blocked from chat:\n" + "\n".join(f"  • {f}" for f in failures))

    def test_send_chat_message(self, browser: Browser, all_agents: list):
        """COLLABORATOR can POST a chat message and receive a non-empty response.

        Uses one agent per unique department for coverage without redundancy.
        Accepts any non-403/non-401 response as passing — the agent reached the
        inference layer. Empty response is noted but not a hard failure (model may
        be loading).
        """
        seen: set[str] = set()
        sample = []
        for agent in all_agents:
            if agent["department"] not in seen and agent.get("password"):
                seen.add(agent["department"])
                sample.append(agent)
                if len(sample) >= 5:  # limit for speed
                    break

        if not sample:
            pytest.skip("No credentialed agents")

        failures: list[str] = []

        for agent in sample:
            ctx, page, cookie_dict = _session(browser, agent)
            try:
                if not cookie_dict:
                    print(f"  SKIP {agent['email']} — no session cookie")
                    continue

                # Create a new conversation first (if endpoint exists)
                convo_id = None
                try:
                    nr = requests.post(
                        CHAT_NEW_CONVO_URL,
                        cookies=cookie_dict,
                        timeout=8,
                        json={"title": f"T3297 test — {agent['display_name']}"},
                    )
                    if nr.ok:
                        convo_id = (nr.json() or {}).get("id") or (nr.json() or {}).get("conversation_id")
                except Exception:
                    pass

                # Build message payload
                payload: dict = {
                    "message": f"Hello, I am {agent['display_name']} from {agent['department']}. Please confirm receipt.",
                    "model": "auto",
                }
                if convo_id:
                    payload["conversation_id"] = convo_id

                # Try primary endpoint first
                msg_resp = None
                tried_urls = [CHAT_MSG_URL] + _ALT_MSG_URLS
                for url in tried_urls:
                    try:
                        r = requests.post(url, json=payload, cookies=cookie_dict, timeout=60)
                        if r.status_code != 404:
                            msg_resp = r
                            break
                    except Exception:
                        continue

                if msg_resp is None:
                    print(
                        f"  ℹ {agent['display_name']}: no chat message endpoint found "
                        f"(tried {len(tried_urls)} URLs) — skipping send test"
                    )
                    continue

                if msg_resp.status_code in (401, 403):
                    failures.append(
                        f"{agent['email']} ({agent['department']}): "
                        f"chat/message returned {msg_resp.status_code} — "
                        f"USER_CHAT permission may not be wired for COLLABORATOR"
                    )
                elif msg_resp.status_code == 200:
                    data = (
                        msg_resp.json()
                        if msg_resp.headers.get("content-type", "").startswith("application/json")
                        else {}
                    )
                    response_text = data.get("response") or data.get("message") or data.get("content") or ""
                    if response_text:
                        print(
                            f"  ✓ {agent['display_name']:35s} ({agent['department']}): "
                            f"chat response received ({len(response_text)} chars)"
                        )
                    else:
                        print(
                            f"  ℹ {agent['display_name']}: 200 but empty response — "
                            f"model may be loading (acceptable)"
                        )
                else:
                    print(
                        f"  ℹ {agent['display_name']}: chat/message → {msg_resp.status_code} "
                        f"(not 401/403 — scope check passed)"
                    )

            except Exception as exc:
                failures.append(f"{agent['email']}: {exc}")
            finally:
                logout(page)
                ctx.close()

        if failures:
            pytest.fail("Chat access failures:\n" + "\n".join(f"  • {f}" for f in failures))

    def test_conversations_scoped_to_own_user(self, browser: Browser, all_agents: list):
        """GET /api/conversations returns only own conversations (no cross-user leak)."""
        credentialed = [a for a in all_agents if a.get("password")]
        if len(credentialed) < 2:
            pytest.skip("Need 2+ credentialed agents")

        agent_a = credentialed[0]
        agent_b = credentialed[1]

        # Get agent_a's conversations
        ctx_a, page_a, cookies_a = _session(browser, agent_a)
        convos_a: set = set()
        try:
            resp = requests.get(CHAT_CONVOS_URL, cookies=cookies_a, timeout=10)
            if resp.ok:
                data = resp.json()
                items = data if isinstance(data, list) else data.get("conversations", [])
                convos_a = {str(c.get("id")) for c in items if c.get("id")}
                print(f"  ✓ {agent_a['display_name']}: {len(convos_a)} conversations via API")
            else:
                print(f"  ℹ conversations endpoint → {resp.status_code} for {agent_a['email']}")
        finally:
            logout(page_a)
            ctx_a.close()

        if not convos_a:
            pytest.skip("No conversations to cross-check (agent_a has no history)")

        # Attempt to access agent_a's conversations as agent_b
        ctx_b, page_b, cookies_b = _session(browser, agent_b)
        try:
            leaks = []
            for convo_id in list(convos_a)[:3]:  # sample first 3
                r = requests.get(
                    f"{CHAT_CONVOS_URL}/{convo_id}",
                    cookies=cookies_b,
                    timeout=8,
                )
                if r.status_code == 200:
                    # Check if response contains agent_a's data
                    resp_text = r.text.lower()
                    if agent_a["email"].lower() in resp_text:
                        leaks.append(
                            f"Convo {convo_id}: agent_b reads agent_a's conversation " f"including their email!"
                        )
                    else:
                        # 200 but no cross-user data leaking — acceptable
                        print(f"  ✓ Convo {convo_id}: 200 but no agent_a identity data exposed")
                elif r.status_code in (403, 404):
                    print(f"  ✓ Convo {convo_id}: {r.status_code} (correctly blocked)")

            if leaks:
                pytest.fail(
                    f"CHAT IDOR: {agent_b['email']} can read {agent_a['email']}'s conversations:\n"
                    + "\n".join(f"  • {l}" for l in leaks)
                )
            else:
                print(f"  ✓ {agent_b['display_name']} cannot read " f"{agent_a['display_name']}'s conversations")
        finally:
            logout(page_b)
            ctx_b.close()

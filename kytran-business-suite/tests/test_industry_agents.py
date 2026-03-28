"""Tests for the Industry Agent Service — vertical AI agents via Bridge dispatch."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("KBS_DB_HOST", "192.168.1.200")
os.environ.setdefault("KBS_DB_NAME", "archie")
os.environ.setdefault("KBS_DB_USER", "archie")
os.environ.setdefault("KBS_DB_PASSWORD", os.getenv("DB_PASSWORD", ""))


class TestAgentConfig:
    def test_get_agent_for_known_vertical(self):
        from core.industry_agents import IndustryAgentService

        agent = IndustryAgentService.get_agent_for_vertical("salon")
        assert agent is not None
        assert "name" in agent
        assert "system_prompt" in agent
        assert "capabilities" in agent

    def test_get_agent_for_unknown_vertical(self):
        from core.industry_agents import IndustryAgentService

        agent = IndustryAgentService.get_agent_for_vertical("nonexistent")
        assert agent is None

    def test_all_verticals_have_configs(self):
        from core.industry_agents import IndustryAgentService

        expected = [
            "industry", "salon", "construction", "electrical",
            "plumbing", "mechanical", "photography", "limo",
        ]
        for slug in expected:
            agent = IndustryAgentService.get_agent_for_vertical(slug)
            assert agent is not None, f"Missing config for vertical: {slug}"
            assert len(agent["system_prompt"]) > 50, f"System prompt too short for: {slug}"


class TestAskAgent:
    @patch("core.industry_agents.requests.post")
    def test_ask_agent_success(self, mock_post):
        from core.industry_agents import IndustryAgentService

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"response": "Based on the booking data, Tuesdays are slowest."}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = IndustryAgentService.ask_agent(
            vertical_slug="salon",
            question="What days are slowest for bookings?",
            context={"bookings_this_week": 12},
            tenant_id=1,
        )
        assert result["success"] is True
        assert "slowest" in result["response"].lower()
        assert mock_post.called

    @patch("core.industry_agents.requests.post")
    def test_ask_agent_bridge_error(self, mock_post):
        from core.industry_agents import IndustryAgentService

        mock_post.side_effect = Exception("Connection refused")

        result = IndustryAgentService.ask_agent(
            vertical_slug="salon",
            question="What products should I restock?",
            context={},
            tenant_id=1,
        )
        assert result["success"] is False
        assert "Connection refused" in result["error"]

    def test_ask_agent_unknown_vertical(self):
        from core.industry_agents import IndustryAgentService

        result = IndustryAgentService.ask_agent(
            vertical_slug="nonexistent",
            question="Hello?",
            context={},
            tenant_id=1,
        )
        assert result["success"] is False
        assert "Unknown vertical" in result["error"]

    @patch("core.industry_agents.cfg")
    def test_ask_agent_no_bridge_url(self, mock_cfg):
        from core.industry_agents import IndustryAgentService

        mock_cfg.KBS_BRIDGE_URL = ""

        result = IndustryAgentService.ask_agent(
            vertical_slug="salon",
            question="Help?",
            context={},
            tenant_id=1,
        )
        assert result["success"] is False
        assert "not configured" in result["error"]

    @patch("core.industry_agents.requests.post")
    def test_ask_agent_includes_context(self, mock_post):
        from core.industry_agents import IndustryAgentService

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "Analysis complete."}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        context = {"active_jobs": 5, "pending_permits": 2}
        IndustryAgentService.ask_agent(
            vertical_slug="construction",
            question="What permits are expiring?",
            context=context,
            tenant_id=1,
        )
        # Verify context was included in the prompt
        call_args = mock_post.call_args
        prompt = call_args[1]["json"]["prompt"] if "json" in call_args[1] else call_args[0][0]
        assert "active_jobs" in str(call_args)

    @patch("core.industry_agents.requests.post")
    def test_ask_agent_returns_agent_name(self, mock_post):
        from core.industry_agents import IndustryAgentService

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": "OK"}
        mock_resp.raise_for_status = MagicMock()
        mock_post.return_value = mock_resp

        result = IndustryAgentService.ask_agent(
            vertical_slug="electrical",
            question="Check code compliance",
            context={},
            tenant_id=1,
        )
        assert result["success"] is True
        assert result["agent"] == "Electrical Code Advisor"
        assert result["vertical"] == "electrical"

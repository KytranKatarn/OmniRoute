"""
StockBot Routes - AI Stock Screener
Phase 7: Standalone Apps - Uses archie_bridge for local-first AI with team agents
Updated: 2026-01-21 - Now uses Stock & Market Expert via archie_bridge
"""

from flask import render_template, jsonify, request
from . import stockbot_bp
import sys
import logging

# Add ai_bridge to path for archie_bridge import
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
try:
    from archie_bridge import archie_bridge

    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

try:
    from ai_bridge.bridge_dispatcher import get_dispatcher

    _dispatcher = get_dispatcher()
except Exception:
    _dispatcher = None

logger = logging.getLogger(__name__)

# Stock & Market Expert agent ID
STOCKBOT_AGENT_ID = 44

# Fallback Ollama endpoint (if bridge unavailable)
OLLAMA_URL = "http://localhost:11434"

# System prompt for stock AI
STOCKBOT_SYSTEM_PROMPT = """You are ALPHA, an AI stock market analyst assistant. You provide educational information about stocks, market analysis, and trading concepts.

IMPORTANT RULES:
1. NEVER provide financial advice or recommend specific buy/sell actions
2. Always include disclaimer: "This is educational information only, not financial advice"
3. Encourage users to do their own research (DYOR)
4. Recommend consulting a licensed financial advisor for investment decisions
5. Be objective and present multiple perspectives on market movements
6. Explain financial concepts in accessible terms
7. Never claim to predict future stock prices with certainty

You can help with:
- Explaining stock market concepts and terminology
- Discussing fundamental analysis (P/E ratios, earnings, etc.)
- Explaining technical analysis basics (patterns, indicators)
- Discussing market news and its potential implications
- Educational information about different investment strategies
- Risk management concepts

Keep responses educational and balanced. Use bullet points for complex topics.
Always maintain a neutral, analytical tone."""


@stockbot_bp.route("/")
def index():
    """StockBot main page"""
    return render_template("tools/stockbot.html")


@stockbot_bp.route("/api/status")
def status():
    """API endpoint for module health check"""
    import requests as req

    # Check Ollama connection (fallback)
    ollama_healthy = False
    try:
        response = req.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_healthy = response.status_code == 200
    except:
        pass

    return jsonify(
        {
            "module": "stockbot",
            "status": "active",
            "healthy": True,
            "bridge_available": BRIDGE_AVAILABLE,
            "ollama_connected": ollama_healthy,
            "agent": "Stock & Market Expert" if BRIDGE_AVAILABLE else "Direct Ollama",
            "message": (
                "ALPHA Stock Analyst is ready via A.R.C.H.I.E. Bridge"
                if BRIDGE_AVAILABLE
                else "ALPHA Stock Analyst is ready (fallback mode)"
            ),
        }
    )


@stockbot_bp.route("/api/chat", methods=["POST"])
def chat():
    """Send message to stock AI via archie_bridge"""
    data = request.get_json() or {}
    message = data.get("message", "")
    user_id = data.get("user_id", 1)

    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400

    try:
        if BRIDGE_AVAILABLE:
            # Use archie_bridge with Stock & Market Expert
            result = archie_bridge(
                prompt=message,
                user_id=user_id,
                agent_id=STOCKBOT_AGENT_ID,
                system_prompt=STOCKBOT_SYSTEM_PROMPT,
                enable_memory=True,
                try_local_first=True,
                task_type="stock_analysis",
            )

            if _dispatcher:
                try:
                    _dispatcher.log_external_call(
                        capability="conversation",
                        module_id="stockbot",
                        model_used=result.get("model_used", ""),
                        success=bool(result.get("response")),
                    )
                except Exception:
                    pass

            if result.get("success"):
                ai_response = result.get("response", "").strip()

                # Always add disclaimer if not present
                if "not financial advice" not in ai_response.lower() and "educational" not in ai_response.lower():
                    ai_response += "\n\n*Disclaimer: This is educational information only, not financial advice. Always do your own research and consult a financial advisor.*"

                return jsonify(
                    {
                        "success": True,
                        "response": ai_response,
                        "model": result.get("model_used", "archie_bridge"),
                        "agent": "Stock & Market Expert",
                        "source": result.get("source", "ai_bridge"),
                        "tokens_used": result.get("tokens_used", 0),
                    }
                )
            else:
                logger.warning("archie_bridge returned error, falling back to direct Ollama")

        # Fallback: Direct Ollama call
        import requests as req

        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        model = data.get("model") or _default_model
        response = req.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": f"{STOCKBOT_SYSTEM_PROMPT}\n\nUser: {message}\n\nALPHA:",
                "stream": False,
                "options": {"temperature": 0.5, "num_predict": 1500},
            },
            timeout=90,
        )

        if response.status_code == 200:
            result = response.json()
            ai_response = result.get("response", "").strip()

            # Always add disclaimer if not present
            if "not financial advice" not in ai_response.lower() and "educational" not in ai_response.lower():
                ai_response += "\n\n*Disclaimer: This is educational information only, not financial advice. Always do your own research and consult a financial advisor.*"

            return jsonify(
                {
                    "success": True,
                    "response": ai_response,
                    "model": model,
                    "agent": "Direct Ollama (fallback)",
                    "source": "ollama_direct",
                }
            )
        else:
            logger.error(f"Ollama error: {response.status_code}")
            return (
                jsonify({"success": False, "error": "AI service temporarily unavailable"}),
                503,
            )

    except Exception as e:
        logger.error(f"StockBot chat error: {str(e)}")
        return (
            jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}),
            500,
        )


@stockbot_bp.route("/api/analyze", methods=["POST"])
def analyze_stock():
    """Get AI analysis of a stock ticker"""
    data = request.get_json() or {}
    ticker = data.get("ticker", "").upper()
    analysis_type = data.get("type", "overview")  # overview, fundamental, technical

    if not ticker:
        return jsonify({"success": False, "error": "Stock ticker is required"}), 400

    prompts = {
        "overview": f"""Provide an educational overview of {ticker}:
1. What company is this and what do they do?
2. What sector/industry are they in?
3. Key factors that typically affect this stock
4. Things an investor might want to research further

Remember: This is educational only, not investment advice.""",
        "fundamental": f"""Explain fundamental analysis concepts as they might apply to {ticker}:
1. What fundamental metrics are typically important for this type of company?
2. What would investors look at in their financial statements?
3. Key ratios to understand (P/E, P/S, debt-to-equity, etc.)
4. What competitive factors affect the business?

Remember: This is educational only, not investment advice.""",
        "technical": f"""Explain technical analysis concepts that traders might use for {ticker}:
1. Common chart patterns to be aware of
2. Popular technical indicators (RSI, MACD, moving averages)
3. Volume analysis basics
4. Support and resistance concepts

Remember: This is educational only, not a trading recommendation.""",
    }

    prompt = prompts.get(analysis_type, prompts["overview"])

    try:
        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        _analyze_model = _default_model or "dolphin3-8k:latest"
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": _analyze_model,
                "prompt": f"{STOCKBOT_SYSTEM_PROMPT}\n\n{prompt}\n\nALPHA:",
                "stream": False,
                "options": {"temperature": 0.4, "num_predict": 2000},
            },
            timeout=120,
        )

        if response.status_code == 200:
            result = response.json()
            if _dispatcher:
                try:
                    _dispatcher.log_external_call(
                        capability="conversation",
                        module_id="stockbot",
                        model_used=_analyze_model,
                        success=True,
                    )
                except Exception:
                    pass
            return jsonify(
                {
                    "success": True,
                    "ticker": ticker,
                    "analysis_type": analysis_type,
                    "analysis": result.get("response", "").strip(),
                }
            )
        else:
            return (
                jsonify({"success": False, "error": "Analysis service unavailable"}),
                503,
            )

    except Exception as e:
        logger.error(f"Stock analysis error: {str(e)}")
        return jsonify({"success": False, "error": "Could not complete analysis"}), 500


@stockbot_bp.route("/api/concepts", methods=["GET"])
def get_concepts():
    """Get list of educational stock market concepts"""
    concepts = {
        "basics": [
            {
                "id": "what_is_stock",
                "name": "What is a Stock?",
                "difficulty": "beginner",
            },
            {
                "id": "market_cap",
                "name": "Market Capitalization",
                "difficulty": "beginner",
            },
            {
                "id": "dividends",
                "name": "Dividends Explained",
                "difficulty": "beginner",
            },
            {
                "id": "bull_bear",
                "name": "Bull vs Bear Markets",
                "difficulty": "beginner",
            },
        ],
        "fundamental": [
            {"id": "pe_ratio", "name": "P/E Ratio", "difficulty": "intermediate"},
            {
                "id": "eps",
                "name": "Earnings Per Share (EPS)",
                "difficulty": "intermediate",
            },
            {
                "id": "revenue_profit",
                "name": "Revenue vs Profit",
                "difficulty": "beginner",
            },
            {
                "id": "balance_sheet",
                "name": "Reading Balance Sheets",
                "difficulty": "advanced",
            },
        ],
        "technical": [
            {
                "id": "candlesticks",
                "name": "Candlestick Charts",
                "difficulty": "intermediate",
            },
            {
                "id": "moving_averages",
                "name": "Moving Averages",
                "difficulty": "intermediate",
            },
            {"id": "rsi", "name": "RSI Indicator", "difficulty": "intermediate"},
            {
                "id": "support_resistance",
                "name": "Support & Resistance",
                "difficulty": "intermediate",
            },
        ],
        "strategies": [
            {
                "id": "value_investing",
                "name": "Value Investing",
                "difficulty": "intermediate",
            },
            {
                "id": "growth_investing",
                "name": "Growth Investing",
                "difficulty": "intermediate",
            },
            {
                "id": "dollar_cost_avg",
                "name": "Dollar-Cost Averaging",
                "difficulty": "beginner",
            },
            {
                "id": "diversification",
                "name": "Diversification",
                "difficulty": "beginner",
            },
        ],
        "risk": [
            {
                "id": "risk_management",
                "name": "Risk Management Basics",
                "difficulty": "intermediate",
            },
            {
                "id": "stop_loss",
                "name": "Stop-Loss Orders",
                "difficulty": "intermediate",
            },
            {
                "id": "position_sizing",
                "name": "Position Sizing",
                "difficulty": "advanced",
            },
            {
                "id": "volatility",
                "name": "Understanding Volatility",
                "difficulty": "intermediate",
            },
        ],
    }

    category = request.args.get("category")
    if category and category in concepts:
        return jsonify({"success": True, "category": category, "concepts": concepts[category]})

    return jsonify({"success": True, "concepts": concepts})


@stockbot_bp.route("/api/concept/<concept_id>", methods=["GET"])
def explain_concept(concept_id):
    """Get AI explanation of a specific concept"""
    concept_prompts = {
        "what_is_stock": "Explain what a stock is in simple terms, including ownership, shares, and how stock prices are determined.",
        "pe_ratio": "Explain the Price-to-Earnings (P/E) ratio, how to calculate it, and what high vs low P/E might indicate.",
        "moving_averages": "Explain moving averages in technical analysis, including SMA and EMA, and how traders use them.",
        "diversification": "Explain portfolio diversification, why it matters, and basic strategies for achieving it.",
        "dollar_cost_avg": "Explain dollar-cost averaging, how it works, and its pros and cons as an investment strategy.",
    }

    prompt = concept_prompts.get(concept_id)
    if not prompt:
        return jsonify({"success": False, "error": "Concept not found"}), 404

    try:
        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        _concept_model = _default_model or "dolphin3-8k:latest"
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": _concept_model,
                "prompt": f"{STOCKBOT_SYSTEM_PROMPT}\n\nExplain this concept for educational purposes:\n{prompt}\n\nALPHA:",
                "stream": False,
                "options": {"temperature": 0.5, "num_predict": 1500},
            },
            timeout=60,
        )

        if response.status_code == 200:
            result = response.json()
            if _dispatcher:
                try:
                    _dispatcher.log_external_call(
                        capability="conversation",
                        module_id="stockbot",
                        model_used=_concept_model,
                        success=True,
                    )
                except Exception:
                    pass
            return jsonify(
                {
                    "success": True,
                    "concept_id": concept_id,
                    "explanation": result.get("response", "").strip(),
                }
            )
        else:
            return jsonify({"success": False, "error": "Service unavailable"}), 503

    except Exception as e:
        logger.error(f"Concept explanation error: {str(e)}")
        return (
            jsonify({"success": False, "error": "Could not retrieve explanation"}),
            500,
        )


@stockbot_bp.route("/api/watchlist", methods=["GET", "POST", "DELETE"])
def manage_watchlist():
    """Manage user's stock watchlist"""
    if request.method == "GET":
        # In production, fetch from database
        # For now, return sample watchlist
        return jsonify(
            {
                "success": True,
                "watchlist": [
                    {"ticker": "AAPL", "name": "Apple Inc.", "added": "2026-01-15"},
                    {
                        "ticker": "MSFT",
                        "name": "Microsoft Corp.",
                        "added": "2026-01-14",
                    },
                    {"ticker": "GOOGL", "name": "Alphabet Inc.", "added": "2026-01-13"},
                ],
            }
        )

    elif request.method == "POST":
        data = request.get_json() or {}
        ticker = data.get("ticker", "").upper()

        if not ticker:
            return jsonify({"success": False, "error": "Ticker is required"}), 400

        # In production, save to database
        return jsonify({"success": True, "message": f"{ticker} added to watchlist"})

    elif request.method == "DELETE":
        data = request.get_json() or {}
        ticker = data.get("ticker", "").upper()

        if not ticker:
            return jsonify({"success": False, "error": "Ticker is required"}), 400

        # In production, remove from database
        return jsonify({"success": True, "message": f"{ticker} removed from watchlist"})


@stockbot_bp.route("/api/models", methods=["GET"])
def get_available_models():
    """Get available AI models via BridgeDispatcher"""
    # Models come from the bridge dispatcher
    models = []
    if _dispatcher:
        try:
            status = _dispatcher.get_dispatch_status()
            seen = set()
            for station_info in status.get("stations", {}).values():
                for agent in station_info.get("agents", []):
                    m = agent.get("model", "")
                    if m and m not in seen:
                        models.append({"name": m, "size": 0, "modified": ""})
                        seen.add(m)
        except Exception:
            pass
    if not models:
        models = [{"name": "default", "size": 0, "modified": ""}]
    return jsonify({"success": True, "models": models})

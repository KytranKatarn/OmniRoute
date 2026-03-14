"""
StockBot Routes - AI Stock Screener
Phase 1 backend: market data, portfolio, watchlist, alerts + AI chat
Phase 2 backend: 5-agent parallel analysis engine + analysis routes
Phase 3 backend: paper trading, strategies, Alpaca integration
Updated: 2026-03-14 - Added Phase 3 routes
"""

import re
import sys
import logging

from flask import render_template, jsonify, request
from flask_login import login_required, current_user

from . import stockbot_bp
from .services.market_data_service import (
    get_quote,
    get_history,
    get_company_info,
    batch_update_prices,
    search_tickers,
    calculate_indicators,
)
from .services.stock_analysis_service import (
    run_full_analysis,
    get_latest_analysis,
    get_analysis_history,
)
from .services.portfolio_service import (
    get_watchlist,
    add_to_watchlist,
    remove_from_watchlist,
    get_portfolio,
    get_portfolio_summary,
    record_transaction,
    get_transactions,
    create_alert,
    get_alerts,
    check_alerts,
)

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

# Fallback Ollama endpoint
OLLAMA_URL = "http://localhost:11434"

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

# Regex to detect tickers in messages (e.g. $AAPL, AAPL, MSFT)
_TICKER_RE = re.compile(r"\b\$?([A-Z]{1,5})\b")


def _extract_tickers(text: str) -> list:
    """Extract uppercase ticker candidates from a message."""
    stopwords = {"I", "A", "THE", "FOR", "AND", "OR", "IS", "IT", "IN", "ON", "AT", "TO", "MY"}
    found = []
    for m in _TICKER_RE.finditer(text.upper()):
        t = m.group(1)
        if t not in stopwords and len(t) >= 2:
            found.append(t)
    return list(dict.fromkeys(found))[:3]  # max 3 tickers


def _build_market_context(tickers: list) -> str:
    """Fetch live quotes for tickers and format as context string."""
    if not tickers:
        return ""
    lines = ["[Live Market Data]"]
    for ticker in tickers:
        try:
            q = get_quote(ticker)
            if q.get("price") is not None:
                price = q["price"]
                chg = q.get("change_pct")
                chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
                pe = q.get("pe_ratio")
                pe_str = f" | P/E: {pe:.1f}" if pe else ""
                lines.append(f"  {ticker}: ${price:.2f}{chg_str}{pe_str}")
        except Exception:
            pass
    return "\n".join(lines) if len(lines) > 1 else ""


# ─── Main page ────────────────────────────────────────────────────────────────


@stockbot_bp.route("/")
def index():
    """StockBot main page"""
    return render_template("tools/stockbot.html")


# ─── Status ───────────────────────────────────────────────────────────────────


@stockbot_bp.route("/api/status")
def status():
    """API endpoint for module health check"""
    import requests as req

    ollama_healthy = False
    try:
        response = req.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_healthy = response.status_code == 200
    except Exception:
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


# ─── AI Chat (upgraded with live market data injection) ───────────────────────


@stockbot_bp.route("/api/chat", methods=["POST"])
@login_required
def chat():
    """Send message to stock AI via archie_bridge, with live ticker data injected."""
    data = request.get_json() or {}
    message = data.get("message", "")
    user_id = current_user.id if current_user.is_authenticated else data.get("user_id", 1)

    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400

    # Inject live market context if tickers detected
    tickers = _extract_tickers(message)
    market_ctx = _build_market_context(tickers)

    # Inject latest analysis context for mentioned tickers (Phase 2)
    analysis_ctx_parts = []
    for ticker in tickers[:3]:
        try:
            latest = get_latest_analysis(ticker)
            if latest:
                sig = latest.get("overall_signal", "N/A")
                conf = latest.get("confidence", 0)
                pt = latest.get("price_target")
                thesis = latest.get("synthesis", {}).get("primary_thesis", "")
                analysis_ctx_parts.append(
                    f"[AI Analysis for {ticker}] Signal: {sig} | Confidence: {conf}% | "
                    f"Target: ${pt or 'N/A'} | {thesis[:200]}"
                )
        except Exception:
            pass
    analysis_ctx = "\n".join(analysis_ctx_parts)

    ctx_parts = [p for p in [market_ctx, analysis_ctx] if p]
    combined_ctx = "\n\n".join(ctx_parts)
    augmented_prompt = f"{combined_ctx}\n\n{message}".strip() if combined_ctx else message

    try:
        if BRIDGE_AVAILABLE:
            result = archie_bridge(
                prompt=augmented_prompt,
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
                        "tickers_detected": tickers,
                    }
                )

        # Fallback: Direct Ollama
        import requests as req

        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        model = data.get("model") or _default_model
        response = req.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": f"{STOCKBOT_SYSTEM_PROMPT}\n\n{augmented_prompt}\n\nALPHA:",
                "stream": False,
                "options": {"temperature": 0.5, "num_predict": 1500},
            },
            timeout=90,
        )

        if response.status_code == 200:
            result = response.json()
            ai_response = result.get("response", "").strip()
            if "not financial advice" not in ai_response.lower() and "educational" not in ai_response.lower():
                ai_response += "\n\n*Disclaimer: This is educational information only, not financial advice. Always do your own research and consult a financial advisor.*"
            return jsonify(
                {
                    "success": True,
                    "response": ai_response,
                    "model": model,
                    "agent": "Direct Ollama (fallback)",
                    "source": "ollama_direct",
                    "tickers_detected": tickers,
                }
            )
        else:
            return jsonify({"success": False, "error": "AI service temporarily unavailable"}), 503

    except Exception as e:
        logger.error(f"StockBot chat error: {e}")
        return jsonify({"success": False, "error": f"An unexpected error occurred: {e}"}), 500


# ─── Market Data Endpoints ────────────────────────────────────────────────────


@stockbot_bp.route("/api/quote/<ticker>", methods=["GET"])
@login_required
def api_quote(ticker):
    """GET /api/quote/<ticker> — latest price quote."""
    result = get_quote(ticker.upper())
    if result.get("error"):
        return jsonify({"success": False, "error": result["error"]}), 404
    return jsonify({"success": True, "quote": result})


@stockbot_bp.route("/api/history/<ticker>", methods=["GET"])
@login_required
def api_history(ticker):
    """GET /api/history/<ticker>?period=1mo&indicators=SMA20,RSI — OHLCV + optional indicators."""
    period = request.args.get("period", "1mo")
    indicators_param = request.args.get("indicators", "")
    indicator_list = [i.strip() for i in indicators_param.split(",") if i.strip()]

    ohlcv = get_history(ticker.upper(), period)
    result = {"ticker": ticker.upper(), "period": period, "ohlcv": ohlcv}

    if indicator_list and ohlcv:
        result["indicators"] = calculate_indicators(ohlcv, indicator_list)

    return jsonify({"success": True, **result})


@stockbot_bp.route("/api/search", methods=["GET"])
@login_required
def api_search():
    """GET /api/search?q=AAPL — ticker search."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"success": False, "error": "q parameter required"}), 400
    results = search_tickers(query)
    return jsonify({"success": True, "results": results})


@stockbot_bp.route("/api/company/<ticker>", methods=["GET"])
@login_required
def api_company(ticker):
    """GET /api/company/<ticker> — company info."""
    result = get_company_info(ticker.upper())
    if result.get("error"):
        return jsonify({"success": False, "error": result["error"]}), 404
    return jsonify({"success": True, "company": result})


# ─── Watchlist Endpoints ──────────────────────────────────────────────────────


@stockbot_bp.route("/api/watchlist", methods=["GET", "POST", "DELETE"])
@login_required
def api_watchlist():
    """GET/POST/DELETE /api/watchlist — manage user's watchlist."""
    user_id = current_user.id

    if request.method == "GET":
        items = get_watchlist(user_id)
        return jsonify({"success": True, "watchlist": items})

    elif request.method == "POST":
        data = request.get_json() or {}
        ticker = data.get("ticker", "").strip().upper()
        notes = data.get("notes")
        if not ticker:
            return jsonify({"success": False, "error": "ticker is required"}), 400
        result = add_to_watchlist(user_id, ticker, notes)
        return jsonify(result), 201

    elif request.method == "DELETE":
        data = request.get_json() or {}
        ticker = data.get("ticker", "").strip().upper()
        if not ticker:
            return jsonify({"success": False, "error": "ticker is required"}), 400
        removed = remove_from_watchlist(user_id, ticker)
        return jsonify({"success": removed, "ticker": ticker})


# ─── Portfolio Endpoints ──────────────────────────────────────────────────────


@stockbot_bp.route("/api/portfolio", methods=["GET"])
@login_required
def api_portfolio():
    """GET /api/portfolio — portfolio summary with P&L."""
    user_id = current_user.id
    summary = get_portfolio_summary(user_id)
    return jsonify({"success": True, **summary})


@stockbot_bp.route("/api/portfolio/trade", methods=["POST"])
@login_required
def api_trade():
    """POST /api/portfolio/trade — record a buy/sell transaction."""
    user_id = current_user.id
    data = request.get_json() or {}
    ticker = data.get("ticker", "").strip().upper()
    action = data.get("action", "").lower()
    shares = data.get("shares")
    price = data.get("price")
    paper_trade = data.get("paper_trade", True)

    if not all([ticker, action, shares, price]):
        return jsonify({"success": False, "error": "ticker, action, shares, price required"}), 400

    try:
        shares = float(shares)
        price = float(price)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "shares and price must be numeric"}), 400

    result = record_transaction(user_id, ticker, action, shares, price, paper_trade)
    if not result.get("success"):
        return jsonify(result), 400
    return jsonify(result), 201


@stockbot_bp.route("/api/transactions", methods=["GET"])
@login_required
def api_transactions():
    """GET /api/transactions?ticker=AAPL&limit=50 — transaction history."""
    user_id = current_user.id
    ticker = request.args.get("ticker")
    try:
        limit = int(request.args.get("limit", 50))
    except ValueError:
        limit = 50
    txns = get_transactions(user_id, ticker, limit)
    return jsonify({"success": True, "transactions": txns, "count": len(txns)})


# ─── Alerts Endpoints ─────────────────────────────────────────────────────────


@stockbot_bp.route("/api/alerts", methods=["GET", "POST"])
@login_required
def api_alerts():
    """GET/POST /api/alerts — list or create price alerts."""
    user_id = current_user.id

    if request.method == "GET":
        alerts = get_alerts(user_id)
        return jsonify({"success": True, "alerts": alerts})

    elif request.method == "POST":
        data = request.get_json() or {}
        ticker = data.get("ticker", "").strip().upper()
        condition = data.get("condition", "")
        threshold = data.get("threshold")

        if not all([ticker, condition, threshold is not None]):
            return jsonify({"success": False, "error": "ticker, condition, threshold required"}), 400

        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            return jsonify({"success": False, "error": "threshold must be numeric"}), 400

        result = create_alert(user_id, ticker, condition, threshold)
        if not result.get("success"):
            return jsonify(result), 400
        return jsonify(result), 201


# ─── Legacy / Educational Endpoints (kept from original) ─────────────────────


@stockbot_bp.route("/api/analyze", methods=["POST"])
@login_required
def analyze_stock():
    """Get AI analysis of a stock ticker"""
    data = request.get_json() or {}
    ticker = data.get("ticker", "").upper()
    analysis_type = data.get("type", "overview")

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
        import requests as req

        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        _analyze_model = _default_model or "dolphin3-8k:latest"
        response = req.post(
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
            return jsonify({"success": False, "error": "Analysis service unavailable"}), 503

    except Exception as e:
        logger.error(f"Stock analysis error: {e}")
        return jsonify({"success": False, "error": "Could not complete analysis"}), 500


@stockbot_bp.route("/api/concepts", methods=["GET"])
def get_concepts():
    """Get list of educational stock market concepts"""
    concepts = {
        "basics": [
            {"id": "what_is_stock", "name": "What is a Stock?", "difficulty": "beginner"},
            {"id": "market_cap", "name": "Market Capitalization", "difficulty": "beginner"},
            {"id": "dividends", "name": "Dividends Explained", "difficulty": "beginner"},
            {"id": "bull_bear", "name": "Bull vs Bear Markets", "difficulty": "beginner"},
        ],
        "fundamental": [
            {"id": "pe_ratio", "name": "P/E Ratio", "difficulty": "intermediate"},
            {"id": "eps", "name": "Earnings Per Share (EPS)", "difficulty": "intermediate"},
            {"id": "revenue_profit", "name": "Revenue vs Profit", "difficulty": "beginner"},
            {"id": "balance_sheet", "name": "Reading Balance Sheets", "difficulty": "advanced"},
        ],
        "technical": [
            {"id": "candlesticks", "name": "Candlestick Charts", "difficulty": "intermediate"},
            {"id": "moving_averages", "name": "Moving Averages", "difficulty": "intermediate"},
            {"id": "rsi", "name": "RSI Indicator", "difficulty": "intermediate"},
            {"id": "support_resistance", "name": "Support & Resistance", "difficulty": "intermediate"},
        ],
        "strategies": [
            {"id": "value_investing", "name": "Value Investing", "difficulty": "intermediate"},
            {"id": "growth_investing", "name": "Growth Investing", "difficulty": "intermediate"},
            {"id": "dollar_cost_avg", "name": "Dollar-Cost Averaging", "difficulty": "beginner"},
            {"id": "diversification", "name": "Diversification", "difficulty": "beginner"},
        ],
        "risk": [
            {"id": "risk_management", "name": "Risk Management Basics", "difficulty": "intermediate"},
            {"id": "stop_loss", "name": "Stop-Loss Orders", "difficulty": "intermediate"},
            {"id": "position_sizing", "name": "Position Sizing", "difficulty": "advanced"},
            {"id": "volatility", "name": "Understanding Volatility", "difficulty": "intermediate"},
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
        import requests as req

        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        _concept_model = _default_model or "dolphin3-8k:latest"
        response = req.post(
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
        logger.error(f"Concept explanation error: {e}")
        return jsonify({"success": False, "error": "Could not retrieve explanation"}), 500


@stockbot_bp.route("/api/models", methods=["GET"])
def get_available_models():
    """Get available AI models via BridgeDispatcher"""
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


# ─── Phase 2: AI Analysis Endpoints ─────────────────────────────────────────


@stockbot_bp.route("/api/analyze-full/<ticker>", methods=["POST"])
@login_required
def analyze_full(ticker):
    """Launch 5-agent parallel analysis in background thread. Returns immediately with analysis_id."""
    import threading

    ticker = ticker.upper().strip()
    user_id = current_user.id if current_user.is_authenticated else 1

    result_holder: dict = {}
    error_holder: dict = {}

    def _run():
        try:
            result_holder["result"] = run_full_analysis(ticker, user_id)
        except Exception as e:
            error_holder["error"] = str(e)
            logger.error(f"analyze_full background error for {ticker}: {e}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    # Give the thread a brief moment to catch immediate import/config errors
    t.join(timeout=0.5)

    if error_holder:
        return jsonify({"success": False, "error": error_holder["error"]}), 500

    # If already completed (fast path / cached data), return result directly
    if result_holder:
        r = result_holder["result"]
        if r.get("error"):
            return jsonify({"success": False, "error": r["error"]}), 500
        return jsonify(
            {
                "success": True,
                "analysis_id": r.get("analysis_id"),
                "ticker": ticker,
                "overall_signal": r.get("overall_signal"),
                "confidence": r.get("confidence"),
                "status": "complete",
            }
        )

    return jsonify(
        {
            "success": True,
            "analysis_id": None,
            "ticker": ticker,
            "status": "running",
            "message": f"5-agent analysis started for {ticker}. Poll /api/analysis/{ticker} for results.",
        }
    )


@stockbot_bp.route("/api/analysis/<ticker>", methods=["GET"])
@login_required
def get_analysis(ticker):
    """Get the latest AI analysis for a ticker."""
    ticker = ticker.upper().strip()
    try:
        analysis = get_latest_analysis(ticker)
        if not analysis:
            return jsonify({"success": False, "error": f"No analysis found for {ticker}"}), 404
        return jsonify({"success": True, "analysis": analysis})
    except Exception as e:
        logger.error(f"get_analysis({ticker}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@stockbot_bp.route("/api/analysis/<ticker>/history", methods=["GET"])
@login_required
def get_analysis_history_route(ticker):
    """Get historical analyses for a ticker."""
    ticker = ticker.upper().strip()
    limit = min(int(request.args.get("limit", 10)), 50)
    try:
        history = get_analysis_history(ticker, limit=limit)
        return jsonify({"success": True, "ticker": ticker, "history": history, "count": len(history)})
    except Exception as e:
        logger.error(f"get_analysis_history({ticker}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Phase 3: Paper Trading Routes ────────────────────────────────────────────

from .services.trading_service import (
    get_or_create_paper_account,
    paper_buy,
    paper_sell,
    get_pnl_summary,
    reset_paper_account,
)
from .services.strategy_service import (
    create_strategy,
    list_strategies,
    delete_strategy,
    toggle_strategy,
)


@stockbot_bp.route("/api/paper/account", methods=["GET"])
@login_required
def paper_account():
    """Get paper account balance and PnL summary."""
    user_id = current_user.id if current_user.is_authenticated else 1
    try:
        summary = get_pnl_summary(user_id)
        return jsonify({"success": True, "account": summary})
    except Exception as e:
        logger.error(f"paper_account({user_id}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@stockbot_bp.route("/api/paper/buy", methods=["POST"])
@login_required
def paper_buy_route():
    """Buy shares in paper account. Body: {ticker, shares}"""
    user_id = current_user.id if current_user.is_authenticated else 1
    data = request.get_json() or {}
    ticker = data.get("ticker", "").strip().upper()
    shares = data.get("shares")
    if not ticker or not shares:
        return jsonify({"success": False, "error": "ticker and shares are required"}), 400
    try:
        shares = float(shares)
        if shares <= 0:
            return jsonify({"success": False, "error": "shares must be positive"}), 400
        result = paper_buy(user_id, ticker, shares)
        return jsonify(result), 200 if result.get("success") else 400
    except (ValueError, TypeError) as e:
        return jsonify({"success": False, "error": f"Invalid shares value: {e}"}), 400
    except Exception as e:
        logger.error(f"paper_buy_route({user_id}, {ticker}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@stockbot_bp.route("/api/paper/sell", methods=["POST"])
@login_required
def paper_sell_route():
    """Sell shares from paper account. Body: {ticker, shares}"""
    user_id = current_user.id if current_user.is_authenticated else 1
    data = request.get_json() or {}
    ticker = data.get("ticker", "").strip().upper()
    shares = data.get("shares")
    if not ticker or not shares:
        return jsonify({"success": False, "error": "ticker and shares are required"}), 400
    try:
        shares = float(shares)
        if shares <= 0:
            return jsonify({"success": False, "error": "shares must be positive"}), 400
        result = paper_sell(user_id, ticker, shares)
        return jsonify(result), 200 if result.get("success") else 400
    except (ValueError, TypeError) as e:
        return jsonify({"success": False, "error": f"Invalid shares value: {e}"}), 400
    except Exception as e:
        logger.error(f"paper_sell_route({user_id}, {ticker}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@stockbot_bp.route("/api/paper/reset", methods=["POST"])
@login_required
def paper_reset():
    """Reset paper account to $100K and clear all positions."""
    user_id = current_user.id if current_user.is_authenticated else 1
    try:
        result = reset_paper_account(user_id)
        return jsonify(result)
    except Exception as e:
        logger.error(f"paper_reset({user_id}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


# ── Phase 3: Strategy Routes ──────────────────────────────────────────────────


@stockbot_bp.route("/api/strategies", methods=["GET"])
@login_required
def get_strategies():
    """List all strategies for the current user."""
    user_id = current_user.id if current_user.is_authenticated else 1
    try:
        strategies = list_strategies(user_id)
        return jsonify({"success": True, "strategies": strategies, "count": len(strategies)})
    except Exception as e:
        logger.error(f"get_strategies({user_id}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@stockbot_bp.route("/api/strategies", methods=["POST"])
@login_required
def create_strategy_route():
    """Create a new trading strategy. Body: {name, ticker, rules}"""
    user_id = current_user.id if current_user.is_authenticated else 1
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    ticker = data.get("ticker", "").strip().upper()
    rules = data.get("rules")
    if not name or not ticker or not rules:
        return jsonify({"success": False, "error": "name, ticker, and rules are required"}), 400
    if not isinstance(rules, dict) or "conditions" not in rules or "action" not in rules:
        return jsonify({"success": False, "error": "rules must have conditions and action keys"}), 400
    try:
        strategy_id = create_strategy(user_id, name, ticker, rules)
        return jsonify({"success": True, "strategy_id": strategy_id}), 201
    except Exception as e:
        logger.error(f"create_strategy_route({user_id}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@stockbot_bp.route("/api/strategies/<int:strategy_id>", methods=["DELETE"])
@login_required
def delete_strategy_route(strategy_id):
    """Delete a strategy (must be owned by current user)."""
    user_id = current_user.id if current_user.is_authenticated else 1
    try:
        result = delete_strategy(strategy_id, user_id)
        return jsonify(result), 200 if result.get("success") else 404
    except Exception as e:
        logger.error(f"delete_strategy_route({strategy_id}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@stockbot_bp.route("/api/strategies/<int:strategy_id>/toggle", methods=["POST"])
@login_required
def toggle_strategy_route(strategy_id):
    """Toggle is_active for a strategy."""
    user_id = current_user.id if current_user.is_authenticated else 1
    try:
        result = toggle_strategy(strategy_id, user_id)
        return jsonify(result), 200 if result.get("success") else 404
    except Exception as e:
        logger.error(f"toggle_strategy_route({strategy_id}) error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

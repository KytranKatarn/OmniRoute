"""Risk API routes — quant metrics at admin/viewer/public levels."""

from flask import Blueprint, jsonify

from auth import tier_required, admin_required
from services.quant_service import (
    calculate_kelly_fraction, calculate_var, calculate_correlations,
    calculate_diversification_score, get_portfolio_beta,
    calculate_risk_grade, refresh_all_metrics,
)

risk_bp = Blueprint("risk", __name__)


@risk_bp.route("/api/trading/risk-metrics")
@tier_required("ai")
@admin_required
def get_risk_metrics():
    """Full quant detail — admin only."""
    kelly = calculate_kelly_fraction()
    var_data = calculate_var()
    corr_data = calculate_correlations()
    div_score = calculate_diversification_score()
    port_beta = get_portfolio_beta()
    grade = calculate_risk_grade()

    return jsonify({
        "success": True,
        "kelly": kelly,
        "var": var_data,
        "correlations": corr_data,
        "diversification_score": div_score,
        "portfolio_beta": port_beta,
        "risk_grade": grade,
    })


@risk_bp.route("/api/trading/risk-metrics/refresh", methods=["POST"])
@tier_required("ai")
@admin_required
def refresh_risk():
    """Force recalculate all risk metrics."""
    grade = refresh_all_metrics()
    return jsonify({"success": True, "message": "Risk metrics refreshed", "risk_grade": grade})


@risk_bp.route("/api/trading/risk-summary")
@tier_required("viewer")
def get_risk_summary():
    """Simplified risk summary — viewer tier."""
    var_data = calculate_var()
    div_score = calculate_diversification_score()
    port_beta = get_portfolio_beta()
    grade = calculate_risk_grade()

    div_label = "Excellent" if div_score >= 80 else "Good" if div_score >= 60 else "Fair" if div_score >= 40 else "Poor"

    return jsonify({
        "success": True,
        "risk_grade": grade["grade"],
        "risk_label": grade["label"],
        "var_95_pct": var_data["var_95_pct"],
        "var_95_dollar": var_data["var_95_dollar"],
        "diversification_score": div_score,
        "diversification_label": div_label,
        "portfolio_beta": port_beta,
    })


@risk_bp.route("/api/public/risk-grade")
def get_public_risk_grade():
    """Public risk grade — no auth."""
    grade = calculate_risk_grade()
    return jsonify({
        "success": True,
        "grade": grade["grade"],
        "label": grade["label"],
        "score": grade["score"],
    })

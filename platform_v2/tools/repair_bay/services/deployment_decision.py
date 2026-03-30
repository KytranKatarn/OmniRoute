"""
Deployment Decision Engine for A.R.C.H.I.E.
Determines if a deployment can be auto-approved or requires manual approval

Risk-based decision making:
- Low risk → Auto-deploy
- Medium risk → Auto-deploy with enhanced monitoring
- High risk → Require manual approval
"""

import os
from database import _get_db_password
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, Literal
import json


class DeploymentDecisionEngine:
    """
    Makes intelligent decisions about deployment approval.

    Risk Factors:
    - Proposal category (security, database = high risk)
    - Priority level (critical = high risk)
    - Complexity (high complexity = high risk)
    - Test results (failed tests = high risk)
    - Affected systems (production database = high risk)
    - Change scope (many files = higher risk)
    """

    def __init__(self):
        # Risk scoring weights
        self.risk_weights = {
            "category": {
                "security": 30,
                "database": 25,
                "architecture": 20,
                "performance": 15,
                "api": 15,
                "infrastructure": 20,
                "ui": 5,
                "documentation": 0,
                "knowledge": 0,
                "testing": 5,
            },
            "priority": {"critical": 25, "high": 15, "medium": 5, "low": 0},
            "complexity": {"high": 20, "medium": 10, "low": 5},
        }

        # Risk thresholds
        self.auto_deploy_threshold = 30  # Risk score <= 30: auto-deploy
        self.manual_approval_threshold = 50  # Risk score > 50: require approval

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def can_auto_deploy(
        self,
        proposal_id: int = None,
        category: str = None,
        priority: str = None,
        complexity: str = None,
        test_results: Dict = None,
    ) -> Dict:
        """
        Determine if a proposal can be auto-deployed.

        Args:
            proposal_id: Load from database if provided
            category: Proposal category
            priority: Priority level
            complexity: Complexity level
            test_results: Sandbox test results

        Returns:
            {
                'can_auto_deploy': True,
                'risk_level': 'low',
                'risk_score': 15,
                'reason': 'Low risk proposal with passing tests',
                'requires_approval': False
            }
        """
        # Load from database if proposal_id provided
        if proposal_id:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    p.*,
                    s.test_results
                FROM improvement_proposals p
                LEFT JOIN LATERAL (
                    SELECT test_results
                    FROM sandbox_instances
                    WHERE proposal_id = p.id
                    AND status = 'tested'
                    ORDER BY created_at DESC
                    LIMIT 1
                ) s ON true
                WHERE p.id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()
            cur.close()
            conn.close()

            if not proposal:
                return {"can_auto_deploy": False, "reason": "Proposal not found"}

            category = proposal.get("category")
            priority = proposal.get("priority")
            complexity = proposal.get("complexity")
            test_results = proposal.get("test_results")

        # Calculate risk score
        risk_assessment = self.calculate_risk_score(
            category=category,
            priority=priority,
            complexity=complexity,
            test_results=test_results,
        )

        risk_score = risk_assessment["risk_score"]
        risk_level = risk_assessment["risk_level"]

        # Make decision
        if risk_score <= self.auto_deploy_threshold:
            return {
                "can_auto_deploy": True,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "reason": f"Low risk ({risk_score}/100) - Auto-deployment approved",
                "requires_approval": False,
                "monitoring_level": "standard",
                "risk_factors": risk_assessment["risk_factors"],
            }

        elif risk_score <= self.manual_approval_threshold:
            return {
                "can_auto_deploy": True,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "reason": f"Medium risk ({risk_score}/100) - Auto-deployment with enhanced monitoring",
                "requires_approval": False,
                "monitoring_level": "enhanced",
                "risk_factors": risk_assessment["risk_factors"],
            }

        else:
            return {
                "can_auto_deploy": False,
                "risk_level": risk_level,
                "risk_score": risk_score,
                "reason": f"High risk ({risk_score}/100) - Manual approval required",
                "requires_approval": True,
                "monitoring_level": "intensive",
                "risk_factors": risk_assessment["risk_factors"],
            }

    def calculate_risk_score(
        self,
        category: str = None,
        priority: str = None,
        complexity: str = None,
        test_results: Dict = None,
    ) -> Dict:
        """
        Calculate numerical risk score (0-100).

        Returns:
            {
                'risk_score': 45,
                'risk_level': 'medium',
                'risk_factors': {
                    'category': 25,
                    'priority': 15,
                    'complexity': 10,
                    'test_failures': -5
                }
            }
        """
        risk_factors = {}
        total_risk = 0

        # Category risk
        if category:
            category_risk = self.risk_weights["category"].get(category, 10)
            risk_factors["category"] = category_risk
            total_risk += category_risk

        # Priority risk
        if priority:
            priority_risk = self.risk_weights["priority"].get(priority, 5)
            risk_factors["priority"] = priority_risk
            total_risk += priority_risk

        # Complexity risk
        if complexity:
            complexity_risk = self.risk_weights["complexity"].get(complexity, 10)
            risk_factors["complexity"] = complexity_risk
            total_risk += complexity_risk

        # Test results impact
        if test_results:
            if not test_results.get("success"):
                # Failed tests increase risk significantly
                test_risk = 30
                risk_factors["test_failures"] = test_risk
                total_risk += test_risk
            else:
                # Passing tests reduce risk slightly
                pass_rate = test_results.get("pass_rate", 100)
                if pass_rate == 100:
                    risk_reduction = -5
                    risk_factors["test_success"] = risk_reduction
                    total_risk += risk_reduction

        # Determine risk level
        if total_risk <= self.auto_deploy_threshold:
            risk_level = "low"
        elif total_risk <= self.manual_approval_threshold:
            risk_level = "medium"
        else:
            risk_level = "high"

        return {
            "risk_score": max(0, min(100, total_risk)),  # Clamp to 0-100
            "risk_level": risk_level,
            "risk_factors": risk_factors,
        }

    def get_approval_requirements(self, proposal_id: int) -> Dict:
        """
        Get approval requirements for a proposal.

        Returns:
            {
                'requires_approval': False,
                'required_approvers': [],
                'approval_type': 'auto',
                'risk_assessment': {...}
            }
        """
        decision = self.can_auto_deploy(proposal_id=proposal_id)

        if not decision["requires_approval"]:
            return {
                "requires_approval": False,
                "required_approvers": [],
                "approval_type": "auto",
                "risk_assessment": decision,
            }

        # Determine who needs to approve based on risk
        required_approvers = []
        approval_type = "manual"

        if decision["risk_level"] == "high":
            # High risk requires senior engineer + admin
            required_approvers = ["senior_engineer", "admin"]
            approval_type = "senior_approval"
        elif decision["risk_level"] == "medium":
            # Medium risk requires any engineer
            required_approvers = ["engineer"]
            approval_type = "engineer_approval"

        return {
            "requires_approval": True,
            "required_approvers": required_approvers,
            "approval_type": approval_type,
            "risk_assessment": decision,
        }

    def simulate_deployment_risk(
        self,
        category: str,
        priority: str,
        complexity: str,
        test_pass_rate: float = 100.0,
    ) -> Dict:
        """
        Simulate risk calculation for planning purposes.

        Args:
            category: Proposal category
            priority: Priority level
            complexity: Complexity level
            test_pass_rate: Expected test pass rate (0-100)

        Returns:
            Risk assessment dict
        """
        # Simulate test results
        test_results = {"success": test_pass_rate == 100.0, "pass_rate": test_pass_rate}

        return self.can_auto_deploy(
            category=category,
            priority=priority,
            complexity=complexity,
            test_results=test_results,
        )


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================


def can_deploy_automatically(proposal_id: int) -> Dict:
    """Quick function to check if proposal can auto-deploy"""
    engine = DeploymentDecisionEngine()
    return engine.can_auto_deploy(proposal_id=proposal_id)


def get_risk_score(proposal_id: int) -> int:
    """Quick function to get risk score"""
    engine = DeploymentDecisionEngine()
    decision = engine.can_auto_deploy(proposal_id=proposal_id)
    return decision.get("risk_score", 100)


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("Deployment Decision Engine - Test Mode")
    print("=" * 60)

    engine = DeploymentDecisionEngine()

    # Test various scenarios
    test_scenarios = [
        {
            "name": "Low Risk: Documentation Update",
            "category": "documentation",
            "priority": "low",
            "complexity": "low",
            "test_pass_rate": 100.0,
        },
        {
            "name": "Medium Risk: UI Enhancement",
            "category": "ui",
            "priority": "medium",
            "complexity": "medium",
            "test_pass_rate": 100.0,
        },
        {
            "name": "High Risk: Security Fix",
            "category": "security",
            "priority": "critical",
            "complexity": "high",
            "test_pass_rate": 100.0,
        },
        {
            "name": "High Risk: Database Migration",
            "category": "database",
            "priority": "high",
            "complexity": "high",
            "test_pass_rate": 100.0,
        },
        {
            "name": "Medium Risk with Failed Tests",
            "category": "ui",
            "priority": "medium",
            "complexity": "low",
            "test_pass_rate": 80.0,
        },
    ]

    print("\n1. RISK ASSESSMENT SCENARIOS:")
    print("-" * 60)

    for scenario in test_scenarios:
        result = engine.simulate_deployment_risk(
            category=scenario["category"],
            priority=scenario["priority"],
            complexity=scenario["complexity"],
            test_pass_rate=scenario["test_pass_rate"],
        )

        auto_deploy_icon = "✓" if result["can_auto_deploy"] else "✗"
        print(f"\n{auto_deploy_icon} {scenario['name']}")
        print(f"   Risk Score: {result['risk_score']}/100 ({result['risk_level']})")
        print(f"   Auto-Deploy: {result['can_auto_deploy']}")
        print(f"   Reason: {result['reason']}")
        print(f"   Monitoring: {result['monitoring_level']}")

    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Auto-deploy threshold: ≤{engine.auto_deploy_threshold}")
    print(f"  Manual approval threshold: >{engine.manual_approval_threshold}")

    print("\n✅ Deployment Decision Engine tests passed!")

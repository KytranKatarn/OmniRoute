"""
Collaborative Report Generator
Generates comprehensive reports from multi-agent discussions and evaluations

Author: A.R.C.H.I.E.
Date: 2026-01-01
Purpose: Synthesize team discussions into actionable reports for both technical and management audiences
"""

import os
import sys
import json
from decimal import Decimal
from datetime import datetime
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from platform_v2.database import get_db
from ai_bridge.team_discussion_engine import TeamDiscussionEngine


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)


class CollaborativeReportGenerator:
    """Generates comprehensive reports from team discussions and consensus"""

    def __init__(self):
        self.discussion_engine = TeamDiscussionEngine()

    def generate_executive_summary(self, discussion_id: int) -> Optional[str]:
        """
        Generate a concise executive summary for management

        Args:
            discussion_id: ID of the discussion

        Returns:
            Formatted executive summary string
        """
        try:
            summary = self.discussion_engine.get_discussion_summary(discussion_id)
            if not summary:
                return None

            discussion = summary["discussion"]
            consensus = summary.get("consensus")
            evaluations = summary.get("evaluations", [])

            # Build executive summary
            report = []
            report.append("=" * 80)
            report.append("EXECUTIVE SUMMARY")
            report.append("=" * 80)
            report.append("")

            # Proposal Information
            report.append(f"Proposal: {discussion['proposal_title']}")
            report.append(f"Discussion Topic: {discussion['topic']}")
            report.append(f"Date: {discussion['started_at']}")
            report.append("")

            # Team Recommendation
            if consensus:
                recommendation = consensus["final_recommendation"].upper()
                score = consensus["score"] * 100
                report.append(f"TEAM RECOMMENDATION: {recommendation} (Consensus: {score:.0f}%)")
                report.append("")

                # Key Points
                report.append("KEY BENEFITS:")
                for i, benefit in enumerate(consensus["benefits"][:5], 1):
                    report.append(f"  {i}. {benefit}")
                report.append("")

                report.append("KEY RISKS:")
                for i, risk in enumerate(consensus["risks"][:5], 1):
                    report.append(f"  {i}. {risk}")
                report.append("")

                # Voting Breakdown
                total = consensus["approvals"] + consensus["rejections"]
                report.append("TEAM CONSENSUS BREAKDOWN:")
                report.append(f"  • Approve: {consensus['approvals']}/{total} agents")
                report.append(f"  • Reject: {consensus['rejections']}/{total} agents")
                report.append("")

            # Agent Summaries (Manager-Friendly)
            if evaluations:
                report.append("AGENT EVALUATIONS (Non-Technical):")
                for eval_data in evaluations[:5]:  # Top 5 evaluations
                    agent_name = eval_data["agent_name"]
                    rec = eval_data["recommendation"].upper()
                    summary_text = eval_data["manager_summary"] or "No summary provided"
                    report.append(f"\n  {agent_name} - {rec}:")
                    report.append(f"  {summary_text}")
                report.append("")

            # Bottom Line
            report.append("-" * 80)
            if consensus:
                if consensus["final_recommendation"] == "approved":
                    report.append("BOTTOM LINE: The team recommends proceeding with this proposal.")
                elif consensus["final_recommendation"] == "rejected":
                    report.append("BOTTOM LINE: The team recommends rejecting this proposal.")
                else:
                    report.append("BOTTOM LINE: The team recommends revisions before proceeding.")
            report.append("=" * 80)

            return "\n".join(report)

        except Exception as e:
            print(f"Error generating executive summary: {e}")
            import traceback

            traceback.print_exc()
            return None

    def generate_technical_report(self, discussion_id: int) -> Optional[str]:
        """
        Generate detailed technical report for developers

        Args:
            discussion_id: ID of the discussion

        Returns:
            Formatted technical report string
        """
        try:
            summary = self.discussion_engine.get_discussion_summary(discussion_id)
            if not summary:
                return None

            discussion = summary["discussion"]
            messages = summary.get("messages", [])
            evaluations = summary.get("evaluations", [])
            consensus = summary.get("consensus")

            # Build technical report
            report = []
            report.append("=" * 80)
            report.append("TECHNICAL ANALYSIS REPORT")
            report.append("=" * 80)
            report.append("")

            # Proposal Details
            report.append(f"Proposal ID: {discussion['proposal_id']}")
            report.append(f"Title: {discussion['proposal_title']}")
            report.append(f"Discussion: {discussion['topic']}")
            report.append(f"Status: {discussion['status']}")
            report.append(f"Started: {discussion['started_at']}")
            if discussion["ended_at"]:
                report.append(f"Ended: {discussion['ended_at']}")
            report.append("")

            # Consensus Analysis
            if consensus:
                report.append("-" * 80)
                report.append("CONSENSUS ANALYSIS")
                report.append("-" * 80)
                report.append(f"Final Recommendation: {consensus['final_recommendation'].upper()}")
                report.append(f"Consensus Score: {consensus['score']:.2f} ({consensus['score']*100:.0f}%)")
                report.append(f"Voting Results: {consensus['approvals']} approve, {consensus['rejections']} reject")
                report.append("")

            # Technical Evaluations
            if evaluations:
                report.append("-" * 80)
                report.append("AGENT EVALUATIONS (Technical)")
                report.append("-" * 80)

                for eval_data in evaluations:
                    report.append("")
                    report.append(f"Agent: {eval_data['agent_name']}")
                    report.append(f"Recommendation: {eval_data['recommendation'].upper()}")
                    report.append(f"Confidence: {eval_data['confidence']:.0%}")
                    report.append(f"Risk Assessment: {eval_data['risk'].upper()}")
                    report.append("")

                    if eval_data["technical_notes"]:
                        report.append("Technical Analysis:")
                        report.append(f"  {eval_data['technical_notes']}")
                        report.append("")

                    if eval_data["concerns"]:
                        report.append("Concerns:")
                        for concern in eval_data["concerns"]:
                            report.append(f"  • {concern}")
                        report.append("")

                    if eval_data["benefits"]:
                        report.append("Benefits:")
                        for benefit in eval_data["benefits"]:
                            report.append(f"  • {benefit}")
                        report.append("")

                    report.append("-" * 40)

            # Discussion Messages
            if messages:
                report.append("")
                report.append("-" * 80)
                report.append("DISCUSSION TRANSCRIPT")
                report.append("-" * 80)

                for msg in messages:
                    report.append("")
                    report.append(f"[{msg['created_at']}] {msg['agent_name']} ({msg['type']})")
                    report.append(f"Confidence: {msg['confidence']:.0%}")
                    report.append(f"Message: {msg['message']}")
                    report.append("-" * 40)

            report.append("")
            report.append("=" * 80)
            report.append("END OF TECHNICAL REPORT")
            report.append("=" * 80)

            return "\n".join(report)

        except Exception as e:
            print(f"Error generating technical report: {e}")
            import traceback

            traceback.print_exc()
            return None

    def generate_consensus_visual(self, discussion_id: int) -> Optional[Dict]:
        """
        Generate data structure for visual consensus display

        Args:
            discussion_id: ID of the discussion

        Returns:
            Dictionary with visualization data
        """
        try:
            consensus_score, stats = self.discussion_engine.calculate_consensus(discussion_id)

            if "error" in stats:
                return None

            # Create visualization data
            visual_data = {
                "consensus_score": consensus_score,
                "recommendation": stats["final_recommendation"],
                "voting": {
                    "approve": stats["approval_count"],
                    "reject": stats["rejection_count"],
                    "needs_changes": stats["needs_changes_count"],
                    "needs_testing": stats["needs_testing_count"],
                    "total": stats["total_evaluations"],
                },
                "confidence": {
                    "average": stats["avg_confidence"],
                    "level": (
                        "high"
                        if stats["avg_confidence"] >= 0.8
                        else "medium" if stats["avg_confidence"] >= 0.6 else "low"
                    ),
                },
                "risk": {
                    "level": stats["highest_risk"],
                    "color": {
                        "low": "#00FF00",
                        "medium": "#FFFF00",
                        "high": "#FFA500",
                        "critical": "#FF0000",
                    }.get(stats["highest_risk"], "#FFFF00"),
                },
                "summary": {
                    "top_concerns": stats["all_concerns"][:5],
                    "top_benefits": stats["all_benefits"][:5],
                    "participating_agents": len(stats["participating_agents"]),
                },
            }

            return visual_data

        except Exception as e:
            print(f"Error generating consensus visual: {e}")
            import traceback

            traceback.print_exc()
            return None

    def generate_notification_report(self, discussion_id: int) -> Optional[Dict]:
        """
        Generate a compact report suitable for notifications

        Args:
            discussion_id: ID of the discussion

        Returns:
            Dictionary with notification data
        """
        try:
            summary = self.discussion_engine.get_discussion_summary(discussion_id)
            if not summary:
                return None

            discussion = summary["discussion"]
            consensus = summary.get("consensus")
            evaluations = summary.get("evaluations", [])

            # Build notification report
            notification = {
                "proposal_id": discussion["proposal_id"],
                "proposal_title": discussion["proposal_title"],
                "discussion_topic": discussion["topic"],
                "status": discussion["status"],
                "consensus_reached": discussion["consensus_reached"],
            }

            if consensus:
                notification["recommendation"] = consensus["final_recommendation"]
                notification["consensus_score"] = consensus["score"]
                notification["vote_summary"] = f"{consensus['approvals']} approve, {consensus['rejections']} reject"

                # Quick summary
                if consensus["final_recommendation"] == "approved":
                    notification["quick_summary"] = f"✅ Team approved with {consensus['score']:.0%} consensus"
                elif consensus["final_recommendation"] == "rejected":
                    notification["quick_summary"] = f"❌ Team rejected with {consensus['score']:.0%} consensus"
                else:
                    notification["quick_summary"] = f"⚠️ Team recommends revisions ({consensus['score']:.0%} consensus)"

                # Top concern and benefit
                if consensus["risks"]:
                    notification["top_concern"] = consensus["risks"][0]
                if consensus["benefits"]:
                    notification["top_benefit"] = consensus["benefits"][0]

            # Agent count
            notification["agents_participated"] = len(evaluations)

            return notification

        except Exception as e:
            print(f"Error generating notification report: {e}")
            import traceback

            traceback.print_exc()
            return None

    def generate_full_report(
        self,
        discussion_id: int,
        include_executive: bool = True,
        include_technical: bool = True,
        include_visual: bool = True,
        include_notification: bool = True,
    ) -> Optional[Dict]:
        """
        Generate a comprehensive report with all sections

        Args:
            discussion_id: ID of the discussion
            include_executive: Include executive summary
            include_technical: Include technical report
            include_visual: Include visualization data
            include_notification: Include notification data

        Returns:
            Dictionary containing all requested report sections
        """
        try:
            full_report = {
                "discussion_id": discussion_id,
                "generated_at": datetime.now().isoformat(),
                "generator": "A.R.C.H.I.E. Collaborative Report Generator v1.0",
            }

            if include_executive:
                full_report["executive_summary"] = self.generate_executive_summary(discussion_id)

            if include_technical:
                full_report["technical_report"] = self.generate_technical_report(discussion_id)

            if include_visual:
                full_report["visual_data"] = self.generate_consensus_visual(discussion_id)

            if include_notification:
                full_report["notification_data"] = self.generate_notification_report(discussion_id)

            # Add raw discussion summary
            full_report["raw_data"] = self.discussion_engine.get_discussion_summary(discussion_id)

            return full_report

        except Exception as e:
            print(f"Error generating full report: {e}")
            import traceback

            traceback.print_exc()
            return None

    def save_report_to_database(self, discussion_id: int, report_data: Dict) -> bool:
        """
        Save generated report to database metadata

        Args:
            discussion_id: ID of the discussion
            report_data: Report data to save

        Returns:
            True if successful, False otherwise
        """
        try:
            conn = get_db()
            cur = conn.cursor()

            # Store report in discussion metadata
            cur.execute(
                """
                UPDATE agent_discussions
                SET metadata = jsonb_set(
                    COALESCE(metadata, '{}'::jsonb),
                    '{generated_reports}',
                    %s::jsonb,
                    true
                )
                WHERE id = %s
            """,
                (
                    json.dumps(report_data, cls=DecimalEncoder),  # Properly serialize with Decimal handling
                    discussion_id,
                ),
            )

            conn.commit()
            cur.close()
            conn.close()

            print(f"✅ Report saved to discussion #{discussion_id} metadata")
            return True

        except Exception as e:
            print(f"Error saving report: {e}")
            import traceback

            traceback.print_exc()
            return False


# Convenience functions for easy import
def generate_management_report(discussion_id: int) -> Optional[str]:
    """Generate executive summary for management"""
    generator = CollaborativeReportGenerator()
    return generator.generate_executive_summary(discussion_id)


def generate_developer_report(discussion_id: int) -> Optional[str]:
    """Generate technical report for developers"""
    generator = CollaborativeReportGenerator()
    return generator.generate_technical_report(discussion_id)


def generate_complete_report(discussion_id: int) -> Optional[Dict]:
    """Generate complete report with all sections"""
    generator = CollaborativeReportGenerator()
    return generator.generate_full_report(discussion_id)


def get_notification_data(discussion_id: int) -> Optional[Dict]:
    """Get compact notification data for a discussion"""
    generator = CollaborativeReportGenerator()
    return generator.generate_notification_report(discussion_id)


if __name__ == "__main__":
    # Test the report generator
    print("🧪 Testing Collaborative Report Generator...")

    generator = CollaborativeReportGenerator()

    # Example usage:
    # report = generator.generate_full_report(discussion_id=1)
    # print(report['executive_summary'])
    # print(report['technical_report'])
    # print(report['visual_data'])
    # print(report['notification_data'])

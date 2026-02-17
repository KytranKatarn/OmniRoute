"""
A.R.C.H.I.E. Improvement Scheduler
Runs automatic improvement detection on a schedule
"""

import schedule
import time
import sys
from datetime import datetime

sys.path.insert(0, "/app/ai_bridge")
from improvement_engine import run_auto_improvement_detection
from improvement_chat import self_reflection_chat


def scheduled_improvement_detection():
    """Run scheduled improvement detection"""
    print(f"\n{'='*80}")
    print(f"🔍 Scheduled Improvement Detection - {datetime.now().isoformat()}")
    print(f"{'='*80}")

    try:
        summary = run_auto_improvement_detection()

        print(f"\n✅ Detection complete!")
        print(f"   Opportunities detected: {summary['opportunities_detected']}")
        print(f"   Proposals created: {summary['proposals_created']}")

        if summary["breakdown"]:
            print(f"\n📊 Breakdown:")
            for opp_type, count in summary["breakdown"].items():
                print(f"   - {opp_type}: {count}")

    except Exception as e:
        print(f"\n❌ Error during detection: {e}")
        import traceback

        traceback.print_exc()


def scheduled_self_reflection():
    """Run scheduled self-reflection"""
    print(f"\n{'='*80}")
    print(f"🪞 Scheduled Self-Reflection - {datetime.now().isoformat()}")
    print(f"{'='*80}")

    try:
        result = self_reflection_chat(topic="overall performance")

        if result.get("success"):
            print(f"\n✅ Self-reflection complete!")
            print(
                f"   Personality state: {result['personality'].get('personality_summary', 'Unknown')}"
            )
            print(f"   Opportunities found: {result['opportunities_count']}")
            print(f"\n💭 Reflection excerpt:")
            print(f"   {result['reflection'][:200]}...")
        else:
            print(f"\n❌ Self-reflection failed: {result.get('error')}")

    except Exception as e:
        print(f"\n❌ Error during self-reflection: {e}")
        import traceback

        traceback.print_exc()


def run_scheduler():
    """Main scheduler loop"""
    print("🤖 A.R.C.H.I.E. Improvement Scheduler Started")
    print("=" * 80)
    print("\nScheduled tasks:")
    print("  - Improvement detection: Every 6 hours")
    print("  - Self-reflection: Daily at 00:00")
    print("\nPress Ctrl+C to stop")
    print("=" * 80)

    # Schedule improvement detection every 6 hours
    schedule.every(6).hours.do(scheduled_improvement_detection)

    # Schedule self-reflection daily at midnight
    schedule.every().day.at("00:00").do(scheduled_self_reflection)

    # Run immediate detection on startup
    print("\n🚀 Running initial improvement detection...")
    scheduled_improvement_detection()

    # Main loop
    while True:
        schedule.run_pending()
        time.sleep(60)  # Check every minute


if __name__ == "__main__":
    try:
        run_scheduler()
    except KeyboardInterrupt:
        print("\n\n👋 Scheduler stopped by user")
    except Exception as e:
        print(f"\n\n❌ Scheduler error: {e}")
        import traceback

        traceback.print_exc()

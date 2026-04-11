"""Inline the plan generation logic with visible logging."""
import sys
import time
import logging

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

from tools.security_network import compliance_service

# Force the service's logger to DEBUG
compliance_service.logger.setLevel(logging.DEBUG)
for h in logging.root.handlers:
    h.setLevel(logging.DEBUG)

print("Calling generate_remediation_plan...")
t0 = time.time()
res = compliance_service.generate_remediation_plan(
    "7d4ccdf3-a948-41a4-8fb7-31beaae4f101", "D-238013", user_id=2
)
print(f"\nelapsed: {round(time.time()-t0,1)}s")
print(f"plan_id: {res.get('plan_id')}  fallback: {res.get('fallback')}")
plan = res.get("plan") or {}
print(f"steps: {len(plan.get('steps') or [])}")
print(f"impact: {(plan.get('impact_analysis') or '')[:200]}")

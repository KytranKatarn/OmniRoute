"""Test AI plan generation for D-238002 (userns-remap)."""

import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

sys.path.insert(0, "/app")
sys.path.insert(0, "/app/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")

from tools.security_network import compliance_service

print("Generating plan for D-238002 (userns-remap)...")
t0 = time.time()
res = compliance_service.generate_remediation_plan("ad6d727e-a7a9-4fab-8f1f-46a9d540c7bb", "D-238002", user_id=2)
elapsed = round(time.time() - t0, 1)
print(f"\nelapsed: {elapsed}s")
print(f"plan_id: {res.get('plan_id')}  fallback: {res.get('fallback')}  success: {res.get('success')}")

plan = res.get("plan") or {}
print(f"\nmodel_used:         {plan.get('model_used', 'n/a')}")
print(f"estimated_downtime: {plan.get('estimated_downtime')}")
print(f"best_window:        {plan.get('best_window')}")
print(f"exemption_candidate:{plan.get('exemption_candidate')}")
print(f"affected_containers:{plan.get('affected_containers')}")
print(f"prerequisites_count:{len(plan.get('prerequisites') or [])}")
print(f"steps_count:        {len(plan.get('steps') or [])}")
print(f"\nimpact_analysis:\n{(plan.get('impact_analysis') or '')[:500]}")
print(f"\nrollback_plan:\n{(plan.get('rollback_plan') or '')[:300]}")
print(f"\nsteps:")
for i, s in enumerate(plan.get("steps") or []):
    print(f"  {i+1}. [{'SAFE' if s.get('safe_auto') else 'MANUAL'}] {s.get('action', '')}")
    if s.get("why"):
        print(f"     why: {s.get('why', '')[:150]}")

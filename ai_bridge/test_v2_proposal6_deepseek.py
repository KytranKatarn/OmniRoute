#!/usr/bin/env python3
"""
Test V2 Code Generation Engine on Proposal #6 with DeepSeek Coder
"""

import sys

sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

print("=" * 60)
print("V2 ENGINE TEST - PROPOSAL #6 with DEEPSEEK-CODER-V2:16B")
print("=" * 60)

from code_generation_engine import CodeGenerationEngine


# Override the model selection to use deepseek-coder-v2:16b
class TestEngine(CodeGenerationEngine):
    def _select_model_for_task(self, category, prefer_contractor):
        return "deepseek-coder-v2:16b"


engine = TestEngine()
print(f"Engine ready. Using: deepseek-coder-v2:16b")

# Get context around line 43
print("\nFile context around line 43:")
context = engine._read_file_content("platform_v2/tools/coderabbit/routes.py", 43)
if context["exists"]:
    for line in context["context"].split("\n")[10:18]:
        print(f"  {line}")

# Run V2 generation
print("\n" + "-" * 60)
print("Running V2 code generation...")
print("-" * 60)

result = engine.generate_with_validation(
    proposal_id=6,
    proposal_title="[CodeRabbit] Fix quality issue in routes.py",
    proposal_description="""Bare except clause catches all exceptions without specifying an exception type.

The bare except at line 43 should be changed to: except Exception:

This is a simple one-line fix - just add 'Exception' after 'except'.""",
    category="code_quality",
    target_files=["platform_v2/tools/coderabbit/routes.py"],
    line_number=43,
    prefer_contractor=False,
)

print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)
print(f"Success: {result.get('success')}")
print(f"Changes: {len(result.get('changes', []))}")

if result.get("metadata"):
    meta = result["metadata"]
    print(f"Model: {meta.get('model_used', 'N/A')}")
    print(f"Validation: {meta.get('validation_enabled', False)}")

if result.get("validation_results"):
    print("\nValidation:")
    for vr in result["validation_results"]:
        if vr.get("valid"):
            print(f"  ✅ {vr.get('file_path')}: {vr.get('match_type', 'valid')}")
        else:
            print(f"  ❌ {vr.get('file_path')}: {vr.get('error', 'unknown')}")

if result.get("changes"):
    for i, change in enumerate(result["changes"], 1):
        print(f"\n--- Change {i} ---")
        print(f"File: {change.get('file_path')}")
        print(f"Description: {change.get('description', 'N/A')}")
        print(f"\nOld content:")
        if change.get("old_content"):
            for line in change["old_content"].split("\n"):
                print(f"  |{line}|")
        print(f"\nNew content:")
        if change.get("new_content"):
            for line in change["new_content"].split("\n"):
                print(f"  |{line}|")

print("\nDone.")

#!/usr/bin/env python3
"""
Test V2 Code Generation Engine on Proposal #4 (SQL Injection Fix)
"""
import sys
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
sys.path.insert(0, "/mnt/archie_brain/platform_v2")

print("=" * 60)
print("V2 ENGINE TEST - PROPOSAL #4 (SQL INJECTION)")
print("=" * 60)

from code_generation_engine import CodeGenerationEngine

engine = CodeGenerationEngine()
print(f"Engine ready. Validator: {engine.validator is not None}")

# Validate target file exists
print("\nValidating target file...")
validation = engine._validate_target_files(["platform_v2/agent_management_api.py"])
print(f"  Valid files: {len(validation['valid_files'])}")
if validation['valid_files']:
    print(f"  Full path: {validation['valid_files'][0]['full_path']}")

# Get context around line 152
print("\nReading context around line 152...")
context = engine._read_file_content("platform_v2/agent_management_api.py", 152)
if context["exists"]:
    print("  Context preview:")
    for line in context["context"].split("\n")[:10]:
        print(f"    {line}")

# Run V2 generation
print("\n" + "-" * 60)
print("Running V2 code generation (may take 1-2 minutes)...")
print("-" * 60)

result = engine.generate_with_validation(
    proposal_id=4,
    proposal_title="[SECURITY] SQL injection fix",
    proposal_description="""Fix potential SQL injection at line 152 in agent_management_api.py.
Ensure parameterized queries are used.""",
    category="security",
    target_files=["platform_v2/agent_management_api.py"],
    line_number=152,
    prefer_contractor=False
)

print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)
print(f"Success: {result.get('success')}")
print(f"Changes: {len(result.get('changes', []))}")

if result.get("metadata"):
    meta = result["metadata"]
    print(f"Model: {meta.get('model_used', 'N/A')}")
    print(f"Retries: {meta.get('retries_used', 0)}")
    print(f"Validation: {meta.get('validation_enabled', False)}")

if result.get("validation_results"):
    print("\nValidation results:")
    for vr in result["validation_results"]:
        print(f"  {vr}")

if result.get("changes"):
    for i, change in enumerate(result["changes"], 1):
        print(f"\n--- Change {i} ---")
        print(f"File: {change.get('file_path')}")
        print(f"Action: {change.get('action')}")
        print(f"Description: {change.get('description', 'N/A')}")
        if change.get('old_content'):
            preview = change['old_content'][:200].replace('\n', '\\n')
            print(f"Old: {preview}...")
        if change.get('new_content'):
            preview = change['new_content'][:200].replace('\n', '\\n')
            print(f"New: {preview}...")

if result.get("error"):
    print(f"\nError: {result['error']}")

print("\nDone.")

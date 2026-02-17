"""
Code Application System
Applies generated code changes to sandbox environment

Author: A.R.C.H.I.E. Self-Improvement System
Date: 2026-01-05
"""

import os
import shutil
from typing import Dict, List
from datetime import datetime


class CodeApplicationSystem:
    """Applies code changes to sandbox files"""

    def __init__(self, sandbox_schema: str = "sandbox"):
        self.sandbox_schema = sandbox_schema
        self.base_path = "/mnt/archie_brain/platform_v2"
        self.backup_path = "/mnt/archie_brain/backups/sandbox_changes"
        os.makedirs(self.backup_path, exist_ok=True)

    def apply_changes_to_sandbox(self, proposal_id: int, changes: List[Dict]) -> Dict:
        """
        Apply code changes to sandbox files

        Args:
            proposal_id: Proposal ID for tracking
            changes: List of change dicts from code generation

        Returns:
            {
                'success': bool,
                'files_modified': int,
                'files_created': int,
                'backup_path': str,
                'application_log': list,
                'errors': list
            }
        """
        application_log = []
        errors = []
        files_modified = 0
        files_created = 0

        # Create backup directory for this application
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(self.backup_path, f"proposal_{proposal_id}_{timestamp}")
        os.makedirs(backup_dir, exist_ok=True)

        application_log.append(f"🔄 Applying {len(changes)} code change(s) to sandbox...")
        application_log.append(f"💾 Backup directory: {backup_dir}")

        for i, change in enumerate(changes, 1):
            try:
                result = self._apply_single_change(change, backup_dir, i, len(changes))

                application_log.extend(result["log"])

                if result["success"]:
                    if change["action"] == "create":
                        files_created += 1
                    else:
                        files_modified += 1
                else:
                    errors.append(result.get("error", "Unknown error"))

            except Exception as e:
                error_msg = f"❌ Error applying change {i}: {str(e)}"
                application_log.append(error_msg)
                errors.append(error_msg)

        success = len(errors) == 0
        application_log.append("")
        application_log.append("=" * 60)
        if success:
            application_log.append(f"✅ All changes applied successfully!")
        else:
            application_log.append(f"⚠️  Completed with {len(errors)} error(s)")
        application_log.append(f"📝 Files modified: {files_modified}")
        application_log.append(f"📄 Files created: {files_created}")

        return {
            "success": success,
            "files_modified": files_modified,
            "files_created": files_created,
            "backup_path": backup_dir,
            "application_log": application_log,
            "errors": errors,
        }

    def _apply_single_change(self, change: Dict, backup_dir: str, change_num: int, total_changes: int) -> Dict:
        """Apply a single code change"""
        log = []
        log.append(f"\n--- Change {change_num}/{total_changes} ---")
        log.append(f"📄 File: {change['file_path']}")
        log.append(f"🔧 Action: {change['action']}")
        log.append(f"💬 Description: {change['description']}")

        file_path = change["file_path"]
        action = change["action"]

        # Resolve full path
        if not file_path.startswith("/"):
            full_path = os.path.join(self.base_path, file_path)
        else:
            full_path = file_path

        try:
            if action == "modify":
                return self._modify_file(full_path, change, backup_dir, log)
            elif action == "create":
                return self._create_file(full_path, change, backup_dir, log)
            elif action == "delete":
                return self._delete_file(full_path, backup_dir, log)
            else:
                log.append(f"⚠️  Unknown action: {action}")
                return {
                    "success": False,
                    "log": log,
                    "error": f"Unknown action: {action}",
                }

        except Exception as e:
            log.append(f"❌ Error: {str(e)}")
            return {"success": False, "log": log, "error": str(e)}

    def _modify_file(self, full_path: str, change: Dict, backup_dir: str, log: List[str]) -> Dict:
        """Modify an existing file"""

        # Check if file exists
        if not os.path.exists(full_path):
            log.append(f"⚠️  File doesn't exist, creating instead")
            return self._create_file(full_path, change, backup_dir, log)

        # Backup original file
        backup_file = os.path.join(backup_dir, os.path.basename(full_path) + ".backup")
        shutil.copy2(full_path, backup_file)
        log.append(f"💾 Backed up to: {os.path.basename(backup_file)}")

        # Read current content
        with open(full_path, "r", encoding="utf-8") as f:
            current_content = f.read()

        old_content = change.get("old_content", "")
        new_content = change.get("new_content", "")

        # Try to find and replace old content
        if old_content and old_content in current_content:
            # Exact match replacement
            modified_content = current_content.replace(old_content, new_content, 1)
            log.append(f"✅ Replaced exact match")
        else:
            # V2 FIX: If old_content specified but not found, FAIL instead of appending
            # This prevents silent file corruption from mismatched content
            if old_content:
                log.append(f"❌ ERROR: old_content not found in file - refusing to modify")
                log.append(f"   This prevents file corruption from incorrect replacements")
                preview = old_content[:100].replace("\n", "\\n")
                log.append(f"   old_content preview: {preview}...")

                # Restore from backup (in case any partial changes were made)
                shutil.copy2(backup_file, full_path)
                log.append(f"↩️  Restored from backup")

                return {
                    "success": False,
                    "file": full_path,
                    "log": log,
                    "error": "old_content not found in file - content mismatch",
                    "suggestion": "Regenerate the code fix with exact file content",
                }
            else:
                # No old content specified, replace entire file
                modified_content = new_content
                log.append(f"✅ Replaced entire file content")

        # Write modified content
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(modified_content)

        log.append(f"✅ File modified successfully")

        return {"success": True, "log": log}

    def _create_file(self, full_path: str, change: Dict, backup_dir: str, log: List[str]) -> Dict:
        """Create a new file"""

        # Create directory if it doesn't exist
        dir_path = os.path.dirname(full_path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
            log.append(f"📁 Created directory: {dir_path}")

        # Check if file already exists
        if os.path.exists(full_path):
            log.append(f"⚠️  File already exists, backing up and overwriting")
            backup_file = os.path.join(backup_dir, os.path.basename(full_path) + ".backup")
            shutil.copy2(full_path, backup_file)
            log.append(f"💾 Backed up existing file")

        # Write new content
        new_content = change.get("new_content", "")
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(new_content)

        log.append(f"✅ File created successfully")

        return {"success": True, "log": log}

    def _delete_file(self, full_path: str, backup_dir: str, log: List[str]) -> Dict:
        """Delete a file"""

        if not os.path.exists(full_path):
            log.append(f"⚠️  File doesn't exist, nothing to delete")
            return {"success": True, "log": log}

        # Backup before deletion
        backup_file = os.path.join(backup_dir, os.path.basename(full_path) + ".deleted")
        shutil.copy2(full_path, backup_file)
        log.append(f"💾 Backed up to: {os.path.basename(backup_file)}")

        # Delete file
        os.remove(full_path)
        log.append(f"✅ File deleted")

        return {"success": True, "log": log}


# Convenience function
def apply_code_changes(proposal_id: int, changes: List[Dict]) -> Dict:
    """Apply code changes to sandbox"""
    system = CodeApplicationSystem()
    return system.apply_changes_to_sandbox(proposal_id, changes)


if __name__ == "__main__":
    # Test code application
    print("=" * 80)
    print("Code Application System - Test")
    print("=" * 80)

    test_changes = [
        {
            "file_path": "/tmp/test_file.txt",
            "action": "create",
            "new_content": "This is a test file created by Code Application System",
            "description": "Create test file",
        }
    ]

    result = apply_code_changes(proposal_id=999, changes=test_changes)

    print(f"\n✅ Success: {result['success']}")
    print(f"📝 Files modified: {result['files_modified']}")
    print(f"📄 Files created: {result['files_created']}")
    print(f"\n📋 Application Log:")
    for line in result["application_log"]:
        print(f"  {line}")

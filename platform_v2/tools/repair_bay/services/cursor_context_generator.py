"""
Cursor Context Generator
Generates .cursorrules files with full proposal context for Cursor IDE

Author: A.R.C.H.I.E. Platform
Date: 2026-01-05
"""

import os
from database import _get_db_password
import sys
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional
from datetime import datetime
from services.time_utils import now_local_str

sys.path.insert(0, "/mnt/archie_brain/platform_v2")
from git_branch_manager import GitBranchManager


class CursorContextGenerator:
    """Generates Cursor IDE context files for proposals"""

    def __init__(self):
        self.git_manager = GitBranchManager()
        self.project_path = "/mnt/archie_brain/platform_v2"

    def get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def get_proposal_details(self, proposal_id: int) -> Optional[Dict]:
        """Get complete proposal details from database"""
        try:
            conn = self.get_db()
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute(
                """
                SELECT
                    id, title, description, category, priority, status,
                    plan_steps, risk_level,
                    proposed_by, proposed_at, approved_at, approved_by,
                    metadata, code_diff, rationale
                FROM improvement_proposals
                WHERE id = %s
            """,
                (proposal_id,),
            )

            proposal = cur.fetchone()
            cur.close()
            conn.close()

            return dict(proposal) if proposal else None

        except Exception as e:
            print(f"Error fetching proposal: {e}")
            return None

    def get_related_knowledge(self, proposal: Dict, limit: int = 10) -> List[Dict]:
        """
        Get related knowledge base entries using hybrid search
        Combines keyword matching (30%) with semantic similarity (70%)
        """
        try:
            # Build search query from proposal
            category = proposal.get("category", "")
            title = proposal.get("title", "")
            description = proposal.get("description", "")

            # Combine proposal fields for richer search context
            search_query = f"{category} {title} {description}"

            # Use hybrid search for best results
            sys.path.insert(0, "/mnt/archie_brain/platform_v2")
            from knowledge_hybrid_search import hybrid_search

            results = hybrid_search(search_query, limit=limit)

            print(f"[Cursor Context] Found {len(results)} related knowledge entries")

            # Format results for .cursorrules
            formatted_results = []
            for result in results:
                formatted_results.append(
                    {
                        "entity_name": result.get("entity_name", ""),
                        "knowledge_type": result.get("knowledge_type", ""),
                        "description": result.get("description", ""),
                        "purpose": result.get("purpose", ""),
                        "file_path": result.get("file_path", ""),
                        "code_snippet": result.get("code_snippet", ""),
                        "documentation": result.get("documentation", ""),
                        "tags": result.get("tags", []),
                        "relevance_score": result.get("hybrid_score", 0.0),
                    }
                )

            return formatted_results

        except Exception as e:
            print(f"[Cursor Context] Error fetching knowledge (falling back to empty): {e}")
            import traceback

            traceback.print_exc()
            return []

    def generate_cursorrules(self, proposal_id: int) -> Dict:
        """
        Generate .cursorrules content for Cursor IDE

        Args:
            proposal_id: Improvement proposal ID

        Returns:
            {
                'success': bool,
                'cursorrules_content': str,
                'proposal': dict,
                'branch_name': str
            }
        """
        try:
            # Get proposal details
            proposal = self.get_proposal_details(proposal_id)
            if not proposal:
                return {"success": False, "error": f"Proposal {proposal_id} not found"}

            # Get related knowledge
            knowledge = self.get_related_knowledge(proposal)

            # Generate branch name
            branch_name = f"sandbox-proposal-{proposal_id}"

            # Build .cursorrules content
            cursorrules = self._build_cursorrules_content(
                proposal=proposal, knowledge=knowledge, branch_name=branch_name
            )

            return {
                "success": True,
                "cursorrules_content": cursorrules,
                "proposal": proposal,
                "branch_name": branch_name,
                "generated_at": datetime.now().isoformat(),
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _build_cursorrules_content(self, proposal: Dict, knowledge: List[Dict], branch_name: str) -> str:
        """Build the actual .cursorrules file content"""

        # Format priority and risk level
        priority = proposal.get("priority", "medium").upper()
        risk_level = proposal.get("risk_level", "medium").upper()
        category = proposal.get("category", "general").title()

        # Format plan steps if available
        plan_steps_section = ""
        if proposal.get("plan_steps"):
            plan_steps = proposal["plan_steps"]
            if isinstance(plan_steps, list):
                plan_steps_section = "\n## IMPLEMENTATION PLAN\n\n"
                for i, step in enumerate(plan_steps, 1):
                    if isinstance(step, dict):
                        plan_steps_section += f"{i}. **{step.get('action', 'Action')}**: {step.get('target', '')}\n"
                        plan_steps_section += f"   - {step.get('description', '')}\n"
                    else:
                        plan_steps_section += f"{i}. {step}\n"
                plan_steps_section += "\n"

        # Format knowledge base examples (from semantic hybrid search)
        knowledge_section = ""
        if knowledge:
            knowledge_section = "\n## RELATED KNOWLEDGE & EXAMPLES\n\n"
            knowledge_section += "These code entities were found using AI semantic search based on your proposal.\n"
            knowledge_section += "They have similar functionality or context to what you're implementing.\n\n"

            for idx, item in enumerate(knowledge, 1):
                entity_name = item.get("entity_name", "Unknown")
                knowledge_type = item.get("knowledge_type", "entity")
                relevance = item.get("relevance_score", 0) * 100  # Convert to percentage

                knowledge_section += f"### {idx}. {entity_name} ({knowledge_type}) - {relevance:.0f}% relevant\n\n"

                # Add description
                if item.get("description"):
                    knowledge_section += f"**Description**: {item['description']}\n\n"

                # Add purpose
                if item.get("purpose"):
                    knowledge_section += f"**Purpose**: {item['purpose']}\n\n"

                # Add file location
                if item.get("file_path"):
                    knowledge_section += f"**Location**: `{item['file_path']}`\n\n"

                # Add tags
                if item.get("tags"):
                    tags_list = item["tags"] if isinstance(item["tags"], list) else []
                    if tags_list:
                        knowledge_section += f"**Tags**: {', '.join(tags_list)}\n\n"

                # Add code snippet if available (truncated)
                if item.get("code_snippet"):
                    code_snippet = item["code_snippet"][:400]
                    if len(item.get("code_snippet", "")) > 400:
                        code_snippet += "\n// ...(truncated)"
                    knowledge_section += f"**Example Code**:\n```python\n{code_snippet}\n```\n\n"

                # Add documentation if available
                if item.get("documentation"):
                    doc = item["documentation"][:300]
                    if len(item.get("documentation", "")) > 300:
                        doc += "...(see file for more)"
                    knowledge_section += f"**Documentation**: {doc}\n\n"

                knowledge_section += "---\n\n"

        # Build complete .cursorrules
        cursorrules = f"""# A.R.C.H.I.E. Improvement Proposal #{proposal['id']}

## PROPOSAL DETAILS
- **Title**: {proposal['title']}
- **Category**: {category}
- **Priority**: {priority}
- **Risk Level**: {risk_level}
- **Status**: {proposal['status'].upper()}

## DESCRIPTION
{proposal['description']}

## YOUR TASK
You are implementing this improvement for A.R.C.H.I.E.'s platform.
The user has requested this change and you should implement it following the guidelines below.

{plan_steps_section}
## PROJECT STRUCTURE

```
/mnt/archie_brain/platform_v2/              # Flask application root
├── app.py                                   # Main Flask application
├── templates/                               # Jinja2 templates
│   ├── base.html                           # Base template (all pages extend this)
│   ├── dashboard.html                      # Main dashboard
│   └── tools/                              # Tool-specific templates
│       ├── admin.html                      # Admin panel
│       └── ...
├── static/                                 # Static assets (CSS, JS, images)
├── tools/                                  # Tool modules (blueprints)
│   ├── admin/routes.py                     # Admin panel routes
│   ├── improvements/                       # Improvements system
│   ├── backup_manager/                     # Backup system
│   └── ...
├── consciousness/                          # A.R.C.H.I.E.'s consciousness
│   ├── archie_consciousness.py             # Agent awareness
│   ├── memory_manager.py                   # Memory system
│   └── archie_tools.py                     # Tool integration
├── ai_bridge/                              # AI integration (outside Docker)
│   └── (AI models and processing)
└── migrations/                             # Database migrations
```

## CURRENT BRANCH
**{branch_name}** (sandbox - based on main)

⚠️ **IMPORTANT**: All your changes will be in this branch. Do NOT modify `main` directly.

## CODING GUIDELINES

### 1. Flask Best Practices
- Use Flask blueprints for modular code
- Follow existing route patterns: `/tools/<tool_name>/...`
- Use `@login_required` decorator for authenticated routes
- Use `@admin_required` for admin-only routes

### 2. Template Inheritance
- All templates should extend `base.html`
- Use template blocks: `title`, `styles`, `content`
- Follow the Matrix/terminal aesthetic (green on black)

### 3. Database Operations
- Use `get_db()` for database connections
- Always close cursors and connections
- Use parameterized queries (never string formatting)
- Use `RealDictCursor` for dict-like results

### 4. Code Style
- Match existing code style (4-space indentation)
- Add docstrings to new functions
- Use type hints where helpful
- Keep functions focused and single-purpose

### 5. Security
- Never expose sensitive data
- Validate all user inputs
- Use CSRF protection for forms
- Sanitize data before database queries

## TESTING YOUR CHANGES

After making changes:
1. **Commit your changes**:
   ```bash
   git add .
   git commit -m "Proposal #{proposal['id']}: <description of changes>"
   ```

2. **Automatic workflow**:
   - A.R.C.H.I.E. will detect your commit
   - Changes will be applied to sandbox environment
   - Tests will run automatically
   - You'll be notified when ready for review

3. **Review in sandbox**:
   - Visit: http://192.168.1.200:3000/sandbox/
   - Test your changes in isolation
   - Verify everything works correctly

4. **Deploy to production**:
   - If satisfied, click "Deploy to Production"
   - Your branch will merge to `main`
   - Changes go live immediately

## WORKFLOW INTEGRATION

This proposal is part of A.R.C.H.I.E.'s automated improvement workflow:

```
Your Commit → Auto-Detect → Apply to Sandbox → Run Tests → Ready for Review → Deploy
```

### State Machine
- **proposed**: Proposal created
- **approved**: Ready for implementation (you're here!)
- **code_generated**: Code changes detected
- **sandbox_created**: Isolated testing environment ready
- **applying_changes**: Changes being applied
- **ready_for_testing**: Ready for automated tests
- **testing**: Tests running
- **tested**: Tests complete
- **ready_for_review**: Ready for user review
- **deploying**: Merging to production
- **deployed**: Live in production

## HELPFUL COMMANDS

```bash
# Check current branch
git branch --show-current

# See what changed
git status
git diff

# Commit changes
git add .
git commit -m "Your commit message"

# View commit history
git log --oneline

# Switch to production to compare
git checkout main
git checkout {branch_name}  # Switch back
```

{knowledge_section}
## IMPORTANT REMINDERS

✅ **DO**:
- Follow existing code patterns
- Test thoroughly before committing
- Write clear commit messages
- Ask A.R.C.H.I.E. if you need clarification

❌ **DON'T**:
- Modify the `main` branch directly
- Skip testing
- Commit broken code
- Remove existing functionality without approval

## NEED HELP?

If you're stuck or need clarification:
1. Check the related knowledge examples above
2. Look at similar files in the codebase
3. Ask A.R.C.H.I.E. in the chat interface

---

**Generated**: {now_local_str()}
**Branch**: {branch_name}
**Proposal**: #{proposal['id']} - {proposal['title']}

🤖 **This .cursorrules file was generated by A.R.C.H.I.E.'s Cursor integration system**
"""

        return cursorrules

    def prepare_cursor_package(self, proposal_id: int) -> Dict:
        """
        Prepare complete package for Cursor IDE

        Creates:
        - Sandbox Git branch
        - .cursorrules file
        - Instructions for user

        Returns:
            {
                'success': bool,
                'branch_name': str,
                'cursorrules_content': str,
                'cursorrules_path': str,
                'git_url': str,
                'instructions': str
            }
        """
        try:
            # Generate .cursorrules content
            rules_result = self.generate_cursorrules(proposal_id)
            if not rules_result["success"]:
                return rules_result

            # Create sandbox branch if it doesn't exist
            branch_name = f"sandbox-proposal-{proposal_id}"
            if not self.git_manager.branch_exists(branch_name):
                branch_result = self.git_manager.create_sandbox_branch(proposal_id)
                if not branch_result["success"]:
                    return {
                        "success": False,
                        "error": f"Failed to create branch: {branch_result.get('error')}",
                    }

            # Write .cursorrules to file
            cursorrules_path = os.path.join(self.project_path, ".cursorrules")

            # Switch to sandbox branch before writing
            self.git_manager.switch_to_branch(branch_name)

            with open(cursorrules_path, "w") as f:
                f.write(rules_result["cursorrules_content"])

            # Commit .cursorrules to sandbox branch
            self.git_manager._run_git_command(["git", "add", ".cursorrules"])
            self.git_manager._run_git_command(["git", "commit", "-m", f"Add .cursorrules for proposal #{proposal_id}"])

            # Switch back to main
            self.git_manager.switch_to_branch("main")

            # Generate instructions
            instructions = self._generate_instructions(proposal_id, branch_name)

            return {
                "success": True,
                "proposal_id": proposal_id,
                "branch_name": branch_name,
                "cursorrules_content": rules_result["cursorrules_content"],
                "cursorrules_path": cursorrules_path,
                "git_url": f"file://{self.project_path}",
                "instructions": instructions,
                "proposal": rules_result["proposal"],
            }

        except Exception as e:
            import traceback

            return {
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc(),
            }

    def _generate_instructions(self, proposal_id: int, branch_name: str) -> str:
        """Generate step-by-step instructions for using Cursor"""
        return f"""
# 🎨 Open in Cursor IDE - Instructions

## Prerequisites
1. **Install Cursor IDE**: https://cursor.sh (if not already installed)
2. **Git access**: Ensure you can access `/mnt/archie_brain/platform_v2`

## Setup Steps

### 1️⃣ Clone/Open Repository in Cursor
If you haven't opened the project in Cursor yet:
```bash
# Open Cursor and select "Open Folder"
# Navigate to: /mnt/archie_brain/platform_v2
```

### 2️⃣ Checkout Sandbox Branch
In Cursor's terminal (Ctrl+` or Cmd+`):
```bash
git checkout {branch_name}
```

### 3️⃣ Verify .cursorrules
The `.cursorrules` file has been created in the project root.
- This tells Cursor AI about your task
- Cursor will automatically use this context

### 4️⃣ Start Coding
- Cursor AI now knows what to do!
- Ask Cursor: "Show me the files I need to modify"
- Ask Cursor: "Help me implement this change"
- Use Cursor's AI features (Cmd+K for inline edits)

### 5️⃣ Commit Your Changes
When done:
```bash
git add .
git commit -m "Proposal #{proposal_id}: <your description>"
```

### 6️⃣ Automatic Workflow
After committing:
- A.R.C.H.I.E. detects your commit automatically
- Changes are applied to sandbox environment
- Tests run automatically
- You'll be notified when ready for review

### 7️⃣ Review & Deploy
- Visit: http://192.168.1.200:3000/sandbox/
- Test your changes
- If satisfied, click "Deploy to Production"

## Quick Tips

💡 **Use Cursor AI**:
- Cmd/Ctrl + K: Inline code generation
- Cmd/Ctrl + L: Chat with AI about code
- Cursor reads .cursorrules automatically

💡 **Check Status**:
```bash
git status                    # See what changed
git diff                      # See detailed changes
git log --oneline             # See commits
```

💡 **Need Help?**:
- Ask Cursor AI: "What should I do next?"
- Check A.R.C.H.I.E.'s dashboard for status updates
- Review the .cursorrules file for guidance

---

**Branch**: {branch_name}
**Proposal**: #{proposal_id}

🚀 Happy coding with Cursor!
"""


# Convenience function
def prepare_cursor_for_proposal(proposal_id: int) -> Dict:
    """Prepare Cursor IDE package for a proposal"""
    generator = CursorContextGenerator()
    return generator.prepare_cursor_package(proposal_id)

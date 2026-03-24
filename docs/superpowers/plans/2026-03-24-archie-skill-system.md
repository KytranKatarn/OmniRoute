# ARCHIE Skill System — Implementation Plan (Plan 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the skill system for ARCHIE Code CLI — slash commands that users invoke (like `/commit`, `/review`, `/explain`). Skills are markdown prompt templates loaded from community, hub, and custom directories.

**Architecture:** Skills live in `archie_engine/skills/` — a loader discovers skill files from multiple directories, a registry maps slash commands to skills, and an executor renders prompt templates and pipes them through the engine's inference + tool pipeline. Community skills ship with the package. Hub skills sync via Plan 3's sync module. Custom skills live in the user's `.archie/skills/` directory.

**Tech Stack:** Python 3.11+, markdown parsing, Jinja2-style template variables, pytest.

**Spec:** `docs/superpowers/specs/2026-03-23-archie-code-cli-design.md` (Section 7)

**Depends on:** Plan 2 (Engine Core), Plan 3 (Hub Sync for hub skills).

**Rollback:** All tasks are additive. Rollback: `rm -rf archie_engine/skills/` and revert commits.

---

## File Structure

```
archie_engine/skills/
  __init__.py          — SkillRegistry (main API)
  loader.py            — Discover and load skill files from directories
  executor.py          — Render skill templates, execute through engine
  skill.py             — Skill dataclass (parsed from markdown frontmatter)
  community/           — Built-in skills shipped with package
    commit.md
    review.md
    explain.md
    debug.md
    refactor.md
    test.md
```

Tests:
```
archie_engine/tests/
  test_skill.py        — Skill parsing
  test_loader.py       — Discovery and loading
  test_executor.py     — Template rendering and execution
  test_skill_registry.py — Full registry integration
```

## Skill File Format

Skills are markdown files with YAML frontmatter:

```markdown
---
name: commit
description: Create a git commit with a descriptive message
arguments:
  - name: message
    description: Optional commit message
    required: false
---

Review the staged changes and create a commit.

{{#if message}}
Use this commit message: {{message}}
{{else}}
Generate a concise commit message based on the diff.
{{/if}}

Steps:
1. Run `git diff --staged` to see changes
2. If no message provided, analyze the diff and generate one
3. Run `git commit -m "<message>"`
4. Report the commit hash
```

---

## Task Overview (7 Tasks)

| # | Task | Scope | Est. Steps |
|---|------|-------|------------|
| 4.1 | Skill dataclass | Parse frontmatter + body from markdown | 6 |
| 4.2 | Skill loader | Discover skills from directories | 8 |
| 4.3 | Community skills | 6 built-in skill files | 6 |
| 4.4 | Skill executor | Render template, execute via inference | 8 |
| 4.5 | Skill registry | Slash command lookup, argument parsing | 6 |
| 4.6 | Engine integration | Wire skills into engine + router | 8 |
| 4.7 | Push and close out | Push, log decision | 4 |

---

### Task 4.1: Skill dataclass

**Files:**
- Create: `archie_engine/skills/skill.py`
- Create: `archie_engine/tests/test_skill.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from archie_engine.skills.skill import Skill, parse_skill


SAMPLE_SKILL = """---
name: commit
description: Create a git commit
arguments:
  - name: message
    description: Optional commit message
    required: false
---

Review staged changes and create a commit.

Steps:
1. Run git diff --staged
2. Generate commit message
3. Commit
"""


def test_parse_skill_name():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    assert skill.name == "commit"


def test_parse_skill_description():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    assert "git commit" in skill.description


def test_parse_skill_arguments():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    assert len(skill.arguments) == 1
    assert skill.arguments[0]["name"] == "message"
    assert skill.arguments[0]["required"] is False


def test_parse_skill_body():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    assert "Review staged changes" in skill.body
    assert "Steps:" in skill.body


def test_parse_skill_source():
    skill = parse_skill(SAMPLE_SKILL, source="hub")
    assert skill.source == "hub"


def test_parse_skill_no_frontmatter():
    raw = "Just a plain markdown file with no frontmatter."
    skill = parse_skill(raw, source="custom")
    assert skill.name == ""
    assert skill.body == raw


def test_skill_to_dict():
    skill = parse_skill(SAMPLE_SKILL, source="community")
    d = skill.to_dict()
    assert d["name"] == "commit"
    assert "arguments" in d
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement skill.py**

```python
"""Skill dataclass — parsed from markdown with YAML frontmatter."""

import re
import yaml
from dataclasses import dataclass, field


@dataclass
class Skill:
    name: str = ""
    description: str = ""
    arguments: list[dict] = field(default_factory=list)
    body: str = ""
    source: str = "community"  # community | hub | custom
    file_path: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "arguments": self.arguments,
            "source": self.source,
        }


def parse_skill(raw: str, source: str = "community", file_path: str = "") -> Skill:
    """Parse a skill markdown file with optional YAML frontmatter."""
    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.DOTALL)

    if not frontmatter_match:
        return Skill(body=raw.strip(), source=source, file_path=file_path)

    try:
        meta = yaml.safe_load(frontmatter_match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}

    body = frontmatter_match.group(2).strip()

    return Skill(
        name=meta.get("name", ""),
        description=meta.get("description", ""),
        arguments=meta.get("arguments", []),
        body=body,
        source=source,
        file_path=file_path,
    )
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): skill dataclass with YAML frontmatter parsing"
```

---

### Task 4.2: Skill loader

**Files:**
- Create: `archie_engine/skills/loader.py`
- Create: `archie_engine/tests/test_loader.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from pathlib import Path
from archie_engine.skills.loader import SkillLoader


@pytest.fixture
def skill_dirs(tmp_path):
    community = tmp_path / "community"
    community.mkdir()
    (community / "commit.md").write_text("---\nname: commit\ndescription: Create commit\n---\nCommit stuff.")
    (community / "review.md").write_text("---\nname: review\ndescription: Review code\n---\nReview stuff.")

    custom = tmp_path / "custom"
    custom.mkdir()
    (custom / "deploy.md").write_text("---\nname: deploy\ndescription: Deploy app\n---\nDeploy stuff.")

    return [community, custom]


@pytest.fixture
def loader(skill_dirs):
    return SkillLoader(skill_dirs=skill_dirs)


def test_load_all_skills(loader):
    skills = loader.load_all()
    assert len(skills) == 3


def test_skill_names(loader):
    skills = loader.load_all()
    names = {s.name for s in skills}
    assert "commit" in names
    assert "review" in names
    assert "deploy" in names


def test_empty_directory(tmp_path):
    loader = SkillLoader(skill_dirs=[tmp_path / "nonexistent"])
    skills = loader.load_all()
    assert len(skills) == 0


def test_ignores_non_md_files(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "readme.txt").write_text("not a skill")
    (d / "commit.md").write_text("---\nname: commit\ndescription: test\n---\nBody.")
    loader = SkillLoader(skill_dirs=[d])
    skills = loader.load_all()
    assert len(skills) == 1


def test_source_from_dirname(skill_dirs):
    loader = SkillLoader(skill_dirs=skill_dirs)
    skills = loader.load_all()
    sources = {s.name: s.source for s in skills}
    assert sources["commit"] == "community"
    assert sources["deploy"] == "custom"
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement loader.py**

```python
"""Skill loader — discover and load skill files from directories."""

import logging
from pathlib import Path
from archie_engine.skills.skill import Skill, parse_skill

logger = logging.getLogger(__name__)


class SkillLoader:
    def __init__(self, skill_dirs: list[Path]):
        self.skill_dirs = skill_dirs

    def load_all(self) -> list[Skill]:
        """Load all .md skill files from all configured directories."""
        skills = []
        for directory in self.skill_dirs:
            if not directory.exists():
                continue
            source = directory.name  # Use directory name as source
            for md_file in sorted(directory.glob("*.md")):
                try:
                    raw = md_file.read_text()
                    skill = parse_skill(raw, source=source, file_path=str(md_file))
                    if skill.name:
                        skills.append(skill)
                except Exception as e:
                    logger.warning("Failed to load skill %s: %s", md_file, e)
        return skills
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): skill loader — discover .md files from multiple directories"
```

---

### Task 4.3: Community skills

**Files:**
- Create: `archie_engine/skills/community/commit.md`
- Create: `archie_engine/skills/community/review.md`
- Create: `archie_engine/skills/community/explain.md`
- Create: `archie_engine/skills/community/debug.md`
- Create: `archie_engine/skills/community/refactor.md`
- Create: `archie_engine/skills/community/test.md`

- [ ] **Step 1: Create community directory**

```bash
mkdir -p archie_engine/skills/community
```

- [ ] **Step 2: Write 6 skill files**

Each skill has frontmatter (name, description, arguments) and a body that serves as the prompt template when invoked. Keep them practical and concise.

**commit.md:**
```markdown
---
name: commit
description: Create a git commit with an auto-generated or provided message
arguments:
  - name: message
    description: Optional commit message (auto-generated if omitted)
    required: false
---

Create a git commit for the current staged changes.

1. Run `git diff --staged` to review what will be committed
2. If no message was provided, analyze the diff and write a concise commit message
3. Run `git commit -m "<message>"`
4. Report the commit hash and summary
```

**review.md:**
```markdown
---
name: review
description: Review code changes for bugs, style, and improvements
arguments:
  - name: target
    description: File path or git ref to review (defaults to staged changes)
    required: false
---

Review the code changes for quality issues.

1. If a target file is specified, read it. Otherwise run `git diff` for unstaged or `git diff --staged` for staged changes
2. Check for: bugs, security issues, style problems, performance concerns
3. Provide specific feedback with file and line references
4. Rate overall quality and suggest improvements
```

**explain.md:**
```markdown
---
name: explain
description: Explain how code works in plain language
arguments:
  - name: target
    description: File path or function name to explain
    required: true
---

Explain how the specified code works.

1. Read the target file or find the specified function/class
2. Explain the purpose, inputs, outputs, and key logic
3. Note any dependencies or side effects
4. Keep the explanation clear and concise
```

**debug.md:**
```markdown
---
name: debug
description: Investigate and fix a bug or error
arguments:
  - name: error
    description: Error message or description of the bug
    required: true
---

Investigate and fix the reported bug.

1. Analyze the error message or bug description
2. Search the codebase for relevant code
3. Identify the root cause
4. Propose a fix with explanation
5. Apply the fix if confidence is high
```

**refactor.md:**
```markdown
---
name: refactor
description: Refactor code for clarity, performance, or maintainability
arguments:
  - name: target
    description: File or function to refactor
    required: true
  - name: goal
    description: What to improve (clarity, performance, DRY, etc.)
    required: false
---

Refactor the specified code.

1. Read the target code
2. Identify improvement opportunities based on the goal
3. Apply refactoring while preserving behavior
4. Run existing tests to verify nothing broke
5. Summarize changes made
```

**test.md:**
```markdown
---
name: test
description: Write or run tests for specified code
arguments:
  - name: target
    description: File or function to test
    required: true
  - name: action
    description: "write" to create tests, "run" to execute existing tests
    required: false
---

Work with tests for the specified code.

1. If action is "run" or not specified, find and run existing tests
2. If action is "write", read the target code and write comprehensive tests
3. Cover edge cases, error paths, and expected behavior
4. Report test results with pass/fail counts
```

- [ ] **Step 3: Verify loader finds community skills**

```bash
python -c "
from pathlib import Path
from archie_engine.skills.loader import SkillLoader
loader = SkillLoader([Path('archie_engine/skills/community')])
skills = loader.load_all()
print(f'{len(skills)} skills loaded: {[s.name for s in skills]}')
"
```

Expected: `6 skills loaded: ['commit', 'debug', 'explain', 'refactor', 'review', 'test']`

- [ ] **Step 4: Commit**

```bash
git add archie_engine/skills/community/ && git commit -m "feat(engine): 6 community skills — commit, review, explain, debug, refactor, test"
```

---

### Task 4.4: Skill executor

**Files:**
- Create: `archie_engine/skills/executor.py`
- Create: `archie_engine/tests/test_executor.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from unittest.mock import AsyncMock
from archie_engine.skills.skill import Skill
from archie_engine.skills.executor import SkillExecutor


@pytest.fixture
def mock_inference():
    client = AsyncMock()
    client.chat = AsyncMock(return_value={
        "message": {"role": "assistant", "content": "Done! Committed as abc123."},
        "model": "qwen2.5:7b",
    })
    return client


@pytest.fixture
def mock_tools():
    from archie_engine.tools import ToolRegistry
    from archie_engine.tools.base import ToolResult
    registry = ToolRegistry()
    from unittest.mock import MagicMock
    mock_git = MagicMock()
    mock_git.name = "git_ops"
    mock_git.description = "Git"
    mock_git.to_dict = MagicMock(return_value={"name": "git_ops", "description": "Git"})
    mock_git.execute = AsyncMock(return_value=ToolResult(success=True, output="diff output"))
    registry.register(mock_git)
    return registry


@pytest.fixture
def executor(mock_inference, mock_tools):
    return SkillExecutor(inference=mock_inference, tools=mock_tools, default_model="qwen2.5:7b")


@pytest.fixture
def commit_skill():
    return Skill(
        name="commit",
        description="Create a git commit",
        arguments=[{"name": "message", "required": False}],
        body="Create a commit.\n1. Run git diff --staged\n2. Generate message\n3. Commit",
    )


@pytest.mark.asyncio
async def test_execute_skill(executor, commit_skill):
    result = await executor.execute(commit_skill, args={})
    assert result["success"]
    assert result["response"]


@pytest.mark.asyncio
async def test_execute_skill_with_args(executor, commit_skill):
    result = await executor.execute(commit_skill, args={"message": "fix bug"})
    assert result["success"]


@pytest.mark.asyncio
async def test_execute_renders_args_in_prompt(executor, commit_skill, mock_inference):
    await executor.execute(commit_skill, args={"message": "my message"})
    call_args = mock_inference.chat.call_args
    messages = call_args[1].get("messages") or call_args[0][0]
    prompt_text = " ".join(m["content"] for m in messages)
    assert "my message" in prompt_text


@pytest.mark.asyncio
async def test_execute_returns_model_used(executor, commit_skill):
    result = await executor.execute(commit_skill, args={})
    assert result.get("model_used") == "qwen2.5:7b"
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement executor.py**

```python
"""Skill executor — renders skill templates and runs through inference."""

import logging
import re
from archie_engine.skills.skill import Skill
from archie_engine.inference import InferenceClient
from archie_engine.tools import ToolRegistry

logger = logging.getLogger(__name__)


class SkillExecutor:
    def __init__(self, inference: InferenceClient, tools: ToolRegistry, default_model: str = "qwen2.5:7b"):
        self.inference = inference
        self.tools = tools
        self.default_model = default_model

    async def execute(self, skill: Skill, args: dict, context: dict | None = None) -> dict:
        """Execute a skill — render template, call inference."""
        # Render the skill body with arguments
        rendered = self._render_template(skill.body, args)

        # Build system prompt from skill metadata
        system = f"You are executing the /{skill.name} skill: {skill.description}"

        # Build messages
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": rendered},
        ]

        # Add context history if available
        if context and context.get("history"):
            for msg in context["history"][-5:]:
                messages.insert(-1, {"role": msg["role"], "content": msg["content"]})

        try:
            result = await self.inference.chat(messages=messages, model=self.default_model)
            response = result.get("message", {}).get("content", "")
            return {
                "success": True,
                "response": response,
                "skill": skill.name,
                "model_used": result.get("model", self.default_model),
            }
        except Exception as e:
            logger.error("Skill %s execution failed: %s", skill.name, e)
            return {"success": False, "response": f"Skill error: {e}", "skill": skill.name}

    def _render_template(self, body: str, args: dict) -> str:
        """Simple template rendering — replace {{arg_name}} with values."""
        rendered = body
        for key, value in args.items():
            rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
        # Also append args as context if any were provided
        if args:
            rendered += "\n\nArguments provided:\n"
            for k, v in args.items():
                rendered += f"- {k}: {v}\n"
        return rendered
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): skill executor — template rendering and inference dispatch"
```

---

### Task 4.5: Skill registry

**Files:**
- Create: `archie_engine/skills/__init__.py`
- Create: `archie_engine/tests/test_skill_registry.py`

- [ ] **Step 1: Write tests**

```python
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from archie_engine.skills import SkillRegistry
from archie_engine.skills.executor import SkillExecutor


@pytest.fixture
def skill_dir(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "commit.md").write_text("---\nname: commit\ndescription: Create commit\narguments:\n  - name: message\n    required: false\n---\nCommit stuff.")
    (d / "review.md").write_text("---\nname: review\ndescription: Review code\n---\nReview stuff.")
    return d


@pytest.fixture
def mock_executor():
    executor = AsyncMock(spec=SkillExecutor)
    executor.execute = AsyncMock(return_value={"success": True, "response": "Done!", "skill": "commit"})
    return executor


@pytest.fixture
def registry(skill_dir, mock_executor):
    return SkillRegistry(skill_dirs=[skill_dir], executor=mock_executor)


def test_registry_loads_skills(registry):
    registry.load()
    assert len(registry.list_skills()) == 2


def test_registry_get_skill(registry):
    registry.load()
    skill = registry.get("commit")
    assert skill is not None
    assert skill.name == "commit"


def test_registry_get_missing(registry):
    registry.load()
    assert registry.get("nonexistent") is None


def test_registry_list_skills(registry):
    registry.load()
    skills = registry.list_skills()
    names = [s["name"] for s in skills]
    assert "commit" in names
    assert "review" in names


@pytest.mark.asyncio
async def test_registry_execute(registry, mock_executor):
    registry.load()
    result = await registry.execute("commit", args={"message": "fix"})
    assert result["success"]
    mock_executor.execute.assert_called_once()


@pytest.mark.asyncio
async def test_registry_execute_missing(registry):
    registry.load()
    result = await registry.execute("nonexistent", args={})
    assert not result["success"]
    assert "not found" in result["response"].lower()


def test_parse_slash_command(registry):
    name, args = registry.parse_command("/commit -m 'fix bug'")
    assert name == "commit"


def test_parse_slash_command_no_args(registry):
    name, args = registry.parse_command("/review")
    assert name == "review"
    assert args == ""
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Implement skills/__init__.py**

```python
"""Skill registry — discover, load, and execute skills."""

import logging
from pathlib import Path
from archie_engine.skills.loader import SkillLoader
from archie_engine.skills.skill import Skill
from archie_engine.skills.executor import SkillExecutor

logger = logging.getLogger(__name__)


class SkillRegistry:
    def __init__(self, skill_dirs: list[Path], executor: SkillExecutor):
        self.loader = SkillLoader(skill_dirs)
        self.executor = executor
        self._skills: dict[str, Skill] = {}

    def load(self) -> None:
        """Load all skills from configured directories."""
        skills = self.loader.load_all()
        self._skills = {s.name: s for s in skills}
        logger.info("Loaded %d skills", len(self._skills))

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def list_skills(self) -> list[dict]:
        return [s.to_dict() for s in self._skills.values()]

    async def execute(self, name: str, args: dict, context: dict | None = None) -> dict:
        skill = self._skills.get(name)
        if not skill:
            return {"success": False, "response": f"Skill not found: {name}"}
        return await self.executor.execute(skill, args=args, context=context)

    @staticmethod
    def parse_command(text: str) -> tuple[str, str]:
        """Parse '/command args' into (command_name, raw_args)."""
        text = text.strip()
        if not text.startswith("/"):
            return ("", text)
        parts = text[1:].split(None, 1)
        name = parts[0] if parts else ""
        raw_args = parts[1] if len(parts) > 1 else ""
        return (name, raw_args)
```

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run all tests**

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): skill registry — load, discover, execute slash commands"
```

---

### Task 4.6: Engine integration

**Files:**
- Modify: `archie_engine/engine.py` — wire skill registry
- Modify: `archie_engine/router.py` — detect slash commands before intent parsing

- [ ] **Step 1: Write integration test**

```python
# archie_engine/tests/test_skill_integration.py
import pytest
import pytest_asyncio
import json
import asyncio
import websockets
from archie_engine.engine import Engine
from archie_engine.config import EngineConfig


@pytest_asyncio.fixture
async def engine(tmp_path):
    # Create a custom skill
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "hello.md").write_text("---\nname: hello\ndescription: Say hello\n---\nSay hello to the user.")

    config = EngineConfig(data_dir=tmp_path, ws_port=0)
    eng = Engine(config, custom_skill_dirs=[skills_dir])
    await eng.start()
    yield eng
    await eng.stop()


@pytest.mark.asyncio
async def test_skill_list_via_websocket(engine):
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({"type": "list_skills"}))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        assert response["type"] == "skills_list"
        names = [s["name"] for s in response["skills"]]
        assert "hello" in names
        # Community skills should also be loaded
        assert "commit" in names


@pytest.mark.asyncio
async def test_slash_command_routes_to_skill(engine):
    uri = f"ws://{engine.config.ws_host}:{engine.server.port}"
    async with websockets.connect(uri) as ws:
        await ws.send(json.dumps({
            "type": "message",
            "content": "/hello",
        }))
        response = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        assert response["type"] == "response"
```

- [ ] **Step 2: Run — verify fail**

- [ ] **Step 3: Wire skills into Engine**

Modify `engine.py`:
1. Import skills modules
2. In `__init__`, create `SkillExecutor` and `SkillRegistry` with community + custom + hub cache dirs
3. Call `self.skill_registry.load()` in `start()`
4. Add `list_skills` message type handler
5. In `_process_chat_message`, detect `/command` prefix before intent parsing — route to skill registry instead

Modify `router.py` or `engine.py`:
- If message starts with `/`, parse as slash command and execute via skill registry
- Otherwise, go through normal intent → router flow

- [ ] **Step 4: Run tests — PASS**

- [ ] **Step 5: Run FULL suite**

```bash
python -m pytest archie_engine/tests/ -v --tb=short
```

- [ ] **Step 6: Commit**

```bash
git add archie_engine/ && git commit -m "feat(engine): skill system integration — slash commands, community skills, custom dirs

Completes Plan 4 — Skill System. Components:
- Skill dataclass with YAML frontmatter parsing
- Loader discovers .md files from community/hub/custom dirs
- Executor renders templates and calls inference
- Registry maps slash commands to skills
- 6 community skills: commit, review, explain, debug, refactor, test
- Engine routes /commands to skills before intent parsing"
```

---

### Task 4.7: Push and close out

- [ ] **Step 1: Push**

```bash
git push
```

- [ ] **Step 2: Log decision**

```
mcp log_decision: "Skill System complete — slash commands with community skills"
mcp update_project_understanding: project 185 to 70%
```

---

## Post-Plan

After Plan 4, the remaining plans are:
- **Plan 5** — Claude Collaboration (MCP server/client)
- **Plan 6** — Go TUI (Bubble Tea)
- **Plan 7** — Distribution (pip, installer)
- **Plan 8** — Website + Public Repo

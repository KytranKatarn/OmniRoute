"""ARCHIE Engine — main daemon wiring all components."""

import logging
from pathlib import Path

from archie_engine.config import EngineConfig
from archie_engine.database import Database
from archie_engine.session import SessionManager
from archie_engine.inference import InferenceClient
from archie_engine.intent import IntentParser
from archie_engine.router import CommandRouter
from archie_engine.server import EngineServer
from archie_engine.tools import ToolRegistry
from archie_engine.tools.file_ops import FileOpsTool
from archie_engine.tools.git_ops import GitOpsTool
from archie_engine.tools.shell_ops import ShellOpsTool

logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, config: EngineConfig):
        self.config = config
        self.db = Database(config.db_path)
        self.sessions = SessionManager(self.db)
        self.inference = InferenceClient(config.ollama_host)
        self.intent_parser = IntentParser()
        self.tools = self._build_tool_registry()
        self.router = CommandRouter(
            tools=self.tools,
            inference=self.inference,
            default_model=config.default_model,
        )
        self.server = EngineServer(config.ws_host, config.ws_port)

    @property
    def is_running(self) -> bool:
        return self.server.is_running

    def _build_tool_registry(self) -> ToolRegistry:
        registry = ToolRegistry()
        workspace = Path.cwd()
        registry.register(FileOpsTool(workspace=workspace))
        registry.register(GitOpsTool(workspace=workspace))
        registry.register(ShellOpsTool(workspace=workspace, config=self.config))
        return registry

    async def start(self) -> None:
        self.config.ensure_dirs()
        await self.db.initialize()
        self.server.set_handler(self.handle_message)
        await self.server.start()
        logger.info("ARCHIE Engine started")

    async def stop(self) -> None:
        await self.server.stop()
        await self.db.close()
        logger.info("ARCHIE Engine stopped")

    async def handle_message(self, msg: dict) -> dict:
        """Process a message from WebSocket client."""
        msg_type = msg.get("type", "")

        if msg_type == "session_create":
            working_dir = msg.get("working_dir", str(Path.cwd()))
            session = await self.sessions.create(working_dir=working_dir)
            return {"type": "session_created", "session_id": session["id"]}

        if msg_type == "session_resume":
            session_id = msg.get("session_id", "")
            session = await self.sessions.get(session_id)
            if session:
                return {"type": "session_resumed", "session_id": session["id"]}
            return {"type": "error", "error": f"Session not found: {session_id}"}

        if msg_type == "message":
            return await self._process_chat_message(msg)

        return {"type": "error", "error": f"Unknown message type: {msg_type}"}

    async def _process_chat_message(self, msg: dict) -> dict:
        content = msg.get("content", "")
        session_id = msg.get("session_id")

        # Create session if needed
        if not session_id:
            session = await self.sessions.create(working_dir=str(Path.cwd()))
            session_id = session["id"]

        # Record user message
        await self.sessions.add_message(session_id, "user", content)

        # Classify intent
        intent = self.intent_parser.classify(content)

        # Build context
        context = await self.sessions.build_context(session_id)

        # Route to handler
        result = await self.router.route(intent, context)

        # Record assistant response
        response_text = result.get("response", "")
        await self.sessions.add_message(session_id, "assistant", response_text)

        return {
            "type": "response",
            "session_id": session_id,
            "content": response_text,
            "intent": intent["type"],
            "tool_calls": result.get("tool_calls", []),
        }

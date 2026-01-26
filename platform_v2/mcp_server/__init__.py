"""
A.R.C.H.I.E. MCP Server
Model Context Protocol server for AI integration

Phase 50: AI Integration Hub
Makes A.R.C.H.I.E. directly callable by Claude and other AI models.
"""

__version__ = "1.0.0"
__author__ = "A.R.C.H.I.E. Platform"

from .server import ArchieMCPServer
from .auth import MCPAuthenticator

__all__ = ['ArchieMCPServer', 'MCPAuthenticator']

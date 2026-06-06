# Read-only MCP HTTP gateway for the Codex container.
# Based on the platform image so the existing knowledge handlers + psycopg2 + deps
# are already present; we only add the MCP SDK + an ASGI server on top.
FROM archie_brain-archie_platform:latest

# MCP SDK (streamable HTTP) + ASGI server. Pinned for reproducibility.
RUN pip install --no-cache-dir "mcp>=1.13,<2" "uvicorn>=0.30"

COPY mcp-gateway/gateway.py /gateway/gateway.py
COPY mcp-gateway/entrypoint.sh /gateway/entrypoint.sh
RUN chmod +x /gateway/entrypoint.sh

WORKDIR /gateway
EXPOSE 7800
ENTRYPOINT ["/gateway/entrypoint.sh"]

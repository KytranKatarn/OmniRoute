"""Render the container's opt-in DS9 profile without persisting its credential."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit


def render(base_url, model):
    parsed = urlsplit(base_url)
    if (parsed.scheme != "http" or parsed.hostname != "host.docker.internal"
            or parsed.port != 20129 or parsed.path != "/v1"
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("DS9 must use the approved container gateway origin on port 20129")
    if model != "cxa/gpt-6.1-sol":
        raise ValueError("DS9 requires the credential's allowed model")
    return f'''model = {json.dumps(model)}
model_provider = "ds9"
approval_policy = "on-request"
sandbox_mode = "workspace-write"

[model_providers.ds9]
name = "Deep Space 9"
base_url = {json.dumps(base_url)}
env_key = "DS9_CODEX_API_KEY"
requires_openai_auth = false
wire_api = "responses"

# This tool set currently makes the app-server bridge reject the request.
# Keep it available in the ordinary direct profile while compatibility is fixed.
[mcp_servers.design_systems]
enabled = false
'''


if __name__ == "__main__":
    content = render(os.environ.get("DS9_CODEX_BASE_URL", "http://host.docker.internal:20129/v1"),
                     os.environ.get("DS9_CODEX_MODEL", "cxa/gpt-6.1-sol"))
    target = Path(os.environ.get("CODEX_HOME", "/codex-home")) / "ds9.config.toml"
    target.write_text(content)
    target.chmod(0o600)

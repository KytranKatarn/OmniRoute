import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ds9_profile", ROOT / "ds9_profile.py")
profile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(profile)


class TerminalConfigurationTests(unittest.TestCase):
    def test_launcher_supplies_mcp_bearer_to_independent_exec_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secrets = root / "secrets"
            secrets.mkdir()
            (secrets / "ds9_codex_gateway_api_key").write_text("fake-ds9")
            (secrets / "codex_kb_bearer").write_text("fake-kb")
            stub = root / "codex"
            stub.write_text('#!/bin/sh\ntest "$DS9_CODEX_API_KEY" = fake-ds9 && test "$ARCHIE_KB_BEARER" = fake-kb\n')
            stub.chmod(0o700)
            script = (ROOT / "codex-ds9.sh").read_text().replace("/run/secrets", str(secrets))
            env = {key: value for key, value in os.environ.items() if key != "ARCHIE_KB_BEARER"}
            env["PATH"] = str(root) + ":" + env["PATH"]
            subprocess.run(["sh"], input=script, text=True, env=env, check=True)

    def test_base_config_heredoc_produces_valid_toml(self):
        source = (ROOT.parents[1] / "scripts/start_codex_terminal.sh").read_text()
        content = source.split('cat > "$CODEX_HOME/config.toml" <<EOF\n', 1)[1].split('\nEOF', 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, CODEX_HOME=directory)
            subprocess.run(["sh"], input='cat > "$CODEX_HOME/config.toml" <<EOF\n' + content + '\nEOF\n',
                           text=True, env=env, check=True)
            data = tomllib.loads((Path(directory) / "config.toml").read_text())
            self.assertEqual(data["projects"]["/work"]["trust_level"], "trusted")
            self.assertEqual(data["mcp_servers"]["archie_kb"]["bearer_token_env_var"], "ARCHIE_KB_BEARER")

    def test_profile_preserves_client_policy_and_uses_env_credential(self):
        data = tomllib.loads(profile.render("http://host.docker.internal:20129/v1", "cxa/gpt-6.1-sol"))
        self.assertEqual(data["approval_policy"], "on-request")
        self.assertEqual(data["sandbox_mode"], "workspace-write")
        provider = data["model_providers"]["ds9"]
        self.assertEqual(provider["env_key"], "DS9_CODEX_API_KEY")
        self.assertEqual(provider["wire_api"], "responses")
        self.assertFalse(provider["requires_openai_auth"])
        self.assertFalse(data["mcp_servers"]["design_systems"]["enabled"])
        self.assertNotIn("archie_kb", data["mcp_servers"])

    def test_rejects_stale_and_credential_bearing_origins(self):
        for url in ["http://host.docker.internal:20128/v1", "http://evil/v1",
                    "http://user:secret@host.docker.internal:20129/v1",
                    "http://host.docker.internal:20129/v1?key=secret"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                profile.render(url, "cxa/gpt-6.1-sol")

    def test_rejects_model_outside_dedicated_credential_scope(self):
        with self.assertRaises(ValueError):
            profile.render("http://host.docker.internal:20129/v1", "auto/coding:free")

    def test_existing_workspace_is_never_reset_or_checked_out(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / ".git").mkdir(parents=True)
            token = root / "token"
            token.write_text("test-only")
            log = root / "git-calls"
            git = root / "git"
            git.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$TEST_GIT_LOG"\n')
            git.chmod(0o700)
            source = (ROOT / "init-workspace.sh").read_text()
            source = source.replace('REPO_DIR="/work/archie-platform"', f'REPO_DIR="{repo}"')
            source = source.replace('TOKEN_FILE="/run/secrets/codex_github_token"', f'TOKEN_FILE="{token}"')
            env = dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"], TEST_GIT_LOG=str(log))
            subprocess.run(["sh"], input=source, text=True, env=env, check=True, capture_output=True)
            calls = log.read_text().splitlines()
            self.assertTrue(any("core.hooksPath" in call for call in calls))
            self.assertFalse(any(word in call.split() for call in calls
                                 for word in ["reset", "checkout", "fetch", "clone"]))


if __name__ == "__main__":
    unittest.main()

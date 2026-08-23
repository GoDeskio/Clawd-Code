"""Tests for GitHub/GitLab connectors, MCP/agent hooks, and branch-then-PR rules."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.agent.session import Session, empty_token_usage, merge_token_usage
from src.config import load_config
from src.connectors.agents import assert_agent_url
from src.connectors.git_common import GitRuleError, assert_push_allowed
from src.connectors.github import GitHubConnector, start_github_device_login
from src.connectors.gitlab import start_gitlab_device_login
from src.connectors.store import (
    DEFAULT_GITHUB_OWNER,
    public_connectors,
    read_connectors,
    save_agent,
    save_forge_login,
    save_mcp_server,
    set_mcp_enabled,
)
from src.desktop.runtime import DesktopRuntime, provider_limit_hint
from src.providers.local_endpoints import RemoteEndpointError


class ConnectorHomeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.workspace = Path(self.tmp.name) / "workspace"
        self.workspace.mkdir()
        self.home_patch = patch("src.config.Path.home", return_value=self.home)
        self.session_home = patch("src.agent.session.Path.home", return_value=self.home)
        self.home_patch.start()
        self.session_home.start()

    def tearDown(self) -> None:
        self.home_patch.stop()
        self.session_home.stop()
        self.tmp.cleanup()


class TestBranchThenPr(unittest.TestCase):
    def test_refuses_default_branch_unless_named(self) -> None:
        with self.assertRaises(GitRuleError):
            assert_push_allowed("main", default="main", operator_named=False)
        with self.assertRaises(GitRuleError):
            assert_push_allowed("master", default="master", operator_named=False)
        with self.assertRaises(GitRuleError):
            assert_push_allowed("", default="main", operator_named=False)

    def test_allows_named_default_or_feature(self) -> None:
        self.assertEqual(assert_push_allowed("main", default="main", operator_named=True), "main")
        self.assertEqual(assert_push_allowed("jonathan/feature", default="main", operator_named=False), "jonathan/feature")


class TestForgeStore(ConnectorHomeTest):
    def test_public_connectors_masks_tokens(self) -> None:
        save_forge_login("github", token="ghp_supersecrettoken", owner="GoDeskio", login="alice")
        save_forge_login("gitlab", token="glpat-anothersecret", owner="group", login="bob", forge_host="https://gitlab.example")
        public = public_connectors()
        dumped = json.dumps(public)
        self.assertNotIn("ghp_supersecrettoken", dumped)
        self.assertNotIn("glpat-anothersecret", dumped)
        self.assertTrue(public["github"]["configured"])
        self.assertEqual(public["github"]["owner"], DEFAULT_GITHUB_OWNER)
        self.assertTrue(public["gitlab"]["configured"])
        self.assertEqual(public["gitlab"]["host"], "https://gitlab.example")

    def test_config_encodes_connector_secrets_on_disk(self) -> None:
        save_forge_login("github", token="ghp_disksecret99", owner="GoDeskio")
        raw = json.loads((self.home / ".clawd" / "config.json").read_text(encoding="utf-8"))
        self.assertNotEqual(raw["connectors"]["github"]["token"], "ghp_disksecret99")
        self.assertNotIn("ghp_disksecret99", json.dumps(raw))
        loaded = load_config()
        self.assertEqual(loaded["connectors"]["github"]["token"], "ghp_disksecret99")

    def test_github_create_defaults_to_godeskio(self) -> None:
        connector = GitHubConnector()
        connector.token = "tok"
        with patch.object(GitHubConnector, "whoami", return_value={"login": "alice"}), patch.object(
            GitHubConnector, "_api", return_value={
                "full_name": "GoDeskio/demo",
                "clone_url": "https://github.com/GoDeskio/demo.git",
                "html_url": "https://github.com/GoDeskio/demo",
                "default_branch": "main",
            }
        ) as api:
            created = connector.create_repo("demo")
        self.assertEqual(created["owner"], "GoDeskio")
        self.assertEqual(created["full_name"], "GoDeskio/demo")
        self.assertEqual(api.call_args.args[0], "/orgs/GoDeskio/repos")

    def test_device_login_requires_user_client_id(self) -> None:
        with self.assertRaises(ValueError):
            start_github_device_login("")
        with self.assertRaises(ValueError):
            start_gitlab_device_login("")


class TestMcpAndAgents(ConnectorHomeTest):
    def test_save_list_enable_mcp(self) -> None:
        public = save_mcp_server(name="fs", command="npx", args=["-y", "demo"], token="mcp-secret")
        self.assertEqual(len(public["mcp"]), 1)
        self.assertTrue(public["mcp"][0]["enabled"])
        self.assertTrue(public["mcp"][0]["has_token"])
        self.assertNotIn("mcp-secret", json.dumps(public))
        disabled = set_mcp_enabled("fs", False)
        self.assertFalse(disabled["mcp"][0]["enabled"])
        data = read_connectors()
        self.assertEqual(data["mcp"][0]["token"], "mcp-secret")

    def test_save_agent_and_reject_wan_http(self) -> None:
        public = save_agent(name="local-codex", base_url="http://127.0.0.1:3999/v1", api_key="agent-secret")
        self.assertEqual(public["agents"][0]["name"], "local-codex")
        self.assertNotIn("agent-secret", json.dumps(public))
        self.assertTrue(assert_agent_url("http://127.0.0.1:3999/v1"))
        self.assertTrue(assert_agent_url("https://agents.example.com/v1", allow_remote=True))
        with self.assertRaises(RemoteEndpointError):
            assert_agent_url("http://8.8.8.8:3999/v1")


class TestInboundHook(ConnectorHomeTest):
    def test_inbound_hook_starts_a_job(self) -> None:
        runtime = DesktopRuntime(workspace=self.workspace)
        result = runtime.inbound_hook("hello from another agent")
        self.assertTrue(result["ok"])
        self.assertTrue(result["job_id"])


class TestDesktopConnectorSurface(ConnectorHomeTest):
    def test_desktop_html_exposes_git_and_agents(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "src" / "desktop" / "web" / "index.html").read_text(encoding="utf-8")
        for needle in (
            "Jonathan Ai",
            "GitHub",
            "GitLab",
            "Create repo and push",
            "MCP",
            "informational",
        ):
            self.assertIn(needle, html)
        self.assertNotIn("Buy tokens", html)
        self.assertNotIn("out of tokens", html)
        self.assertNotIn("upgrade prompt", html)

    def test_wizard_html_exposes_forges_and_clone(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "src" / "install" / "web" / "index.html").read_text(encoding="utf-8")
        self.assertIn("GitHub", html)
        self.assertIn("GitLab", html)
        self.assertIn("MCP", html)
        self.assertIn("Clone GoDeskio/Clawd-Code", html)
        self.assertIn("GoDeskio", html)


class TestTokenUsage(ConnectorHomeTest):
    def test_session_persists_usage(self) -> None:
        session = Session.create("openai", "gpt-test", workspace=str(self.workspace))
        self.assertEqual(session.token_usage, empty_token_usage())
        session.record_usage({"input_tokens": 10, "output_tokens": 4})
        session.record_usage({"prompt_tokens": 2, "completion_tokens": 3})
        self.assertEqual(session.token_usage["input_tokens"], 12)
        self.assertEqual(session.token_usage["output_tokens"], 7)
        self.assertEqual(session.token_usage["total_tokens"], 19)
        session.save()
        loaded = Session.load(session.session_id)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded.token_usage["total_tokens"], 19)
        listed = Session.list_sessions()
        self.assertEqual(listed[0]["token_usage"]["total_tokens"], 19)

    def test_merge_usage_is_informational(self) -> None:
        totals = merge_token_usage(None, {"input_tokens": 1})
        self.assertEqual(totals["total_tokens"], 1)

    def test_provider_limit_is_not_a_jonathan_wall(self) -> None:
        hint = provider_limit_hint("Error 429 rate_limit exceeded")
        self.assertIn("not a Jonathan Ai token store", hint)
        self.assertIn("informational", hint.lower())
        self.assertFalse(provider_limit_hint("file not found"))


if __name__ == "__main__":
    unittest.main()

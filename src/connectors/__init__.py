"""First-class Jonathan Ai connectors: GitHub, GitLab, MCP, and other agents.

Credentials stay in ~/.clawd/config.json. Nothing here phones home unless
the user clicks a connect / list / push / test action.
"""

from .agents import invoke_agent, list_agent_tools, test_agent_endpoint
from .github import GitHubConnector
from .gitlab import GitLabConnector
from .mcp_client import McpProcessClient, connect_mcp
from .store import (
    DEFAULT_GITHUB_OWNER,
    public_connectors,
    read_connectors,
    save_agent,
    save_forge_login,
    save_mcp_server,
    set_agent_enabled,
    set_mcp_enabled,
)

__all__ = [
    "DEFAULT_GITHUB_OWNER",
    "GitHubConnector",
    "GitLabConnector",
    "McpProcessClient",
    "connect_mcp",
    "invoke_agent",
    "list_agent_tools",
    "public_connectors",
    "read_connectors",
    "save_agent",
    "save_forge_login",
    "save_mcp_server",
    "set_agent_enabled",
    "set_mcp_enabled",
    "test_agent_endpoint",
]

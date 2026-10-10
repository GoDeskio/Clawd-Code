"""Hand a coding task to a local ACP runner.

Jonathan Ai speaks the Agent Client Protocol over stdin and stdout. The
runner program stays on this machine. OpenCode, Claude Code, Codex, and Zed
are the built-in runners; each one is off until the user enables it and
sets its path.

Adapted from Octop's outbound ACP runner. Jonathan Ai does not vendor the
harness package or expose Jonathan as an ACP server.

Source: https://github.com/TencentCloud/Octop
Copyright (c) 2026 Octop
SPDX-License-Identifier: MIT
"""

from src.acp.service import format_acp_command

__all__ = ["format_acp_command"]

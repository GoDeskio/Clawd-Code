from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.tool_system.context import ToolContext
from src.tool_system.errors import ToolInputError
from src.tool_system.permission_handler import PermissionBehavior
from src.tool_system.tools.remote_computer import RemoteTriggerTool


class RemoteComputerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.tmp.name)
        self.context = ToolContext(workspace_root=self.workspace, gate_destructive_tools=True)
        self.tool = RemoteTriggerTool()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_remote_actions_are_permission_gated(self) -> None:
        result = self.tool.check_permissions({"action": "run", "host": "server.lan"}, self.context)
        self.assertEqual(result.behavior, PermissionBehavior.ASK)

    def test_rejects_host_command_injection(self) -> None:
        with self.assertRaises(ToolInputError):
            self.tool.run({"action": "probe", "host": "server; shutdown", "port": 22}, self.context)

    def test_probe_uses_bounded_tcp_connection(self) -> None:
        connection = MagicMock()
        connection.__enter__.return_value.getpeername.return_value = ("192.168.1.20", 22)
        with patch("src.tool_system.tools.remote_computer.socket.create_connection", return_value=connection) as connect:
            result = self.tool.run({"action": "probe", "host": "server.lan", "port": 22, "timeout_s": 7}, self.context)
        self.assertFalse(result.is_error)
        self.assertTrue(result.output["reachable"])
        connect.assert_called_once_with(("server.lan", 22), timeout=7)

    def test_ssh_uses_argument_array_and_existing_credentials(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="remote-ready\n", stderr="")
        with patch("src.tool_system.tools.remote_computer.shutil.which", return_value="C:/Windows/System32/OpenSSH/ssh.exe"), patch(
            "src.tool_system.tools.remote_computer.subprocess.run", return_value=completed
        ) as run:
            result = self.tool.run({
                "action": "run",
                "transport": "ssh",
                "host": "192.168.1.20",
                "user": "admin",
                "command": "hostname",
                "host_key_policy": "strict",
            }, self.context)
        self.assertFalse(result.is_error)
        args = run.call_args.args[0]
        self.assertIn("admin@192.168.1.20", args)
        self.assertIn("BatchMode=yes", args)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertEqual(args[-1], "hostname")
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_capabilities_never_accept_password_input(self) -> None:
        with patch("src.tool_system.tools.remote_computer.shutil.which", return_value="ssh"):
            result = self.tool.run({"action": "capabilities"}, self.context)
        self.assertFalse(result.output["password_input_supported"])
        schema = self.tool.spec().input_schema
        self.assertNotIn("password", schema["properties"])


if __name__ == "__main__":
    unittest.main()

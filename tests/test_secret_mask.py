"""API keys, tokens, passwords, and private keys are masked in output and logs."""

from __future__ import annotations

import io
import json
import logging
import tempfile
import unittest
from pathlib import Path

from src.secret_mask import install_log_masking, mask_secrets, mask_tool_output
from src.tool_system.context import ToolContext
from src.tool_system.protocol import ToolResult
from src.tool_system.tools.bash import BashTool
from src.tool_system.tools.read import FileReadTool


class TestSecretMask(unittest.TestCase):
    def test_masks_api_keys_tokens_and_passwords(self) -> None:
        openai_key = "sk-" + ("a" * 24)
        anthropic_key = "sk-ant-" + ("b" * 24)
        aws_key = "AKIA" + ("C" * 16)
        github_token = "ghp_" + ("d" * 20)
        bearer = "Bearer " + ("e" * 16)
        password = "password=hunter2hunter2"
        text = "\n".join([openai_key, anthropic_key, aws_key, github_token, bearer, password])
        masked = mask_secrets(text)
        for secret in (openai_key, anthropic_key, aws_key, github_token, "e" * 16, "hunter2hunter2"):
            self.assertNotIn(secret, masked)
        self.assertIn("sk-", masked)
        self.assertIn("password=", masked)
        self.assertIn("*", masked)
        self.assertEqual(mask_secrets(masked), masked)

    def test_masks_private_key_block(self) -> None:
        pem = "\n".join(
            [
                "-----BEGIN OPENSSH PRIVATE KEY-----",
                "AAAAB3NzaC1yc2EAAAADAQABAAABAQDsecretmaterial",
                "-----END OPENSSH PRIVATE KEY-----",
            ]
        )
        masked = mask_secrets("prefix {0} suffix".format(pem))
        self.assertNotIn("secretmaterial", masked)
        self.assertNotIn("BEGIN OPENSSH PRIVATE KEY", masked)
        self.assertIn("[REDACTED PRIVATE KEY]", masked)
        self.assertIn("prefix", masked)
        self.assertIn("suffix", masked)

    def test_leaves_uuid_and_plain_text(self) -> None:
        uuid = "123e4567-e89b-12d3-a456-426614174000"
        text = "commit {0} and hello".format(uuid)
        self.assertEqual(mask_secrets(text), text)

    def test_tool_result_masks_nested_output(self) -> None:
        secret = "sk-proj-" + ("f" * 24)
        result = ToolResult(name="Read", output={"file": {"content": "1\t{0}".format(secret)}})
        encoded = json.dumps(result.output)
        self.assertNotIn(secret, encoded)
        self.assertIn("*", encoded)

    def test_bash_stdout_is_masked(self) -> None:
        secret = "sk-" + ("a" * 28)
        with tempfile.TemporaryDirectory() as tmp:
            ctx = ToolContext(workspace_root=Path(tmp))
            output = BashTool().run({"command": "echo {0}".format(secret)}, ctx).output
        self.assertNotIn(secret, output["stdout"])
        self.assertIn("sk-", output["stdout"])

    def test_read_tool_masks_file_secrets(self) -> None:
        password_line = "password=s3cret-value"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "notes.txt"
            target.write_text("name=widget\n{0}\n".format(password_line), encoding="utf-8")
            ctx = ToolContext(workspace_root=root)
            output = FileReadTool().run({"file_path": str(target)}, ctx).output
        content = output["file"]["content"]
        self.assertNotIn("s3cret-value", content)
        self.assertIn("password=", content)
        self.assertIn("widget", content)

    def test_logs_are_masked(self) -> None:
        install_log_masking()
        secret = "hf_" + ("a" * 32)
        logger = logging.getLogger("jonathan.test.secretmask")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        buffer = io.StringIO()
        handler = logging.StreamHandler(buffer)
        logger.addHandler(handler)
        try:
            logger.info("provider token %s", secret)
            logger.warning("password=%s", "correcthorsebatterystaple")
        finally:
            logger.removeHandler(handler)
        logged = buffer.getvalue()
        self.assertNotIn(secret, logged)
        self.assertNotIn("correcthorsebatterystaple", logged)
        self.assertIn("*", logged)

    def test_mapping_keys_are_masked(self) -> None:
        secret = "glpat-" + ("a" * 20)
        masked = mask_tool_output({secret: "visible"})
        self.assertNotIn(secret, json.dumps(masked))


if __name__ == "__main__":
    unittest.main()

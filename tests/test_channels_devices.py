"""Chat channels and LAN device control. No live network and no real bots."""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.channels.parse import parse_discord_message, parse_slack_event, parse_telegram_updates
from src.channels.service import (
    format_channels_command,
    ingest_payload,
    public_channels,
    route_inbound,
    update_channels,
)
from src.channels.parse import Inbound
from src.channels.transport import official_url
from src.command_system.builtins import execute_command_sync
from src.command_system.engine import create_command_context
from src.desktop.runtime import ChatJob, DesktopRuntime, _HELP_TEXT
from src.desktop.server import DesktopServer
from src.devices.control import perform_action
from src.devices.discover import (
    build_mdns_address,
    build_mdns_query,
    build_ssdp_probe,
    discover_from_sources,
    parse_arp_table,
    parse_ssdp_response,
)
from src.devices.lan import WanTargetError, require_private_host
from src.devices.registry import public_devices, update_devices
from src.secret_mask import mask_secrets
from src.secret_store import get_secret, put_secret
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.permission_handler import PermissionBehavior
from src.tool_system.protocol import ToolCall
from src.tool_system.registry import ToolRegistry
from src.tool_system.tools.device import DeviceTool

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "123456789:" + ("A" * 35)
DISCORD_TOKEN = "M" + ("a" * 23) + ".abcdef." + ("b" * 27)
SLACK_TOKEN = "xoxb-" + ("c" * 24)


class MemoryKeyring:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, account: str, value: str) -> None:
        self.data[(service, account)] = value

    def get_password(self, service: str, account: str) -> str | None:
        return self.data.get((service, account))


class GatewayTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.channels = self.root / "channels"
        self.devices = self.root / "devices"
        self._env = patch.dict(
            os.environ,
            {
                "JONATHAN_CHANNELS_DIR": str(self.channels),
                "JONATHAN_DEVICES_DIR": str(self.devices),
                "JONATHAN_USER": "gateway-test",
                "JONATHAN_SECRET_BACKEND": "file",
            },
        )
        self._env.start()

    def tearDown(self) -> None:
        self._env.stop()
        self.tmp.cleanup()


class TestSecretStore(GatewayTestCase):
    def test_file_roundtrip_is_private_and_keyring_is_separate(self) -> None:
        put_secret(self.channels, "alice", "channel-telegram", TOKEN)
        self.assertEqual(get_secret(self.channels, "alice", "channel-telegram"), TOKEN)
        self.assertEqual(get_secret(self.channels, "bob", "channel-telegram"), "")
        path = next(self.channels.glob("secret-alice-*.bin"))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(TOKEN.encode(), path.read_bytes())
        ring = MemoryKeyring()
        put_secret(self.channels, "alice", "channel-slack", SLACK_TOKEN, backend=ring)
        self.assertEqual(get_secret(self.channels, "alice", "channel-slack", backend=ring), SLACK_TOKEN)
        self.assertFalse(list(self.channels.glob("secret-alice-*slack*")))


class TestChannels(GatewayTestCase):
    def test_allow_list_routes_only_named_users(self) -> None:
        update_channels(
            [{"id": "telegram", "enabled": True, "allow_user_ids": "42", "token": TOKEN}],
            self.channels,
        )
        view = public_channels(self.channels)
        blob = json.dumps(view)
        self.assertNotIn(TOKEN, blob)
        self.assertTrue(view["channels"][0]["token_set"])
        self.assertEqual((self.channels / "settings-gateway-test.json").stat().st_mode & 0o777, 0o600)

        called: list[str] = []

        def reply(text: str) -> str:
            called.append(text)
            return "echo " + text

        dropped = route_inbound(Inbound("telegram", "7", "nope", "7"), reply, directory=self.channels)
        self.assertFalse(dropped["accepted"])
        self.assertEqual(called, [])

        sent: list[str] = []

        def transport(method: str, url: str, headers: dict, payload: dict) -> dict:
            sent.append(urlparse_host(url))
            self.assertNotIn("example.com", url)
            return {"ok": True}

        accepted = route_inbound(
            Inbound("telegram", "42", "lights", "42"),
            reply,
            directory=self.channels,
            transport=transport,
        )
        self.assertTrue(accepted["accepted"])
        self.assertEqual(called, ["lights"])
        self.assertEqual(sent, ["api.telegram.org"])
        self.assertNotIn(TOKEN, accepted["reply"])

    def test_payloads_and_logs_hide_the_token(self) -> None:
        update_channels(
            [
                {"id": "discord", "enabled": True, "allow_user_ids": ["99"], "token": DISCORD_TOKEN},
                {"id": "slack", "enabled": True, "allow_user_ids": ["U1"], "token": SLACK_TOKEN},
            ],
            self.channels,
        )
        records: list[str] = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        logger = logging.getLogger("src.channels.service")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        try:
            telegram = parse_telegram_updates(
                {"ok": True, "result": [{"update_id": 1, "message": {"text": "hi", "from": {"id": 42}, "chat": {"id": 42}}}]}
            )
            self.assertEqual(telegram[0].user_id, "42")
            discord = parse_discord_message(
                {"t": "MESSAGE_CREATE", "d": {"author": {"id": "99"}, "content": "hi", "channel_id": "c1"}}
            )
            slack = parse_slack_event({"event": {"type": "message", "user": "U1", "text": "hi", "channel": "C1"}})
            assert discord is not None and slack is not None
            calls: list[str] = []

            def transport(method: str, url: str, headers: dict, payload: dict) -> dict:
                calls.append(urlparse_host(url))
                joined = json.dumps({"headers": headers, "payload": payload})
                if "discord.com" in url:
                    self.assertIn("Bot ", headers["Authorization"])
                if "slack.com" in url:
                    self.assertNotIn(SLACK_TOKEN, payload["text"])
                return {"ok": True}

            ingest_payload("discord", {"t": "MESSAGE_CREATE", "d": {"author": {"id": "99", "bot": False}, "content": "ping", "channel_id": "c1"}}, lambda text: TOKEN, directory=self.channels, transport=transport)
            ingest_payload("slack", {"event": {"user": "U1", "text": "ping", "channel": "C1"}}, lambda text: "ok", directory=self.channels, transport=transport)
        finally:
            logger.removeHandler(handler)
        self.assertEqual(calls, ["discord.com", "slack.com"])
        self.assertTrue(records)
        self.assertFalse(any(TOKEN in line or DISCORD_TOKEN in line or SLACK_TOKEN in line for line in records))
        self.assertNotIn(TOKEN, mask_secrets("see " + TOKEN))

    def test_unofficial_host_and_unknown_channel_are_refused(self) -> None:
        with self.assertRaises(ValueError):
            official_url("telegram", "https://example.invalid/bot")
        with self.assertRaises(ValueError):
            update_channels([{"id": "weixin", "enabled": True}], self.channels)
        listed = format_channels_command("list", directory=self.channels)
        self.assertIn("telegram", listed)
        self.assertIn("discord", listed)
        self.assertIn("slack", listed)
        self.assertNotIn(TOKEN, listed)

    def test_users_do_not_share_settings(self) -> None:
        update_channels([{"id": "slack", "enabled": True, "allow_user_ids": ["U9"]}], self.channels, user_id="alice")
        bob = public_channels(self.channels, user_id="bob")
        alice = public_channels(self.channels, user_id="alice")
        self.assertFalse(next(row for row in bob["channels"] if row["id"] == "slack")["enabled"])
        self.assertTrue(next(row for row in alice["channels"] if row["id"] == "slack")["enabled"])


class TestDevices(GatewayTestCase):
    def _register(self, **extra) -> None:
        row = {
            "id": "lamp",
            "kind": "homeassistant",
            "host": "192.168.1.20",
            "actions": ["light.turn_on"],
            "secret": "ha-token-secret-value",
        }
        row.update(extra)
        update_devices([row], self.devices)

    def test_lan_check_and_discovery_drop_wan(self) -> None:
        self.assertEqual(require_private_host("192.168.1.10"), "192.168.1.10")
        self.assertEqual(require_private_host("10.0.0.2"), "10.0.0.2")
        self.assertEqual(require_private_host("169.254.1.5"), "169.254.1.5")
        self.assertEqual(require_private_host("fd00::1"), "fd00::1")
        with self.assertRaises(WanTargetError):
            require_private_host("8.8.8.8")
        with self.assertRaises(WanTargetError):
            require_private_host("1.1.1.1")
        with self.assertRaises(WanTargetError):
            update_devices([{"id": "wan", "kind": "http", "host": "8.8.8.8", "actions": ["on"]}], self.devices)
        arp = parse_arp_table(
            "IP address HW Flags HW address Mask Device\n"
            "192.168.1.5 0x1 0x2 aa:bb:cc:dd:ee:ff * eth0\n"
            "8.8.8.8 0x1 0x2 11:22:33:44:55:66 * eth0\n"
        )
        self.assertEqual([row["address"] for row in arp], ["192.168.1.5"])
        self.assertIsNone(parse_ssdp_response("HTTP/1.1 200 OK\r\nLOCATION: http://1.1.1.1/desc.xml\r\nST: upnp\r\n"))
        local = parse_ssdp_response("HTTP/1.1 200 OK\r\nLOCATION: http://192.168.1.40:1400/desc.xml\r\nST: MediaRenderer\r\n")
        assert local is not None
        rows = discover_from_sources(
            arp_text="192.168.1.5 aa:bb:cc:dd:ee:ff",
            ssdp_texts=["LOCATION: http://192.168.1.40:1400/x\r\nST: lamp\r\n"],
            mdns_packets=[build_mdns_address("lamp.local", "192.168.1.9"), build_mdns_address("wan.example", "8.8.8.8")],
        )
        addresses = {row["address"] for row in rows}
        self.assertIn("192.168.1.9", addresses)
        self.assertNotIn("8.8.8.8", addresses)
        self.assertIn(b"M-SEARCH", build_ssdp_probe())
        self.assertTrue(build_mdns_query().startswith(b"\x00\x00"))

    def test_actions_are_approval_gated_even_with_a_session_grant(self) -> None:
        self._register()
        ctx = ToolContext(workspace_root=self.root, devices_dir=self.devices)
        ctx.gate_destructive_tools = True
        ctx.session_grants.add("*")
        calls: list[str] = []

        def poster(method: str, url: str, headers: dict, body: bytes) -> str:
            calls.append(url)
            self.assertNotIn("ha-token-secret-value", url)
            return "ok"

        ctx.device_poster = poster
        tool = DeviceTool()
        decision = tool.check_permissions({"device": "lamp", "action": "light.turn_on"}, ctx)
        self.assertEqual(decision.behavior, PermissionBehavior.ASK)
        self.assertIn("192.168.1.20", decision.message or "")
        self.assertIn("light.turn_on", decision.message or "")
        registry = ToolRegistry(tools=[DeviceTool()])
        blocked = registry.dispatch(ToolCall(name="Device", input={"device": "lamp", "action": "light.turn_on"}), ctx)
        self.assertTrue(blocked.is_error)
        self.assertEqual(calls, [])
        denied = tool.check_permissions({"device": "lamp", "action": "light.turn_off"}, ctx)
        self.assertEqual(denied.behavior, PermissionBehavior.DENY)

        def allow(tool_name: str, message: str, suggestion: str | None) -> tuple[bool, bool]:
            del tool_name, message, suggestion
            return True, False

        ctx.permission_handler = allow
        result = registry.dispatch(ToolCall(name="Device", input={"device": "lamp", "action": "light.turn_on"}), ctx)
        self.assertFalse(result.is_error)
        self.assertEqual(calls, ["http://192.168.1.20:8123/api/services/light/turn_on"])
        self.assertNotIn("ha-token-secret-value", result.output["text"])

    def test_ssh_danger_and_mqtt_stay_local(self) -> None:
        update_devices(
            [
                {"id": "shell", "kind": "ssh", "host": "10.1.2.3", "user": "pi", "actions": ["rm -rf /", "echo hi"]},
                {"id": "broker", "kind": "mqtt", "host": "192.168.1.8", "actions": ["lamps/on"], "secret": "mqtt-secret"},
            ],
            self.devices,
        )
        ctx = ToolContext(workspace_root=self.root, devices_dir=self.devices)
        ran: list[list[str]] = []

        def ssh_runner(argv: list[str]) -> str:
            ran.append(argv)
            return "ok"

        ctx.device_ssh = ssh_runner
        danger = DeviceTool().check_permissions({"device": "shell", "action": "rm -rf /"}, ctx)
        self.assertEqual(danger.behavior, PermissionBehavior.ASK)
        self.assertIn("rm", (danger.message or "").lower())
        blocked = DeviceTool().run({"device": "shell", "action": "rm -rf /"}, ctx)
        self.assertTrue(blocked.is_error)
        self.assertEqual(ran, [])
        key_ctx = ToolContext(workspace_root=self.root, devices_dir=self.devices)
        from src.devices.control import approval_key

        key_ctx.approved_shell_commands.add(approval_key("shell", "echo hi"))
        key_ctx.device_ssh = ssh_runner
        safe = DeviceTool().run({"device": "shell", "action": "echo hi"}, key_ctx)
        self.assertFalse(safe.is_error)
        self.assertEqual(ran[0][0], "ssh")
        self.assertEqual(ran[0][-1], "echo hi")
        self.assertNotIn("-c", ran[0])
        packets: list[bytes] = []

        def tcp(host: str, port: int, packet: bytes) -> None:
            self.assertEqual(host, "192.168.1.8")
            packets.append(packet)

        text = perform_action(
            {"id": "broker", "kind": "mqtt", "host": "192.168.1.8", "port": 1883, "user": "", "actions": ["lamps/on"]},
            "lamps/on",
            directory=self.devices,
            user_id="gateway-test",
            tcp_send=tcp,
        )
        self.assertIn("192.168.1.8", text)
        self.assertIn(b"lamps/on", packets[0])
        self.assertNotIn(b"mqtt-secret", packets[0])
        view = public_devices(self.devices)
        self.assertNotIn("mqtt-secret", json.dumps(view))
        self.assertNotIn("ha-token-secret-value", json.dumps(view))


class TestUiAndCommands(GatewayTestCase):
    def test_help_panel_and_registry(self) -> None:
        html = (ROOT / "src" / "desktop" / "web" / "index.html").read_text(encoding="utf-8")
        for label in ("Telegram", "Discord", "Slack", "Home Assistant", "channels-save", "devices-save", "LAN devices"):
            self.assertIn(label, html)
        for banned in ("WeChat", "Feishu", "DingTalk", "GLM", "Minimax", "Zhipu"):
            self.assertNotIn(banned, html)
        self.assertIn("/channels", _HELP_TEXT)
        self.assertIn("/devices", _HELP_TEXT)
        names = [spec.name for spec in build_default_registry(include_user_tools=False).list_specs()]
        self.assertEqual(names[17], "Skill")
        self.assertGreater(names.index("Device"), 17)
        context = create_command_context(self.root)
        ok, text, error = execute_command_sync("channels", "list", context)
        self.assertTrue(ok, error)
        self.assertIn("slack", text or "")
        ok, devices, error = execute_command_sync("devices", "list", context)
        self.assertTrue(ok, error)
        self.assertIn("none registered", devices or "")

    def test_import_does_not_load_channel_sdks(self) -> None:
        import src.channels
        import src.devices

        self.assertIn("src.channels", sys.modules)
        self.assertIn("src.devices", sys.modules)
        for name in ("telegram", "discord", "paho", "octop_gateway", "slack_sdk"):
            self.assertNotIn(name, sys.modules)

    def test_desktop_routes_inbound_and_asks_before_control(self) -> None:
        update_channels([{"id": "slack", "enabled": True, "allow_user_ids": ["U1"]}], self.channels)
        update_devices(
            [{"id": "plug", "kind": "http", "host": "192.168.1.30", "actions": ["/on"]}],
            self.devices,
        )
        server = DesktopServer(DesktopRuntime(workspace=self.root, permission_timeout_s=1.0))
        status, body = server.handle_api("GET", "/api/channels", {}, {})
        self.assertEqual(status, 200)
        self.assertNotIn("token", json.dumps(body).replace("token_set", ""))
        accepted = server.runtime.channel_inbound({"channel": "slack", "user_id": "U1", "text": "hello"})
        self.assertTrue(accepted["accepted"])
        self.assertIn("hello", accepted["reply"])
        dropped = server.runtime.channel_inbound({"channel": "slack", "user_id": "U2", "text": "hello"})
        self.assertFalse(dropped["accepted"])
        calls: list[str] = []
        server.runtime.tool_context.devices_dir = self.devices

        def poster(method: str, url: str, headers: dict, body: bytes) -> str:
            calls.append(url)
            return "ok"

        server.runtime.tool_context.device_poster = poster

        def allow(tool_name: str, message: str, suggestion: str | None) -> tuple[bool, bool]:
            self.assertIn("192.168.1.30", message)
            del tool_name, suggestion
            return True, False

        server.runtime.tool_context.permission_handler = allow
        job = ChatJob(job_id="device-job")
        server.runtime._run_device_slash(job, "do plug /on")
        self.assertTrue(job.done)
        self.assertEqual(calls, ["http://192.168.1.30:80/on"])


def urlparse_host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).hostname or ""


if __name__ == "__main__":
    unittest.main()

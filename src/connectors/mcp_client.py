"""Minimal MCP client (stdio JSON-RPC and HTTP JSON-RPC).

Only connects to servers the user added. No bundled fake agents.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from typing import Any
from urllib.request import Request, urlopen

from src.version import get_version

from .store import read_connectors


class McpError(RuntimeError):
    pass


class McpProcessClient:
    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> None:
        self.command = command
        self.args = list(args or [])
        self.env = env or {}
        self._proc: subprocess.Popen[bytes] | None = None
        self._id = 0
        self._lock = threading.Lock()

    def _ensure(self) -> subprocess.Popen[bytes]:
        if self._proc and self._proc.poll() is None:
            return self._proc
        env = os.environ.copy()
        env.update(self.env)
        self._proc = subprocess.Popen(
            [self.command, *self.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self._rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "jonathan-ai", "version": get_version()},
        })
        self._notify("notifications/initialized", {})
        return self._proc

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _write(self, payload: dict[str, Any]) -> None:
        proc = self._ensure()
        assert proc.stdin is not None
        raw = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
        proc.stdin.write(header + raw)
        proc.stdin.flush()

    def _read(self) -> dict[str, Any]:
        proc = self._proc
        assert proc is not None and proc.stdout is not None
        headers: dict[str, str] = {}
        while True:
            line = proc.stdout.readline()
            if not line:
                raise McpError("MCP server closed stdout")
            if line in {b"\r\n", b"\n"}:
                break
            key, _, value = line.decode("utf-8", errors="replace").partition(":")
            headers[key.strip().lower()] = value.strip()
        length = int(headers.get("content-length") or "0")
        raw = proc.stdout.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        with self._lock:
            message = {"jsonrpc": "2.0", "id": self._next_id(), "method": method, "params": params or {}}
            self._write(message)
            deadline = time.time() + 20
            while time.time() < deadline:
                reply = self._read()
                if reply.get("id") == message["id"]:
                    if reply.get("error"):
                        raise McpError(str(reply["error"]))
                    return reply.get("result")
            raise McpError(f"timeout waiting for {method}")

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def list_tools(self) -> list[str]:
        result = self._rpc("tools/list")
        tools = result.get("tools") if isinstance(result, dict) else result
        names: list[str] = []
        if isinstance(tools, list):
            for item in tools:
                if isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]))
                elif isinstance(item, str):
                    names.append(item)
        return names

    def call_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        return self._rpc("tools/call", {"name": tool_name, "arguments": args})

    def list_resources(self) -> list[dict[str, Any]]:
        try:
            result = self._rpc("resources/list")
        except Exception:
            return []
        items = result.get("resources") if isinstance(result, dict) else result
        return items if isinstance(items, list) else []

    def read_resource(self, uri: str) -> dict[str, Any]:
        result = self._rpc("resources/read", {"uri": uri})
        return result if isinstance(result, dict) else {"contents": result}


class McpHttpClient:
    def __init__(self, url: str, token: str | None = None) -> None:
        self.url = url.rstrip("/")
        self.token = (token or "").strip()
        self._id = 0

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> Any:
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "JonathanAi/0.1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = Request(self.url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        if data.get("error"):
            raise McpError(str(data["error"]))
        return data.get("result")

    def list_tools(self) -> list[str]:
        result = self._rpc("tools/list")
        tools = result.get("tools") if isinstance(result, dict) else result
        names = []
        if isinstance(tools, list):
            for item in tools:
                if isinstance(item, dict) and item.get("name"):
                    names.append(str(item["name"]))
        return names

    def call_tool(self, tool_name: str, args: dict[str, Any]) -> Any:
        return self._rpc("tools/call", {"name": tool_name, "arguments": args})

    def list_resources(self) -> list[dict[str, Any]]:
        try:
            result = self._rpc("resources/list")
        except Exception:
            return []
        items = result.get("resources") if isinstance(result, dict) else result
        return items if isinstance(items, list) else []

    def read_resource(self, uri: str) -> dict[str, Any]:
        result = self._rpc("resources/read", {"uri": uri})
        return result if isinstance(result, dict) else {"contents": result}


def connect_mcp(record: dict[str, Any]) -> McpProcessClient | McpHttpClient:
    if record.get("command"):
        return McpProcessClient(str(record["command"]), list(record.get("args") or []))
    if record.get("url"):
        return McpHttpClient(str(record["url"]), token=str(record.get("token") or ""))
    raise ValueError("MCP server needs a command or URL")


def enabled_mcp_clients() -> dict[str, Any]:
    clients: dict[str, Any] = {}
    for item in read_connectors().get("mcp") or []:
        if not isinstance(item, dict) or not item.get("enabled", True):
            continue
        name = str(item.get("name") or item.get("id") or "")
        if not name:
            continue
        try:
            clients[name] = connect_mcp(item)
        except Exception:
            continue
    return clients


def test_mcp_record(record: dict[str, Any]) -> dict[str, Any]:
    client = connect_mcp(record)
    tools = client.list_tools()
    return {"ok": True, "tools": tools, "name": record.get("name")}

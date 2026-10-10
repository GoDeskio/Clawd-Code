"""Local stand-in for an ACP coding agent. Speaks newline JSON-RPC on stdio."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    cwd = Path.cwd()
    session_id = "sess-1"
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        message = json.loads(line)
        method = message.get("method")
        msg_id = message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "initialize":
            _emit(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": 1,
                        "agentInfo": {"name": "fake-acp", "version": "0"},
                    },
                }
            )
            continue
        if method == "session/new":
            raw_cwd = params.get("cwd")
            if isinstance(raw_cwd, str) and raw_cwd:
                cwd = Path(raw_cwd)
            _emit({"jsonrpc": "2.0", "id": msg_id, "result": {"sessionId": session_id}})
            continue
        if method == "session/prompt":
            text = ""
            for block in params.get("prompt") or []:
                if isinstance(block, dict):
                    text += str(block.get("text") or "")
            (cwd / "delegated.txt").write_text(text + "\n", encoding="utf-8")
            _emit(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "agent_message_chunk",
                            "content": {"type": "text", "text": "Writing delegated.txt\n" + text},
                        },
                    },
                }
            )
            _emit(
                {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": session_id,
                        "update": {
                            "sessionUpdate": "tool_call",
                            "toolCallId": "call-1",
                            "title": "write delegated.txt",
                            "kind": "edit",
                            "status": "completed",
                            "locations": [{"path": "delegated.txt"}],
                        },
                    },
                }
            )
            _emit({"jsonrpc": "2.0", "id": msg_id, "result": {"stopReason": "end_turn"}})
            continue
        if msg_id is not None:
            _emit(
                {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"unsupported method {method}"},
                }
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

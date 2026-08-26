"""Durable, bounded goal governance for long-running conversation agents."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from ..context import ToolContext
from ..errors import ToolExecutionError, ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{7,63}$")
_READ_ACTIONS = {"list", "status", "continuation"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any, name: str, *, limit: int = 4000, required: bool = True) -> str:
    result = str(value or "").strip()
    if required and not result:
        raise ToolInputError(f"{name} is required")
    if len(result) > limit:
        raise ToolInputError(f"{name} must be at most {limit} characters")
    return result


def _identifier(prefix: str) -> str:
    return f"{prefix}_{_now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def _store_dir() -> Path:
    override = os.environ.get("JONATHAN_GOAL_STORE", "").strip()
    return Path(override).expanduser().resolve() if override else Path.home() / ".clawd" / "goals"


def _goal_path(goal_id: str) -> Path:
    if not _ID_RE.fullmatch(goal_id):
        raise ToolInputError("goal_id is invalid")
    return _store_dir() / f"{goal_id}.json"


@contextmanager
def _goal_lock(goal_id: str) -> Iterator[None]:
    store = _store_dir()
    store.mkdir(parents=True, exist_ok=True)
    lock = store / f".{goal_id}.lock"
    deadline = time.monotonic() + 5.0
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(descriptor)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 30:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise ToolExecutionError("goal is busy; retry the action")
            time.sleep(0.025)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _load(goal_id: str) -> dict[str, Any]:
    path = _goal_path(goal_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolInputError(f"goal not found: {goal_id}") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ToolExecutionError(f"goal state is unreadable: {goal_id}") from exc
    if not isinstance(payload, dict) or payload.get("id") != goal_id:
        raise ToolExecutionError(f"goal state is invalid: {goal_id}")
    return payload


def _save(goal: dict[str, Any]) -> None:
    path = _goal_path(str(goal["id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    goal["updated_at"] = _stamp()
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(goal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError as exc:
        raise ToolExecutionError(f"could not persist goal: {goal['id']}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _item(items: list[dict[str, Any]], item_id: str, label: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise ToolInputError(f"{label} not found: {item_id}")


def _lease_active(todo: dict[str, Any]) -> bool:
    lease = str(todo.get("lease_until") or "")
    if not lease:
        return False
    try:
        return datetime.fromisoformat(lease.replace("Z", "+00:00")) > _now()
    except ValueError:
        return False


def _decision(goal: dict[str, Any]) -> dict[str, Any]:
    if goal.get("status") != "active":
        return {"may_continue": False, "reason": f"goal is {goal.get('status', 'unknown')}"}
    open_gates = [gate for gate in goal.get("gates", []) if gate.get("status") == "open"]
    if open_gates:
        return {
            "may_continue": False,
            "reason": "an unresolved gate requires judgment",
            "blocking_gates": [gate["id"] for gate in open_gates],
        }
    if int(goal.get("turns_used", 0)) >= int(goal.get("max_turns", 1)):
        return {"may_continue": False, "reason": "bounded turn budget is exhausted"}
    todos = list(goal.get("todos", []))
    incomplete = [todo for todo in todos if todo.get("status") != "completed"]
    if not incomplete:
        return {"may_continue": False, "reason": "no incomplete work remains; close the goal"}
    completed = {todo["id"] for todo in todos if todo.get("status") == "completed"}
    ready = [
        todo for todo in incomplete
        if set(todo.get("depends_on") or []).issubset(completed)
        and (not _lease_active(todo) or todo.get("status") == "pending")
    ]
    if not ready:
        return {"may_continue": False, "reason": "no unblocked todo is available"}
    return {
        "may_continue": True,
        "reason": "bounded work is available",
        "ready_todos": [todo["id"] for todo in ready],
        "turns_remaining": int(goal["max_turns"]) - int(goal["turns_used"]),
    }


def _summary(goal: dict[str, Any]) -> dict[str, Any]:
    result = dict(goal)
    result["continuation"] = _decision(goal)
    return result


class LongHorizonControlTool:
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="LongHorizonControl",
            description=(
                "Persist and govern long-running goals across conversations: bounded turns, scoped todos, "
                "agent claims with leases, human/evidence gates, receipts, handoffs, and fail-closed continuation checks."
            ),
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": [
                        "create", "list", "status", "add_todo", "claim_todo", "complete_todo",
                        "add_gate", "resolve_gate", "record_evidence", "spend_turn", "handoff",
                        "continuation", "close",
                    ]},
                    "goal_id": {"type": "string"}, "objective": {"type": "string"},
                    "scope": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
                    "max_turns": {"type": "integer", "minimum": 1, "maximum": 100000},
                    "include_all": {"type": "boolean"}, "todo_id": {"type": "string"},
                    "title": {"type": "string"}, "required": {"type": "boolean"},
                    "evidence_required": {"type": "boolean"},
                    "depends_on": {"type": "array", "items": {"type": "string"}, "maxItems": 100},
                    "agent_id": {"type": "string"},
                    "lease_seconds": {"type": "integer", "minimum": 30, "maximum": 86400},
                    "gate_id": {"type": "string"},
                    "gate_kind": {"type": "string", "enum": ["human", "evidence"]},
                    "resolution": {"type": "string"}, "summary": {"type": "string"},
                    "reference": {"type": "string"}, "to_agent": {"type": "string"},
                },
                "required": ["action"],
            },
            is_destructive=True,
            max_result_size_chars=120_000,
            strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        action = str(tool_input.get("action") or "")
        if action in _READ_ACTIONS:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(
            context,
            "LongHorizonControl",
            f"Persist long-horizon goal action: {action}",
            "Allow goal-control updates for the rest of this session",
        )

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        if action == "create":
            goal_id = _identifier("goal")
            scope = [_text(value, "scope item", limit=1000) for value in tool_input.get("scope") or []]
            goal = {
                "version": 1, "id": goal_id, "objective": _text(tool_input.get("objective"), "objective"),
                "workspace": str(context.workspace_root), "scope": scope, "status": "active",
                "max_turns": int(tool_input.get("max_turns") or 50), "turns_used": 0,
                "todos": [], "gates": [], "evidence": [], "handoffs": [],
                "created_at": _stamp(), "updated_at": _stamp(),
            }
            with _goal_lock(goal_id):
                _save(goal)
            return ToolResult(name="LongHorizonControl", output=_summary(goal))

        if action == "list":
            store = _store_dir()
            goals: list[dict[str, Any]] = []
            for path in sorted(store.glob("goal_*.json"), key=lambda item: item.stat().st_mtime, reverse=True) if store.is_dir() else []:
                try:
                    goal = json.loads(path.read_text(encoding="utf-8"))
                    if tool_input.get("include_all") or goal.get("workspace") == str(context.workspace_root):
                        goals.append({
                            "id": goal.get("id"), "objective": goal.get("objective"), "status": goal.get("status"),
                            "workspace": goal.get("workspace"), "updated_at": goal.get("updated_at"),
                            "continuation": _decision(goal),
                        })
                except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
                    continue
            return ToolResult(name="LongHorizonControl", output={"goals": goals[:500], "count": len(goals)})

        goal_id = _text(tool_input.get("goal_id"), "goal_id", limit=64)
        if action in {"status", "continuation"}:
            goal = _load(goal_id)
            output = _summary(goal) if action == "status" else _decision(goal)
            return ToolResult(name="LongHorizonControl", output=output)

        with _goal_lock(goal_id):
            goal = _load(goal_id)
            if goal.get("status") != "active" and action != "close":
                raise ToolInputError(f"goal is {goal.get('status')}; it cannot be changed")
            output = self._mutate(action, goal, tool_input)
            _save(goal)
        return ToolResult(name="LongHorizonControl", output=output)

    def _mutate(self, action: str, goal: dict[str, Any], tool_input: dict[str, Any]) -> dict[str, Any]:
        if action == "add_todo":
            dependencies = list(dict.fromkeys(str(value) for value in tool_input.get("depends_on") or []))
            known = {todo["id"] for todo in goal["todos"]}
            missing = [value for value in dependencies if value not in known]
            if missing:
                raise ToolInputError(f"unknown todo dependencies: {', '.join(missing)}")
            todo = {
                "id": _identifier("todo"), "title": _text(tool_input.get("title"), "title", limit=1000),
                "status": "pending", "required": bool(tool_input.get("required", True)),
                "evidence_required": bool(tool_input.get("evidence_required", True)),
                "depends_on": dependencies, "agent_id": None, "lease_until": None,
                "evidence_ids": [], "created_at": _stamp(), "completed_at": None,
            }
            goal["todos"].append(todo)
            return {"todo": todo, "continuation": _decision(goal)}

        if action == "claim_todo":
            todo = _item(goal["todos"], _text(tool_input.get("todo_id"), "todo_id", limit=64), "todo")
            agent_id = _text(tool_input.get("agent_id"), "agent_id", limit=200)
            if todo["status"] == "completed":
                raise ToolInputError("completed todo cannot be claimed")
            if _lease_active(todo) and todo.get("agent_id") != agent_id:
                raise ToolInputError(f"todo is leased to {todo.get('agent_id')} until {todo.get('lease_until')}")
            completed = {item["id"] for item in goal["todos"] if item["status"] == "completed"}
            if not set(todo.get("depends_on") or []).issubset(completed):
                raise ToolInputError("todo dependencies are not complete")
            seconds = int(tool_input.get("lease_seconds") or 900)
            todo.update({"status": "in_progress", "agent_id": agent_id, "lease_until": _stamp(_now() + timedelta(seconds=seconds))})
            return {"todo": todo}

        if action == "complete_todo":
            todo = _item(goal["todos"], _text(tool_input.get("todo_id"), "todo_id", limit=64), "todo")
            agent_id = _text(tool_input.get("agent_id"), "agent_id", limit=200)
            if todo["status"] == "completed":
                return {"todo": todo, "already_completed": True}
            if _lease_active(todo) and todo.get("agent_id") not in {None, agent_id}:
                raise ToolInputError(f"todo is leased to {todo.get('agent_id')}")
            summary = _text(tool_input.get("summary"), "summary", required=bool(todo.get("evidence_required")))
            if summary:
                receipt = self._receipt(goal, summary, tool_input.get("reference"), agent_id, todo["id"])
                todo["evidence_ids"].append(receipt["id"])
            todo.update({"status": "completed", "agent_id": agent_id, "lease_until": None, "completed_at": _stamp()})
            return {"todo": todo, "continuation": _decision(goal)}

        if action == "add_gate":
            gate = {
                "id": _identifier("gate"), "title": _text(tool_input.get("title"), "title", limit=1000),
                "kind": str(tool_input.get("gate_kind") or "human"), "status": "open",
                "resolution": None, "created_at": _stamp(), "resolved_at": None,
            }
            goal["gates"].append(gate)
            return {"gate": gate, "continuation": _decision(goal)}

        if action == "resolve_gate":
            gate = _item(goal["gates"], _text(tool_input.get("gate_id"), "gate_id", limit=64), "gate")
            gate.update({"status": "resolved", "resolution": _text(tool_input.get("resolution"), "resolution"), "resolved_at": _stamp()})
            return {"gate": gate, "continuation": _decision(goal)}

        if action == "record_evidence":
            receipt = self._receipt(goal, _text(tool_input.get("summary"), "summary"), tool_input.get("reference"), tool_input.get("agent_id"), tool_input.get("todo_id"))
            return {"evidence": receipt}

        if action == "spend_turn":
            if int(goal["turns_used"]) >= int(goal["max_turns"]):
                raise ToolInputError("bounded turn budget is exhausted")
            receipt = self._receipt(goal, _text(tool_input.get("summary"), "summary"), tool_input.get("reference"), tool_input.get("agent_id"), tool_input.get("todo_id"))
            goal["turns_used"] = int(goal["turns_used"]) + 1
            return {"turns_used": goal["turns_used"], "evidence": receipt, "continuation": _decision(goal)}

        if action == "handoff":
            handoff = {
                "id": _identifier("handoff"), "from_agent": _text(tool_input.get("agent_id"), "agent_id", limit=200),
                "to_agent": _text(tool_input.get("to_agent"), "to_agent", limit=200),
                "summary": _text(tool_input.get("summary"), "summary"), "created_at": _stamp(),
            }
            goal["handoffs"].append(handoff)
            return {"handoff": handoff}

        if action == "close":
            if goal.get("status") == "completed":
                return _summary(goal)
            incomplete = [todo["id"] for todo in goal["todos"] if todo.get("required") and todo.get("status") != "completed"]
            open_gates = [gate["id"] for gate in goal["gates"] if gate.get("status") == "open"]
            if incomplete or open_gates:
                raise ToolInputError(f"goal cannot close; incomplete todos={incomplete}, open gates={open_gates}")
            goal["status"] = "completed"
            goal["completed_at"] = _stamp()
            return _summary(goal)

        raise ToolInputError(f"unsupported action: {action}")

    @staticmethod
    def _receipt(goal: dict[str, Any], summary: Any, reference: Any, agent_id: Any, todo_id: Any) -> dict[str, Any]:
        todo_value = _text(todo_id, "todo_id", limit=64, required=False)
        if todo_value:
            _item(goal["todos"], todo_value, "todo")
        receipt = {
            "id": _identifier("evidence"), "summary": _text(summary, "summary"),
            "reference": _text(reference, "reference", limit=4000, required=False) or None,
            "agent_id": _text(agent_id, "agent_id", limit=200, required=False) or None,
            "todo_id": todo_value or None, "created_at": _stamp(),
        }
        goal["evidence"].append(receipt)
        return receipt

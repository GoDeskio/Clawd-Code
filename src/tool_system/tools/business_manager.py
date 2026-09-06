from __future__ import annotations

import csv
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from ..context import ToolContext
from ..errors import ToolInputError
from ..permission_handler import PermissionResult
from ..permissions import maybe_ask_for_gated_tool
from ..protocol import ToolResult
from ..registry import ToolSpec


def business_database_path() -> Path:
    root = Path.home() / ".clawd" / "business"
    root.mkdir(parents=True, exist_ok=True)
    return root / "business.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(business_database_path())
    connection.row_factory = sqlite3.Row
    connection.executescript("""
    PRAGMA journal_mode=WAL;
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS customers (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT DEFAULT '', phone TEXT DEFAULT '', company TEXT DEFAULT '',
      address TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS projects (
      id TEXT PRIMARY KEY, name TEXT NOT NULL, customer_id TEXT DEFAULT '', status TEXT DEFAULT 'active',
      budget REAL DEFAULT 0, due_date TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS tasks (
      id TEXT PRIMARY KEY, title TEXT NOT NULL, project_id TEXT DEFAULT '', status TEXT DEFAULT 'open', priority TEXT DEFAULT 'normal',
      due_date TEXT DEFAULT '', assignee TEXT DEFAULT '', notes TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS invoices (
      id TEXT PRIMARY KEY, number TEXT UNIQUE NOT NULL, customer_id TEXT DEFAULT '', project_id TEXT DEFAULT '', status TEXT DEFAULT 'draft',
      issue_date TEXT NOT NULL, due_date TEXT DEFAULT '', currency TEXT DEFAULT 'USD', subtotal REAL NOT NULL, tax REAL NOT NULL,
      total REAL NOT NULL, paid REAL DEFAULT 0, items_json TEXT NOT NULL, notes TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS transactions (
      id TEXT PRIMARY KEY, kind TEXT NOT NULL, amount REAL NOT NULL, currency TEXT DEFAULT 'USD', category TEXT DEFAULT '',
      occurred_on TEXT NOT NULL, customer_id TEXT DEFAULT '', project_id TEXT DEFAULT '', invoice_id TEXT DEFAULT '',
      description TEXT DEFAULT '', created_at TEXT NOT NULL
    );
    """)
    return connection


@contextmanager
def _database():
    connection = _connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _rows(connection: sqlite3.Connection, table: str, limit: int) -> list[dict[str, Any]]:
    allowed = {"customers", "projects", "tasks", "invoices", "transactions"}
    if table not in allowed:
        raise ToolInputError(f"entity must be one of: {', '.join(sorted(allowed))}")
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]


def _dashboard(connection: sqlite3.Connection) -> dict[str, Any]:
    invoice = connection.execute("SELECT COALESCE(SUM(total),0), COALESCE(SUM(paid),0), COALESCE(SUM(total-paid),0), COUNT(*) FROM invoices").fetchone()
    transactions = connection.execute("SELECT kind, COALESCE(SUM(amount),0) AS total FROM transactions GROUP BY kind").fetchall()
    totals = {str(row["kind"]): float(row["total"]) for row in transactions}
    income = totals.get("income", 0.0)
    expense = totals.get("expense", 0.0)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "customers": connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
        "active_projects": connection.execute("SELECT COUNT(*) FROM projects WHERE status NOT IN ('complete','cancelled')").fetchone()[0],
        "open_tasks": connection.execute("SELECT COUNT(*) FROM tasks WHERE status NOT IN ('done','cancelled')").fetchone()[0],
        "invoices": {"count": invoice[3], "billed": float(invoice[0]), "paid": float(invoice[1]), "outstanding": float(invoice[2])},
        "ledger": {"income": income, "expenses": expense, "net": income - expense},
        "currency_note": "Totals are not converted across currencies; filter/export before combining multi-currency books.",
    }


class BusinessManagerTool:
    READ_ONLY = {"list", "dashboard"}

    def spec(self) -> ToolSpec:
        item_schema = {"type": "object", "additionalProperties": False, "properties": {
            "description": {"type": "string"}, "quantity": {"type": "number", "minimum": 0},
            "unit_price": {"type": "number"}, "tax_rate": {"type": "number", "minimum": 0, "maximum": 1}
        }, "required": ["description", "quantity", "unit_price"]}
        return ToolSpec(
            name="BusinessManager",
            description=(
                "Manage a durable local business workspace: customers, projects, tasks, invoices, income/expenses, dashboards, "
                "and downloadable JSON/CSV/HTML reports. Data is stored locally under ~/.clawd/business."
            ),
            input_schema={"type": "object", "additionalProperties": False, "properties": {
                "action": {"type": "string", "enum": ["create_customer", "create_project", "create_task", "create_invoice", "record_transaction", "list", "dashboard", "update_status", "report", "export"]},
                "entity": {"type": "string", "enum": ["customers", "projects", "tasks", "invoices", "transactions"]},
                "id": {"type": "string"}, "name": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"},
                "company": {"type": "string"}, "address": {"type": "string"}, "notes": {"type": "string"},
                "customer_id": {"type": "string"}, "project_id": {"type": "string"}, "invoice_id": {"type": "string"},
                "title": {"type": "string"}, "status": {"type": "string"}, "priority": {"type": "string"}, "assignee": {"type": "string"},
                "budget": {"type": "number"}, "number": {"type": "string"}, "issue_date": {"type": "string"}, "due_date": {"type": "string"},
                "currency": {"type": "string"}, "items": {"type": "array", "items": item_schema}, "paid": {"type": "number", "minimum": 0},
                "kind": {"type": "string", "enum": ["income", "expense"]}, "amount": {"type": "number", "minimum": 0},
                "category": {"type": "string"}, "description": {"type": "string"}, "occurred_on": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10000}, "output": {"type": "string"},
                "format": {"type": "string", "enum": ["json", "csv", "html"]}
            }, "required": ["action"]},
            is_destructive=True, max_result_size_chars=100_000, strict=True,
        )

    def check_permissions(self, tool_input: dict[str, Any], context: ToolContext) -> PermissionResult:
        if tool_input.get("action") in self.READ_ONLY:
            return PermissionResult.allow()
        return maybe_ask_for_gated_tool(context, "BusinessManager", f"Change or export business records: {tool_input.get('action')}",
                                        "Allow BusinessManager changes for the rest of this session")

    def run(self, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(tool_input["action"])
        now = datetime.now(timezone.utc).isoformat()
        with _database() as db:
            if action == "create_customer":
                name = str(tool_input.get("name") or "").strip()
                if not name:
                    raise ToolInputError("name is required")
                item_id = str(tool_input.get("id") or uuid.uuid4().hex[:12])
                db.execute("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?)", (item_id, name, tool_input.get("email", ""), tool_input.get("phone", ""),
                    tool_input.get("company", ""), tool_input.get("address", ""), tool_input.get("notes", ""), now, now))
                return ToolResult(name="BusinessManager", output={"customer": dict(db.execute("SELECT * FROM customers WHERE id=?", (item_id,)).fetchone())})
            if action == "create_project":
                name = str(tool_input.get("name") or "").strip()
                if not name:
                    raise ToolInputError("name is required")
                item_id = str(tool_input.get("id") or uuid.uuid4().hex[:12])
                db.execute("INSERT INTO projects VALUES (?,?,?,?,?,?,?,?,?)", (item_id, name, tool_input.get("customer_id", ""), tool_input.get("status", "active"),
                    float(tool_input.get("budget") or 0), tool_input.get("due_date", ""), tool_input.get("notes", ""), now, now))
                return ToolResult(name="BusinessManager", output={"project": dict(db.execute("SELECT * FROM projects WHERE id=?", (item_id,)).fetchone())})
            if action == "create_task":
                title = str(tool_input.get("title") or "").strip()
                if not title:
                    raise ToolInputError("title is required")
                item_id = str(tool_input.get("id") or uuid.uuid4().hex[:12])
                db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)", (item_id, title, tool_input.get("project_id", ""), tool_input.get("status", "open"),
                    tool_input.get("priority", "normal"), tool_input.get("due_date", ""), tool_input.get("assignee", ""), tool_input.get("notes", ""), now, now))
                return ToolResult(name="BusinessManager", output={"task": dict(db.execute("SELECT * FROM tasks WHERE id=?", (item_id,)).fetchone())})
            if action == "create_invoice":
                items = list(tool_input.get("items") or [])
                if not items:
                    raise ToolInputError("items is required for an invoice")
                subtotal = sum(float(item["quantity"]) * float(item["unit_price"]) for item in items)
                tax = sum(float(item["quantity"]) * float(item["unit_price"]) * float(item.get("tax_rate") or 0) for item in items)
                item_id = str(tool_input.get("id") or uuid.uuid4().hex[:12])
                number = str(tool_input.get("number") or f"INV-{datetime.now().strftime('%Y%m%d')}-{item_id[:4].upper()}")
                values = (item_id, number, tool_input.get("customer_id", ""), tool_input.get("project_id", ""), tool_input.get("status", "draft"),
                          tool_input.get("issue_date", date.today().isoformat()), tool_input.get("due_date", ""), tool_input.get("currency", "USD"), subtotal, tax,
                          subtotal + tax, float(tool_input.get("paid") or 0), json.dumps(items, ensure_ascii=False), tool_input.get("notes", ""), now, now)
                db.execute("INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
                return ToolResult(name="BusinessManager", output={"invoice": dict(db.execute("SELECT * FROM invoices WHERE id=?", (item_id,)).fetchone())})
            if action == "record_transaction":
                kind = str(tool_input.get("kind") or "")
                if kind not in {"income", "expense"}:
                    raise ToolInputError("kind=income|expense is required")
                item_id = str(tool_input.get("id") or uuid.uuid4().hex[:12])
                values = (item_id, kind, float(tool_input.get("amount") or 0), tool_input.get("currency", "USD"), tool_input.get("category", ""),
                          tool_input.get("occurred_on", date.today().isoformat()), tool_input.get("customer_id", ""), tool_input.get("project_id", ""),
                          tool_input.get("invoice_id", ""), tool_input.get("description", ""), now)
                db.execute("INSERT INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?)", values)
                return ToolResult(name="BusinessManager", output={"transaction": dict(db.execute("SELECT * FROM transactions WHERE id=?", (item_id,)).fetchone())})
            if action == "update_status":
                entity = str(tool_input.get("entity") or "")
                if entity not in {"projects", "tasks", "invoices"}:
                    raise ToolInputError("status can be updated for projects, tasks, or invoices")
                item_id, status = str(tool_input.get("id") or ""), str(tool_input.get("status") or "")
                if not item_id or not status:
                    raise ToolInputError("id and status are required")
                cursor = db.execute(f"UPDATE {entity} SET status=?, updated_at=? WHERE id=?", (status, now, item_id))
                return ToolResult(name="BusinessManager", output={"updated": cursor.rowcount == 1, "entity": entity, "id": item_id, "status": status}, is_error=cursor.rowcount != 1)
            if action == "list":
                entity = str(tool_input.get("entity") or "customers")
                return ToolResult(name="BusinessManager", output={"entity": entity, "items": _rows(db, entity, int(tool_input.get("limit") or 100))})
            if action == "dashboard":
                return ToolResult(name="BusinessManager", output=_dashboard(db))
            if action in {"report", "export"}:
                return self._export(db, tool_input, context)
        raise ToolInputError(f"unsupported business action: {action}")

    @staticmethod
    def _export(db: sqlite3.Connection, tool_input: dict[str, Any], context: ToolContext) -> ToolResult:
        fmt = str(tool_input.get("format") or ("html" if tool_input.get("action") == "report" else "json"))
        entity = str(tool_input.get("entity") or "")
        data: Any = _rows(db, entity, int(tool_input.get("limit") or 10000)) if entity else {
            "dashboard": _dashboard(db), **{table: _rows(db, table, int(tool_input.get("limit") or 10000)) for table in ("customers", "projects", "tasks", "invoices", "transactions")}}
        output = context.ensure_allowed_path(str(tool_input.get("output") or f"business/business-report.{fmt}"))
        output.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "json":
            output.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        elif fmt == "csv":
            if not entity:
                raise ToolInputError("CSV export requires entity")
            rows = data
            with output.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else ["id"])
                writer.writeheader(); writer.writerows(rows)
        else:
            dashboard = data["dashboard"] if isinstance(data, dict) and "dashboard" in data else _dashboard(db)
            output.write_text("<!doctype html><meta charset='utf-8'><title>Business report</title><style>body{font:16px system-ui;max-width:900px;margin:40px auto}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:8px}</style>"
                + "<h1>Jonathan Ai Business Report</h1><pre>" + json.dumps(dashboard, indent=2, ensure_ascii=False).replace("&", "&amp;").replace("<", "&lt;") + "</pre>", encoding="utf-8")
        artifacts = [context.artifact_publisher(output, output.name)] if context.artifact_publisher else []
        return ToolResult(name="BusinessManager", output={"path": str(output), "format": fmt,
            "artifact": artifacts[0] if artifacts else None, "artifacts": artifacts})

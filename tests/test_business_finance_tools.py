from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import get_finance_config
from src.tool_system.context import ToolContext
from src.tool_system.permission_handler import PermissionBehavior
from src.tool_system.tools.business_manager import BusinessManagerTool
from src.tool_system.tools.finance_markets import FinanceMarketsTool
from src.tool_system.tools.trading import TradingTool


class BusinessFinanceToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.workspace = self.root / "workspace"
        self.home.mkdir(); self.workspace.mkdir()
        self.home_patch = patch("pathlib.Path.home", return_value=self.home)
        self.home_patch.start()
        self.context = ToolContext(workspace_root=self.workspace)
        self.context.artifact_publisher = lambda path, name=None: {
            "name": name or Path(path).name, "download_url": f"/api/artifacts/download?name={name or Path(path).name}",
            "size": Path(path).stat().st_size,
        }

    def tearDown(self) -> None:
        self.home_patch.stop(); self.tmp.cleanup()

    def test_business_customer_invoice_ledger_dashboard_and_report(self) -> None:
        tool = BusinessManagerTool()
        customer = tool.run({"action": "create_customer", "name": "Acme", "email": "ops@example.com"}, self.context).output["customer"]
        invoice = tool.run({"action": "create_invoice", "customer_id": customer["id"], "currency": "USD",
                            "items": [{"description": "Automation", "quantity": 2, "unit_price": 500, "tax_rate": .1}]}, self.context).output["invoice"]
        self.assertEqual(invoice["subtotal"], 1000)
        self.assertEqual(invoice["total"], 1100)
        tool.run({"action": "record_transaction", "kind": "income", "amount": 1000, "invoice_id": invoice["id"], "category": "services"}, self.context)
        tool.run({"action": "record_transaction", "kind": "expense", "amount": 250, "category": "software"}, self.context)
        dashboard = tool.run({"action": "dashboard"}, self.context).output
        self.assertEqual(dashboard["ledger"]["net"], 750)
        report = tool.run({"action": "report", "format": "html", "output": "business/report.html"}, self.context).output
        self.assertTrue(Path(report["path"]).is_file())
        self.assertTrue(report["artifacts"])

    def test_finance_quote_technical_and_portfolio_are_serializable(self) -> None:
        rows = [{"timestamp": f"2026-01-{day:02d}", "close": float(100 + day), "open": 100.0, "high": 102.0, "low": 99.0, "volume": 1000}
                for day in range(1, 61)]
        with patch("src.tool_system.tools.finance_markets._history", return_value=rows):
            technical = FinanceMarketsTool().run({"action": "technical", "symbol": "TEST"}, self.context).output
            self.assertIn("rsi_14", technical)
            portfolio = FinanceMarketsTool().run({"action": "portfolio", "positions": [{"symbol": "TEST", "quantity": 2, "cost_basis": 120}]}, self.context).output
            self.assertEqual(portfolio["market_value"], 320)
            json.dumps(portfolio)

    def test_trading_credentials_are_encoded_and_orders_always_ask(self) -> None:
        tool = TradingTool()
        configured = tool.run({"action": "configure", "api_key": "paper-key", "secret_key": "paper-secret", "paper": True}, self.context)
        self.assertTrue(configured.output["configured"])
        raw = (self.home / ".clawd" / "config.json").read_text(encoding="utf-8")
        self.assertNotIn("paper-secret", raw)
        self.assertEqual(get_finance_config()["alpaca"]["secret_key"], "paper-secret")
        self.context.session_grants.add("trading")
        permission = tool.check_permissions({"action": "submit_order", "symbol": "AAPL", "side": "buy", "quantity": 1}, self.context)
        self.assertEqual(permission.behavior, PermissionBehavior.ASK)
        with patch("src.tool_system.tools.trading._request", return_value={"id": "order-1", "status": "accepted"}):
            result = tool.run({"action": "submit_order", "symbol": "AAPL", "side": "buy", "quantity": 1,
                               "order_type": "market", "time_in_force": "day"}, self.context)
        self.assertEqual(result.output["order"]["id"], "order-1")
        self.assertEqual(result.output["mode"], "paper")


if __name__ == "__main__":
    unittest.main()

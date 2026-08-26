from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from src.integrations.securo import SecuroManager
from src.tool_system.defaults import build_default_registry

class PersonalFinanceTests(unittest.TestCase):
    def test_native_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager=SecuroManager(tmp); manager.database=Path(tmp)/"finance.sqlite"
            account=manager.action("add_account",name="Checking",amount=100,currency="USD")["account"]
            manager.action("add_transaction",account_id=account["id"],amount=-12.5,category="Food")
            dash=manager.action("dashboard"); self.assertEqual(dash["totals_by_currency"]["USD"],-12.5)
            status=manager.status(); self.assertTrue(status["runtime_ready"]); self.assertTrue(status["repository"].startswith("internal://")); self.assertFalse(status["payments_required"])
    def test_tool_registered(self): self.assertIsNotNone(build_default_registry(include_user_tools=False).get("PersonalFinanceVault"))
if __name__=="__main__": unittest.main()

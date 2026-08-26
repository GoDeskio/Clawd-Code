from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from src.integrations.kronos import KronosManager
from src.tool_system.defaults import build_default_registry

class ForecastTests(unittest.TestCase):
    def test_native_forecast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/"history.csv"; source.write_text("timestamp,open,high,low,close\n"+"\n".join(f"2026-01-{i:02d},{i},{i+1},{i-1},{i+.5}" for i in range(1,21)),encoding="utf-8")
            target=root/"forecast.csv"; manager=KronosManager(root); result=manager.forecast(source,target,pred_len=3,lookback=16)
            self.assertTrue(result["ok"]); self.assertEqual(result["rows"],3); self.assertTrue(target.is_file()); self.assertTrue(result["repository"].startswith("internal://")); self.assertIn("Not investment advice",result["disclaimer"])
    def test_tool_registered(self): self.assertIsNotNone(build_default_registry(include_user_tools=False).get("KronosForecast"))
if __name__=="__main__": unittest.main()

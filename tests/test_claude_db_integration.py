from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from src.integrations.claude_db import ClaudeDbManager
from src.tool_system.defaults import build_default_registry

class TestCodeMemory(unittest.TestCase):
    def test_native_scan_search_and_notes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); project=root/"project"; project.mkdir(); (project/"sample.py").write_text("def hello():\n    return world()\n",encoding="utf-8")
            manager=ClaudeDbManager(root); manager.database=root/"memory.sqlite"
            scan=manager.execute("scan",workspace=project); self.assertIn("symbols",scan["output"])
            explain=manager.execute("explain",workspace=project,query="hello"); self.assertIn("sample.py:1",explain["output"])
            manager.execute("remember",workspace=project,query="Always test UTF-8 café")
            found=manager.execute("search",workspace=project,query="UTF"); self.assertIn("café",found["output"])
            status=manager.status(); self.assertTrue(status["runtime_ready"]); self.assertTrue(status["local_only"]); self.assertFalse(status["hooks_installed"]); self.assertTrue(status["repository"].startswith("internal://"))
    def test_tool_registered(self): self.assertIsNotNone(build_default_registry(include_user_tools=False).get("CodeMemory"))
if __name__=="__main__": unittest.main()

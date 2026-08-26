from __future__ import annotations
import tempfile,unittest,wave
from pathlib import Path
from src.tool_system.context import ToolContext
from src.tool_system.defaults import build_default_registry
from src.tool_system.tools.audio_studio import AudioStudioTool

class AudioStudioTests(unittest.TestCase):
    def test_generate_and_normalize_downloadable_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); context=ToolContext(workspace_root=root)
            made=AudioStudioTool().run({"action":"generate","prompt":"calm blue ambient","duration":1,"output":"tone.wav"},context).output
            path=Path(made["path"]); self.assertTrue(path.is_file()); self.assertEqual(made["engine"],"internal://jonathan/audio-studio")
            with wave.open(str(path),"rb") as audio: self.assertEqual(audio.getframerate(),44100); self.assertGreater(audio.getnframes(),40000)
            fixed=AudioStudioTool().run({"action":"normalize","input":"tone.wav","output":"fixed.wav"},context).output
            self.assertTrue(Path(fixed["path"]).is_file())
    def test_registered(self): self.assertIsNotNone(build_default_registry(include_user_tools=False).get("AudioStudio"))
if __name__=="__main__": unittest.main()

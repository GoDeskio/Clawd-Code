from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from PIL import Image
from src.integrations.character_studio import generate_character
from src.integrations.drawai import DrawAiManager
from src.integrations.procoder import ProcoderManager
from src.tool_system.defaults import build_default_registry

class NativeEngineTests(unittest.TestCase):
    def test_character_is_deterministic_and_editable(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=generate_character(tmp,seed="same",name="Pip"); text=Path(first["svg"]).read_text(encoding="utf-8"); self.assertIn('id="rig"',text); self.assertIn("blink",text); self.assertTrue(Path(first["recipe"]).is_file())
    def test_editable_graphics_outputs_svg_pptx(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); image=root/"diagram.png"; Image.new("RGB",(120,80),"white").save(image); manager=DrawAiManager(root); result=manager.convert(image,root/"out")
            self.assertTrue(any(str(path).endswith(".svg") for path in result["artifacts"])); self.assertTrue(any(str(path).endswith(".pptx") for path in result["artifacts"])); self.assertTrue(result["repository"].startswith("internal://"))
    def test_gate_fails_conflicts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/"bad.py").write_text("<<<<<<< ours\n=======\n>>>>>>> theirs\n",encoding="utf-8"); result=ProcoderManager(root).execute("check",workspace=root); self.assertFalse(result["ok"]); self.assertIn("conflict marker",result["output"]); self.assertTrue(result["repository"].startswith("internal://"))
    def test_tools_registered(self):
        registry=build_default_registry(include_user_tools=False)
        for name in ("CharacterStudio","EditableGraphics","Procoder"): self.assertIsNotNone(registry.get(name))
if __name__=="__main__": unittest.main()

"""Product version is 0.4.9 and is referenced from docs and packaging."""

from __future__ import annotations

import unittest
from pathlib import Path

from src import __version__
from src.version import get_version


ROOT = Path(__file__).resolve().parents[1]


class TestVersion(unittest.TestCase):
    def test_version_file_and_package(self) -> None:
        self.assertEqual((ROOT / "VERSION").read_text(encoding="utf-8").strip(), "0.4.9")
        self.assertEqual(get_version(), "0.4.9")
        self.assertEqual(__version__, "0.4.9")

    def test_docs_and_installer_mention_version(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        win = (ROOT / "packaging" / "windows" / "README.md").read_text(encoding="utf-8")
        iss = (ROOT / "packaging" / "windows" / "JonathanAi.iss").read_text(encoding="utf-8")
        nsis = (ROOT / "packaging" / "windows" / "JonathanAi.nsi").read_text(encoding="utf-8")
        html = (ROOT / "src" / "desktop" / "web" / "index.html").read_text(encoding="utf-8")
        setup_c = (ROOT / "packaging" / "windows" / "JonathanAi-Setup.c").read_text(encoding="utf-8")
        self.assertIn("0.4.9", readme)
        self.assertIn("0.4.9", win)
        self.assertIn("0.4.9", iss)
        self.assertIn("0.4.9", nsis)
        self.assertIn("0.4.9", html)
        self.assertIn("0.4.9", setup_c)
        self.assertIn("standalone", readme.lower())
        self.assertIn("rename", readme.lower())
        self.assertIn("input_schema.type", readme)
        self.assertIn("Jonathan-Ai", readme)
        self.assertIn("JonathanAi-Setup.exe", readme)


if __name__ == "__main__":
    unittest.main()

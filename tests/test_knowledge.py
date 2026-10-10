"""Local document knowledge base: parse, cite, and keep text on this machine."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.command_system import create_command_context, execute_command_sync
from src.desktop.runtime import _HELP_TEXT
from src.desktop.server import DesktopServer
from src.knowledge.bm25 import bm25_scores
from src.knowledge.chunk import chunk_text
from src.knowledge.models import (
    ChecksumError,
    ModelSourceError,
    PinnedFile,
    assert_cloud_embed_url,
    assert_model_url,
    file_url,
    read_model_bytes,
    store_verified_bytes,
    verify_model_dir,
)
from src.knowledge.parse import parse_document
from src.knowledge.service import KnowledgeBase, format_kb_command

SECRET = "sk-knowledgebaseSecretKey99"


def _docx(path: Path, body: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", body)
    path.write_bytes(buffer.getvalue())


class TestParseAndChunk(unittest.TestCase):
    def test_markdown_text_html_and_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            notes = root / "notes.md"
            notes.write_text("# Otters\n\nOtters live in rivers.\n", encoding="utf-8")
            plain = root / "plain.txt"
            plain.write_text("Plain text about beavers.\n", encoding="utf-8")
            page = root / "page.html"
            page.write_text(
                "<html><script>hiddenphrase</script><style>skipme</style><p>Visible otter habitat.</p></html>",
                encoding="utf-8",
            )
            document = root / "brief.docx"
            _docx(
                document,
                """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006">
  <w:body>
    <w:p><w:r><w:t>DOCX otter paragraph</w:t></w:r></w:p>
    <mc:AlternateContent>
      <mc:Choice Requires="w14"><w:p><w:r><w:t>choice otter</w:t></w:r></w:p></mc:Choice>
      <mc:Fallback><w:p><w:r><w:t>fallback secretphrase</w:t></w:r></w:p></mc:Fallback>
    </mc:AlternateContent>
  </w:body>
</w:document>
""",
            )
            self.assertIn("Otters live in rivers", parse_document(notes))
            self.assertIn("beavers", parse_document(plain))
            html_text = parse_document(page)
            self.assertIn("Visible otter habitat", html_text)
            self.assertNotIn("hiddenphrase", html_text)
            self.assertNotIn("skipme", html_text)
            docx_text = parse_document(document)
            self.assertIn("DOCX otter paragraph", docx_text)
            self.assertIn("choice otter", docx_text)
            self.assertNotIn("fallback secretphrase", docx_text)
            with self.assertRaises(ValueError):
                parse_document(root / "skip.csv")

    def test_pdf_uses_injected_reader_without_the_extra(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.pdf"
            path.write_bytes(b"%PDF-1.4")
            text = parse_document(path, pdf_reader=lambda source: f"pdf otter from {source.name}")
        self.assertIn("pdf otter", text)
        self.assertNotIn("pypdf", sys.modules)

    def test_chunks_overlap(self) -> None:
        parts = chunk_text("a" * 800 + "b" * 100, size=800, overlap=120)
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[1].startswith("a" * 120))
        self.assertEqual(chunk_text("   "), [])


class TestModelSources(unittest.TestCase):
    def test_official_url_is_allowed_and_mirrors_are_refused_before_fetch(self) -> None:
        assert_model_url(file_url("model_optimized.onnx"))
        calls: list[str] = []

        def fetch(url: str) -> bytes:
            calls.append(url)
            return b""

        for url in (
            "https://hf-mirror.com/Qdrant/bge-small-en-v1.5-onnx-Q/resolve/main/model_optimized.onnx",
            "https://npmmirror.com/mirrors/bge/model_optimized.onnx",
            "https://www.modelscope.cn/models/bge/model_optimized.onnx",
            "https://example.cn/model_optimized.onnx",
            "http://huggingface.co/Qdrant/bge-small-en-v1.5-onnx-Q/resolve/main/model_optimized.onnx",
            "https://huggingface.co/other/repo/resolve/main/model_optimized.onnx",
        ):
            with self.assertRaises(ModelSourceError):
                read_model_bytes(url, fetch)
        self.assertEqual(calls, [])

    def test_cloud_embeddings_only_use_openai(self) -> None:
        assert_cloud_embed_url("https://api.openai.com/v1/embeddings")
        for url in (
            "https://hf-mirror.com/v1/embeddings",
            "https://api.openai.com.evil.example/v1/embeddings",
            "http://api.openai.com/v1/embeddings",
            "https://example.cn/v1/embeddings",
        ):
            with self.assertRaises(ModelSourceError):
                assert_cloud_embed_url(url)

    def test_checksum_mismatch_discards_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = b"not-the-model"
            item = PinnedFile("weights.bin", hashlib.sha256(b"real-model").hexdigest(), len(b"real-model"))
            dest = root / "weights.bin"
            dest.write_bytes(b"stale")
            with self.assertRaises(ChecksumError):
                store_verified_bytes(dest, payload, item)
            self.assertFalse(dest.exists())
            store_verified_bytes(dest, b"real-model", item)
            self.assertEqual(dest.read_bytes(), b"real-model")

            model_dir = root / "model"
            model_dir.mkdir()
            self.assertFalse(verify_model_dir(model_dir))
            bad = model_dir / "model_optimized.onnx"
            bad.write_bytes(b"corrupt-onnx")
            with self.assertRaises(ChecksumError):
                verify_model_dir(model_dir)
            self.assertFalse(bad.exists())


class _KbCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self._old_dir = os.environ.get("JONATHAN_KB_DIR")
        os.environ["JONATHAN_KB_DIR"] = str(self.root)
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        if self._old_dir is None:
            os.environ.pop("JONATHAN_KB_DIR", None)
        else:
            os.environ["JONATHAN_KB_DIR"] = self._old_dir

    def _write(self, name: str, text: str) -> Path:
        path = self.root / name
        path.write_text(text, encoding="utf-8")
        return path


class TestKnowledgeBase(_KbCase):
    def test_bm25_cites_file_and_passage_without_calling_cloud(self) -> None:
        def transport(*_args: object) -> dict[str, object]:
            raise AssertionError("cloud embedding was called")

        base = KnowledgeBase(self.root, user_id="reader", transport=transport)
        notes = self._write("rivers.md", "Otters live in rivers and eat fish.\n")
        other = self._write("forest.txt", "Pine trees grow in the forest.\n")
        added = base.add_document(notes)
        base.add_document(other)
        self.assertIn("BM25", added)
        self.assertIn("stayed on this machine", added)
        later = "x" * 900 + " zebrapassage is the later habitat note."
        base.add_document(self._write("later.md", later))
        found = base.search("zebrapassage")
        self.assertIn("later.md, passage 2", found)
        self.assertIn("(bm25)", found)
        self.assertIn("Sources:", found)
        otter = base.search("otters")
        self.assertIn("rivers.md, passage 1", otter)
        self.assertNotIn("forest.txt", otter)
        self.assertIn("rivers.md", base.list_documents())
        self.assertTrue(base.status()["documents_stay_local"])
        self.assertEqual(base.status()["embedding_backend"], "local")

    def test_local_embeddings_cite_the_matching_passage(self) -> None:
        def embedder(texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] if "otter" in text.lower() else [0.0, 1.0] for text in texts]

        base = KnowledgeBase(self.root, user_id="reader", embedder=embedder)
        base.add_document(self._write("rivers.md", "Otters live in rivers.\n"))
        base.add_document(self._write("forest.txt", "Pine trees grow here.\n"))
        added = base.list_documents()
        self.assertIn("embedding", added)
        found = base.search("where do otters live")
        self.assertIn("rivers.md, passage 1 (embedding)", found)
        self.assertNotIn("forest.txt", found)

    def test_cloud_is_used_only_after_it_is_selected(self) -> None:
        sent: list[tuple[str, object]] = []

        def transport(url: str, body: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
            del headers
            sent.append((url, body["input"]))
            vectors = []
            for text in body["input"]:
                vectors.append([1.0, 0.0] if "otter" in str(text).lower() else [0.0, 1.0])
            return {"data": [{"index": index, "embedding": vector} for index, vector in enumerate(vectors)]}

        base = KnowledgeBase(self.root, user_id="reader", transport=transport)
        notes = self._write("rivers.md", "Otters live in rivers.\n")
        base.add_document(notes)
        self.assertEqual(sent, [])
        base.update({"embedding_backend": "openai"})
        with self.assertRaises(RuntimeError) as caught:
            base.add_document(self._write("again.md", "Otters again.\n"))
        self.assertIn("was not sent", str(caught.exception))
        self.assertEqual(sent, [])
        self.assertNotIn("again.md", base.list_documents())
        base.update({"openai_api_key": "sk-cloudKeyForKnowledge1234"})
        cloud = base.add_document(self._write("cloud.md", "Otters live in rivers.\n"))
        self.assertIn("api.openai.com", cloud)
        self.assertEqual(sent[0][0], "https://api.openai.com/v1/embeddings")
        self.assertIn("Otters live in rivers.", sent[0][1])
        found = base.search("otters")
        self.assertIn("cloud.md, passage 1", found)
        self.assertIn("otters", str(sent[-1][1]).lower())
        public = base.status()
        self.assertFalse(public["documents_stay_local"])
        self.assertNotIn("sk-cloudKeyForKnowledge1234", json.dumps(public))
        stored = base.settings_path.read_text(encoding="utf-8")
        self.assertIn("sk-cloudKeyForKnowledge1234", stored)
        self.assertEqual(base.settings_path.stat().st_mode & 0o777, 0o600)

    def test_secrets_are_masked_before_they_are_stored(self) -> None:
        base = KnowledgeBase(self.root, user_id="reader")
        base.add_document(self._write("secret.txt", f"The key is {SECRET} and otters swim.\n"))
        blob = base.index.path.read_bytes()
        self.assertNotIn(SECRET.encode("utf-8"), blob)
        self.assertNotIn(b"knowledgebaseSecret", blob)
        visible = base.search("otters")
        self.assertNotIn(SECRET, visible)
        self.assertNotIn("knowledgebaseSecret", visible)

    def test_users_do_not_share_an_index(self) -> None:
        left = KnowledgeBase(self.root, user_id="alpha")
        right = KnowledgeBase(self.root, user_id="beta")
        left.add_document(self._write("alpha.md", "Alpha keeps otter notes.\n"))
        self.assertIn("alpha.md", left.list_documents())
        self.assertIn("No documents", right.list_documents())
        self.assertNotEqual(left.index.path, right.index.path)

    def test_remove_and_replace_the_same_file(self) -> None:
        base = KnowledgeBase(self.root, user_id="reader")
        path = self._write("notes.md", "First otter note.\n")
        base.add_document(path)
        path.write_text("Second otter note.\n", encoding="utf-8")
        base.add_document(path)
        listed = base.list_documents()
        self.assertEqual(listed.count("notes.md"), 1)
        doc_id = listed.split()[2]
        self.assertIn("Removed", base.remove_document(doc_id))
        self.assertIn("No documents", base.list_documents())
        self.assertIn("No document", base.remove_document(doc_id))

    def test_pdf_docx_and_html_are_indexed(self) -> None:
        base = KnowledgeBase(
            self.root,
            user_id="reader",
            pdf_reader=lambda source: "PDF passage about otters.",
        )
        pdf = self.root / "paper.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        html = self._write("page.html", "<p>HTML passage about herons.</p><script>hiddenphrase</script>")
        document = self.root / "brief.docx"
        _docx(
            document,
            """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>DOCX passage about beavers.</w:t></w:r></w:p></w:body>
</w:document>
""",
        )
        base.add_document(pdf)
        base.add_document(html)
        base.add_document(document)
        self.assertIn("paper.pdf, passage 1", base.search("otters"))
        heron = base.search("herons")
        self.assertIn("page.html, passage 1", heron)
        self.assertNotIn("hiddenphrase", heron)
        self.assertIn("brief.docx, passage 1", base.search("beavers"))

    def test_corrupt_model_file_falls_back_to_bm25(self) -> None:
        base = KnowledgeBase(self.root, user_id="reader")
        model = base.model_dir
        model.mkdir(parents=True)
        bad = model / "model_optimized.onnx"
        bad.write_bytes(b"corrupt-onnx")
        base.add_document(self._write("rivers.md", "Otters live in rivers.\n"))
        found = base.search("otters")
        self.assertIn("(bm25)", found)
        self.assertFalse(bad.exists())
        self.assertNotIn("fastembed", sys.modules)


class TestCommandsAndSettings(_KbCase):
    def test_kb_command_roundtrip(self) -> None:
        path = self._write("rivers.md", "Otters live in rivers.\n")
        context = create_command_context(self.root)
        success, added, error = execute_command_sync("kb", f"add {path}", context)
        self.assertTrue(success, error)
        self.assertIn("BM25", added or "")
        success, listed, error = execute_command_sync("kb", "list", context)
        self.assertTrue(success, error)
        self.assertIn("rivers.md", listed or "")
        success, found, error = execute_command_sync("kb", "search otters", context)
        self.assertTrue(success, error)
        self.assertIn("rivers.md, passage 1", found or "")
        doc_id = (listed or "").split()[2]
        success, removed, error = execute_command_sync("kb", f"remove {doc_id}", context)
        self.assertTrue(success, error)
        self.assertIn("Removed", removed or "")
        success, usage, error = execute_command_sync("kb", "explode", context)
        self.assertTrue(success, error)
        self.assertIn("Usage: /kb", usage or "")
        self.assertIn("/kb", _HELP_TEXT)

    def test_settings_panel_and_api(self) -> None:
        html = (ROOT / "src" / "desktop" / "web" / "index.html").read_text(encoding="utf-8")
        script = (ROOT / "src" / "desktop" / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Knowledge base", html)
        self.assertIn("Documents stay on this machine", html)
        self.assertIn("kb-backend", html)
        self.assertIn("/api/kb", script)
        server = DesktopServer(runtime=object())
        status, body = server.handle_api("GET", "/api/kb", {}, {})
        self.assertEqual(status, 200)
        self.assertEqual(body["embedding_backend"], "local")
        self.assertTrue(body["documents_stay_local"])
        self.assertNotIn("openai_api_key", body)
        status, saved = server.handle_api(
            "POST",
            "/api/kb",
            {},
            {"embedding_backend": "openai", "openai_api_key": SECRET},
        )
        self.assertEqual(status, 200)
        self.assertTrue(saved["cloud_key_configured"])
        self.assertNotIn(SECRET, json.dumps(saved))
        with self.assertRaises(ValueError):
            server.handle_api("POST", "/api/kb", {}, {"embedding_backend": "hf-mirror"})
        self.assertIn('kb = [', (ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        notice = (ROOT / "NOTICE").read_text(encoding="utf-8")
        self.assertIn("https://github.com/TencentCloud/Octop", notice)
        self.assertIn("knowledge base", notice.lower())

    def test_format_helper_matches_the_command(self) -> None:
        path = self._write("notes.md", "Otters live in rivers.\n")
        text = format_kb_command(f"add {path}", directory=self.root, user_id="reader")
        self.assertIn("notes.md", text)
        self.assertIn("bm25", format_kb_command("list", directory=self.root, user_id="reader"))


class TestImportDoesNotPullOptionalEngines(unittest.TestCase):
    def test_fastembed_and_pypdf_stay_unimported(self) -> None:
        self.assertNotIn("fastembed", sys.modules)
        self.assertNotIn("pypdf", sys.modules)
        self.assertGreater(bm25_scores("otters", ["otters live here", "pine trees"])[0], 0)


if __name__ == "__main__":
    unittest.main()

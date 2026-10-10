"""Extract text from PDF, DOCX, Markdown, plain text, and HTML.

PDF reading uses pypdf from the optional knowledge extra. DOCX, Markdown,
text, and HTML use the Python standard library. Tests can pass a PDF reader
so the extra does not need to be installed.

Adapted from Octop's document parser (MIT). Image OCR and spreadsheet
formats from that parser are not included.

Source: https://github.com/TencentCloud/Octop
Copyright (c) 2026 Octop
SPDX-License-Identifier: MIT
"""

from __future__ import annotations

import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from xml.etree import ElementTree

SUPPORTED_SUFFIXES = frozenset({".pdf", ".docx", ".md", ".markdown", ".txt", ".html", ".htm"})

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MC_NS = "http://schemas.openxmlformats.org/markup-compatibility/2006"
_PDF_EXTRA = 'PDF ingest needs the optional knowledge extra: pip install "clawd-codex[kb]"'


def parse_document(path: Path, *, pdf_reader: Callable[[Path], str] | None = None) -> str:
    """Return searchable text for a supported local document."""
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"unsupported knowledge document: {suffix or '(none)'}")
    if suffix in {".md", ".markdown", ".txt"}:
        return _read_text(path)
    if suffix in {".html", ".htm"}:
        return _html_text(_read_text(path))
    if suffix == ".pdf":
        return _parse_pdf(path, pdf_reader)
    return _parse_docx(path)


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    text = data.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _parse_pdf(path: Path, pdf_reader: Callable[[Path], str] | None) -> str:
    if pdf_reader is not None:
        return pdf_reader(path)
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(_PDF_EXTRA) from exc
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)


def _parse_docx(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
    except (zipfile.BadZipFile, KeyError) as exc:
        raise ValueError(f"could not read DOCX: {path.name}") from exc
    root = ElementTree.fromstring(xml_bytes)
    paragraphs: list[str] = []

    def walk(node: ElementTree.Element) -> None:
        if node.tag == f"{{{_MC_NS}}}Fallback":
            return
        if node.tag == f"{{{_W_NS}}}p":
            paragraphs.append(_paragraph_text(node))
            return
        for child in list(node):
            walk(child)

    walk(root)
    return "\n".join(line for line in paragraphs if line.strip())


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts: list[str] = []

    def walk(node: ElementTree.Element) -> None:
        if node.tag == f"{{{_MC_NS}}}Fallback":
            return
        if node.tag == f"{{{_W_NS}}}t" and node.text:
            parts.append(node.text)
        if node.tag == f"{{{_W_NS}}}tab":
            parts.append("\t")
        for child in list(node):
            walk(child)

    walk(paragraph)
    return "".join(parts).strip()


def _html_text(raw: str) -> str:
    parser = _HTMLTextParser()
    parser.feed(raw)
    parser.close()
    lines = [" ".join(line.split()) for line in parser.text().splitlines()]
    return "\n".join(line for line in lines if line)


class _HTMLTextParser(HTMLParser):
    _SKIP = frozenset({"script", "style", "noscript", "template"})
    _BLOCK = frozenset(
        {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "blockquote"}
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        name = tag.lower()
        if name in self._SKIP:
            self._skip_depth += 1
        elif name in self._BLOCK and self._skip_depth == 0:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        name = tag.lower()
        if name in self._SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif name in self._BLOCK and self._skip_depth == 0:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)

"""Local document knowledge base for Jonathan Ai.

Documents are parsed, chunked, and stored in a per-user SQLite file on this
machine. Search uses a local ONNX embedding model when its Hugging Face
checksums match, and BM25 otherwise. Document text is sent to a cloud
embedding provider only when that provider is explicitly selected.

The chunking and citation shape follow Octop's knowledge base. Jonathan Ai
does not vendor Octop's service, OCR, or mirror download race.

Source: https://github.com/TencentCloud/Octop
Copyright (c) 2026 Octop
SPDX-License-Identifier: MIT
"""

from src.knowledge.service import format_kb_command, knowledge_status, update_knowledge_settings

__all__ = [
    "format_kb_command",
    "knowledge_status",
    "update_knowledge_settings",
]

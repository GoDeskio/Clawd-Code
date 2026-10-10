"""Add, list, remove, and search the local document knowledge base.

Answers name the file and the passage they came from. Document text stays
in the per-user SQLite file unless the OpenAI embedding provider is selected.
"""

from __future__ import annotations

import math
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.agent.memory import current_user_id
from src.knowledge.bm25 import bm25_scores
from src.knowledge.chunk import chunk_text
from src.knowledge.embed import Embedder, Transport, embed_cloud, embed_local
from src.knowledge.index import ChunkRecord, KnowledgeIndex
from src.knowledge.models import ChecksumError, verify_model_dir
from src.knowledge.parse import parse_document
from src.knowledge.settings import CLOUD_BACKEND, load_settings, public_view, update_settings
from src.secret_mask import mask_secrets

_USER_ID_RE = re.compile(r"[^A-Za-z0-9_.-]")

_USAGE = (
    "Usage: /kb add <path> | /kb list | /kb remove <id> | /kb search <query>\n"
    "Documents stay on this machine unless a cloud embedding provider is chosen."
)


@dataclass(frozen=True)
class PassageHit:
    filename: str
    passage: int
    text: str
    score: float
    method: str


def knowledge_root(directory: Path | None = None) -> Path:
    if directory is not None:
        path = directory
    else:
        raw = os.environ.get("JONATHAN_KB_DIR", "").strip()
        path = Path(raw) if raw else Path.home() / ".clawd" / "knowledge"
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(0o700)
    except OSError:
        pass
    return path


class KnowledgeBase:
    """Index for one user under one local directory."""

    def __init__(
        self,
        directory: Path | None = None,
        *,
        user_id: str | None = None,
        embedder: Embedder | None = None,
        transport: Transport | None = None,
        pdf_reader: Callable[[Path], str] | None = None,
    ) -> None:
        self.root = knowledge_root(directory)
        self.user_id = _safe_user_id(user_id)
        self.index = KnowledgeIndex(self.root / f"knowledge-{self.user_id}.sqlite")
        self.settings_path = self.root / f"settings-{self.user_id}.json"
        self.model_dir = self.root / "models" / "bge-small-en-v1.5"
        self._embedder = embedder
        self._transport = transport
        self._pdf_reader = pdf_reader

    def status(self) -> dict[str, object]:
        settings = load_settings(self.settings_path)
        return public_view(
            settings,
            document_count=len(self.index.list_documents()),
            model_ready=self._model_ready(),
        )

    def update(self, changes: dict[str, object]) -> dict[str, object]:
        update_settings(self.settings_path, changes)
        return self.status()

    def add_document(self, path: str | Path) -> str:
        source = Path(path).expanduser()
        if not source.is_file():
            raise ValueError(f"document not found: {source}")
        resolved = str(source.resolve())
        text = mask_secrets(parse_document(source, pdf_reader=self._pdf_reader))
        passages = chunk_text(text)
        if not passages:
            raise ValueError(f"document has no text: {source.name}")
        settings = load_settings(self.settings_path)
        backend = settings["embedding_backend"]
        embeddings: list[list[float]] | None = None
        method = "bm25"
        if backend == CLOUD_BACKEND:
            embeddings = embed_cloud(
                passages,
                api_key=settings.get("openai_api_key", ""),
                model=settings.get("cloud_model", ""),
                transport=self._transport,
            )
            method = "embedding"
        else:
            local = embed_local(passages, self.model_dir, embedder=self._embedder)
            if local is not None:
                embeddings = local
                method = "embedding"
        doc_id = uuid.uuid4().hex[:12]
        self.index.replace_document(
            doc_id=doc_id,
            filename=source.name,
            source_path=resolved,
            method=method,
            texts=passages,
            embeddings=embeddings,
        )
        if backend == CLOUD_BACKEND:
            how = "OpenAI embeddings"
            stay = "Document text was sent to api.openai.com because a cloud embedding provider is selected."
        elif method == "embedding":
            how = "local embeddings"
            stay = "Document text stayed on this machine."
        else:
            how = "BM25"
            stay = "Document text stayed on this machine."
        return f"Added {source.name} ({len(passages)} passages, {doc_id}) with {how}. {stay}"

    def list_documents(self) -> str:
        documents = self.index.list_documents()
        if not documents:
            return "No documents in the local knowledge base."
        lines = ["Local documents:"]
        for document in documents:
            lines.append(
                f"{document.doc_id}  {document.filename}  {document.passages} passages  {document.method}"
            )
        return "\n".join(lines)

    def remove_document(self, doc_id: str) -> str:
        token = doc_id.strip()
        if not token:
            raise ValueError("remove needs a document id")
        if self.index.delete(token):
            return f"Removed {token}."
        return f"No document {token}."

    def search(self, query: str, *, k: int = 5) -> str:
        text = query.strip()
        if not text:
            raise ValueError("search needs a query")
        hits = self._search(text, k=k)
        if not hits:
            return "No matching passage."
        lines: list[str] = []
        sources: list[str] = []
        for hit in hits:
            label = f"{hit.filename}, passage {hit.passage}"
            lines.append(f"{label} ({hit.method})")
            lines.append(hit.text.strip())
            lines.append("")
            sources.append(f"- {label}")
        lines.append("Sources:")
        lines.extend(sources)
        return "\n".join(lines).strip()

    def _search(self, query: str, *, k: int) -> list[PassageHit]:
        chunks = self.index.chunks()
        if not chunks or k <= 0:
            return []
        settings = load_settings(self.settings_path)
        vector_hits = self._embedding_hits(query, chunks, settings, k=k)
        if vector_hits:
            return vector_hits
        return self._bm25_hits(query, chunks, k=k)

    def _embedding_hits(
        self,
        query: str,
        chunks: list[ChunkRecord],
        settings: dict[str, str],
        *,
        k: int,
    ) -> list[PassageHit]:
        stored = [chunk for chunk in chunks if chunk.embedding]
        if not stored:
            return []
        backend = settings.get("embedding_backend", "local")
        if backend == CLOUD_BACKEND:
            vectors = embed_cloud(
                [query],
                api_key=settings.get("openai_api_key", ""),
                model=settings.get("cloud_model", ""),
                transport=self._transport,
            )
        else:
            vectors = embed_local([query], self.model_dir, embedder=self._embedder)
            if not vectors:
                return []
        return _cosine_hits(vectors[0], stored, k=k)

    def _bm25_hits(self, query: str, chunks: list[ChunkRecord], *, k: int) -> list[PassageHit]:
        scores = bm25_scores(query, [chunk.text for chunk in chunks])
        ranked = sorted(
            (
                PassageHit(
                    filename=chunk.filename,
                    passage=chunk.ordinal + 1,
                    text=chunk.text,
                    score=score,
                    method="bm25",
                )
                for chunk, score in zip(chunks, scores)
                if score > 0
            ),
            key=lambda hit: hit.score,
            reverse=True,
        )
        return ranked[:k]

    def _model_ready(self) -> bool:
        try:
            return verify_model_dir(self.model_dir)
        except ChecksumError:
            return False


def _safe_user_id(user_id: str | None) -> str:
    raw = user_id if user_id else current_user_id()
    cleaned = _USER_ID_RE.sub("_", raw).strip("._-")
    return cleaned or "local"


def format_kb_command(
    args: str,
    *,
    directory: Path | None = None,
    user_id: str | None = None,
    embedder: Embedder | None = None,
    transport: Transport | None = None,
    pdf_reader: Callable[[Path], str] | None = None,
) -> str:
    """Run one /kb command and return text for the user."""
    base = KnowledgeBase(
        directory,
        user_id=user_id,
        embedder=embedder,
        transport=transport,
        pdf_reader=pdf_reader,
    )
    parts = args.strip().split(maxsplit=1)
    if not parts:
        return _USAGE
    action = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""
    try:
        if action == "add":
            if not rest:
                return _USAGE
            return base.add_document(rest)
        if action == "list":
            return base.list_documents()
        if action == "remove":
            if not rest:
                return _USAGE
            return base.remove_document(rest)
        if action == "search":
            if not rest:
                return _USAGE
            return base.search(rest)
    except (ValueError, RuntimeError, OSError) as exc:
        return str(exc)
    return _USAGE


def knowledge_status(directory: Path | None = None, *, user_id: str | None = None) -> dict[str, object]:
    return KnowledgeBase(directory, user_id=user_id).status()


def update_knowledge_settings(
    changes: dict[str, Any],
    directory: Path | None = None,
    *,
    user_id: str | None = None,
) -> dict[str, object]:
    clean = {key: value for key, value in changes.items() if key in {
        "embedding_backend",
        "model_id",
        "cloud_model",
        "openai_api_key",
    }}
    return KnowledgeBase(directory, user_id=user_id).update(clean)


def _cosine_hits(query: list[float], chunks: list[ChunkRecord], *, k: int) -> list[PassageHit]:
    query_norm = math.sqrt(sum(value * value for value in query))
    if query_norm == 0:
        return []
    hits: list[PassageHit] = []
    for chunk in chunks:
        embedding = chunk.embedding
        if not embedding or len(embedding) != len(query):
            continue
        norm = math.sqrt(sum(value * value for value in embedding))
        score = 0.0 if norm == 0 else sum(left * right for left, right in zip(query, embedding)) / (query_norm * norm)
        if score <= 0:
            continue
        hits.append(
            PassageHit(
                filename=chunk.filename,
                passage=chunk.ordinal + 1,
                text=chunk.text,
                score=score,
                method="embedding",
            )
        )
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:k]

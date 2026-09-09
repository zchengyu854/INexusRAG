"""Document ingestion pipeline backed by PostgreSQL and pgvector."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from src.ingestion.embedder import Embedder, get_embedder
from src.ingestion.splitter import split_document
from src.storage.database import (
    create_document,
    ensure_database,
    get_document_by_source_path,
    replace_chunks,
    update_document,
)


@dataclass
class IngestionResult:
    doc_name: str
    success: bool
    chunks: int = 0
    chunk_texts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    latency_ms: float = 0.0


class IngestionPipeline:
    def __init__(
        self,
        embedder: Embedder | None = None,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        strategy: str = "recursive",
    ):
        self.embedder = embedder or get_embedder()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy

    def ingest(self, path: str | Path) -> IngestionResult:
        path = Path(path)
        result = IngestionResult(doc_name=path.name, success=False)
        started = time.perf_counter()
        try:
            ensure_database()
            document = get_document_by_source_path(str(path))
            if document is None:
                doc_id = f"pipeline-{uuid.uuid4().hex[:12]}"
                create_document(doc_id, path.name, str(path))
                document = {"id": doc_id, "filename": path.name}

            chunks = split_document(
                path,
                doc_name=path.name,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                strategy=self.strategy,
            )
            if not chunks:
                raise ValueError("切片后无有效内容")
            texts = [chunk.text for chunk in chunks]
            metadata = [chunk.metadata or {} for chunk in chunks]
            embeddings = self.embedder.encode(texts)
            replace_chunks(document["id"], path.name, texts, embeddings, metadata)
            update_document(
                document["id"],
                status="ready",
                chunks=len(texts),
                latency_ms=round((time.perf_counter() - started) * 1000, 1),
                config={
                    "strategy": self.strategy,
                    "chunk_size": self.chunk_size,
                    "chunk_overlap": self.chunk_overlap,
                },
                error=None,
            )
            result.success = True
            result.chunks = len(texts)
            result.chunk_texts = texts
        except Exception as exc:
            result.errors.append(str(exc))
        result.latency_ms = (time.perf_counter() - started) * 1000
        return result

    def ingest_batch(self, paths: Iterable[str | Path]) -> list[IngestionResult]:
        return [self.ingest(path) for path in paths]

    def remove_document(self, doc_name: str) -> int:
        from src.storage.database import delete_document_by_filename
        return delete_document_by_filename(doc_name)


def ingest_document(path: str | Path, **kwargs) -> IngestionResult:
    return IngestionPipeline(**kwargs).ingest(path)


def ingest_batch_documents(paths: list[str | Path], **kwargs) -> list[IngestionResult]:
    return IngestionPipeline(**kwargs).ingest_batch(paths)

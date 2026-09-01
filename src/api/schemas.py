from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    stream: bool = True
    top_k: int = Field(5, ge=1, le=50)


class Source(BaseModel):
    doc_name: str
    page: int | None = None
    text: str
    score: float | None = None  # 余弦相似度（1 - distance）


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    latency_ms: float = 0.0


class DocInfo(BaseModel):
    id: str
    filename: str
    chunks: int = 0
    status: str = "ready"  # pending | indexing | ready | failed


class DocConfig(BaseModel):
    strategy: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_model: str = ""
    embedding_dimension: int = 0


class DocDetail(BaseModel):
    id: str
    filename: str
    status: str
    chunks: int
    latency_ms: float
    config: DocConfig
    error: str | None = None
    embeddings: list[list[float]] = []  # 每切片的前 8 维（向量预览）


class DocChunkPreview(BaseModel):
    index: int
    chunk_id: str
    text: str
    length: int
    overlap_with_next: int = 0  # 与下一块的 overlap 字符数


class ChunksPreviewResponse(BaseModel):
    doc_id: str
    filename: str
    total_chunks: int
    strategy: str
    chunk_size: int
    chunk_overlap: int
    chunks: list[DocChunkPreview]


class SystemStats(BaseModel):
    total_documents: int
    total_chunks: int
    embedding_dimension: int
    total_size_kb: float


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"

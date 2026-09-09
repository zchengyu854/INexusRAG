from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=50)
    conversation_id: str | None = Field(None, min_length=1, max_length=100)


class Source(BaseModel):
    doc_name: str
    chunk_index: int | None = None
    page: int | None = None
    text: str
    score: float | None = None  # 余弦相似度（1 - distance）


class ChatMessage(BaseModel):
    id: str
    role: str
    content: str
    sources: list[Source] = []
    created_at: str


class ConversationSummary(BaseModel):
    id: str
    title: str
    message_count: int
    updated_at: str


class QueryResponse(BaseModel):
    answer: str
    sources: list[Source] = []
    latency_ms: float = 0.0
    conversation_id: str | None = None


class DocInfo(BaseModel):
    id: str
    filename: str
    chunks: int = 0
    status: str = "ready"  # pending | indexing | ready | failed


class DocConfig(BaseModel):
    strategy: str = "recursive"
    chunk_size: int = 512
    chunk_overlap: int = 64


class RechunkRequest(BaseModel):
    chunk_size: int = Field(512, ge=64, le=4096)
    chunk_overlap: int = Field(64, ge=0, lt=4096)
    strategy: str = "recursive"

    @model_validator(mode="after")
    def validate_overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        return self


class RechunkResult(BaseModel):
    doc_id: str
    filename: str
    old_chunks: int
    new_chunks: int
    old_config: DocConfig
    new_config: DocConfig
    latency_ms: float
    success: bool
    error: str | None = None


class DocChunkPreview(BaseModel):
    index: int
    chunk_id: str
    text: str
    length: int
    page: int | None = None
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

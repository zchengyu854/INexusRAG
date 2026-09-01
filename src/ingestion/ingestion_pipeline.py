"""
文档入库管道

串联 loaders → splitter → embedder → vector_store，完成端到端入库流程。

用法：
    from src.ingestion.ingestion_pipeline import ingest_document

    # 单文档入库
    result = ingest_document("data/test_docs/fastapi_readme.md")
    print(f"入库 {result['chunks']} 个切片")

    # 批量入库
    results = ingest_batch(["doc1.md", "doc2.pdf"])
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.ingestion.embedder import Embedder
from src.ingestion.loaders import load
from src.ingestion.splitter import split_text
from src.ingestion.vector_store import VectorStore


@dataclass
class IngestionResult:
    """单次入库结果。"""
    doc_name: str
    success: bool
    chunks: int = 0
    chunk_texts: list[str] = None
    errors: list[str] = None
    latency_ms: float = 0.0

    def __post_init__(self):
        if self.chunk_texts is None:
            self.chunk_texts = []
        if self.errors is None:
            self.errors = []


class IngestionPipeline:
    """
    文档入库管道。

    流程：
        加载 → 切片 → 编码 → 写入向量库

    用法：
        pipeline = IngestionPipeline()
        result = pipeline.ingest("document.md")
    """

    def __init__(
        self,
        embedder: Embedder | None = None,
        vector_store: VectorStore | None = None,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        strategy: str = "recursive",
    ):
        self.embedder = embedder or Embedder()
        self.vector_store = vector_store or VectorStore()
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.strategy = strategy

    def ingest(self, path: str | Path) -> IngestionResult:
        """
        单文档入库。

        Args:
            path: 文档路径

        Returns:
            IngestionResult
        """
        path = Path(path)
        doc_name = path.name
        start_time = time.time()

        result = IngestionResult(doc_name=doc_name, success=False)

        try:
            # 1. 加载
            text = load(path)
            if not text.strip():
                result.errors.append("文档内容为空")
                return result

            # 2. 切片
            chunks = split_text(
                text,
                doc_name=doc_name,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                strategy=self.strategy,
            )
            if not chunks:
                result.errors.append("切片后无有效内容")
                return result

            # 3. 编码
            embeddings = self.embedder.encode([c.text for c in chunks])

            # 4. 写入
            chunk_ids = self.vector_store.add(doc_name, [c.text for c in chunks], embeddings)

            result.success = True
            result.chunks = len(chunk_ids)
            result.chunk_texts = [c.text for c in chunks]

        except Exception as e:
            result.errors.append(str(e))

        result.latency_ms = (time.time() - start_time) * 1000
        return result

    def ingest_batch(self, paths: Iterable[str | Path]) -> list[IngestionResult]:
        """
        批量入库。

        Args:
            paths: 文档路径列表

        Returns:
            每个文档的 IngestionResult
        """
        return [self.ingest(p) for p in paths]

    def remove_document(self, doc_name: str) -> int:
        """
        删除文档及其所有切片。

        Args:
            doc_name: 文档名称（不含扩展名）

        Returns:
            删除的切片数
        """
        return self.vector_store.delete(doc_name)


# 便捷函数
def ingest_document(
    path: str | Path,
    chunk_size: int = 512,
    chunk_overlap: int = 64,
    strategy: str = "recursive",
) -> IngestionResult:
    """便捷函数：单文档入库。"""
    pipeline = IngestionPipeline(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        strategy=strategy,
    )
    return pipeline.ingest(path)


def ingest_batch_documents(
    paths: list[str | Path],
    **kwargs,
) -> list[IngestionResult]:
    """便捷函数：批量文档入库。"""
    pipeline = IngestionPipeline(**kwargs)
    return pipeline.ingest_batch(paths)

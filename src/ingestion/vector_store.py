"""
向量数据库封装模块

支持两种后端：
1. ChromaDB：轻量本地，零部署，适合学习和原型
2. 占位扩展：Qdrant / Milvus（生产级）

核心接口：
  - add(doc_name, chunks, embeddings)    批量写入
  - search(query_vector, top_k)          向量检索
  - search_hybrid(query_vector, keywords, top_k)  混合检索占位
  - delete(doc_name)                     按文档删除
  - count()                              统计文档数
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import chromadb
from chromadb.config import Settings


@dataclass
class SearchResult:
    """检索结果。"""
    chunk_id: str
    doc_name: str
    text: str
    score: float
    metadata: dict = field(default_factory=dict)


class VectorStore:
    """
    向量数据库封装，默认使用 ChromaDB。

    用法：
        store = VectorStore(persist_dir="./data/chroma")
        store.add("doc1.pdf", chunks, embeddings)
        results = store.search(query_vector, top_k=5)
    """

    def __init__(
        self,
        persist_dir: str = "./data/chroma",
        collection_name: str = "nexus_rag",
        provider: str = "chroma",
    ):
        self.provider = provider
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name

        if provider == "chroma":
            self._client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._collection = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        else:
            raise ValueError(f"不支持的向量库 provider: {provider}")

    def add(
        self,
        doc_name: str,
        chunks: Iterable[str],
        embeddings: Iterable[list[float]],
    ) -> list[str]:
        """
        批量写入文档切片和对应向量。

        Args:
            doc_name: 文档名称（用于标识和删除）
            chunks: 文本切片列表
            embeddings: 对应的向量列表

        Returns:
            生成的 chunk_id 列表
        """
        chunks = list(chunks)
        embeddings = list(embeddings)
        if len(chunks) != len(embeddings):
            raise ValueError(f"chunks 和 embeddings 长度不匹配: {len(chunks)} vs {len(embeddings)}")

        ids = [f"{doc_name}-{uuid.uuid4().hex[:8]}" for _ in chunks]
        metadatas = [
            {"doc_name": doc_name, "chunk_index": i}
            for i, _ in enumerate(chunks)
        ]

        self._collection.add(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        return ids

    def search(
        self,
        query_vector: list[float],
        top_k: int = 5,
        where: dict | None = None,
    ) -> list[SearchResult]:
        """
        向量相似度检索。

        Args:
            query_vector: 查询向量
            top_k: 返回结果数量
            where: 元数据过滤条件（如 {"doc_name": "xxx.pdf"}）

        Returns:
            SearchResult 列表，按相似度降序排列
        """
        kwargs = {
            "query_embeddings": [query_vector],
            "n_results": min(top_k, self._collection.count()),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        output = []
        for i in range(len(results["ids"][0])):
            output.append(SearchResult(
                chunk_id=results["ids"][0][i],
                doc_name=results["metadatas"][0][i].get("doc_name", ""),
                text=results["documents"][0][i],
                score=1.0 - results["distances"][0][i],  # cosine distance → similarity
                metadata=results["metadatas"][0][i],
            ))
        return output

    def search_hybrid(
        self,
        query_vector: list[float],
        keywords: str = "",
        top_k: int = 5,
    ) -> list[SearchResult]:
        """
        混合检索占位实现（Dense + BM25）。

        当前仅实现向量检索，BM25 部分需接入 rank_bm25 库后完善。
        Phase 2 实现。
        """
        # TODO: 接入 BM25 稀疏检索
        # TODO: RRF 融合 Dense + Sparse 结果
        return self.search(query_vector, top_k=top_k)

    def delete(self, doc_name: str) -> int:
        """
        删除指定文档的所有切片。

        Returns:
            删除的切片数量
        """
        results = self._collection.get(
            where={"doc_name": doc_name},
            include=["metadatas"],
        )
        ids = results["ids"]
        if ids:
            self._collection.delete(ids=ids)
            return len(ids)
        return 0

    def count(self) -> int:
        """返回向量库中总切片数。"""
        return self._collection.count()

    def list_documents(self) -> list[dict]:
        """列出所有文档及其切片数。"""
        all_results = self._collection.get(include=["metadatas"])
        doc_stats: dict[str, dict] = {}
        for meta in all_results["metadatas"]:
            name = meta.get("doc_name", "unknown")
            if name not in doc_stats:
                doc_stats[name] = {"filename": name, "chunks": 0}
            doc_stats[name]["chunks"] += 1
        return list(doc_stats.values())


# 全局单例
_store_instance: VectorStore | None = None


def get_vector_store(
    persist_dir: str = "./data/chroma",
    collection_name: str = "nexus_rag",
) -> VectorStore:
    """获取全局 VectorStore 实例。"""
    global _store_instance
    if _store_instance is None:
        _store_instance = VectorStore(persist_dir, collection_name)
    return _store_instance


def reset_vector_store():
    """重置全局实例（用于测试）。"""
    global _store_instance
    _store_instance = None

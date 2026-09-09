"""
Embedding 封装模块

支持两种模式：
1. API 模式：OpenAI / 兼容接口（从 .env 读取配置）
2. 本地模式：sentence-transformers（离线，无需 API Key）

环境变量：
  EMBEDDING_PROVIDER=openai | local
  EMBEDDING_API_KEY=your_key
  EMBEDDING_BASE_URL=https://api.openai.com/v1
  EMBEDDING_MODEL=text-embedding-3-small
  EMBEDDING_DIMENSION=1536
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from dotenv import load_dotenv

load_dotenv()


def _get_env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


class Embedder:
    """
    Embedding 封装，支持 OpenAI API 和本地模型。

    用法：
        embedder = Embedder()
        vectors = embedder.encode(["文档片段1", "文档片段2"])
    """

    def __init__(self, provider: str | None = None):
        self.provider = provider or _get_env("EMBEDDING_PROVIDER", "openai").lower()
        self.api_key = _get_env("EMBEDDING_API_KEY", "")
        self.base_url = _get_env("EMBEDDING_BASE_URL", "https://api.openai.com/v1")
        self.model = _get_env("EMBEDDING_MODEL", "text-embedding-3-small")
        self.dimension = int(_get_env("EMBEDDING_DIMENSION", "1536"))

        if self.provider == "openai":
            self._client = self._init_openai()
        elif self.provider == "local":
            self._client = self._init_local()
        else:
            raise ValueError(f"不支持的 embedding provider: {self.provider}")

    def _init_openai(self):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("使用 OpenAI embedding 需要安装 openai: uv add openai")

        if not self.api_key:
            raise ValueError("EMBEDDING_API_KEY 未设置，请在 .env 中配置")

        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def _init_local(self):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            raise ImportError("使用本地 embedding 需要安装 sentence-transformers: uv add sentence-transformers")

        model_name = _get_env("LOCAL_EMBEDDING_MODEL", "BAAI/bge-m3")
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        return SentenceTransformer(model_name, local_files_only=True)

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        """
        将文本列表编码为向量（每批 32 条）。

        Args:
            texts: 文本列表

        Returns:
            向量列表，每个向量是 float 列表
        """
        texts = list(texts)
        if not texts:
            return []

        if self.provider == "openai":
            return self._encode_openai(texts)
        else:
            return self._encode_local(texts)

    def _encode_openai(self, texts: list[str]) -> list[list[float]]:
        """OpenAI API 批量编码。"""
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), 32):
            batch = texts[i:i + 32]
            response = self._client.embeddings.create(
                model=self.model,
                input=batch,
                encoding_format="float",
            )
            # API 可能重排，按 index 固定回原始顺序
            for item in sorted(response.data, key=lambda item: item.index):
                all_embeddings.append(item.embedding)
        return all_embeddings

    def _encode_local(self, texts: list[str]) -> list[list[float]]:
        """本地模型批量编码。"""
        embeddings = self._client.encode(texts, batch_size=32, show_progress_bar=False)
        # sentence-transformers 返回 numpy array，转为 list
        if hasattr(embeddings, "tolist"):
            return embeddings.tolist()
        return [list(e) for e in embeddings]

    @property
    def model_name(self) -> str:
        if self.provider == "openai":
            return f"openai/{self.model}"
        return _get_env("LOCAL_EMBEDDING_MODEL", "BAAI/bge-m3")

    def get_dimension(self) -> int:
        return self.dimension


# 全局单例（便于其他模块直接导入使用）
_embedder_instance: Embedder | None = None


def get_embedder(provider: str | None = None) -> Embedder:
    """获取全局 Embedder 实例。"""
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = Embedder(provider)
    return _embedder_instance


def reset_embedder():
    """重置全局实例（用于测试）。"""
    global _embedder_instance
    _embedder_instance = None

"""重排策略（可切换）：RERANK_STRATEGY=rrf|cross|llm|colbert。

四者实现独立、共用同一接口 rerank(query, candidates, top_k) -> 重排后的行（附 rerank_score）。
RRF 分数由 two_stage_search/rrf_merge 在行上产出（row["score"]），作为 rrf 策略的打分来源。
"""
from __future__ import annotations

import os

_MODEL_NAME = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
_COLBERT_MODEL = os.getenv("COLBERT_MODEL", "models/colbert")  # 需先 `snapshot_download castorini/tct_colbert-v2-msmarco` 到此目录

_reranker = None
_colbert = None


def get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        _reranker = CrossEncoder(_MODEL_NAME, local_files_only=True)
    return _reranker


def _score_rrf(query: str, candidates: list[dict]) -> list[float]:
    return [c.get("score", 0.0) for c in candidates]


def _score_cross(query: str, candidates: list[dict]) -> list[float]:
    return list(get_reranker().predict([[query, c["text"]] for c in candidates]))


def _score_llm(query: str, candidates: list[dict]) -> list[float]:
    """LLM pointwise 打分（function calling 格式）：一次批量调用输出 {chunk_id: 0-10 分}；失败保持 RRF 序。"""
    _SCORE_TOOL: dict = {
        "name": "score_chunks",
        "description": "按与问题的相关性对每个片段打 0-10 分（10 最相关）",
        "parameters": {
            "type": "object",
            "properties": {
                "scores": {
                    "type": "object",
                    "description": "键为片段 id，值为 0-10 的相关性分",
                    "additionalProperties": {"type": "number"},
                },
            },
            "required": ["scores"],
        },
    }
    from src.llm.client import get_llm

    llm = get_llm()
    if not llm.enabled:
        return _score_rrf(candidates)
    listing = "\n".join(f"{c['chunk_id']}: {c['text'][:200]}" for c in candidates)
    try:
        data = llm.tool_call(f"问题：{query}\n片段：\n{listing}", _SCORE_TOOL)
        data = data.get("scores", {})
        return [float(data.get(c["chunk_id"], c.get("score", 0.0))) for c in candidates]
    except Exception:
        return _score_rrf(query, candidates)


def _score_colbert(query: str, candidates: list[dict]) -> list[float]:
    """ColBERT 真 Late Interaction：token 级 MaxSim；ponytail: 需预下载模型到 models/colbert。"""
    global _colbert
    if _colbert is None:
        if not os.path.isdir(_COLBERT_MODEL) or not os.path.exists(os.path.join(_COLBERT_MODEL, "config.json")):
            raise FileNotFoundError(
                f"ColBERT 模型目录 {_COLBERT_MODEL} 不存在。先下载："
                "HF_ENDPOINT=https://hf-mirror.com 用 huggingface_hub.snapshot_download 拉 castorini/tct_colbert-v2-hn-msmarco 到此目录")
        from colbert import Checkpoint
        from colbert.modeling.colbert import colbert_score
        from colbert.searcher import ColBERTConfig

        cfg = ColBERTConfig()
        cfg.configure(checkpoint=_COLBERT_MODEL)
        checkpoint = Checkpoint(_COLBERT_MODEL, colbert_config=cfg)

        def encode_docs(texts):
            input_ids, attention_mask = checkpoint.doc_tokenizer.tensorize(texts)
            D, mask = checkpoint.doc(input_ids, attention_mask, keep_dims="return_mask", to_cpu=True)
            return D, mask

        def encode_query(text):
            return checkpoint.queryFromText([text], bsize=1, to_cpu=True)

        _colbert = (colbert_score, encode_docs, encode_query, cfg)

    colbert_score, encode_docs, encode_query, cfg = _colbert
    Q = encode_query(query)
    D, mask = encode_docs([c["text"] for c in candidates])
    return [float(s) for s in colbert_score(Q, D, mask, config=cfg).tolist()]


_STRATEGIES = {"rrf": _score_rrf, "cross": _score_cross, "llm": _score_llm, "colbert": _score_colbert}


def rerank(query: str, candidates: list[dict], top_k: int, strategy: str | None = None) -> list[dict]:
    """按 RERANK_STRATEGY（默认 rrf）重排 candidates，返回前 top_k 并写入 rerank_score。

    strategy 显式传入时优先于环境变量，供请求级切换（问答页的「重排策略」选项）。
    """
    if not candidates:
        return []
    if strategy is None:
        strategy = os.getenv("RERANK_STRATEGY", "rrf")
    strategy = strategy.lower()
    if strategy not in _STRATEGIES:
        raise ValueError(f"未知 RERANK_STRATEGY: {strategy}（可选 {sorted(_STRATEGIES)}）")
    scores = _STRATEGIES[strategy](query, candidates)
    ranked = sorted(((c, float(s)) for c, s in zip(candidates, scores)), key=lambda p: p[1], reverse=True)
    return [dict(c, rerank_score=round(s, 6)) for c, s in ranked[:top_k]]

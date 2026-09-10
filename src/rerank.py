"""重排策略（可切换）：RERANK_STRATEGY=rrf|cross|llm|colbert。

四者实现独立、共用同一接口 rerank(query, candidates, top_k) -> 重排后的行（附 rerank_score）。
RRF 分数由 two_stage_search/rrf_merge 在行上产出（row["score"]），作为 rrf 策略的打分来源。
"""
from __future__ import annotations

import json
import os

_MODEL_NAME = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
_COLBERT_MODEL = os.getenv("COLBERT_MODEL", "castorini/colbert-ir")

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
    """LLM pointwise 打分：一次批量调用输出 {chunk_id: 0-10 分}；失败保持 RRF 序。"""
    from src.llm.client import get_llm

    llm = get_llm()
    if not llm.enabled:
        return _score_rrf(candidates)
    listing = "\n".join(f"{c['chunk_id']}: {c['text'][:200]}" for c in candidates)
    try:
        response = llm._get_client().chat.completions.create(
            model=llm.model,
            messages=[
                {"role": "system", "content": (
                    "对每个片段与问题的相关性打 0-10 分（10 最相关）。"
                    '只输出 JSON 对象，键为片段 id，如 {"c-1": 8, "c-2": 3}。')},
                {"role": "user", "content": f"问题：{query}\n片段：\n{listing}"},
            ],
            temperature=0,
        )
        data = json.loads((response.choices[0].message.content or "{}").strip().removeprefix("```json").removeprefix("```").strip())
        return [float(data.get(c["chunk_id"], c.get("score", 0.0))) for c in candidates]
    except Exception:
        return _score_rrf(candidates)


def _score_colbert(query: str, candidates: list[dict]) -> list[float]:
    """ColBERT MaxSim：token 级 max-over-tokens 余弦和；ponytail: 英文模型默认，中文换 XLM-R 系 colbert。"""
    global _colbert
    if _colbert is None:
        from sentence_transformers import CrossEncoder
        _colbert = CrossEncoder(_COLBERT_MODEL, local_files_only=False)
    return list(_colbert.predict([[query, c["text"]] for c in candidates]))


_STRATEGIES = {"rrf": _score_rrf, "cross": _score_cross, "llm": _score_llm, "colbert": _score_colbert}


def rerank(query: str, candidates: list[dict], top_k: int) -> list[dict]:
    """按 RERANK_STRATEGY（默认 rrf）重排 candidates，返回前 top_k 并写入 rerank_score。"""
    if not candidates:
        return []
    strategy = os.getenv("RERANK_STRATEGY", "rrf").lower()
    if strategy not in _STRATEGIES:
        raise ValueError(f"未知 RERANK_STRATEGY: {strategy}（可选 {sorted(_STRATEGIES)}）")
    scores = _STRATEGIES[strategy](query, candidates)
    ranked = sorted(((c, float(s)) for c, s in zip(candidates, scores)), key=lambda p: p[1], reverse=True)
    return [dict(c, rerank_score=round(s, 6)) for c, s in ranked[:top_k]]

"""混合检索：向量通道 + 关键词通道，RRF（倒数排名融合）合并；复杂问题多查询分解。"""
from __future__ import annotations

import json
import re

import jieba

from src.storage.database import keyword_chunks, search_chunks, search_doc_index, upsert_doc_index

# 提问里常见的无检索价值词（jieba 精确命中才过滤）
_JUNK = set((
    "的 了 吗 呢 啊 吧 么 是 在 有 和 与 或 及 着 被 把 对 向 于 从 到 "
    "什么 怎么 如何 哪些 哪个 为什么 可以 能否 是否 这个 那个 一个 我们 你们 他们 你 我"
).split())
_ASCII = re.compile(r"[0-9A-Za-z]")
_CJK = re.compile(r"[\u4e00-\u9fff]+\Z")


def extract_terms(question: str, max_terms: int = 12) -> list[str]:
    """从问题中提取关键词：jieba 分词 + 数字/字母串，去掉停用词和单字。"""
    terms: list[str] = []
    seen: set[str] = set()
    for token in jieba.lcut(question):
        token = token.strip()
        if len(token) < 2 or token in _JUNK:
            continue
        if not (_ASCII.search(token) or _CJK.match(token)):
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
            if len(terms) >= max_terms:
                break
    return terms


def rrf_merge(channels: list[list[dict]], top_k: int, k: int = 60) -> list[dict]:
    """RRF 融合多个有序结果通道，返回带融合分的行（按 chunk_id 去重）。"""
    scores: dict[str, float] = {}
    rows: dict[str, dict] = {}
    for channel in channels:
        for rank, row in enumerate(channel):
            key = row["chunk_id"]
            rows.setdefault(key, row)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank + 1)
    ranked = sorted(scores, key=scores.get, reverse=True)[:top_k]
    return [dict(rows[key], score=round(scores[key], 6)) for key in ranked]


def build_routing_summary(filename: str, chunks: list) -> str:
    """机械式路由摘要：文件名 + 前两级标题 + 开头 200 字。"""
    headings: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        for heading in ((chunk.metadata or {}).get("heading_path") or [])[:2]:
            if heading not in seen:
                seen.add(heading)
                headings.append(heading)
    lines = [filename]
    if headings:
        lines.append("章节: " + " / ".join(headings[:15]))
    if chunks:
        lines.append("开头: " + chunks[0].text.strip()[:200])
    return "\n".join(lines)


def index_document_route(doc_id: str, doc_name: str, chunks: list, encode) -> None:
    """生成/更新文档路由条目（ingest 与 rechunk 后调用）。"""
    summary = build_routing_summary(doc_name, chunks)
    upsert_doc_index(doc_id, doc_name, summary, encode([summary])[0])


_ROUTE_TOP = 3
_MIN_ROUTE_SCORE = 0.3  # ponytail: 余弦阈值未校准（bge-m3），观测到路由漏检后调


def two_stage_search(query_embedding: list[float], top_k: int, terms: list[str], filters: dict | None = None) -> list[dict]:
    """两级检索：先路由命中目标文档，再在目标文档内检索；关键词通道全局兑底。"""
    routed = search_doc_index(query_embedding, top_k=_ROUTE_TOP)
    limit = max(top_k * 5, 25)
    channels: list[list[dict]] = []
    if terms:
        channels.append(keyword_chunks(terms, limit=limit, filters=filters))
    if routed:
        for row in routed:
            channels.append(search_chunks(query_embedding, top_k=limit, doc_id=row["doc_id"], filters=filters))
        if routed[0]["score"] < _MIN_ROUTE_SCORE:
            channels.append(search_chunks(query_embedding, top_k=limit, filters=filters))
    else:
        channels.append(search_chunks(query_embedding, top_k=limit, filters=filters))
    if not channels:
        return []
    return rrf_merge(channels, top_k)


def plan_question(question: str) -> dict:
    """检索规划：一次 LLM 调用决定子问题/退步抽象/HyDE 段落三项（不用则留空），让 LLM 自行门控。

    LLM 不可用或输出不合法时返回全空计划——检索永远不退化为失败。"""
    empty = {"subs": [], "step_back": None, "hyde": None}
    from src.llm.client import get_llm

    llm = get_llm()
    if not llm.enabled:
        return empty
    try:
        response = llm._get_client().chat.completions.create(
            model=llm.model,
            messages=[
                {"role": "system", "content": (
                    "你是检索规划器，为问题规划检索通道，判断三项：\n"
                    "1. subs: 若问题包含多个子主题，拆成不超过 5 个可被单次检索独立回答的具体子问题；"
                    "问题已足够具体则留空数组。\n"
                    "2. step_back: 若问题过于细节具体，退一步写一个更宽泛的概念问题，"
                    "其答案包含回答原问题所需的知识背景；已够抽象则置 null。\n"
                    "3. hyde: 写一段 150~300 字中文段落，描述回答该问题的文档会包含哪些关键信息"
                    "（具体概念、术语、因果关系），使语义嵌入接近真实相关文档；不直接答题、不声明假设，"
                    "简单事实型问题可置 null。\n"
                    '只输出 JSON 对象: {"subs": [], "step_back": null, "hyde": null}')},
                {"role": "user", "content": question},
            ],
            temperature=0,
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`").removeprefix("json").strip()
        data = json.loads(raw)
        subs = [str(s).strip() for s in data.get("subs", []) if str(s).strip()][:5]
        step = data.get("step_back")
        hyde = data.get("hyde")
        return {
            "subs": subs,
            "step_back": step.strip() if isinstance(step, str) and len(step.strip()) >= 8 else None,
            "hyde": hyde.strip() if isinstance(hyde, str) and len(hyde.strip()) >= 40 else None,
        }
    except Exception:
        return empty


def multi_query_search(question: str, top_k: int, filters: dict | None = None) -> list[dict]:
    """多查询：LLM 规划（分解/退步/HyDE，单次调用门控）→ 各通道两级检索 → RRF 合并去重。"""
    from src.ingestion.embedder import get_embedder

    plan = plan_question(question)
    queries = [question, *[s for s in plan["subs"] if s != question]]
    if plan["step_back"] and plan["step_back"] != question:
        queries.append(plan["step_back"])
    vectors = get_embedder().encode(queries)
    channels = [
        two_stage_search(vec, top_k=top_k, terms=extract_terms(q), filters=filters)
        for q, vec in zip(queries, vectors)
    ]
    if plan["hyde"]:
        hyde_vec = get_embedder().encode([plan["hyde"]])[0]
        channels.append(two_stage_search(hyde_vec, top_k=top_k, terms=[], filters=filters))
    return rrf_merge(channels, top_k)

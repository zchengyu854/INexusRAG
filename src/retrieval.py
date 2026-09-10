"""混合检索：向量通道 + 关键词通道，RRF（倒数排名融合）合并；复杂问题多查询分解。"""
from __future__ import annotations

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


def two_stage_search(query_embedding: list[float], top_k: int, terms: list[str], filters: dict | None = None, use_routing: bool = True) -> list[dict]:
    """两级检索：先路由命中目标文档，再在目标文档内检索；关键词通道全局兑底。use_routing=False 时只做全局向量检索。"""
    limit = max(top_k * 5, 25)
    channels: list[list[dict]] = []
    if terms:
        channels.append(keyword_chunks(terms, limit=limit, filters=filters))
    if not use_routing:
        channels.append(search_chunks(query_embedding, top_k=limit, filters=filters))
        return rrf_merge(channels, top_k) if channels else []
    routed = search_doc_index(query_embedding, top_k=_ROUTE_TOP)
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


# function-calling 检索规划 schema：三项各带判据，LLM 按 schema 填参（不适用留空）
_PLAN_TOOL: dict = {
    "name": "plan_question",
    "description": "判断 subs/step_back/hyde 三项是否适用本题，不适用留 null/[]",
    "parameters": {
        "type": "object",
        "properties": {
            "subs": {
                "type": "array",
                "maxItems": 5,
                "description": "子问题：问题含多个子主题时拆成不超过 5 个可独立检索回答的具体子问题；已够具体则 []",
                "items": {"type": "string"},
            },
            "step_back": {
                "type": "string",
                "description": "退步概念问题：问题过于细节具体时，退一步写更宽泛的概念问题（答案需包含回答原问题的背景）；已够抽象则 null",
            },
            "hyde": {
                "type": "string",
                "description": "假想文档片段：150~300 字中文段落，描述回答该问题的文档会包含的关键信息（概念、术语、因果）；不直接答题；简单事实型问题置 null",
            },
        },
    },
}


def plan_question(question: str) -> dict:
    """检索规划：一次 LLM 调用（function calling 格式）决定子问题/退步抽象/HyDE 段落三项，让 LLM 自行门控。

    LLM 不可用或输出不合法时返回全空计划——检索永远不退化为失败。"""
    empty = {"subs": [], "step_back": None, "hyde": None}
    from src.llm.client import get_llm

    llm = get_llm()
    if not llm.enabled:
        return empty
    try:
        data = llm.tool_call(question, _PLAN_TOOL)
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


ALL_FEATURES = ("routing", "keywords", "decompose", "stepback", "hyde", "rerank", "graph")
_DEFAULT_FEATURES = ("routing", "keywords", "decompose", "stepback", "hyde")  # rerank/graph 默认关，消融时显式传 features


def multi_query_search(question: str, top_k: int, filters: dict | None = None, features: list[str] | None = None) -> list[dict]:
    """多查询：features 控制通道开关（None = 默认全开除 rerank）→ 两级检索 → RRF → 可选 rerank。"""
    from src.ingestion.embedder import get_embedder

    active = set(_DEFAULT_FEATURES) if features is None else set(features)
    # 只有启用规划类特性才付 LLM 规划调用
    plan = plan_question(question) if {"decompose", "stepback", "hyde"} & active else {"subs": [], "step_back": None, "hyde": None}
    queries = [question]
    if "decompose" in active:
        queries += [s for s in plan["subs"] if s != question]
    if "stepback" in active and plan["step_back"] and plan["step_back"] != question:
        queries.append(plan["step_back"])
    vectors = get_embedder().encode(queries)
    use_routing = "routing" in active
    channels = [
        two_stage_search(vec, top_k=top_k,
                         terms=(extract_terms(q) if "keywords" in active else []),
                         filters=filters, use_routing=use_routing)
        for q, vec in zip(queries, vectors)
    ]
    if "hyde" in active and plan["hyde"]:
        hyde_vec = get_embedder().encode([plan["hyde"]])[0]
        channels.append(two_stage_search(hyde_vec, top_k=top_k, terms=[], filters=filters, use_routing=use_routing))
    if "graph" in active:
        # 图谱通道：复用原问题的向量做实体锚点，零额外 embedding 成本
        from src.graph import graph_channel
        channels.append(graph_channel(vectors[0], top_k=max(top_k * 5, 25), filters=filters))
    merged = rrf_merge(channels, top_k if "rerank" not in active else top_k * 5)
    if "rerank" in active and merged:
        from src.rerank import rerank
        merged = rerank(question, merged, top_k)
    return merged

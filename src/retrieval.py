"""混合检索：向量通道 + 关键词通道，RRF（倒数排名融合）合并；复杂问题多查询分解。"""
from __future__ import annotations

import os
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


def two_stage_search(
    query_embedding: list[float],
    top_k: int,
    terms: list[str],
    filters: dict | None = None,
    use_routing: bool = True,
    stats: dict | None = None,
) -> list[dict]:
    """两级检索：先路由命中目标文档，再在目标文档内检索；关键词通道全局兑底。use_routing=False 时只做全局向量检索。

    stats 为可选的出参字典，仅在需要观测时传入（用于 /api/query 的 debug trace）。
    传 None 时全部记账代码被跳过，检索路径与不传时完全一致。
    """
    limit = max(top_k * 5, 25)
    channels: list[list[dict]] = []
    if terms:
        keyword_rows = keyword_chunks(terms, limit=limit, filters=filters)
        if stats is not None:
            stats["keywords"] = stats.get("keywords", 0) + len(keyword_rows)
        channels.append(keyword_rows)
    if not use_routing:
        vector_rows = search_chunks(query_embedding, top_k=limit, filters=filters)
        if stats is not None:
            stats["vector"] = stats.get("vector", 0) + len(vector_rows)
        channels.append(vector_rows)
        return rrf_merge(channels, top_k) if channels else []
    routed = search_doc_index(query_embedding, top_k=_ROUTE_TOP)
    if stats is not None:
        # 多查询时每条查询各自路由，这里按 doc_id 去重统计，避免「命中 8 篇文档」式的误读
        stats.setdefault("route_top_score", round(float(routed[0]["score"]), 4) if routed else 0.0)
        stats.setdefault("route_fallback", False)
        stats.setdefault("routed_doc_ids", set()).update(row["doc_id"] for row in routed)
    if routed:
        for row in routed:
            doc_rows = search_chunks(query_embedding, top_k=limit, doc_id=row["doc_id"], filters=filters)
            if stats is not None:
                stats["vector"] = stats.get("vector", 0) + len(doc_rows)
            channels.append(doc_rows)
        if routed[0]["score"] < _MIN_ROUTE_SCORE:
            # 路由置信度不足，补一路全局向量兜底
            fallback_rows = search_chunks(query_embedding, top_k=limit, filters=filters)
            if stats is not None:
                stats["vector"] = stats.get("vector", 0) + len(fallback_rows)
                stats["route_fallback"] = True
            channels.append(fallback_rows)
    else:
        # 路由层没有命中任何文档（如 doc_index 为空），退回全局向量
        fallback_rows = search_chunks(query_embedding, top_k=limit, filters=filters)
        if stats is not None:
            stats["vector"] = stats.get("vector", 0) + len(fallback_rows)
            stats["route_fallback"] = True
        channels.append(fallback_rows)
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


def multi_query_search(
    question: str,
    top_k: int,
    filters: dict | None = None,
    features: list[str] | None = None,
    debug: bool = False,
    rerank_strategy: str | None = None,
) -> list[dict] | dict:
    """多查询：features 控制通道开关（None = 默认全开除 rerank）→ 两级检索 → RRF → 可选 rerank。

    debug=True 时返回 {"results": [...], "trace": {...}}，只为把过程暴露给检视面板，不重复跑检索。
    trace 区分「请求的」与「真正生效的」：applied 是实际起了作用的通道，空转或被降级的进 skipped
    并附原因（例如 LLM 未配置导致规划类特性失效），避免面板把空转的开关显示成生效。
    debug=False（默认）时不构建 trace、不记账，检索路径与改动前一致。
    """
    import time as _time

    from src.ingestion.embedder import get_embedder

    t_start = _time.perf_counter() if debug else 0.0
    requested = set(_DEFAULT_FEATURES) if features is None else set(features)
    wants_plan = bool({"decompose", "stepback", "hyde"} & requested)
    # 只有启用规划类特性才付 LLM 规划调用
    plan = plan_question(question) if wants_plan else {"subs": [], "step_back": None, "hyde": None}
    t_planned = _time.perf_counter() if debug else 0.0

    queries = [question]
    sub_queries: list[str] = []
    if "decompose" in requested:
        sub_queries = [s for s in plan["subs"] if s != question]
        queries += sub_queries
    step_back_used = bool("stepback" in requested and plan["step_back"] and plan["step_back"] != question)
    if step_back_used:
        queries.append(plan["step_back"])
    vectors = get_embedder().encode(queries)
    use_routing = "routing" in requested
    # 仅 debug 时记账；传 None 会让 two_stage_search 跳过全部计数代码
    stats: dict | None = {} if debug else None

    def _search(query: str, vector: list[float]) -> list[dict]:
        return two_stage_search(
            vector, top_k=top_k,
            terms=(extract_terms(query) if "keywords" in requested else []),
            filters=filters, use_routing=use_routing, stats=stats,
        )

    channels: list[list[dict]] = []
    primary = _search(queries[0], vectors[0])
    channels.append(primary)
    expanded = [_search(query, vector) for query, vector in zip(queries[1:], vectors[1:])]
    channels.extend(expanded)
    hyde_used = bool("hyde" in requested and plan["hyde"])
    hyde_rows: list[dict] = []
    if hyde_used:
        hyde_vec = get_embedder().encode([plan["hyde"]])[0]
        hyde_rows = two_stage_search(hyde_vec, top_k=top_k, terms=[], filters=filters, use_routing=use_routing, stats=stats)
        channels.append(hyde_rows)
    graph_rows: list[dict] = []
    if "graph" in requested:
        # 图谱通道：复用原问题的向量做实体锚点，零额外 embedding 成本
        from src.graph import graph_channel
        graph_rows = graph_channel(vectors[0], top_k=max(top_k * 5, 25), filters=filters)
        channels.append(graph_rows)
    t_retrieved = _time.perf_counter() if debug else 0.0

    merged = rrf_merge(channels, top_k if "rerank" not in requested else top_k * 5)
    fused_count = len(merged) if debug else 0
    rerank_used = False
    effective_strategy: str | None = None
    rerank_error: str | None = None
    if "rerank" in requested and merged:
        from src.rerank import rerank
        effective_strategy = (rerank_strategy or os.getenv("RERANK_STRATEGY", "rrf")).lower()
        try:
            merged = rerank(question, merged, top_k, strategy=effective_strategy)
            rerank_used = True
        except Exception as exc:
            # ponytail: cross/colbert 依赖本地模型，未下载时不能让整个问答 500，
            # 这里退回 RRF 序并在 trace 里记 reason（界面上表现为"请求了但空转"）。
            rerank_error = f"{type(exc).__name__}: {exc}"
            merged = merged[:top_k]  # 融合时为重排预留了 top_k*5 候选，降级后要收回

    if not debug:
        return merged

    from src.llm.client import get_llm

    assert stats is not None
    llm_available = get_llm().enabled if wants_plan else False
    routed_docs = len(stats.get("routed_doc_ids", ()))
    applied: list[str] = []
    skipped: list[dict] = []

    if "routing" in requested:
        if routed_docs > 0:
            applied.append("routing")
            if stats.get("route_fallback"):
                skipped.append({
                    "name": "routing",
                    "reason": f"最高路由分低于阈值 {_MIN_ROUTE_SCORE}，已补一路全局向量兜底",
                })
        else:
            skipped.append({"name": "routing", "reason": "路由层未命中任何文档（doc_index 可能为空），已退回全局向量"})
    if "keywords" in requested:
        if stats.get("keywords", 0) > 0:
            applied.append("keywords")
        else:
            skipped.append({"name": "keywords", "reason": "未从问题中提取到有效关键词"})
    for name, used, absent_reason in (
        ("decompose", bool(sub_queries), "该问题无需拆分（未产出子问题）"),
        ("stepback", step_back_used, "该问题已足够抽象（未产出退步问题）"),
        ("hyde", hyde_used, "该问题为事实型（未产出假想段落）"),
    ):
        if name not in requested:
            continue
        if used:
            applied.append(name)
        else:
            skipped.append({
                "name": name,
                "reason": "LLM 未配置，检索规划未执行" if not llm_available else absent_reason,
            })
    if "graph" in requested:
        if graph_rows:
            applied.append("graph")
        else:
            skipped.append({"name": "graph", "reason": "图谱通道无命中（图谱未构建，或问题与实体锚点不匹配）"})
    if "rerank" in requested:
        if rerank_used:
            applied.append("rerank")
        elif rerank_error:
            skipped.append({"name": "rerank", "reason": f"重排失败已退回 RRF 序（{rerank_error}）"})
        else:
            skipped.append({"name": "rerank", "reason": "候选为空，未执行重排"})

    trace_channels: list[dict] = []
    if "routing" in requested:
        note = "，已兜底全局" if stats.get("route_fallback") else ""
        trace_channels.append({
            "name": "routing", "label": "路由", "hits": routed_docs,
            "detail": f"命中 {routed_docs} 篇文档{note}",
        })
    if "keywords" in requested:
        trace_channels.append({"name": "keywords", "label": "关键词", "hits": stats.get("keywords", 0), "detail": None})
    trace_channels.append({
        "name": "vector", "label": "向量", "hits": stats.get("vector", 0),
        "detail": f"{len(queries)} 条查询合并" if len(queries) > 1 else None,
    })
    if hyde_used:
        trace_channels.append({"name": "hyde", "label": "假想文档", "hits": len(hyde_rows), "detail": None})
    if "graph" in requested:
        trace_channels.append({"name": "graph", "label": "图谱", "hits": len(graph_rows), "detail": None})

    return {
        "results": merged,
        "trace": {
            "features": sorted(requested),
            "applied": applied,
            "skipped": skipped,
            "params": {
                "top_k": top_k,
                "filters": filters or {},
                "rerank_strategy": effective_strategy,
            },
            "plan": {
                "subs": list(plan["subs"]),
                "step_back": plan["step_back"],
                "hyde": plan["hyde"],
                "queries": list(queries),
            },
            "routing": {
                "routed_docs": routed_docs,
                "top_score": stats.get("route_top_score", 0.0),
                "fallback": bool(stats.get("route_fallback")),
                "min_score": _MIN_ROUTE_SCORE,
            },
            "channels": trace_channels,
            "fusion": {
                "channels": len(channels),
                "pre_merge": len({row["chunk_id"] for channel in channels for row in channel}),
                "post_merge": fused_count,
                "rerank": effective_strategy if rerank_used else None,
                "final": len(merged),
            },
            "timings": {
                "plan_ms": round((t_planned - t_start) * 1000, 1),
                "retrieve_ms": round((t_retrieved - t_planned) * 1000, 1),
                "generate_ms": 0.0,
            },
        },
    }
